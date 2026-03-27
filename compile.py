#!/usr/bin/env python3
"""
compile.py — Assemble all chapter drafts into a single .md ebook.

Usage:
    python3 compile.py                  # default: output book.md
    python3 compile.py --output mybook.md
    python3 compile.py --dry-run          # preview without writing
"""
import os, re, argparse, glob

DEFAULT_OUTPUT = "book.md"

def count_words(text):
    return len(text.split())

def extract_title(story_bible_path):
    """Pull the first # Title from story_bible.md."""
    if not os.path.exists(story_bible_path):
        return "Untitled Story"
    with open(story_bible_path) as f:
        for line in f:
            m = re.match(r"^#\s+(.+)", line)
            if m:
                return m.group(1).strip()
    return "Untitled Story"

def extract_chapter_title(story_bible_path, chapter_num):
    """Find 'N. **Chapter Title**' from the outline in story_bible.md."""
    if not os.path.exists(story_bible_path):
        return None
    with open(story_bible_path) as f:
        content = f.read()
    # Match lines like: 1. **Chapter 1 - The Letter** — ...
    pattern = rf"^\d+\.\s+\*\*Chapter\s+\d+\s*[-–—]\s*([^*`]+?)\*\*"
    for line in content.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            return m.group(1).strip()
    return None

def get_chapter_order(story_bible_path):
    """Return ordered list of (chapter_num, title) from outline."""
    if not os.path.exists(story_bible_path):
        return []
    with open(story_bible_path) as f:
        content = f.read()
    results = []
    for line in content.splitlines():
        m = re.match(r"^(\d+)\.\s+\*\*([^*]+)\*\*", line.strip())
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            results.append((num, title))
    return results

def get_word_count_annotation(word_count, target):
    """Return a small annotation string if worthwhile."""
    if word_count < target * 0.7:
        return f" (~{word_count:,} words — short)"
    elif word_count > target * 1.3:
        return f" (~{word_count:,} words — long)"
    return f" (~{word_count:,} words)"

def compile_book(output_path=None, dry_run=False):
    root = os.path.dirname(__file__)
    story_bible = os.path.join(root, "story_bible.md")
    chapters_dir = os.path.join(root, "chapters")

    output_path = output_path or os.path.join(root, DEFAULT_OUTPUT)

    title = extract_title(story_bible)
    chapter_order = get_chapter_order(story_bible)

    # Collect all existing drafts
    draft_files = sorted(glob.glob(os.path.join(chapters_dir, "chapter_*_draft.txt")))

    if not draft_files:
        print("No chapter drafts found in chapters/. Run generate_chapter.py first.")
        return

    lines = []
    lines.append(f"# {title}\n")
    lines.append(f"_Compiled: {len(draft_files)} chapters_\n")
    lines.append("\n---\n")

    target_path = os.path.join(root, "config.json")
    target = 25000
    if os.path.exists(target_path):
        import json
        with open(target_path) as f:
            target = json.load(f).get("story", {}).get("word_count_target", 25000)

    for draft_path in draft_files:
        # Extract chapter number from filename: chapter_1_draft.txt
        basename = os.path.basename(draft_path)
        m = re.match(r"chapter_(\d+)_draft\.txt", basename)
        if not m:
            continue
        chapter_num = int(m.group(1))

        with open(draft_path) as f:
            draft_text = f.read().strip()

        word_count = count_words(draft_text)
        annotation = get_word_count_annotation(word_count, target // len(draft_files))

        # Try to get the title from the outline
        chapter_title = None
        for cnum, ctitle in chapter_order:
            if cnum == chapter_num:
                chapter_title = ctitle
                break

        if chapter_title:
            lines.append(f"## Chapter {chapter_num}: {chapter_title}{annotation}\n")
        else:
            lines.append(f"## Chapter {chapter_num}{annotation}\n")
        lines.append(draft_text)
        lines.append("\n\n---\n")

    assembled = "\n".join(lines)

    if dry_run:
        print(assembled)
        print(f"\n[dry-run] Would write {len(assembled.split())} words to {output_path}")
        return

    with open(output_path, "w") as f:
        f.write(assembled)

    total_words = count_words(assembled)
    print(f"Compiled {len(draft_files)} chapters ({total_words:,} words) -> {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assemble chapter drafts into a single .md book")
    parser.add_argument("--output", help=f"Output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing file")
    args = parser.parse_args()
    compile_book(output_path=args.output, dry_run=args.dry_run)
