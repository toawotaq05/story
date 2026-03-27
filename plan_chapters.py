#!/usr/bin/env python3
"""
plan_chapters.py — Generate the full chapter outline before writing begins.

Usage:
  python3 plan_chapters.py                       # interactive: ask for concept or use existing
  python3 plan_chapters.py "my concept"           # one-shot with concept
  python3 plan_chapters.py --beats               # also generate all chapter beats upfront
  python3 plan_chapters.py --beats 8             # 8 chapters (default: 8-12 based on story_bible or auto)
  python3 plan_chapters.py --regen-outline       # regenerate outline only
  python3 plan_chapters.py --regen-beats        # regenerate all beats from existing outline
"""
import subprocess, sys, os, argparse, threading, re
from config import get_model, get_default_chapters

DEFAULT_CHAPTERS = get_default_chapters()

def stream_llm(prompt, model=None, system="You are a story architect."):
    if model is None:
        model = get_model("outline")
    proc = subprocess.Popen(
        ["llm", "-m", model, "-s", system, "--stream"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=0,
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
    proc.communicate(input=prompt.encode())
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        raise RuntimeError(f"LLM failed: {proc.stderr.read()}")
    return ''.join(output)

def main():
    parser = argparse.ArgumentParser(description="Plan the full chapter outline before writing.")
    parser.add_argument("concept", nargs="?", default=None,
                        help="Story concept (if not given, use existing story_bible.md)")
    parser.add_argument("--beats", action="store_true",
                        help="Also generate all chapter beats after the outline")
    parser.add_argument("--chapters", type=int, default=None,
                        help=f"Number of chapters (default: {DEFAULT_CHAPTERS}, range: 8-12)")
    parser.add_argument("--regen-outline", action="store_true",
                        help="Regenerate outline only, keep existing beats")
    parser.add_argument("--regen-beats", action="store_true",
                        help="Regenerate all beats from existing outline")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    story_bible_path = os.path.join(script_dir, "story_bible.md")
    chapters_dir = os.path.join(script_dir, "chapters")

    num_chapters = args.chapters or DEFAULT_CHAPTERS

    # --- Load existing story bible if no new concept ---
    if args.concept:
        concept = args.concept
        if not os.path.exists(story_bible_path) or args.regen_outline:
            print("Note: --regen-outline not set but story_bible.md doesn't exist.")
            print("Will generate full story bible + outline together.\n")
        story_bible_text = ""
        has_story_bible = False
    else:
        if not os.path.exists(story_bible_path):
            print("ERROR: No concept given and story_bible.md not found.")
            print("Run with a concept: python3 plan_chapters.py \"my story\"")
            sys.exit(1)
        with open(story_bible_path) as f:
            story_bible_text = f.read()
        has_story_bible = True
        # Extract concept from existing story bible (the user prompt is lost)
        # We'll just say "continue from existing story bible"
        concept = "(Use existing story_bible.md — concept embedded in the document)"

    # --- Check/create chapters directory ---
    os.makedirs(chapters_dir, exist_ok=True)

    # --- Generate chapter outline ---
    if args.regen_beats and not args.regen_outline:
        # Skip outline, go straight to beats from existing
        pass
    else:
        print("=== Generating Chapter Outline ===")
        print()

        if has_story_bible:
            outline_prompt = f"""Based on the existing story bible below, generate a chapter outline for the full story.

STORY BIBLE:
{story_bible_text}

TASK: Create a chapter outline with exactly {num_chapters} chapters.
For each chapter provide:
- Chapter number and title
- A one-line summary of what happens in that chapter
- A brief note on how it ends / what it sets up for the next chapter

FORMAT your response exactly as follows (one chapter per line, keep summaries concise):

# Chapter Outline

1. **Chapter 1 — [Title]** — [One line what happens] → ends: [setup for Ch2]
2. **Chapter 2 — [Title]** — [One line what happens] → ends: [setup for Ch3]
...and so on through Chapter {num_chapters}

Do not include any preamble, commentary, or extra text. Output only the outline."""
        else:
            outline_prompt = f"""Story concept: {concept}

TASK: You are a story architect. Create a complete chapter outline for this story concept.

First, fill in the story bible (all bracketed placeholders) with creative choices.
Then create a chapter outline with exactly {num_chapters} chapters.

For each chapter provide:
- Chapter number and title
- A one-line summary of what happens in that chapter
- A brief note on how it ends / what it sets up for the next chapter

FORMAT your response exactly as follows:

# [STORY TITLE]
## Story Bible
[Fill in the complete story bible — all characters, world rules, themes]

---

# Chapter Outline

1. **Chapter 1 — [Title]** — [One line what happens] → ends: [setup for Ch2]
2. **Chapter 2 — [Title]** — [One line what happens] → ends: [setup for Ch3]
...and so on through Chapter {num_chapters}

Do not include any preamble, commentary, or extra text. Output only the story bible and outline."""

        print("Streaming outline:")
        print("-" * 40)
        outline_output = stream_llm(outline_prompt)
        print("-" * 40)
        print()

        # Save raw output
        with open(os.path.join(script_dir, "llm_raw_output.txt"), "w") as f:
            f.write(outline_output)

        if not has_story_bible:
            # Split story bible + outline
            marker = "---"
            if marker not in outline_output:
                print("ERROR: Could not parse story bible from outline output")
                sys.exit(1)
            parts = outline_output.split(marker, 1)
            story_bible_content = parts[0].strip()
            outline_content = parts[1].strip() if len(parts) > 1 else ""

            with open(story_bible_path, "w") as f:
                f.write(story_bible_content)
            print(f"✓ story_bible.md written ({len(story_bible_content.split())} words)")
        else:
            # Append outline section to existing story bible
            outline_content = outline_output.strip()

        # Append outline to story_bible.md as a new section
        outline_section = f"\n\n---\n\n{outline_content}\n"
        with open(story_bible_path, "a") as f:
            f.write(outline_section)
        print(f"✓ Chapter outline appended to story_bible.md")
        print()

    # --- Optionally generate all chapter beats ---
    if args.beats or args.regen_beats:
        # Load story bible and outline
        with open(story_bible_path) as f:
            full_text = f.read()

        # Extract outline section (after the last --- divider)
        outline_start = full_text.rfind('\n---\n')
        if outline_start == -1:
            print("ERROR: Could not find chapter outline in story_bible.md")
            sys.exit(1)
        outline_section = full_text[outline_start + 4:].strip()
        story_bible_core = full_text[:outline_start].strip()

        # Extract individual chapter entries
        chapter_entries = []
        for line in outline_section.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Match: "1. **Chapter 1 — Title** — summary → ends: note"
            import re
            m = re.match(r'^\d+\.\s+\*\*Chapter\s+(\d+)\s*—\s*([^*]+)\*\*\s*—\s*(.+)', line)
            if m:
                ch_num = m.group(1).lstrip('0')
                ch_title = m.group(2).strip()
                summary = m.group(3).strip()
                chapter_entries.append((ch_num, ch_title, summary))

        if not chapter_entries:
            print("ERROR: Could not parse chapter entries from outline")
            print(f"Outline section:\n{outline_section[:500]}")
            sys.exit(1)

        print(f"=== Generating Beats for {len(chapter_entries)} Chapters ===")
        print()

        # Load beats template from chapter 1 if it exists, else generate from scratch
        template_path = os.path.join(chapters_dir, "chapter_1_beats.md")
        if os.path.exists(template_path):
            with open(template_path) as f:
                beats_template = f.read()
        else:
            # Try from story_bible or use a minimal template
            beats_template = None

        for ch_num, ch_title, ch_summary in chapter_entries:
            beats_file = os.path.join(chapters_dir, f"chapter_{ch_num}_beats.md")
            if os.path.exists(beats_file) and not args.regen_beats:
                print(f"  Skipping Chapter {ch_num} (already exists)")
                continue

            print(f"  Generating Chapter {ch_num} — {ch_title}")

            # Build context: what came before
            prior_beats = []
            for prev_num, prev_title, prev_summary in chapter_entries:
                if int(prev_num) >= int(ch_num):
                    break
                prev_file = os.path.join(chapters_dir, f"chapter_{prev_num}_beats.md")
                if os.path.exists(prev_file):
                    with open(prev_file) as f:
                        prior_beats.append(f"# Chapter {prev_num} — {prev_title}\n{f.read()}")

            prior_context = "\n\n".join(prior_beats) if prior_beats else "(No prior chapters — this is the opening)"

            system_prompt = "You are a story architect."
            user_prompt = f"""Write detailed chapter beats for Chapter {ch_num} of the story.

CHAPTER OUTLINE ENTRY:
{ch_title} — {ch_summary}

STORY BIBLE (do not change established facts):
{story_bible_core}

STORY SO FAR (prior chapter beats):
{prior_context}

{f"CHAPTER BEATS TEMPLATE (follow this exact format):\n{beats_template}" if beats_template else ""}

INSTRUCTIONS:
- Follow the format of the template above exactly
- Be specific: name characters, describe scenes, give dialogue cues
- Plant threads that pay off in later chapters
- Do not include any preamble or commentary — output only the beats document"""

            beats_content = stream_llm(user_prompt, model=get_model("beats"), system=system_prompt)
            print()

            with open(beats_file, "w") as f:
                f.write(beats_content)
            print(f"  ✓ chapter_{ch_num}_beats.md written")

        print()
        print(f"✓ All chapter beats generated")
        print()
        print("Ready to write! Run:")
        print("  python3 generate_chapter.py 1")

    else:
        print("Chapter outline generated.")
        print()
        print("To review the outline, open: story_bible.md")
        print()
        print("Next steps:")
        print("  python3 plan_chapters.py --beats          # generate all chapter beats")
        print("  python3 plan_chapters.py --beats --regen-beats  # regenerate all beats")

if __name__ == "__main__":
    main()
