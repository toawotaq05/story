#!/usr/bin/env python3
"""
status.py — Show the current state of the story project.

Usage: python3 status.py
"""
import os, glob, re
from config import get_word_count_target

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chapters_dir = os.path.join(script_dir, "chapters")
    story_bible = os.path.join(script_dir, "story_bible.md")
    cumulative = os.path.join(script_dir, "cumulative_summary.md")

    print("=" * 50)
    print("STORY PIPELINE STATUS")
    print("=" * 50)
    print()

    # --- Story bible ---
    if os.path.exists(story_bible):
        with open(story_bible) as f:
            sb = f.read()
        # Extract title
        title = "Untitled"
        for line in sb.split("\n"):
            if line.startswith("# ") and not line.startswith("##"):
                title = line[2:].strip()
                break
        # Extract outline chapters
        import re
        outline_entries = re.findall(r'^\d+\.\s+\*\*Chapter\s+(\d+)', sb, re.MULTILINE)
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
        m = re.search(r'Completed Chapters:\s*(\d+)', cum)
        if m:
            completed = int(m.group(1))
        summaries = re.findall(r'^### Chapter \d+', cum, re.MULTILINE)
        print(f"  Completed chapters: {completed}")
        if summaries:
            print(f"  Chapter summaries in cumulative_summary.md:")
            for s in summaries:
                print(f"    {s[4:]}")  # strip "### "
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
        for m in re.finditer(r'^\d+\.\s+\*\*Chapter\s+(\d+)\s*—\s*([^*]+)\*\*', sb, re.MULTILINE):
            num = m.group(1).lstrip('0') or m.group(1)
            title = m.group(2).strip()
            planned_map[num] = title

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
    import re
    main()
