#!/usr/bin/env python3
"""
build_story_bible.py — End-to-end story bible + chapter 1 beats generator.
"""
import subprocess, sys, os, threading

def stream_llm(prompt, model="openrouter/thedrummer/cydonia-24b-v4.1",
               system="You are a creative story architect."):
    """Stream LLM output to stdout and capture it for return."""
    proc = subprocess.Popen(
        ["llm", "-m", model, "-s", system, "--stream"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,  # unbuffered
    )
    output = []
    done = False

    def pump():
        try:
            for char in iter(lambda: proc.stdout.read(1), ''):
                if char:
                    sys.stdout.write(char)
                    sys.stdout.flush()
                    output.append(char)
        except Exception:
            pass
        finally:
            done = True

    t = threading.Thread(target=pump)
    t.start()

    proc.communicate(input=prompt.encode() if isinstance(prompt, str) else prompt)
    proc.wait()
    t.join(timeout=2)

    if proc.returncode != 0:
        stderr = proc.stderr.read()
        raise RuntimeError(f"LLM call failed: {stderr}")
    return ''.join(output)

def split_on_marker(text, marker="@@@STORY_BIBLE_END_MARKER@@@"):
    if marker not in text:
        raise ValueError(f"Marker '{marker}' not found in LLM output")
    story_bible_content, chapter_beats_content = text.split(marker, 1)
    return story_bible_content.strip(), chapter_beats_content.strip()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 build_story_bible.py \"Your story concept here\"")
        sys.exit(1)

    concept = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(script_dir, "story_bible.md")) as f:
        story_bible_template = f.read()
    with open(os.path.join(script_dir, "chapters/chapter_1_beats.md")) as f:
        chapter_template = f.read()

    print("=== Building Story Bible from Concept ===")
    print(f"Concept: {concept}")
    print()

    user_prompt = f"""Story concept:
{concept}

---

TASK 1: Fill in the STORY BIBLE

Fill in every [BRACKETED PLACEHOLDER] in the template below. Make creative choices that are original, coherent, and compelling. Match the tone and genre of the concept. Fill in ALL sections — do not skip any. Write in plain prose for description fields, use lists where indicated, and complete all tables.

Story Bible Template:
{story_bible_template}

---

TASK 2: Write CHAPTER 1 BEATS

Using the story bible you just filled in, write detailed chapter 1 beats for a new story. Follow the chapter_1_beats.md template below — fill in the opening scene, key events in order, a turning point/cliffhanger, character beats, and themes. Be specific — name the characters, describe the scenes, give enough detail that another LLM could write the chapter from this alone.

Chapter 1 Beats Template:
{chapter_template}

---

OUTPUT FORMAT

Write the story bible first, beginning with the line "# [YOUR TITLE]", replacing [STORY TITLE] and all other bracketed placeholders with your creative choices.

After the story bible, write exactly this line on its own line:
@@@STORY_BIBLE_END_MARKER@@@

Then write the chapter 1 beats section starting with "# Chapter 1 — [YOUR CHAPTER TITLE]", replacing all bracketed placeholders.

Do not include any preamble, commentary, or explanation — only the two documents.
"""

    system_prompt = "You are a creative story architect. The user has provided a story concept. Your task is to produce TWO outputs based on that concept."

    print("Calling LLM... (streaming output below)")
    print()

    output = stream_llm(user_prompt, system=system_prompt)

    # Save raw output for debugging
    with open(os.path.join(script_dir, "llm_raw_output.txt"), "w") as f:
        f.write(output)

    print()
    print()

    try:
        story_bible_content, chapter_beats_content = split_on_marker(output)
    except ValueError as e:
        print(f"ERROR: Could not parse LLM output: {e}")
        print(f"Raw output saved to llm_raw_output.txt")
        sys.exit(1)

    if not story_bible_content:
        print("ERROR: Story bible content is empty")
        sys.exit(1)
    if not chapter_beats_content:
        print("ERROR: Chapter 1 beats content is empty")
        sys.exit(1)

    with open(os.path.join(script_dir, "story_bible.md"), "w") as f:
        f.write(story_bible_content)
    with open(os.path.join(script_dir, "chapters/chapter_1_beats.md"), "w") as f:
        f.write(chapter_beats_content)

    print("✓ story_bible.md written")
    print("✓ chapters/chapter_1_beats.md written")
    print()
    print("Next steps:")
    print("  1. Review story_bible.md")
    print("  2. Review chapters/chapter_1_beats.md")
    print("  3. python3 generate_chapter.py 1")

if __name__ == "__main__":
    main()
