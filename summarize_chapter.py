#!/usr/bin/env python3
"""
summarize_chapter.py — Summarize a completed chapter, update cumulative_summary.md,
and generate the next chapter brief.
"""
import argparse
import os
import sys

from chapter_planning import build_chapter_beats_prompt, get_total_chapters
from config import get_model, get_word_count_target
from dual_llm import stream_llm
from paths import (
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    CHAPTER_BEATS_TEMPLATE_PATH,
    chapter_beats_path,
    chapter_draft_path,
)
from story_utils import (
    build_initial_cumulative_summary,
    extract_summary_headers,
    set_completed_chapters,
    upsert_chapter_summary,
)


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


def main():
    args = parse_args()
    chapter = int(args.chapter)
    next_chapter = chapter + 1
    chapter_draft = chapter_draft_path(chapter)
    next_beats = chapter_beats_path(next_chapter)
    cumulative = CUMULATIVE_SUMMARY_PATH
    story_bible = STORY_BIBLE_PATH

    if not os.path.exists(chapter_draft):
        print(f"ERROR: Chapter draft not found: {chapter_draft}")
        print(f"Run: python3 generate_chapter.py {chapter}")
        sys.exit(1)
    if not os.path.exists(story_bible):
        print(f"ERROR: Story bible not found: {story_bible}")
        sys.exit(1)

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

    log(f"=== Summarizing Chapter {chapter} ===\n", args.quiet)

    system_prompt = (
        "You are a continuity tracker. Extract rough chapter state for later drafting. "
        "Be factual, compressed, and utilitarian. Follow the format exactly."
    )
    user_prompt = build_summary_prompt(chapter, draft_content)

    log("Summarizing chapter (streaming):", args.quiet)
    if not args.quiet:
        print("-" * 40)
    summary = stream_llm(user_prompt, model=get_model("summarize"), system=system_prompt, silent=args.quiet)
    if not args.quiet:
        print("-" * 40)
        print()

    with open(cumulative) as f:
        existing_content = f.read()

    updated_content = upsert_chapter_summary(existing_content, chapter, summary)
    new_content = set_completed_chapters(updated_content, chapter)
    with open(cumulative, "w") as f:
        f.write(new_content)

    log(f"✓ Chapter {chapter} summarized", args.quiet)

    total_chapters = get_total_chapters(story_bible_text)
    if next_chapter > total_chapters:
        log("Final chapter summarized; no next chapter brief needed.", args.quiet)
    elif os.path.exists(next_beats):
        log(f"Note: {next_beats} already exists — skipping brief generation.", args.quiet)
    else:
        with open(CHAPTER_BEATS_TEMPLATE_PATH) as f:
            beats_template = f.read()
        user_prompt2 = build_chapter_beats_prompt(
            story_bible_text,
            next_chapter,
            cumulative_summary=new_content,
            beats_template=beats_template,
        )

        log(f"\nGenerating Chapter {next_chapter} brief (streaming):", args.quiet)
        if not args.quiet:
            print("-" * 40)
        next_beats_content = stream_llm(
            user_prompt2,
            model=get_model("beats"),
            system="You are a story architect.",
            silent=args.quiet,
        )
        if not args.quiet:
            print("-" * 40)
            print()

        with open(next_beats, "w") as f:
            f.write(next_beats_content)
        log(f"✓ {next_beats} written", args.quiet)

    if args.quiet:
        return

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
