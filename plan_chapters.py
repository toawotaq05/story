#!/usr/bin/env python3
"""
plan_chapters.py — Generate the full chapter outline before writing begins.

Usage:
  python3 plan_chapters.py                       # interactive: ask for concept or use existing
  python3 plan_chapters.py "my concept"           # one-shot with concept
  python3 plan_chapters.py --beats               # also generate all chapter briefs upfront
  python3 plan_chapters.py --beats 8             # 8 chapters (default: 8-12 based on story_bible or auto)
  python3 plan_chapters.py --regen-outline       # regenerate outline only
  python3 plan_chapters.py --regen-beats        # regenerate all chapter briefs from existing outline
"""
import sys
import os
import argparse

from chapter_planning import build_chapter_beats_prompt
from dual_llm import stream_llm
from config import get_model, get_default_chapters
from paths import (
    CHAPTERS_DIR,
    CHAPTER_BEATS_TEMPLATE_PATH,
    STORY_BIBLE_PATH,
    chapter_beats_path,
    ensure_runtime_dirs,
    raw_output_path,
)
from story_utils import (
    analyze_beats_document,
    build_outline_section,
    is_valid_beats_document,
    merge_story_bible_and_outline,
    parse_outline_entries,
    split_story_bible_and_outline,
)

DEFAULT_CHAPTERS = get_default_chapters()

def main():
    parser = argparse.ArgumentParser(description="Plan the full chapter outline before writing.")
    parser.add_argument("concept", nargs="?", default=None,
                        help="Story concept (if not given, use existing story_bible.md)")
    parser.add_argument("--beats", action="store_true",
                        help="Also generate all chapter briefs after the outline")
    parser.add_argument("--chapters", type=int, default=None,
                        help=f"Number of chapters (default: {DEFAULT_CHAPTERS}, range: 8-12)")
    parser.add_argument("--regen-outline", action="store_true",
                        help="Regenerate outline only, keep existing chapter briefs")
    parser.add_argument("--regen-beats", action="store_true",
                        help="Regenerate all chapter briefs from existing outline")
    args = parser.parse_args()

    story_bible_path = STORY_BIBLE_PATH
    chapters_dir = CHAPTERS_DIR

    num_chapters = args.chapters or DEFAULT_CHAPTERS

    # --- Load existing story bible if no new concept ---
    if args.concept:
        concept = args.concept
        if not os.path.exists(story_bible_path) or args.regen_outline:
            print("Note: --regen-outline not set but story_bible.md doesn't exist.")
            print("Will generate full story bible + outline together.\n")
        story_bible_text = ""
        has_story_bible = False
    else:
        if not os.path.exists(story_bible_path):
            print("ERROR: No concept given and story_bible.md not found.")
            print("Run with a concept: python3 plan_chapters.py \"my story\"")
            sys.exit(1)
        with open(story_bible_path) as f:
            story_bible_text = f.read()
        has_story_bible = True
        # Extract concept from existing story bible (the user prompt is lost)
        # We'll just say "continue from existing story bible"
        concept = "(Use existing story_bible.md — concept embedded in the document)"

    # --- Check/create chapters directory ---
    ensure_runtime_dirs()

    # --- Generate chapter outline ---
    if args.regen_beats and not args.regen_outline:
        # Skip outline, go straight to beats from existing
        pass
    else:
        print("=== Generating Chapter Outline ===")
        print()

        if has_story_bible:
            outline_prompt = f"""Based on the existing story bible below, generate a chapter outline for the full story.

STORY BIBLE:
{story_bible_text}

TASK: Create a chapter outline with exactly {num_chapters} chapters.
For each chapter provide:
- Chapter number and title
- A one-line summary of what happens in that chapter
- A brief note on how it ends / what it sets up for the next chapter

FORMAT your response exactly as follows (one chapter per line, keep summaries concise):

# Chapter Outline

1. **Chapter 1 — [Title]** — [One line what happens] → ends: [setup for Ch2]
2. **Chapter 2 — [Title]** — [One line what happens] → ends: [setup for Ch3]
...and so on through Chapter {num_chapters}

Do not include any preamble, commentary, or extra text. Output only the outline."""
        else:
            outline_prompt = f"""Story concept: {concept}

TASK: You are a story architect. Create a complete chapter outline for this story concept.

First, fill in the story bible (all bracketed placeholders) with creative choices.
Then create a chapter outline with exactly {num_chapters} chapters.

For each chapter provide:
- Chapter number and title
- A one-line summary of what happens in that chapter
- A brief note on how it ends / what it sets up for the next chapter

FORMAT your response exactly as follows:

# [STORY TITLE]
## Story Bible
[Fill in the complete story bible — all characters, world rules, themes]

---

# Chapter Outline

1. **Chapter 1 — [Title]** — [One line what happens] → ends: [setup for Ch2]
2. **Chapter 2 — [Title]** — [One line what happens] → ends: [setup for Ch3]
...and so on through Chapter {num_chapters}

Do not include any preamble, commentary, or extra text. Output only the story bible and outline."""

        print("Streaming outline:")
        print("-" * 40)
        outline_output = stream_llm(outline_prompt, model="outline")
        print("-" * 40)
        print()

        # Save raw output
        with open(raw_output_path("llm_raw_output.txt"), "w") as f:
            f.write(outline_output)

        if not has_story_bible:
            story_bible_content, outline_content = split_story_bible_and_outline(outline_output)
            if not outline_content:
                print("ERROR: Could not parse chapter outline from combined output")
                sys.exit(1)

            with open(story_bible_path, "w") as f:
                f.write(story_bible_content)
            print(f"✓ story_bible.md written ({len(story_bible_content.split())} words)")
        else:
            outline_content = outline_output.strip()

        outline_entries = parse_outline_entries(outline_content)
        if not outline_entries:
            print("ERROR: Could not parse chapter entries from generated outline")
            sys.exit(1)

        normalized_outline = build_outline_section(outline_entries)
        base_story_bible, _ = split_story_bible_and_outline(story_bible_text if has_story_bible else story_bible_content)
        with open(story_bible_path, "w") as f:
            f.write(merge_story_bible_and_outline(base_story_bible, normalized_outline))
        print(f"✓ Chapter outline written to story_bible.md")
        print()

    # --- Optionally generate all chapter briefs ---
    if args.beats or args.regen_beats:
        # Load story bible and outline
        with open(story_bible_path) as f:
            full_text = f.read()

        story_bible_core, outline_section = split_story_bible_and_outline(full_text)
        if not outline_section:
            print("ERROR: Could not find chapter outline in story_bible.md")
            sys.exit(1)
        chapter_entries = parse_outline_entries(outline_section)

        if not chapter_entries:
            print("ERROR: Could not parse chapter entries from outline")
            print(f"Outline section:\n{outline_section[:500]}")
            sys.exit(1)

        print(f"=== Generating Chapter Briefs for {len(chapter_entries)} Chapters ===")
        print()

        # Load beats template from chapter 1 if it exists AND has actual content
        template_path = CHAPTER_BEATS_TEMPLATE_PATH
        if os.path.exists(template_path) and os.path.getsize(template_path) > 50:
            with open(template_path) as f:
                beats_template = f.read()

        for entry in chapter_entries:
            ch_num = str(entry.number)
            ch_title = entry.title
            beats_file = chapter_beats_path(ch_num)
            skip_chapter = os.path.exists(beats_file) and not args.regen_beats
            if skip_chapter:
                print(f"  Skipping Chapter {ch_num} (already exists)")
                continue

            print(f"  Generating Chapter {ch_num} — {ch_title}")

            system_prompt = "You are a story architect."
            current_template = beats_template
            if "{chapter}" in current_template:
                current_template = current_template.format(chapter=ch_num, title=ch_title)
            user_prompt = build_chapter_beats_prompt(
                story_bible_core,
                ch_num,
                cumulative_summary="",
                beats_template=current_template,
            )

            beats_content = stream_llm(user_prompt, model=get_model("beats"), system=system_prompt)
            print()

            issues = analyze_beats_document(beats_content)
            if issues:
                print(
                    f"  Repairing Chapter {ch_num} brief because: "
                    + "; ".join(issues[:3])
                )
                repair_prompt = (
                    f"Rewrite this chapter brief so it is clean and draftable for Chapter {ch_num}.\n\n"
                    f"ISSUES TO FIX:\n" + "\n".join(f"- {issue}" for issue in issues) + "\n\n"
                    "REQUIREMENTS:\n"
                    "- Keep the same planned chapter events and ending direction\n"
                    "- Output only the chapter brief document\n"
                    "- Use 4-6 concrete, distinct beat sections\n"
                    "- Remove placeholders, duplicated beats, and vague filler\n\n"
                    f"CURRENT BRIEF:\n{beats_content}"
                )
                beats_content = stream_llm(
                    repair_prompt,
                    model=get_model("beats"),
                    system="You repair malformed chapter briefs into clean drafting plans.",
                )
                print()
                issues = analyze_beats_document(beats_content)

            if issues:
                print(f"  ⚠ WARNING: Generated beats for Chapter {ch_num} still look wrong")
                print(f"  ⚠ Issues: {'; '.join(issues[:3])}")
                print(f"  ⚠ NOT writing chapter_{ch_num}_beats.md — run with --regen-beats to retry")
                print(f"  ⚠ If this persists, check if local LLM context window is too small")
                continue

            with open(beats_file, "w") as f:
                f.write(beats_content)
            print(f"  ✓ chapter_{ch_num}_beats.md written")

        print()
        print(f"✓ All chapter briefs generated")
        print()
        print("Ready to write! Run:")
        print("  python3 generate_chapter.py 1")

    else:
        print("Chapter outline generated.")
        print()
        print(f"To review the outline, open: {story_bible_path}")
        print()
        print("Next steps:")
        print("  python3 plan_chapters.py --beats          # generate all chapter briefs")
        print("  python3 plan_chapters.py --beats --regen-beats  # regenerate all chapter briefs")

if __name__ == "__main__":
    main()
