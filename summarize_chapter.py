#!/usr/bin/env python3
"""
summarize_chapter.py — Summarize a completed chapter, update cumulative_summary.md,
and generate the next chapter's beats. Streaming output enabled.
"""
import argparse
import os
import re
import sys

from dual_llm import stream_llm
from config import get_default_chapters


def main():
    parser = argparse.ArgumentParser(description="Summarize a chapter and generate next beats")
    parser.add_argument("chapter", help="Chapter number to summarize")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress non-essential output (useful when called by generate_chapter.py --all)")
    args = parser.parse_args()

    script_dir   = os.path.dirname(os.path.abspath(__file__))
    chapter      = args.chapter
    next_chapter = str(int(chapter) + 1)

    chapter_draft = os.path.join(script_dir, f"chapters/chapter_{chapter}_draft.txt")
    next_beats    = os.path.join(script_dir, f"chapters/chapter_{next_chapter}_beats.md")
    cumulative    = os.path.join(script_dir, "cumulative_summary.md")
    story_bible   = os.path.join(script_dir, "story_bible.md")

    if not os.path.exists(chapter_draft):
        print(f"ERROR: Chapter draft not found: {chapter_draft}")
        print(f"Run: python3 generate_chapter.py {chapter}")
        sys.exit(1)

    with open(chapter_draft) as f:
        draft_content = f.read()

    print(f"=== Summarizing Chapter {chapter} ===\n")

    # Read cumulative to check current state
    if os.path.exists(cumulative):
        with open(cumulative) as f:
            existing_cum = f.read()
    else:
        existing_cum = ""

    system_prompt = (
        "You are a story analyst. Read the chapter draft below and produce a "
        "structured summary. Follow the format exactly."
    )
    user_prompt = f"""Chapter to summarize:

---

{draft_content}

---

Format your response EXACTLY as follows — do not add any preamble, commentary, or extra text:

### Chapter {chapter} — [TWO TO FOUR WORD CHAPTER TITLE]
[4-6 sentences: what happens in order, key character decisions, setting details established, how the chapter ends and what it sets up for the next chapter]

### Key Plot Points Established
- [Important fact, reveal, or event established in this chapter]
- ...

### Character Status
- [Character name]: [Their state at end of chapter — location, emotional state, relationship changes]
- ...

### Open Threads / Loose Ends
- [Question raised, setup planted, or tension left unresolved]
- ..."""

    print("Summarizing chapter (streaming):")
    print("-" * 40)
    try:
        summary = stream_llm(user_prompt, model="summarize", system=system_prompt)
    except Exception as e:
        print(f"\nERROR: LLM call failed during summarization: {e}", file=sys.stderr)
        sys.exit(1)
    print("-" * 40)
    print()

    if not summary or len(summary.strip()) < 50:
        print(f"ERROR: Summary is empty or too short ({len(summary.strip()) if summary else 0} chars)", file=sys.stderr)
        print("The LLM may have returned an empty response. Check your server.", file=sys.stderr)
        sys.exit(1)

    with open(cumulative, "a") as f:
        f.write("\n" + summary)

    with open(cumulative) as f:
        content = f.read()

    new_content = re.sub(
        r"(Completed Chapters:\s*)\d+",
        rf"\g<1>{chapter}",
        content,
    )
    with open(cumulative, "w") as f:
        f.write(new_content)

    # Verify the update stuck
    with open(cumulative) as f:
        verify = f.read()
    if f"Completed Chapters: {chapter}" not in verify:
        print(f"WARNING: cumulative_summary.md may not have updated correctly", file=sys.stderr)
    else:
        print(f"✓ Chapter {chapter} summarized — cumulative_summary.md updated (Completed Chapters: {chapter})")

    # --- Generate next chapter beats ---
    with open(story_bible) as f:
        story_bible_text = f.read()
    with open(os.path.join(script_dir, f"chapters/chapter_{chapter}_beats.md")) as f:
        beats_format = f.read()

    system_prompt2 = "You are a story architect."
    user_prompt2 = f"""Based on the story so far, write detailed beats for Chapter {next_chapter}.

STORY BIBLE (do not change these established facts):
{story_bible_text}

STORY SO FAR (cumulative summary):
{content}

CHAPTER {next_chapter} BEATS TEMPLATE (follow this format):
{beats_format}

INSTRUCTIONS:
- Continue the story from where Chapter {chapter} left off
- Follow the same level of detail as the template above
- Be specific: name characters, describe scenes, give dialogue cues
- Plant seeds for future chapters in "Open Threads / Loose Ends"
- Do not include any preamble or commentary — output only the beats document"""

    total_chapters = get_default_chapters()
    is_last_chapter = int(chapter) >= total_chapters

    if is_last_chapter:
        print(f"\n✓ Final chapter ({chapter}/{total_chapters}) summarized — no next beats needed.")
    elif os.path.exists(next_beats):
        print(f"Note: chapters/chapter_{next_chapter}_beats.md already exists — skipping beats generation.")
    else:
        print()
        print(f"Generating Chapter {next_chapter} beats (streaming):")
        print("-" * 40)
        try:
            next_beats_content = stream_llm(user_prompt2, model="beats", system=system_prompt2)
        except Exception as e:
            print(f"\nERROR: LLM call failed during beats generation: {e}", file=sys.stderr)
            sys.exit(1)
        print("-" * 40)
        print()

        if not next_beats_content or len(next_beats_content.strip()) < 50:
            print(f"ERROR: Next beats output is empty or too short ({len(next_beats_content.strip()) if next_beats_content else 0} chars)", file=sys.stderr)
            sys.exit(1)

        with open(next_beats, "w") as f:
            f.write(next_beats_content)
        print(f"✓ chapters/chapter_{next_chapter}_beats.md written")

    print()
    print("Current completed chapters:")
    for line in content.split("\n"):
        if "Completed Chapters" in line:
            print(" ", line)
            break
    print()
    print("Chapter summaries so far:")
    for line in content.split("\n"):
        if line.startswith("### Chapter "):
            print(" ", line)
    if not args.quiet:
        print()
        print("Next step:")
        print(f"  python3 generate_chapter.py {next_chapter}")


if __name__ == "__main__":
    main()
