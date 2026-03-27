#!/usr/bin/env python3
"""
generate_chapter.py — Generate a chapter (or all chapters) using the story pipeline.

Usage:
    python3 generate_chapter.py 1              # generate chapter 1
    python3 generate_chapter.py --all         # generate all chapters with beats but no draft
    python3 generate_chapter.py --all --skip-existing  # same, but skip done chapters silently
"""
import subprocess, sys, os, glob, threading, argparse, re
from config import get_model, get_word_count_target

def stream_llm(prompt, model=None, system="", silent=False):
    if model is None:
        model = get_model("write")
    proc = subprocess.Popen(
        ["llm", "-m", model, "-s", system, "--stream"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
    )
    output = []

    def pump():
        try:
            for char in iter(lambda: proc.stdout.read(1), ''):
                if char:
                    if not silent:
                        sys.stdout.write(char)
                        sys.stdout.flush()
                    output.append(char)
        except Exception:
            pass

    t = threading.Thread(target=pump)
    t.start()
    proc.communicate(input=prompt.encode() if isinstance(prompt, str) else prompt)
    proc.wait()
    t.join(timeout=2)
    return ''.join(output)

def init_cumulative(script_dir):
    cumulative_path = os.path.join(script_dir, "cumulative_summary.md")
    if not os.path.exists(cumulative_path) or os.path.getsize(cumulative_path) == 0:
        header = """# Story So Far

Completed Chapters: 0

---

_This document grows as chapters are completed. Each summarized chapter appends here._

"""
        with open(cumulative_path, "w") as f:
            f.write(header)
    return cumulative_path

def generate_chapter(chapter, script_dir, silent=False, output_file=None):
    """Core logic: read inputs, call LLM, write draft. Returns (word_count, output_path)."""
    story_bible = os.path.join(script_dir, "story_bible.md")
    cumulative = init_cumulative(script_dir)
    chapter_beats = os.path.join(script_dir, f"chapters/chapter_{chapter}_beats.md")
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
        chapter_beats_text = f.read()
    with open(system_prompt_file) as f:
        system_prompt_text = f.read().strip()

    # Inject dynamic values from config
    target = get_word_count_target()
    system_prompt_text = system_prompt_text.replace("[WORD_COUNT_TARGET]", f"{target:,}")

    context = f"{story_bible_text}\n\n{cumulative_text}\n\n{chapter_beats_text}"

    if not silent:
        print(f"=== Generating Chapter {chapter} ===")
        print(f"Output: {output_file or f'chapters/chapter_{chapter}_draft.txt'}")
        print()
        print("Streaming output:")
        print("-" * 40)

    result = stream_llm(context, system=system_prompt_text, silent=silent)

    if not silent:
        print("-" * 40)
        print()

    if output_file is None:
        output_file = os.path.join(script_dir, f"chapters/chapter_{chapter}_draft.txt")

    with open(output_file, "w") as f:
        f.write(result)

    word_count = len(result.split())
    return word_count, output_file

def generate_all(script_dir, skip_existing=True):
    """Find all chapter_N_beats.md files, generate drafts for those missing one."""
    chapters_dir = os.path.join(script_dir, "chapters")
    beats_files = sorted(
        glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
        key=lambda p: int(re.search(r"chapter_(\d+)_beats", p).group(1))
    )

    if not beats_files:
        print("No chapter beats found in chapters/. Run plan_chapters.py --beats first.")
        sys.exit(1)

    # Detect range
    chapter_nums = []
    for bf in beats_files:
        m = re.search(r"chapter_(\d+)_beats", bf)
        if m:
            chapter_nums.append(int(m.group(1)))

    if not chapter_nums:
        print("Could not parse chapter numbers from beats filenames.")
        sys.exit(1)

    min_c, max_c = min(chapter_nums), max(chapter_nums)
    total = len(range(min_c, max_c + 1))
    print(f"Found beats for chapters {min_c}–{max_c} ({total} chapters)")
    print()

    generated = 0
    skipped = 0

    for ch in range(min_c, max_c + 1):
        draft_path = os.path.join(chapters_dir, f"chapter_{ch}_draft.txt")
        beats_path = os.path.join(chapters_dir, f"chapter_{ch}_beats.md")

        if skip_existing and os.path.exists(draft_path):
            print(f"[{ch}/{max_c}] Skipping chapter {ch} — draft exists")
            skipped += 1
            continue

        if not os.path.exists(beats_path):
            print(f"[{ch}/{max_c}] Skipping chapter {ch} — no beats file")
            continue

        print(f"\n{'='*60}")
        print(f"  CHAPTER {ch} / {max_c}  [{ch - min_c + 1} of {total}]")
        print(f"{'='*60}")

        try:
            wc, path = generate_chapter(str(ch), script_dir, silent=False)
            print(f"  >> Chapter {ch} written ({wc:,} words) -> {path}")
            generated += 1
        except Exception as e:
            print(f"  >> ERROR on chapter {ch}: {e}")
            print("  >> Continuing to next chapter...")

    print()
    print(f"Done. Generated: {generated}, skipped: {skipped}")

def main():
    parser = argparse.ArgumentParser(description="Generate chapter drafts")
    parser.add_argument("chapter", nargs="?", help="Chapter number to generate (or omit with --all)")
    parser.add_argument("--all", action="store_true", help="Generate all chapters with beats but no draft")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip chapters that already have a draft (default: True)")
    parser.add_argument("--no-skip", action="store_false", dest="skip_existing",
                        help="Do NOT skip existing drafts (will overwrite)")
    parser.add_argument("output_file", nargs="?", help="Custom output path (default: chapters/chapter_N_draft.txt)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(script_dir, "chapters"), exist_ok=True)

    if args.all:
        generate_all(script_dir, skip_existing=args.skip_existing)
        return

    if not args.chapter:
        parser.print_help()
        sys.exit(1)

    chapter = args.chapter
    output_file = args.output_file

    wc, path = generate_chapter(chapter, script_dir, silent=False, output_file=output_file)

    print(f"Chapter {chapter} written to {path} ({wc:,} words)")
    print()
    next_ch = int(chapter) + 1
    print("Next steps:")
    print(f"  1. Review: {path}")
    print(f"  2. python3 summarize_chapter.py {chapter}")

if __name__ == "__main__":
    main()
