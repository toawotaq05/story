#!/usr/bin/env python3
"""
compile.py — Assemble all chapter drafts into a single .md ebook and optional .epub.

Usage:
    python3 compile.py
    python3 compile.py --output mybook.md
    python3 compile.py --project-dir /abs/path/to/project
    python3 compile.py --dry-run
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess

from paths import BOOK_OUTPUT_PATH, CONFIG_PATH, PROJECT_DIR
from story_utils import count_words, extract_story_title, parse_outline_entries, split_story_bible_and_outline


def get_word_count_annotation(word_count, target):
    if word_count < target * 0.7:
        return f" (~{word_count:,} words — short)"
    if word_count > target * 1.3:
        return f" (~{word_count:,} words — long)"
    return f" (~{word_count:,} words)"


def resolve_project_dir(project_dir=None):
    return os.path.abspath(project_dir or PROJECT_DIR)


def resolve_output_paths(project_dir, output_path=None):
    if output_path:
        resolved = os.path.abspath(output_path)
        if os.path.isdir(resolved):
            md_path = os.path.join(resolved, "book.md")
        else:
            base, ext = os.path.splitext(resolved)
            md_path = resolved if ext.lower() == ".md" else resolved + ".md"
    else:
        md_path = os.path.join(project_dir, "book.md")

    base, _ = os.path.splitext(md_path)
    epub_path = base + ".epub"
    return md_path, epub_path


def build_compiled_markdown(project_dir):
    story_bible_path = os.path.join(project_dir, "story_bible.md")
    chapters_dir = os.path.join(project_dir, "chapters")

    title = "Untitled Story"
    chapter_order = []
    if os.path.exists(story_bible_path):
        with open(story_bible_path) as handle:
            story_bible_content = handle.read()
        title = extract_story_title(story_bible_content)
        _, outline_section = split_story_bible_and_outline(story_bible_content)
        chapter_order = [(entry.number, entry.title) for entry in parse_outline_entries(outline_section)]

    draft_files = sorted(glob.glob(os.path.join(chapters_dir, "chapter_*_draft.txt")))
    if not draft_files:
        raise FileNotFoundError("No chapter drafts found in chapters/. Run generate_chapter.py first.")

    target = 25000
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as handle:
            target = json.load(handle).get("story", {}).get("word_count_target", 25000)

    lines = [f"# {title}\n", f"_Compiled: {len(draft_files)} chapters_\n", "\n---\n"]
    for draft_path in draft_files:
        basename = os.path.basename(draft_path)
        match = re.match(r"chapter_(\d+)_draft\.txt", basename)
        if not match:
            continue
        chapter_num = int(match.group(1))
        with open(draft_path) as handle:
            draft_text = handle.read().strip()

        chapter_title = None
        for number, current_title in chapter_order:
            if number == chapter_num:
                chapter_title = current_title
                break

        word_count = count_words(draft_text)
        annotation = get_word_count_annotation(word_count, max(target // len(draft_files), 1))
        if chapter_title:
            lines.append(f"## Chapter {chapter_num}: {chapter_title}{annotation}\n")
        else:
            lines.append(f"## Chapter {chapter_num}{annotation}\n")
        lines.append(draft_text)
        lines.append("\n\n---\n")

    return "\n".join(lines), len(draft_files)


def write_epub(md_path, epub_path):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return False, "pandoc not found on PATH; wrote Markdown only."

    result = subprocess.run(
        [pandoc, md_path, "-o", epub_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, f"pandoc failed: {detail[:300]}"
    return True, None


def compile_book(project_dir=None, output_path=None, dry_run=False):
    project_dir = resolve_project_dir(project_dir)
    md_path, epub_path = resolve_output_paths(project_dir, output_path)
    compiled_markdown, chapter_count = build_compiled_markdown(project_dir)

    if dry_run:
        print(compiled_markdown)
        print(f"\n[dry-run] Would write {count_words(compiled_markdown):,} words to {md_path}")
        print(f"[dry-run] Would also try to write EPUB to {epub_path}")
        return

    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w") as handle:
        handle.write(compiled_markdown)

    total_words = count_words(compiled_markdown)
    print(f"Compiled {chapter_count} chapters ({total_words:,} words) -> {md_path}")

    wrote_epub, message = write_epub(md_path, epub_path)
    if wrote_epub:
        print(f"Wrote EPUB -> {epub_path}")
    elif message:
        print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assemble chapter drafts into a single .md and optional .epub book")
    parser.add_argument("--output", help="Output .md path or directory (default: project_dir/book.md)")
    parser.add_argument("--project-dir", help=f"Project directory to compile (default: {PROJECT_DIR})")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing files")
    args = parser.parse_args()
    try:
        compile_book(project_dir=args.project_dir, output_path=args.output, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(str(exc))
