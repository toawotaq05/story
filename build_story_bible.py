#!/usr/bin/env python3
"""
build_story_bible.py — End-to-end story bible + chapter 1 brief generator.

Usage:
  python3 build_story_bible.py "Your story concept here"
"""
import sys
import os

from chapter_planning import build_chapter_beats_prompt
from dual_llm import stream_llm
from config import get_default_chapters, get_word_count_target, is_local_mode
from paths import (
    CHAPTER_BEATS_TEMPLATE_PATH,
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    STORY_BIBLE_TEMPLATE_PATH,
    chapter_beats_path,
    ensure_runtime_dirs,
    raw_output_path,
)
from story_utils import (
    analyze_beats_document,
    build_initial_cumulative_summary,
    build_outline_section,
    is_valid_beats_document,
    merge_story_bible_and_outline,
    parse_outline_entries,
    split_story_bible_and_outline,
)


def _outline_matches_target(outline_entries, default_chapters):
    if len(outline_entries) != int(default_chapters):
        return False
    numbers = [entry.number for entry in outline_entries]
    return numbers == list(range(1, int(default_chapters) + 1))


def ensure_story_bible_has_outline(story_bible_text, default_chapters):
    _, outline_section = split_story_bible_and_outline(story_bible_text)
    outline_entries = parse_outline_entries(outline_section)
    if _outline_matches_target(outline_entries, default_chapters):
        normalized_outline = build_outline_section(outline_entries)
        story_bible_core, _ = split_story_bible_and_outline(story_bible_text)
        return merge_story_bible_and_outline(story_bible_core, normalized_outline), None

    if not outline_entries:
        reason = "story bible did not contain a parseable chapter outline"
    else:
        reason = (
            f"outline chapter count/numbering mismatch "
            f"(found {[entry.number for entry in outline_entries]}, expected 1-{int(default_chapters)})"
        )

    outline_prompt = f"""Based on the story bible below, generate a chapter outline with exactly {default_chapters} chapters.

STORY BIBLE:
{story_bible_text}

REQUIREMENTS:
- Output only the chapter outline
- Include exactly {default_chapters} numbered chapter entries
- Use this format for every line:
  1. **Chapter 1 — [Title]** — [Two sentences summary] → ends: [setup for next chapter]
- Keep each chapter summary concrete and sequential.
- Include what sex acts is taking place if any.
- Make the final chapter ending feel conclusive

FORMAT:
# Chapter Outline

1. **Chapter 1 — [Title]** — [one or two sentences about what happens] → ends: [setup for Chapter 2]
2. **Chapter 2 — [Title]** — [one or two sentences about what happens] → ends: [setup for Chapter 3]
...and so on
"""

    outline_output = stream_llm(
        outline_prompt,
        model="outline",
        system="You are an erotic story architect. Return only a clean chapter outline.",
    )

    outline_entries = parse_outline_entries(outline_output)
    if not _outline_matches_target(outline_entries, default_chapters):
        raise ValueError("Could not generate a valid chapter outline from the story bible")

    normalized_outline = build_outline_section(outline_entries)
    story_bible_core, _ = split_story_bible_and_outline(story_bible_text)
    return merge_story_bible_and_outline(story_bible_core, normalized_outline), reason


def repair_chapter_beats_if_needed(chapter_beats_content, chapter_number):
    issues = analyze_beats_document(chapter_beats_content)
    if not issues:
        return chapter_beats_content, []

    repair_prompt = (
        f"Rewrite this chapter brief so it is clean and draftable for Chapter {chapter_number}.\n\n"
        f"ISSUES TO FIX:\n" + "\n".join(f"- {issue}" for issue in issues) + "\n\n"
        "REQUIREMENTS:\n"
        "- Output only the chapter brief document\n"
        "- Start with a '# Chapter N — Title' heading\n"
        "- Use 4-6 concrete '### Beat N: Label' sections\n"
        "- Keep the same planned chapter events and ending direction\n"
        "- Remove vague filler, malformed headings, and placeholder-like formatting\n\n"
        f"CURRENT BRIEF:\n{chapter_beats_content}"
    )
    repaired = stream_llm(
        repair_prompt,
        model="beats",
        system="You repair malformed chapter briefs into clean drafting plans.",
    )
    return repaired, issues


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_story_bible.py \"Your story concept here\"")
        sys.exit(1)

    concept = sys.argv[1]
    default_chapters = get_default_chapters()
    word_count_target = get_word_count_target()

    # Load templates
    ensure_runtime_dirs()

    with open(STORY_BIBLE_TEMPLATE_PATH) as f:
        story_bible_template = f.read()
    with open(CHAPTER_BEATS_TEMPLATE_PATH) as f:
        chapter_template = f.read()

    print("=== Building Story Bible from Concept ===")
    print(f"Concept: {concept}")
    print(f"Configuration: {default_chapters} chapters, {word_count_target} words target")
    print(f"Local mode: {is_local_mode()}")
    print()

    chapter_words = word_count_target // default_chapters
    config_section = f"""### Story Specifications

The finished story will have {default_chapters} chapters totaling approximately {word_count_target:,} words (~{chapter_words:,} words per chapter).

Use these specs to plan your story bible — character arcs, plot beats, pacing, and chapter structure. This is a PLANNING DOCUMENT, not the story itself. Do not write prose or story text — only the outline and worldbuilding details.
"""

    # ----------------------------------------------------------------
    # TASK 1: Generate the Story Bible
    # ----------------------------------------------------------------
    bible_prompt = f"""{config_section}
---

Story concept:
{concept}

---

TASK: Fill in the STORY BIBLE

Fill in every [BRACKETED PLACEHOLDER] in the template below. Make creative choices that are original, coherent, and compelling. Match the tone and genre of the prompt. If the prompt is sexual, then be clear about planning sexual events clearly. Fill in ALL sections — do not skip any.

Story Bible Template:
{story_bible_template}

---

OUTPUT FORMAT:

Write the story bible beginning with "# [YOUR TITLE]", replacing [STORY TITLE] and all other bracketed placeholders with your creative choices.
If an erotic story, include sexual acts in most chapters.

Do not include any preamble, commentary, or explanation — output only the completed story bible.
"""

    system_prompt = (
        "You are a creative erotic story architect. Fill in the provided template "
        "with original, coherent creative choices. Be thorough — complete every section."
    )

    print("--- Step 1: Generating Story Bible ---")
    print()
    story_bible_content = stream_llm(bible_prompt, model="story_bible", system=system_prompt)
    print()

    # Save raw for debugging
    with open(raw_output_path("llm_raw_bible.txt"), "w") as f:
        f.write(story_bible_content)

    if not story_bible_content or len(story_bible_content.strip()) < 200:
        print("ERROR: Story bible content is empty or too short")
        sys.exit(1)

    # Check it looks like a story bible (starts with #)
    if not story_bible_content.strip().startswith("#"):
        print("WARNING: Story bible does not start with '#'. It may be garbled.")
        print(f"Preview: {story_bible_content[:200]!r}")

    story_bible_content, outline_regen_reason = ensure_story_bible_has_outline(
        story_bible_content,
        default_chapters,
    )
    if outline_regen_reason:
        print("INFO: Regenerated chapter outline before writing story_bible.md")
        print(f"Reason: {outline_regen_reason}")

    with open(STORY_BIBLE_PATH, "w") as f:
        f.write(story_bible_content)
    print("✓ story_bible.md written")

    # Initialize cumulative_summary.md if it doesn't exist
    if not os.path.exists(CUMULATIVE_SUMMARY_PATH):
        with open(CUMULATIVE_SUMMARY_PATH, "w") as f:
            f.write(build_initial_cumulative_summary(default_chapters, word_count_target))
        print("✓ cumulative_summary.md initialized")

    # ----------------------------------------------------------------
    # TASK 2: Generate Chapter 1 Beats (separate call — safer for small models)
    # ----------------------------------------------------------------
    beats_prompt = build_chapter_beats_prompt(
        story_bible_content,
        1,
        cumulative_summary="",
        beats_template=chapter_template,
    )

    beats_system = (
        "You are an erotic story architect. Write a specific, detailed chapter brief that "
        "another LLM could use to draft the full chapter. Name characters, describe "
        "scenes, give dialogue cues. Do not summarise — be vivid and concrete."
    )

    print("--- Step 2: Generating Chapter 1 Beats ---")
    print()
    chapter_beats_content = stream_llm(beats_prompt, model="beats", system=beats_system)
    print()

    with open(raw_output_path("llm_raw_beats.txt"), "w") as f:
        f.write(chapter_beats_content)

    if not chapter_beats_content or len(chapter_beats_content.strip()) < 100:
        print("ERROR: Chapter 1 beats content is empty or too short")
        sys.exit(1)

    if not is_valid_beats_document(chapter_beats_content):
        repaired_content, repair_issues = repair_chapter_beats_if_needed(chapter_beats_content, 1)
        reason = "; ".join(repair_issues[:3]) if repair_issues else "invalid chapter brief format"
        print("WARNING: Chapter 1 brief is malformed. Attempting one repair pass.")
        print(f"Reason: {reason}")
        chapter_beats_content = repaired_content
        print()

    issues = analyze_beats_document(chapter_beats_content)
    if issues:
        print("ERROR: Chapter 1 brief is still malformed after repair.")
        print(f"Issues: {'; '.join(issues[:3])}")
        sys.exit(1)

    with open(chapter_beats_path(1), "w") as f:
        f.write(chapter_beats_content)
    print("✓ chapters/chapter_001_beats.md written")

    print()
    print("=== Done ===")
    print("Next steps:")
    print(f"  1. Review {STORY_BIBLE_PATH}")
    print(f"  2. Review {chapter_beats_path(1)}")
    print("  3. python3 generate_chapter.py 1")


if __name__ == "__main__":
    main()
