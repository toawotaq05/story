#!/usr/bin/env python3
"""
summarize_chapter.py — Summarize a completed chapter, update cumulative_summary.md,
and generate the next chapter's beats. Streaming output enabled.
"""
import sys, os
from dual_llm import stream_llm
from config import get_model
from paths import (
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    chapter_beats_path,
    chapter_draft_path,
)
from story_utils import extract_summary_headers, set_completed_chapters, upsert_chapter_summary

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 summarize_chapter.py <chapter_number>")
        sys.exit(1)

    chapter = sys.argv[1]
    next_chapter = str(int(chapter) + 1)
    chapter_draft = chapter_draft_path(chapter)
    next_beats = chapter_beats_path(next_chapter)
    cumulative = CUMULATIVE_SUMMARY_PATH
    story_bible = STORY_BIBLE_PATH

    if not os.path.exists(chapter_draft):
        print(f"ERROR: Chapter draft not found: {chapter_draft}")
        print(f"Run: python3 generate_chapter.py {chapter}")
        sys.exit(1)

    with open(chapter_draft) as f:
        draft_content = f.read()

    print(f"=== Summarizing Chapter {chapter} ===")
    print()

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
    summary = stream_llm(user_prompt, system=system_prompt)
    print("-" * 40)
    print()

    existing_content = ""
    if os.path.exists(cumulative):
        with open(cumulative) as f:
            existing_content = f.read()

    updated_content = upsert_chapter_summary(existing_content, chapter, summary)
    new_content = set_completed_chapters(updated_content, chapter)
    with open(cumulative, "w") as f:
        f.write(new_content)
    content = new_content

    print(f"✓ Chapter {chapter} summarized")

    # --- Generate next chapter beats ---
    with open(story_bible) as f:
        story_bible_text = f.read()
    current_beats = chapter_beats_path(chapter)
    with open(current_beats) as f:
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

    if os.path.exists(next_beats):
        print(f"Note: chapters/chapter_{next_chapter}_beats.md already exists — skipping beats generation.")
    else:
        print()
        print(f"Generating Chapter {next_chapter} beats (streaming):")
        print("-" * 40)
        next_beats_content = stream_llm(user_prompt2, model=get_model("beats"), system=system_prompt2)
        print("-" * 40)
        print()
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
    for chapter_number, title in extract_summary_headers(content):
        print(f"  Chapter {chapter_number} — {title}")
    print()
    print("Next step:")
    print(f"  python3 generate_chapter.py {next_chapter}")

if __name__ == "__main__":
    main()
