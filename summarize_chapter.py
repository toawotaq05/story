#!/usr/bin/env python3
"""
summarize_chapter.py — Summarize a completed chapter, update cumulative_summary.md,
and generate the next chapter brief.
"""
import argparse
import os
import sys

from chapter_planning import build_chapter_beats_prompt, find_chapter_entry, get_total_chapters
from config import get_model, get_word_count_target
from dual_llm import stream_llm
from paths import (
    CHAPTER_BEATS_TEMPLATE_PATH,
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    chapter_beats_path,
    chapter_draft_path,
    get_project_paths,
)
from story_utils import (
    build_initial_cumulative_summary,
    extract_summary_headers,
    finalize_beats_document,
    is_valid_beats_document,
    sanitize_cumulative_summary_document,
    sanitize_summary_document,
    set_completed_chapters,
    upsert_chapter_summary,
)

STORY_BIBLE_PATH = None
CUMULATIVE_SUMMARY_PATH = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize a completed chapter and generate the next chapter brief."
    )
    parser.add_argument("chapter", help="Chapter number to summarize")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return parser.parse_args()


def log(message, quiet=False):
    if not quiet:
        print(message)


def _story_bible_path():
    return STORY_BIBLE_PATH or get_project_paths().story_bible_path


def _cumulative_summary_path():
    return CUMULATIVE_SUMMARY_PATH or get_project_paths().cumulative_summary_path

def build_summary_prompt(chapter, draft_content):
    return f"""Chapter to summarize:

---

{draft_content}

---

Return a rough working summary for downstream story-state tracking.

Rules:
- Be literal and compressed, not polished
- Do not rewrite the chapter as elegant prose
- Prefer short bullet points over long sentences
- Keep only durable facts needed for later continuity
- Mention what changed, where characters ended up, and what remains unresolved

Format your response EXACTLY as follows — do not add any preamble, commentary, or extra text:

### Chapter {chapter} — [SHORT TITLE]
- Sequence:
  - [Plain fact about what happens first]
  - [Plain fact about what happens next]
  - [Plain fact about how the chapter ends]
- Plot facts established:
  - [Reveal, decision, event, or world fact that later chapters must remember]
  - ...
- Character end states:
  - [Character name]: [location / emotional state / relationship change / immediate goal]
  - ...
- Open threads:
  - [Unresolved question, threat, promise, or setup]
  - ..."""


def summarize_chapter(chapter, quiet=False):
    chapter = int(chapter)
    next_chapter = chapter + 1
    chapter_draft = chapter_draft_path(chapter)
    next_beats = chapter_beats_path(next_chapter)
    cumulative = _cumulative_summary_path()
    story_bible = _story_bible_path()

    if not os.path.exists(chapter_draft):
        raise FileNotFoundError(
            f"Chapter draft not found: {chapter_draft}\nRun: python3 generate_chapter.py {chapter}"
        )
    if not os.path.exists(story_bible):
        raise FileNotFoundError(f"Story bible not found: {story_bible}")

    with open(chapter_draft) as f:
        draft_content = f.read()
    with open(story_bible) as f:
        story_bible_text = f.read()

    if not os.path.exists(cumulative):
        with open(cumulative, "w") as f:
            f.write(
                build_initial_cumulative_summary(
                    get_total_chapters(story_bible_text),
                    get_word_count_target(),
                )
            )

    log(f"=== Summarizing Chapter {chapter} ===\n", quiet)

    system_prompt = (
        "You are a continuity tracker. Extract rough chapter state for later drafting. "
        "Be factual, compressed, and utilitarian. Follow the format exactly."
    )
    user_prompt = build_summary_prompt(chapter, draft_content)

    log("Summarizing chapter (streaming):", quiet)
    if not quiet:
        print("-" * 40)
    summary = stream_llm(user_prompt, model=get_model("summarize"), system=system_prompt, silent=quiet, max_words=200)
    summary = sanitize_summary_document(
        summary,
        chapter_number=chapter,
        fallback_title=f"Chapter {chapter}",
    )
    if not quiet:
        print("-" * 40)
        print()

    with open(cumulative) as f:
        existing_content = sanitize_cumulative_summary_document(f.read())

    updated_content = upsert_chapter_summary(existing_content, chapter, summary)
    new_content = set_completed_chapters(updated_content, chapter)
    new_content = sanitize_cumulative_summary_document(new_content)
    with open(cumulative, "w") as f:
        f.write(new_content)

    log(f"✓ Chapter {chapter} summarized", quiet)

    total_chapters = get_total_chapters(story_bible_text)
    if next_chapter > total_chapters:
        log("Final chapter summarized; no next chapter brief needed.", quiet)
    elif os.path.exists(next_beats):
        log(f"Note: {next_beats} already exists — skipping brief generation.", quiet)
    else:
        with open(CHAPTER_BEATS_TEMPLATE_PATH) as f:
            beats_template = f.read()
        user_prompt2 = build_chapter_beats_prompt(
            story_bible_text,
            next_chapter,
            cumulative_summary=new_content,
            beats_template=beats_template,
        )

        log(f"\nGenerating Chapter {next_chapter} brief (streaming):", quiet)
        if not quiet:
            print("-" * 40)
        next_beats_content = stream_llm(
            user_prompt2,
            model=get_model("beats"),
            system="You are a story architect.",
            silent=quiet,
            max_words=500,
        )
        if not quiet:
            print("-" * 40)
            print()

        next_entry = find_chapter_entry(story_bible_text, next_chapter)
        next_title = next_entry.title if next_entry else f"Chapter {next_chapter}"
        brief_result = finalize_beats_document(
            next_beats_content,
            chapter_number=next_chapter,
            chapter_title=next_title,
            current_chapter_target_prompt=user_prompt2,
            llm_call=lambda user_prompt, system_prompt: stream_llm(
                user_prompt,
                model=get_model("beats"),
                system=system_prompt,
                silent=quiet,
                max_words=500,
            ),
        )
        next_beats_content = brief_result["content"]

        if brief_result["repaired"]:
            reason = "; ".join(brief_result["initial_issues"][:3]) or "invalid chapter brief format"
            log(
                f"Warning: Chapter {next_chapter} brief was malformed. Attempting one repair pass. Reason: {reason}",
                quiet,
            )
        issues = brief_result["issues"]
        if issues:
            raise ValueError(
                f"ERROR: Chapter {next_chapter} brief is still malformed after repair: "
                + "; ".join(issues[:3])
            )

        with open(next_beats, "w") as f:
            f.write(next_beats_content)
        log(f"✓ {next_beats} written", quiet)

    return {
        "chapter": chapter,
        "next_chapter": next_chapter,
        "total_chapters": total_chapters,
        "summary_content": new_content,
    }


def main():
    args = parse_args()
    try:
        result = summarize_chapter(args.chapter, quiet=args.quiet)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        sys.exit(1)

    if args.quiet:
        return

    next_chapter = result["next_chapter"]
    total_chapters = result["total_chapters"]
    new_content = result["summary_content"]

    print()
    print("Current completed chapters:")
    for line in new_content.split("\n"):
        if "Completed Chapters" in line:
            print(" ", line)
            break
    print()
    print("Chapter summaries so far:")
    for chapter_number, title in extract_summary_headers(new_content):
        print(f"  Chapter {chapter_number} — {title}")
    if next_chapter <= total_chapters:
        print()
        print("Next step:")
        print(f"  python3 generate_chapter.py {next_chapter}")


if __name__ == "__main__":
    main()
