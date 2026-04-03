#!/usr/bin/env python3
"""
generate_chapter.py — Generate a chapter draft from a chapter brief.

Usage:
    python3 generate_chapter.py 1
    python3 generate_chapter.py --all
"""
import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime

from chapter_planning import (
    build_block_system_prompt,
    build_chapter_beats_prompt,
    build_chapter_cleanup_prompt,
    build_chapter_revision_prompt,
    build_scene_block_prompt,
    find_chapter_entry,
    get_target_words_per_chapter,
    get_total_chapters,
)
from config import get_model
from config import is_chapter_length_enforced
from dual_llm import stream_llm
from paths import (
    CHAPTERS_DIR,
    CHAPTER_BEATS_TEMPLATE_PATH,
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    SYSTEM_PROMPT_PATH,
    chapter_beats_path,
    chapter_draft_path,
    chapter_generation_log_path,
    ensure_runtime_dirs,
)
from story_utils import (
    analyze_beats_document,
    build_initial_cumulative_summary,
    group_beats_into_blocks,
    has_summary_for_chapter,
    is_valid_beats_document,
    parse_beats,
)
from text_quality import compression_ratio, max_ngram_repetition_ratio

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHAPTER_MIN_RATIO = 0.6
CHAPTER_MAX_RATIO = 1.35
META_NARRATION_PATTERNS = [
    re.compile(r"\bthe chapter (?:ends|ended|concludes|concluded)\b", re.IGNORECASE),
    re.compile(r"\bthis chapter\b", re.IGNORECASE),
]
STRUCTURAL_LEAK_PATTERNS = [
    re.compile(r"(?mi)^#{1,6}\s*chapter\b"),
    re.compile(r"(?mi)^#{1,6}\s*beat\b"),
    re.compile(r"(?mi)^##\s*beat\b"),
    re.compile(r"(?mi)^###\s*word count\b"),
    re.compile(r"(?mi)^###\s*notes\b"),
    re.compile(r"(?mi)^-\s+the chapter\b"),
]


def parse_story_bible(content):
    pov_match = re.search(r"- \*\*POV:\*\* (.+)", content)
    tense_match = re.search(r"- \*\*Tense:\*\* (.+)", content)
    pov = pov_match.group(1).strip() if pov_match else None
    tense = tense_match.group(1).strip() if tense_match else None
    return pov, tense


def prepare_system_prompt(system_prompt, story_bible_text):
    target_words_total = get_target_words_per_chapter(story_bible_text)
    pov, tense = parse_story_bible(story_bible_text)

    if tense and tense.lower() == "past":
        tense_placeholder = "past tense"
    elif tense and tense.lower() == "present":
        tense_placeholder = "present tense"
    else:
        tense_placeholder = tense or "past tense"

    if pov and "first person" in pov.lower():
        pov_placeholder = "first person"
    elif pov and "third person" in pov.lower():
        pov_placeholder = "third person"
    else:
        pov_placeholder = pov or "third person"

    prompt = system_prompt.replace("[WORD_COUNT_TARGET]", f"{target_words_total:,}")
    prompt = prompt.replace("{target_words:,}", f"{target_words_total:,}")
    prompt = prompt.replace("[PAST_TENSE/PRESENT_TENSE]", tense_placeholder)
    prompt = prompt.replace("[FIRST_PERSON/THIRD_PERSON]", pov_placeholder)
    return prompt, target_words_total


def ensure_cumulative_summary(story_bible_text):
    if os.path.exists(CUMULATIVE_SUMMARY_PATH):
        with open(CUMULATIVE_SUMMARY_PATH) as f:
            return f.read()

    content = build_initial_cumulative_summary(
        get_total_chapters(story_bible_text),
        get_target_words_per_chapter(story_bible_text) * get_total_chapters(story_bible_text),
    )
    with open(CUMULATIVE_SUMMARY_PATH, "w") as f:
        f.write(content)
    return content


def summarize_block_text(text, word_limit=140):
    words = text.split()
    if len(words) <= word_limit:
        return text.strip()
    return " ".join(words[:word_limit]).strip() + " ..."


def tail_text(text, word_limit=120):
    words = text.split()
    if len(words) <= word_limit:
        return text.strip()
    return "..." + " ".join(words[-word_limit:]).strip()


def normalized_paragraphs(text):
    paragraphs = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        cleaned = " ".join(raw.split())
        if not cleaned:
            continue
        normalized = re.sub(r"[^a-z0-9\s]", "", cleaned.lower())
        normalized = " ".join(normalized.split())
        if len(normalized.split()) >= 20:
            paragraphs.append(normalized)
    return paragraphs


def find_quality_issues(text, target_words_total, enforce_length=False):
    issues = []
    word_count = len(text.split())
    min_words = max(int(target_words_total * CHAPTER_MIN_RATIO), 1)
    max_words = max(int(target_words_total * CHAPTER_MAX_RATIO), min_words)

    if enforce_length and word_count < min_words:
        issues.append(
            f"Too short: {word_count:,} words. Expand to at least {min_words:,} words."
        )
    if enforce_length and word_count > max_words:
        issues.append(
            f"Too long: {word_count:,} words. Compress to at most {max_words:,} words."
        )

    for pattern in STRUCTURAL_LEAK_PATTERNS:
        if pattern.search(text):
            issues.append("Contains outline/beat/note formatting instead of clean chapter prose.")
            break

    for pattern in META_NARRATION_PATTERNS:
        if pattern.search(text):
            issues.append("Contains meta narration about the chapter instead of in-scene prose.")
            break

    seen = set()
    duplicate_count = 0
    for paragraph in normalized_paragraphs(text):
        if paragraph in seen:
            duplicate_count += 1
        else:
            seen.add(paragraph)
    if duplicate_count:
        issues.append(
            f"Contains repeated long paragraph material ({duplicate_count} repeated section(s))."
        )

    repetition_ratio = max_ngram_repetition_ratio(text, n=3, max_words=240)
    compression_ratio_value = compression_ratio(text, max_chars=4000)
    if repetition_ratio >= 0.24:
        issues.append(
            f"Contains suspicious short-range repetition (3-gram ratio {repetition_ratio:.2f})."
        )
    elif word_count >= 180 and compression_ratio_value <= 0.30:
        issues.append(
            f"Compresses too well for natural prose (ratio {compression_ratio_value:.2f}); likely looping or repetitive."
        )

    return issues


def summarize_retry_reasons(issues, limit=3):
    if not issues:
        return "no specific issues recorded"
    return "; ".join(issues[:limit])


def recover_final_chapter_text(
    chapter_text,
    story_bible_text,
    cumulative_content,
    chapter_beats_text,
    prepared_system_prompt,
    chapter,
    target_words_total,
    enforce_length=False,
    silent=False,
):
    min_words = max(int(target_words_total * CHAPTER_MIN_RATIO), 1)
    max_words = max(int(target_words_total * CHAPTER_MAX_RATIO), min_words)
    issues = find_quality_issues(
        chapter_text,
        target_words_total,
        enforce_length=enforce_length,
    )
    if not issues:
        return chapter_text

    recovery_prompt = build_chapter_cleanup_prompt(
        story_bible_text,
        cumulative_content,
        chapter_beats_text,
        prepared_system_prompt,
        chapter,
        chapter_text,
        target_words_total,
        min_words,
        max_words,
        issues + [
            "Do not use chapter headings, beat headings, markdown notes, or word-count sections.",
            "Return only continuous chapter prose.",
        ],
    )
    recovery_max_words = min(max_words + 600, 12000)
    return stream_llm(
        recovery_prompt,
        model=get_model("write"),
        system="",
        silent=silent,
        max_words=recovery_max_words,
        loop_detection=True,
    )


def clean_chapter_text(
    chapter_text,
    story_bible_text,
    cumulative_content,
    chapter_beats_text,
    prepared_system_prompt,
    chapter,
    target_words_total,
    enforce_length=False,
    silent=False,
):
    min_words = max(int(target_words_total * CHAPTER_MIN_RATIO), 1)
    max_words = max(int(target_words_total * CHAPTER_MAX_RATIO), min_words)

    current_text = chapter_text
    passes = []
    for _ in range(1):
        issues = find_quality_issues(
            current_text,
            target_words_total,
            enforce_length=enforce_length,
        )
        if not issues:
            return current_text, passes

        reason_summary = summarize_retry_reasons(issues)
        if not silent:
            print(f"Cleanup pass {len(passes) + 1} triggered: {reason_summary}")
        passes.append(
            {
                "issues": issues,
                "reason_summary": reason_summary,
                "word_count_before": len(current_text.split()),
            }
        )
        cleanup_prompt = build_chapter_cleanup_prompt(
            story_bible_text,
            cumulative_content,
            chapter_beats_text,
            prepared_system_prompt,
            chapter,
            current_text,
            target_words_total,
            min_words,
            max_words,
            issues,
        )
        cleanup_max_words = min(max_words + 400, 12000)
        current_text = stream_llm(
            cleanup_prompt,
            model=get_model("write"),
            system="",
            silent=silent,
            max_words=cleanup_max_words,
            loop_detection=True,
        )
        passes[-1]["word_count_after"] = len(current_text.split())

    return current_text, passes


def generate_chapter(
    chapter,
    script_dir,
    silent=False,
    output_file=None,
    beats_per_block=2,
    revise=False,
    enforce_length=None,
    cleanup=False,
):
    ensure_runtime_dirs()
    story_bible = STORY_BIBLE_PATH
    chapter_brief = chapter_beats_path(chapter)
    system_prompt_file = SYSTEM_PROMPT_PATH

    for path in [story_bible, chapter_brief, system_prompt_file]:
        if not os.path.exists(path):
            print(f"ERROR: Missing required file: {path}")
            sys.exit(1)

    with open(story_bible) as f:
        story_bible_text = f.read()
    cumulative_content = ensure_cumulative_summary(story_bible_text)
    with open(chapter_brief) as f:
        chapter_beats_text = f.read()
    with open(system_prompt_file) as f:
        system_prompt = f.read()

    if not is_valid_beats_document(chapter_beats_text):
        print(f"ERROR: Could not parse chapter brief for chapter {chapter}: {chapter_brief}")
        sys.exit(1)

    prepared_system_prompt, target_words_total = prepare_system_prompt(system_prompt, story_bible_text)
    if enforce_length is None:
        enforce_length = is_chapter_length_enforced()
    chapter_entry = find_chapter_entry(story_bible_text, chapter)
    chapter_title = chapter_entry.title if chapter_entry else f"Chapter {chapter}"
    beats = parse_beats(chapter_beats_text)
    blocks = group_beats_into_blocks(beats, beats_per_block=beats_per_block)

    if not silent:
        print(f"\n{'=' * 70}")
        print(f"  GENERATING CHAPTER {chapter} — {chapter_title}")
        print(f"{'=' * 70}")
        print("Method: staged scene-block drafting")
        print(f"Target: ~{target_words_total:,} words")
        print(f"Blocks: {len(blocks)} (up to {beats_per_block} beats each)")
        print(f"{'=' * 70}\n")

    block_target_words = max(target_words_total // max(len(blocks), 1), 1)
    block_max_words = min(int(block_target_words * 1.8) + 500, 7000)
    block_texts = []
    block_word_counts = []
    prior_block_summaries = []
    regeneration_events = []

    for block in blocks:
        if not silent:
            print(
                f"Generating block {block['index']}/{len(blocks)} "
                f"(beats {block['start_beat']}-{block['end_beat']})..."
            )

        prior_summary = "\n\n".join(prior_block_summaries)
        prior_tail = tail_text(block_texts[-1]) if block_texts else ""
        beats_in_block = max(len(block.get("beats", [])), 1)
        block_target_for_prompt = max(
            block_target_words,
            int(block_target_words * (beats_in_block / max(beats_per_block, 1))),
        )
        block_system_prompt = build_block_system_prompt(
            prepared_system_prompt,
            block_target_for_prompt,
        )
        block_prompt = build_scene_block_prompt(
            story_bible_text,
            cumulative_content,
            chapter_beats_text,
            block_system_prompt,
            chapter,
            block,
            block_target_words=block_target_for_prompt,
            prior_blocks_summary=prior_summary,
            prior_text_tail=prior_tail,
            total_blocks=len(blocks),
        )
        block_text = stream_llm(
            block_prompt,
            model=get_model("write"),
            system="",
            silent=silent,
            max_words=block_max_words,
            loop_detection=True,
        )
        block_texts.append(block_text.strip())
        block_word_counts.append(len(block_text.split()))
        prior_block_summaries.append(
            f"Block {block['index']} summary: {summarize_block_text(block_text)}"
        )

        if not silent:
            print(f"  {block_word_counts[-1]:,} words")

    assembled_text = "\n\n".join(text for text in block_texts if text)

    if revise:
        if not silent:
            print("Revising assembled chapter for flow...")
        revision_prompt = build_chapter_revision_prompt(
            story_bible_text,
            cumulative_content,
            chapter_beats_text,
            prepared_system_prompt,
            chapter,
            assembled_text,
        )
        revision_max_words = min(int(target_words_total * 1.35) + 500, 12000)
        chapter_text = stream_llm(
            revision_prompt,
            model=get_model("write"),
            system="",
            silent=silent,
            max_words=revision_max_words,
            loop_detection=True,
        )
    else:
        chapter_text = assembled_text

    cleanup_passes = []
    if cleanup:
        chapter_text, cleanup_passes = clean_chapter_text(
            chapter_text,
            story_bible_text,
            cumulative_content,
            chapter_beats_text,
            prepared_system_prompt,
            chapter,
            target_words_total,
            enforce_length=enforce_length,
            silent=silent,
        )

    final_issues = find_quality_issues(
        chapter_text,
        target_words_total,
        enforce_length=enforce_length,
    )
    has_structural_leak = any(pattern.search(chapter_text) for pattern in STRUCTURAL_LEAK_PATTERNS)
    has_meta_narration = any(pattern.search(chapter_text) for pattern in META_NARRATION_PATTERNS)
    severe_final_issues = [
        issue for issue in final_issues
        if "outline/beat/note formatting" in issue.lower()
        or "meta narration" in issue.lower()
    ]
    if cleanup and (severe_final_issues or has_structural_leak or has_meta_narration):
        recovery_reason = summarize_retry_reasons(severe_final_issues or final_issues)
        regeneration_events.append(f"Final recovery triggered: {recovery_reason}")
        if not silent:
            print(
                "Final draft still has blocking quality issues; attempting one final recovery pass..."
            )
            print(f"  Reason: {recovery_reason}")
        chapter_text = recover_final_chapter_text(
            chapter_text,
            story_bible_text,
            cumulative_content,
            chapter_beats_text,
            prepared_system_prompt,
            chapter,
            target_words_total,
            enforce_length=enforce_length,
            silent=silent,
        )
        recovered_issues = find_quality_issues(
            chapter_text,
            target_words_total,
            enforce_length=enforce_length,
        )
        recovered_has_structural_leak = any(pattern.search(chapter_text) for pattern in STRUCTURAL_LEAK_PATTERNS)
        recovered_has_meta_narration = any(pattern.search(chapter_text) for pattern in META_NARRATION_PATTERNS)
        severe_recovered_issues = [
            issue for issue in recovered_issues
            if "outline/beat/note formatting" in issue.lower()
            or "meta narration" in issue.lower()
        ]
        if severe_recovered_issues or recovered_has_structural_leak or recovered_has_meta_narration:
            print(
                f"ERROR: Final chapter draft for chapter {chapter} is still invalid: "
                + "; ".join((severe_recovered_issues or ["Malformed chapter structure remains after recovery."])[:3])
            )
            sys.exit(1)
        final_issues = recovered_issues

    if final_issues and not silent:
        warning_label = (
            "WARNING: Final chapter draft has non-blocking quality issues: "
            if cleanup else
            "WARNING: Writing permissive draft with quality issues: "
        )
        print(warning_label + "; ".join(final_issues[:3]))

    if cleanup_passes:
        for index, cleanup in enumerate(cleanup_passes, start=1):
            regeneration_events.append(
                f"Cleanup pass {index} triggered: {cleanup.get('reason_summary', summarize_retry_reasons(cleanup['issues']))}"
            )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = (
        f"# Chapter {chapter} Draft\n"
        f"Generated: {timestamp}\n"
        "Method: staged scene-block drafting\n"
        f"Target: {target_words_total:,} words\n"
        f"Actual: {len(chapter_text.split()):,} words\n\n"
        "---\n\n"
    )
    full_draft = metadata + chapter_text

    if output_file:
        output_path = output_file if os.path.isabs(output_file) else os.path.abspath(output_file)
    else:
        output_path = chapter_draft_path(chapter)
    with open(output_path, "w") as f:
        f.write(full_draft)

    with open(chapter_generation_log_path(chapter), "w") as f:
        f.write(
            f"# Generation Log - Chapter {chapter}\n"
            f"Timestamp: {timestamp}\n"
            "Method: staged scene-block drafting\n"
            f"Target: {target_words_total:,} words\n"
            f"Actual: {len(chapter_text.split()):,} words\n"
            f"Blocks: {len(blocks)}\n"
            f"Block word counts: {', '.join(str(count) for count in block_word_counts)}\n"
            f"Revision pass: {'yes' if revise else 'no'}\n"
            f"Length enforcement: {'yes' if enforce_length else 'no'}\n"
            f"Cleanup enforcement: {'yes' if cleanup else 'no'}\n"
            f"Cleanup passes: {len(cleanup_passes)}\n"
            f"Brief file: {os.path.basename(chapter_brief)}\n"
            f"Draft file: {os.path.basename(output_path)}\n"
        )
        if regeneration_events:
            f.write("\nRegeneration events:\n")
            for event in regeneration_events:
                f.write(f"- {event}\n")
        for index, cleanup in enumerate(cleanup_passes, start=1):
            f.write(
                f"\nCleanup pass {index}: {cleanup['word_count_before']:,} -> "
                f"{cleanup.get('word_count_after', cleanup['word_count_before']):,} words\n"
            )
            for issue in cleanup["issues"]:
                f.write(f"- {issue}\n")

    return len(chapter_text.split()), output_path


def generate_next_chapter_beats(chapter):
    next_chapter = int(chapter) + 1
    next_beats = chapter_beats_path(next_chapter)
    if os.path.exists(next_beats):
        return None

    with open(STORY_BIBLE_PATH) as f:
        story_bible_text = f.read()
    if next_chapter > get_total_chapters(story_bible_text):
        return None

    cumulative_content = ensure_cumulative_summary(story_bible_text)
    with open(CHAPTER_BEATS_TEMPLATE_PATH) as f:
        beats_template = f.read()

    prompt = build_chapter_beats_prompt(
        story_bible_text,
        next_chapter,
        cumulative_summary=cumulative_content,
        beats_template=beats_template,
    )
    content = stream_llm(
        prompt,
        model=get_model("beats"),
        system="You are a story architect.",
    )

    if not content or len(content.strip()) < 50:
        print(
            f"  ERROR: Chapter brief output is empty or too short "
            f"({len(content.strip()) if content else 0} chars)",
            file=sys.stderr,
        )
        return None
    issues = analyze_beats_document(content)
    if issues:
        repair_prompt = (
            f"Rewrite this chapter brief so it is immediately usable for drafting.\n\n"
            f"ISSUES TO FIX:\n" + "\n".join(f"- {issue}" for issue in issues) + "\n\n"
            "REQUIREMENTS:\n"
            "- Keep the same chapter intent and story events\n"
            "- Output a single chapter brief only\n"
            "- Use a chapter heading followed by 4-6 concrete beat sections\n"
            "- Each beat must be specific, distinct, and prose-draftable\n"
            "- Remove placeholders, vague filler, and duplicated beats\n\n"
            f"CURRENT BRIEF:\n{content}"
        )
        content = stream_llm(
            repair_prompt,
            model=get_model("beats"),
            system="You repair malformed chapter briefs into clean drafting plans.",
        )
        issues = analyze_beats_document(content)
    if issues:
        print(
            "  ERROR: Generated chapter brief did not match expected quality: "
            + "; ".join(issues[:3]),
            file=sys.stderr,
        )
        return None

    with open(next_beats, "w") as f:
        f.write(content)
    return next_beats


def generate_all_sequential(
    script_dir,
    skip_existing=True,
    silent=False,
    beats_per_block=2,
    revise=False,
    enforce_length=None,
    cleanup=False,
):
    chapters_dir = CHAPTERS_DIR
    beats_files = sorted(
        glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
        key=lambda path: int(re.search(r"chapter_(\d+)_beats", path).group(1)),
    )

    if not beats_files:
        print("No chapter beats found in chapters/. Run plan_chapters.py --beats first.")
        sys.exit(1)

    chapter_nums = []
    for beats_file in beats_files:
        match = re.search(r"chapter_(\d+)_beats", beats_file)
        if match:
            chapter_nums.append(int(match.group(1)))

    if not chapter_nums:
        print("Could not parse chapter numbers from beats filenames.")
        sys.exit(1)

    with open(STORY_BIBLE_PATH) as f:
        story_bible_text = f.read()
    total_chapters = get_total_chapters(story_bible_text)
    min_chapter, max_chapter = min(chapter_nums), max(chapter_nums)

    print(f"\n{'=' * 70}")
    print("  SEQUENTIAL CHAPTER GENERATION")
    print(f"{'=' * 70}")
    print(f"Found chapter briefs for chapters {min_chapter}-{max_chapter} ({len(chapter_nums)} chapters)")
    print(f"Planned total: {total_chapters} chapters")
    print("Workflow: Draft chapter -> Summarize -> Generate next chapter brief")
    print(f"{'=' * 70}\n")

    chapter = min_chapter
    while chapter <= total_chapters:
        draft_path = chapter_draft_path(chapter)
        beats_path = chapter_beats_path(chapter)
        if not os.path.exists(beats_path):
            break

        cumulative_content = ensure_cumulative_summary(story_bible_text)
        chapter_summarized = has_summary_for_chapter(cumulative_content, chapter)

        if os.path.exists(draft_path) and chapter_summarized and skip_existing:
            print(f"[{chapter}] Skipping chapter {chapter} — draft exists and is summarized")
            chapter += 1
            continue

        if os.path.exists(draft_path) and not chapter_summarized:
            print(f"[{chapter}] Draft exists but not yet summarized — summarizing...")
        elif not os.path.exists(draft_path):
            print(f"\n[{chapter}] Generating chapter {chapter}...")
            word_count, path = generate_chapter(
                chapter,
                script_dir,
                silent=silent,
                beats_per_block=beats_per_block,
                revise=revise,
                enforce_length=enforce_length,
                cleanup=cleanup,
            )
            print(f"  ✓ {os.path.basename(path)} written ({word_count:,} words)")

        print(f"  → Summarizing chapter {chapter}...")
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "summarize_chapter.py"), str(chapter), "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  ✗ summarize_chapter.py FAILED (exit code {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr.strip()[:500]}")
            if result.stdout:
                print(f"  stdout: {result.stdout.strip()[:500]}")
            print("  Stopping — fix the error above and rerun.")
            sys.exit(1)
        print(f"  ✓ chapter {chapter} summarized, cumulative_summary.md updated")

        if chapter < total_chapters:
            next_beats_path = chapter_beats_path(chapter + 1)
            if os.path.exists(next_beats_path):
                print(f"  ✓ chapter_{chapter + 1:03d}_beats.md already exists")
            else:
                print(f"  → Generating chapter_{chapter + 1:03d}_beats.md...")
                created = generate_next_chapter_beats(chapter)
                if created:
                    print(f"  ✓ {os.path.basename(created)} written")

        print()
        chapter += 1

    print(f"{'=' * 70}")
    if chapter > total_chapters:
        print(f"All {total_chapters} chapters complete!")
    else:
        print(f"Stopped at chapter {chapter} — no chapter brief found.")
    print("Check chapters/ for drafts and cumulative_summary.md for story state.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a chapter draft from a chapter brief."
    )
    parser.add_argument("chapter", nargs="?", help="Chapter number to generate")
    parser.add_argument("--all", action="store_true", help="Generate all chapters sequentially")
    parser.add_argument("--silent", action="store_true", help="Suppress streaming output")
    parser.add_argument("-o", "--output", help="Custom output path")
    parser.add_argument(
        "--beats-per-block",
        type=int,
        default=2,
        help="How many beats to combine into each draft block (default: 2)",
    )
    parser.add_argument(
        "--revise",
        action="store_true",
        default=False,
        help="Run the final chapter-level smoothing pass",
    )
    parser.add_argument(
        "--no-revise",
        action="store_false",
        dest="revise",
        help="Skip the final chapter-level smoothing pass",
    )
    parser.add_argument(
        "--enforce-length",
        action="store_true",
        default=None,
        help="Enable chapter-length cleanup/retry checks",
    )
    parser.add_argument(
        "--no-enforce-length",
        action="store_false",
        dest="enforce_length",
        help="Disable chapter-length cleanup/retry checks",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="Enable chapter cleanup/recovery passes and blocking structural validation",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_false",
        dest="cleanup",
        help="Disable chapter cleanup/recovery passes and write drafts permissively",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip chapters that already have drafts and summaries (default: True)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_false",
        dest="skip_existing",
        help="Regenerate even if draft exists",
    )
    args = parser.parse_args()

    if args.all:
        generate_all_sequential(
            SCRIPT_DIR,
            skip_existing=args.skip_existing,
            silent=args.silent,
            beats_per_block=args.beats_per_block,
            revise=args.revise,
            enforce_length=args.enforce_length,
            cleanup=args.cleanup,
        )
        return

    if not args.chapter:
        parser.error("chapter is required unless --all is used")

    word_count, output_path = generate_chapter(
        args.chapter,
        SCRIPT_DIR,
        silent=args.silent,
        output_file=args.output,
        beats_per_block=args.beats_per_block,
        revise=args.revise,
        enforce_length=args.enforce_length,
        cleanup=args.cleanup,
    )
    print(f"Wrote {output_path} ({word_count:,} words)")


if __name__ == "__main__":
    main()
