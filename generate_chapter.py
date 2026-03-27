#!/usr/bin/env python3
"""
generate_chapter.py — Generate a chapter using the story pipeline with streaming output.
"""
import subprocess, sys, os, threading
from config import get_model

def stream_llm(prompt, model=None, system=""):
    if model is None:
        model = get_model("write")
    """Stream LLM output to stdout and capture it for return."""
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

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_chapter.py <chapter_number> [output_filename]")
        sys.exit(1)

    chapter = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        output_file = os.path.join(script_dir, f"chapters/chapter_{chapter}_draft.txt")

    os.makedirs(os.path.join(script_dir, "chapters"), exist_ok=True)

    # Init cumulative_summary.md if missing or empty
    cumulative_path = os.path.join(script_dir, "cumulative_summary.md")
    if not os.path.exists(cumulative_path) or os.path.getsize(cumulative_path) == 0:
        header = f"""# Story So Far

Completed Chapters: 0

---

_This document grows as chapters are completed. Each summarized chapter appends here._

"""
        with open(cumulative_path, "w") as f:
            f.write(header)

    story_bible = os.path.join(script_dir, "story_bible.md")
    cumulative = os.path.join(script_dir, "cumulative_summary.md")
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

    context = f"{story_bible_text}\n\n{cumulative_text}\n\n{chapter_beats_text}"

    print(f"=== Generating Chapter {chapter} ===")
    print(f"Output: {output_file}")
    print()
    print("Streaming output:")
    print("-" * 40)

    result = stream_llm(context, system=system_prompt_text)

    print("-" * 40)
    print()

    with open(output_file, "w") as f:
        f.write(result)

    word_count = len(result.split())
    print(f"✓ Chapter {chapter} written to {output_file} ({word_count} words)")
    print()
    next_ch = int(chapter) + 1
    print("Next steps:")
    print(f"  1. Review: {output_file}")
    print(f"  2. python3 summarize_chapter.py {chapter}")

if __name__ == "__main__":
    main()
