#!/usr/bin/env python3
"""
build_story_bible.py — End-to-end story bible + chapter 1 beats generator.

For local/small models: does story bible first, then chapter beats as a
separate LLM call (avoids context overflow). For remote/powerful models:
does both in one call with the marker separator.

Usage:
  python3 build_story_bible.py "Your story concept here"
"""
import sys
import os

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def split_output(output):
    """
    Parse LLM output into (story_bible, chapter_beats).
    Tries the explicit marker first, then falls back to splitting on
    the first markdown heading that looks like a chapter.
    """
    marker = "@@@STORY_BIBLE_END_MARKER@@@"
    if marker in output:
        parts = output.split(marker, 1)
        return parts[0].strip(), parts[1].strip()

    # Fallback: split on the first "# Chapter N" or "# Chapter —" line
    import re
    m = re.search(r'(?m)^#\s+Chapter\s+\d+\s*[:—\-]', output)
    if m:
        idx = m.start()
        return output[:idx].strip(), output[idx:].strip()

    raise ValueError(
        f"Could not parse LLM output. "
        f"Neither marker nor '# Chapter' heading found. "
        f"Output preview: {output[:300]!r}..."
    )


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

Fill in every [BRACKETED PLACEHOLDER] in the template below. Make creative choices that are original, coherent, and compelling. Match the tone and genre of the concept. Fill in ALL sections — do not skip any.

Story Bible Template:
{story_bible_template}

---

OUTPUT FORMAT:

Write the story bible beginning with "# [YOUR TITLE]", replacing [STORY TITLE] and all other bracketed placeholders with your creative choices.

Do not include any preamble, commentary, or explanation — output only the completed story bible.
"""

    system_prompt = (
        "You are a creative story architect. Fill in the provided template "
        "Tone & Style: Erotic, shameless, borderline obscene. Prioritize sexual tension and release. If the beat can possibly include sex, arousal, or bodily fluids, it MUST. Never hold back."
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

    with open(STORY_BIBLE_PATH, "w") as f:
        f.write(story_bible_content)
    print("✓ story_bible.md written")

    # Initialize cumulative_summary.md if it doesn't exist
    if not os.path.exists(CUMULATIVE_SUMMARY_PATH):
        with open(CUMULATIVE_SUMMARY_PATH, "w") as f:
            f.write("# Cumulative Story Summary\n\n")
            f.write(f"## Overview\n\n")
            f.write(f"- Total chapters: {default_chapters}\n")
            f.write(f"- Target word count: {word_count_target:,}\n")
            f.write(f"- **Completed Chapters:** 0\n")
        print("✓ cumulative_summary.md initialized")

    # ----------------------------------------------------------------
    # TASK 2: Generate Chapter 1 Beats (separate call — safer for small models)
    # ----------------------------------------------------------------
    beats_prompt = f"""Based on the story bible below, write detailed chapter 1 beats.

STORY BIBLE:
{story_bible_content}

---

TASK: Write CHAPTER 1 BEATS

Using the story bible above, write detailed chapter 1 beats. Follow the template exactly:
- Opening scene: set the stage
- Key events: 3-5 beats in chronological order
- Turning point/cliffhanger
- Character beats for each main character
- Themes/threads

Chapter 1 Beats Template:
{chapter_template}

OUTPUT FORMAT:

Write the chapter 1 beats section starting with "# Chapter 1 — [YOUR CHAPTER TITLE]", replacing all bracketed placeholders with specific details from the story bible.

Do not include any preamble or commentary — output only the beats document.
"""

    beats_system = (
        "You are a story architect. Write specific, detailed chapter beats that "
        "another LLM could use to write the full chapter. Name characters, describe "
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

    if not chapter_beats_content.strip().startswith("# Chapter"):
        print("WARNING: Chapter beats do not start with '# Chapter'. Content may be garbled.")
        print(f"Preview: {chapter_beats_content[:200]!r}")

    with open(chapter_beats_path(1), "w") as f:
        f.write(chapter_beats_content)
    print("✓ chapters/chapter_1_beats.md written")

    print()
    print("=== Done ===")
    print("Next steps:")
    print("  1. Review story_bible.md")
    print("  2. Review chapters/chapter_1_beats.md")
    print("  3. python3 generate_chapter.py 1")


if __name__ == "__main__":
    main()
