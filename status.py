#!/usr/bin/env python3
"""
status.py — Show the current state of the story project.

Usage: python3 status.py
"""
import os, glob, re
from config import get_word_count_target
from paths import CHAPTERS_DIR, CUMULATIVE_SUMMARY_PATH, STORY_BIBLE_PATH, PROJECT_DIR
from story_utils import extract_story_title, extract_summary_headers, parse_completed_chapters, parse_outline_entries, split_story_bible_and_outline

def main():
    chapters_dir = CHAPTERS_DIR
    story_bible = STORY_BIBLE_PATH
    cumulative = CUMULATIVE_SUMMARY_PATH

    print("=" * 50)
    print("STORY PIPELINE STATUS")
    print("=" * 50)
    print(f"Project dir: {PROJECT_DIR}")
    print(f"Chapters dir: {chapters_dir}")
    print()

    # --- Story bible ---
    if os.path.exists(story_bible):
        with open(story_bible) as f:
            sb = f.read()
        title = extract_story_title(sb)
        _, outline_section = split_story_bible_and_outline(sb)
        outline_entries = parse_outline_entries(outline_section)
        planned = len(outline_entries)
        print(f"  Title:   {title}")
        print(f"  Planned chapters: {planned if planned > 0 else '? (run plan_chapters.py)'}")
    else:
        print("  story_bible.md: NOT FOUND (run build_story_bible.py)")
    print()

    # --- Cumulative summary ---
    completed = 0
    if os.path.exists(cumulative):
        with open(cumulative) as f:
            cum = f.read()
        completed = parse_completed_chapters(cum)
        summaries = extract_summary_headers(cum)
        print(f"  Completed chapters: {completed}")
        if summaries:
            print(f"  Chapter summaries in cumulative_summary.md:")
            for number, title in summaries:
                print(f"    Chapter {number} — {title}")
    else:
        print("  cumulative_summary.md: NOT FOUND")
    print()

    # --- Chapters ---
    print("  Chapters:")
    beats_files = sorted(glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")))
    draft_files = sorted(glob.glob(os.path.join(chapters_dir, "chapter_*_draft.txt")))

    draft_map = {}
    for d in draft_files:
        bn = os.path.basename(d)
        # extract chapter number
        import re
        m = re.search(r'chapter_(\d+)_draft', bn)
        if m:
            draft_map[m.group(1)] = d

    # Extract planned from story bible outline
    planned_map = {}
    if os.path.exists(story_bible):
        with open(story_bible) as f:
            sb = f.read()
        _, outline_section = split_story_bible_and_outline(sb)
        for entry in parse_outline_entries(outline_section):
            planned_map[str(entry.number)] = entry.title

    all_chapters = set(list(draft_map.keys()) + list(planned_map.keys()))
    if not all_chapters:
        print("    No chapters found.")
    else:
        for ch in sorted(all_chapters, key=lambda x: int(x)):
            parts = []
            if ch in planned_map:
                parts.append(f'"{planned_map[ch]}"')
            if ch in draft_map:
                wc = 0
                with open(draft_map[ch]) as f:
                    text = f.read()
                    wc = len(text.split())
                parts.append(f"{wc} words")
            status = " · ".join(parts) if parts else "?"
            print(f"    Ch{ch}: {status}")

    # --- Total word count ---
    total_wc = 0
    for d in draft_files:
        with open(d) as f:
            total_wc += len(f.read().split())
    target = get_word_count_target()
    if total_wc > 0:
        pct = int(total_wc / target * 100)
        print()
        print(f"  Total draft words: {total_wc:,} / {target:,} ({pct}%)")
    else:
        print()
        print(f"  Total draft words: 0 (target: {target:,})")
    print()
    print("=" * 50)

if __name__ == "__main__":
    main()
