#!/usr/bin/env python3
"""
generate_chapter.py — Generate a chapter (or all chapters) using the story pipeline.

Usage:
    python3 generate_chapter.py 1              # generate chapter 1
    python3 generate_chapter.py --all         # generate all chapters sequentially
    python3 generate_chapter.py --all --no-skip # overwrite existing drafts
"""
import argparse
import glob
import os
import re
import subprocess
import sys

from dual_llm import stream_llm
from config import get_word_count_target


# ── helpers ──────────────────────────────────────────────────────────────────

def init_cumulative(script_dir):
    path = os.path.join(script_dir, "cumulative_summary.md")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w") as f:
            f.write(
                "# Story So Far\n\n"
                "Completed Chapters: 0\n\n"
                "---\n\n"
                "_This document grows as chapters are completed. Each summarized chapter appends here._\n\n"
            )
    return path


# ── core chapter generation ───────────────────────────────────────────────────

def generate_chapter(chapter, script_dir, silent=False, output_file=None):
    """Read inputs, call LLM, write draft. Returns (word_count, output_path)."""
    story_bible    = os.path.join(script_dir, "story_bible.md")
    cumulative     = init_cumulative(script_dir)
    chapter_beats  = os.path.join(script_dir, f"chapters/chapter_{chapter}_beats.md")
    system_prompt_file = os.path.join(script_dir, "system_prompt.txt")

    for f in [story_bible, cumulative, chapter_beats, system_prompt_file]:
        if not os.path.exists(f):
            print(f"ERROR: Missing required file: {f}")
            sys.exit(1)

    with open(story_bible) as f:
        story_bible_text = f.read()
    with open(cumulative) as f:
        cumulative_text = f.read()
    with open(chapter_beats) as f:
        beats_content = f.read()
    with open(system_prompt_file) as f:
        system_prompt = f.read()

    target_words = get_word_count_target()

    prompt = f"""{system_prompt}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT (from cumulative_summary.md):
{cumulative_text}

BEATS FOR CHAPTER {chapter}:
{beats_content}

YOUR TASK:
Generate a complete draft for Chapter {chapter} based on the story bible, current context, and beats.

Write the chapter as a continuous narrative (approximately {target_words:,} words), following the beats and maintaining consistency with the story bible.

Include:
- Natural dialogue and descriptive passages
- Character development and interactions
- Scene transitions and setting details
- Plot progression that builds on established elements

Output only the chapter content (no preamble or commentary).

---

CHAPTER {chapter} DRAFT:
"""

    if not silent:
        print(f"\nGenerating Chapter {chapter} (streaming)...\n")
        print("-" * 60)

    draft = stream_llm(prompt, system="", silent=silent)

    if not silent:
        print("\n" + "-" * 60)

    os.makedirs(os.path.join(script_dir, "chapters"), exist_ok=True)

    if output_file:
        output_path = os.path.join(script_dir, output_file)
    else:
        output_path = os.path.join(script_dir, f"chapters/chapter_{chapter}_draft.txt")

    with open(output_path, "w") as f:
        f.write(draft)

    return len(draft.split()), output_path


# ── next-beats generation (used by --all workflow) ──────────────────────────

def generate_next_chapter_beats(chapter, script_dir):
    """Generate chapter N+1 beats if they don't already exist. Returns beats path or None."""
    next_chapter  = str(int(chapter) + 1)
    next_beats    = os.path.join(script_dir, f"chapters/chapter_{next_chapter}_beats.md")

    if os.path.exists(next_beats):
        return None

    with open(os.path.join(script_dir, "story_bible.md")) as f:
        story_bible = f.read()
    with open(os.path.join(script_dir, "cumulative_summary.md")) as f:
        summary_content = f.read()
    with open(os.path.join(script_dir, f"chapters/chapter_{chapter}_beats.md")) as f:
        beats_format = f.read()

    system_prompt = "You are a story architect."
    user_prompt = f"""Based on the story so far, write detailed beats for Chapter {next_chapter}.

STORY BIBLE (do not change these established facts):
{story_bible}

STORY SO FAR (cumulative summary):
{summary_content}

CHAPTER {next_chapter} BEATS TEMPLATE (follow this format):
{beats_format}

INSTRUCTIONS:
- Continue the story from where Chapter {chapter} left off
- Follow the same level of detail as the template above
- Be specific: name characters, describe scenes, give dialogue cues
- Plant seeds for future chapters in "Open Threads / Loose Ends"
- Do not include any preamble or commentary — output only the beats document"""

    content = stream_llm(user_prompt, model="beats", system=system_prompt)

    with open(next_beats, "w") as f:
        f.write(content)

    return next_beats


# ── --all sequential workflow ────────────────────────────────────────────────

def generate_all_sequential(script_dir, skip_existing=True, silent=False):
    """
    For each chapter that has beats but no draft:
      1. Generate the chapter draft
      2. Run summarize_chapter.py <ch> as a subprocess (summarizes + generates next beats)
    """
    chapters_dir = os.path.join(script_dir, "chapters")
    beats_files = sorted(
        glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
        key=lambda p: int(re.search(r"chapter_(\d+)_beats", p).group(1)),
    )

    if not beats_files:
        print("No chapter beats found in chapters/. Run plan_chapters.py --beats first.")
        sys.exit(1)

    chapter_nums = []
    for bf in beats_files:
        m = re.search(r"chapter_(\d+)_beats", bf)
        if m:
            chapter_nums.append(int(m.group(1)))

    if not chapter_nums:
        print("Could not parse chapter numbers from beats filenames.")
        sys.exit(1)

    min_c, max_c = min(chapter_nums), max(chapter_nums)
    print(f"Found beats for chapters {min_c}–{max_c} ({len(chapter_nums)} chapters)")
    print()
    print("Workflow: Generate → Summarize → Next Beats")
    print("=" * 70)
    print()

    # Use a dynamic loop: after processing chapter N, check if chapter N+1
    # now has beats (possibly generated by summarize_chapter.py). Keep going
    # until we reach a chapter with no beats — that means the story bible's
    # planned chapter count has been reached.
    ch = min_c
    while True:
        ch_str = str(ch)
        draft_path = os.path.join(chapters_dir, f"chapter_{ch_str}_draft.txt")
        beats_path = os.path.join(chapters_dir, f"chapter_{ch_str}_beats.md")

        if not os.path.exists(beats_path):
            # No beats for this chapter — story is complete
            break

        if skip_existing and os.path.exists(draft_path):
            print(f"[{ch_str}] Skipping chapter {ch_str} — draft exists")
            ch += 1
            continue

        print(f"\n[{ch_str}] Generating chapter {ch_str}...")
        wc, _ = generate_chapter(ch_str, script_dir, silent=silent)
        print(f"  ✓ chapter_{ch_str}_draft.txt written ({wc:,} words)")

        # Summarize + generate next beats via the existing summarize_chapter.py script
        print(f"  → Summarizing chapter {ch_str}...")
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "summarize_chapter.py"), ch_str, "--quiet"],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"  ⚠ summarize_chapter.py exited with code {result.returncode}")
        else:
            print(f"  ✓ chapter {ch_str} summarized, cumulative_summary.md updated")

        # Generate next-beats directly (summarize_chapter.py may have already done this)
        next_beats_path = os.path.join(chapters_dir, f"chapter_{ch+1}_beats.md")
        if os.path.exists(next_beats_path):
            print(f"  ✓ chapter_{ch+1}_beats.md already exists")
        else:
            print(f"  → Generating chapter_{ch+1}_beats.md...")
            try:
                bp = generate_next_chapter_beats(ch_str, script_dir)
                if bp:
                    print(f"  ✓ chapter_{ch+1}_beats.md written")
            except Exception as e:
                print(f"  ⚠ Could not generate next beats: {e}")

        print()
        ch += 1

    print("=" * 70)
    print(f"All chapters complete. Check chapters/ for drafts and cumulative_summary.md for the story so far.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def show_beats_status(script_dir):
    chapters_dir = os.path.join(script_dir, "chapters")
    beats_files = sorted(
        glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
        key=lambda p: int(re.search(r"chapter_(\d+)_beats", p).group(1)),
    )
    if not beats_files:
        print("No chapter beats found in chapters/.")
        return
    print("\n" + "=" * 70)
    print("  CHAPTER BEATS STATUS")
    print("=" * 70 + "\n")
    for bf in beats_files:
        ch = re.search(r"chapter_(\d+)_beats", os.path.basename(bf)).group(1)
        draft = os.path.join(chapters_dir, f"chapter_{ch}_draft.txt")
        status = "✓ Draft exists" if os.path.exists(draft) else "○ No draft"
        print(f"Chapter {ch}: {status}")


def main():
    parser = argparse.ArgumentParser(description="Generate chapter drafts")
    parser.add_argument("chapter", nargs="?", help="Chapter number to generate (or omit with --all)")
    parser.add_argument("--all", action="store_true", help="Generate all chapters sequentially")
    parser.add_argument("--beats", action="store_true", help="Show available chapter beats and their status")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip", action="store_false", dest="skip_existing")
    parser.add_argument("output_file", nargs="?", help="Custom output path")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(script_dir, "chapters"), exist_ok=True)

    if args.all:
        print("\n" + "=" * 70)
        print("  Sequential --all Workflow")
        print("  Each chapter: generate → summarize → next beats")
        print("=" * 70 + "\n")
        generate_all_sequential(script_dir, skip_existing=args.skip_existing)
        return

    if args.beats:
        show_beats_status(script_dir)
        return

    if not args.chapter:
        parser.print_help()
        sys.exit(1)

    wc, path = generate_chapter(args.chapter, script_dir)
    print(f"Chapter {args.chapter} written to {path} ({wc:,} words)\n")
    print("Next steps:")
    print(f"  1. Review: {path}")
    print(f"  2. python3 summarize_chapter.py {args.chapter}")


if __name__ == "__main__":
    main()
