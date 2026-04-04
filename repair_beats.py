#!/usr/bin/env python3
"""
repair_beats.py — Validate and repair malformed chapter brief files.

Usage:
  python3 repair_beats.py <chapter_number>   # repair specific chapter
  python3 repair_beats.py --all              # repair all chapters with malformed ones
  python3 repair_beats.py --force <chapter>  # force regeneration even if valid
"""
import os
import sys
import re
import argparse

from chapter_planning import build_chapter_beats_prompt
from dual_llm import stream_llm
from config import get_model
from paths import (
    CHAPTER_BEATS_TEMPLATE_PATH,
    chapter_beats_path,
    get_project_paths,
)
from story_utils import is_valid_beats_document, parse_beats
from story_utils import sanitize_beats_document


def validate_beats_file(beats_path):
    if not os.path.exists(beats_path):
        return False, f"File not found: {beats_path}"
    try:
        with open(beats_path) as f:
            content = f.read()
        beats = parse_beats(content)
        if not beats:
            return False, "No beats could be parsed (missing ### Beat N: sections)"
        if len(beats) < 2:
            return False, f"Only {len(beats)} beat(s) found"
        return True, ""
    except Exception as e:
        return False, f"Parse error: {e}"


def regenerate_beats(chapter, force=False):
    chapter_str = str(chapter)
    runtime_paths = get_project_paths()
    beats_path = chapter_beats_path(chapter_str)

    if not force:
        is_valid, msg = validate_beats_file(beats_path)
        if is_valid:
            print(f"[{chapter_str}] Beats file is valid. Skipping (use --force to regenerate).")
            return True
        else:
            print(f"[{chapter_str}] Beats file invalid: {msg}. Regenerating...")
    else:
        if os.path.exists(beats_path):
            print(f"[{chapter_str}] Force regeneration: overwriting existing beats file.")
        else:
            print(f"[{chapter_str}] Beats file doesn't exist. Generating...")

    if not os.path.exists(runtime_paths.story_bible_path):
        print(f"ERROR: Missing story_bible.md")
        return False
    with open(runtime_paths.story_bible_path) as f:
        story_bible = f.read()

    cumulative_content = ""
    if os.path.exists(runtime_paths.cumulative_summary_path):
        with open(runtime_paths.cumulative_summary_path) as f:
            cumulative_content = f.read()

    with open(CHAPTER_BEATS_TEMPLATE_PATH) as f:
        beats_template = f.read()
    system_prompt = "You are a story architect."
    user_prompt = build_chapter_beats_prompt(
        story_bible,
        chapter_str,
        cumulative_summary=cumulative_content,
        beats_template=beats_template,
    )

    print(f"[{chapter_str}] Generating beats...")
    content = sanitize_beats_document(
        stream_llm(user_prompt, model=get_model("beats"), system=system_prompt, silent=False),
        chapter_number=chapter_str,
        chapter_title=f"Chapter {chapter_str}",
    )

    if not content or len(content.strip()) < 50:
        print(f"ERROR: Beats output is empty or too short ({len(content.strip()) if content else 0} chars)")
        return False
    if not is_valid_beats_document(content):
        print(f"ERROR: Generated beats did not match expected chapter-beats format")
        return False

    os.makedirs(runtime_paths.chapters_dir, exist_ok=True)
    with open(beats_path, "w") as f:
        f.write(content)

    is_valid, msg = validate_beats_file(beats_path)
    if is_valid:
        print(f"[{chapter_str}] ✓ Beats regenerated successfully: {beats_path}")
        return True
    else:
        print(f"[{chapter_str}] ⚠ Regenerated beats still invalid: {msg}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Repair malformed chapter brief files")
    parser.add_argument("chapter", nargs="?", help="Chapter number to repair")
    parser.add_argument("--all", action="store_true", help="Check all chapters and regenerate malformed ones")
    parser.add_argument("--force", action="store_true", help="Force regeneration even if file is valid")
    args = parser.parse_args()

    chapters_dir = get_project_paths().chapters_dir

    if args.all:
        import glob
        beats_files = sorted(
            glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
            key=lambda p: int(re.search(r"chapter_(\d+)_beats", os.path.basename(p)).group(1))
        )
        chapters = [re.search(r"chapter_(\d+)_beats", os.path.basename(p)).group(1) for p in beats_files]
        if not chapters:
            print("No chapter beats files found.")
            return
    elif args.chapter:
        chapters = [args.chapter]
    else:
        parser.print_help()
        return

    success_count = 0
    fail_count = 0
    for ch in chapters:
        if regenerate_beats(ch, force=args.force):
            success_count += 1
        else:
            fail_count += 1

    print(f"\nCompleted: {success_count} succeeded, {fail_count} failed")
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
