#!/usr/bin/env python3
"""
summarize_chapter.py — Summarize a completed chapter, update cumulative_summary.md,
and generate the next chapter's beats. Streaming output enabled.
"""
import subprocess, sys, os, re, threading
from config import get_model

def stream_llm(prompt, model=None,
               system="You are a story analyst."):
    if model is None:
        model = get_model("summarize")
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
        print("Usage: python3 summarize_chapter.py <chapter_number>")
        sys.exit(1)

    chapter = sys.argv[1]
    next_chapter = str(int(chapter) + 1)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    chapter_draft = os.path.join(script_dir, f"chapters/chapter_{chapter}_draft.txt")
    next_beats = os.path.join(script_dir, f"chapters/chapter_{next_chapter}_beats.md")
    cumulative = os.path.join(script_dir, "cumulative_summary.md")
    story_bible = os.path.join(script_dir, "story_bible.md")

    if not os.path.exists(chapter_draft):
        print(f"ERROR: Chapter draft not found: {chapter_draft}")
        print(f"Run: python3 generate_chapter.py {chapter}")
        sys.exit(1)

    with open(chapter_draft) as f:
        draft_content = f.read()

    print(f"=== Summarizing Chapter {chapter} ===")
    print()

    system_prompt = (
        "You are a story analyst. Read the chapter draft below and produce a "
        "structured summary. Follow the format exactly."
    )
    user_prompt = f"""Chapter to summarize:

---

{draft_content}

---

Format your response EXACTLY as follows — do not add any preamble, commentary, or extra text:

### Chapter {chapter} — [TWO TO FOUR WORD CHAPTER TITLE]
[4-6 sentences: what happens in order, key character decisions, setting details established, how the chapter ends and what it sets up for the next chapter]

### Key Plot Points Established
- [Important fact, reveal, or event established in this chapter]
- ...

### Character Status
- [Character name]: [Their state at end of chapter — location, emotional state, relationship changes]
- ...

### Open Threads / Loose Ends
- [Question raised, setup planted, or tension left unresolved]
- ..."""

    print("Summarizing chapter (streaming):")
    print("-" * 40)
    summary = stream_llm(user_prompt, system=system_prompt)
    print("-" * 40)
    print()

    with open(cumulative, "a") as f:
        f.write("\n" + summary)
    with open(cumulative) as f:
        content = f.read()
    new_content = re.sub(
        r'(Completed Chapters:\s*)\d+',
        rf'\g<1>{chapter}',
        content
    )
    with open(cumulative, "w") as f:
        f.write(new_content)

    print(f"✓ Chapter {chapter} summarized")

    # --- Generate next chapter beats ---
    with open(story_bible) as f:
        story_bible_text = f.read()
    current_beats = os.path.join(script_dir, f"chapters/chapter_{chapter}_beats.md")
    with open(current_beats) as f:
        beats_format = f.read()

    system_prompt2 = "You are a story architect."
    user_prompt2 = f"""Based on the story so far, write detailed beats for Chapter {next_chapter}.

STORY BIBLE (do not change these established facts):
{story_bible_text}

STORY SO FAR (cumulative summary):
{content}

CHAPTER {next_chapter} BEATS TEMPLATE (follow this format):
{beats_format}

INSTRUCTIONS:
- Continue the story from where Chapter {chapter} left off
- Follow the same level of detail as the template above
- Be specific: name characters, describe scenes, give dialogue cues
- Plant seeds for future chapters in "Open Threads / Loose Ends"
- Do not include any preamble or commentary — output only the beats document"""

    if os.path.exists(next_beats):
        print(f"Note: chapters/chapter_{next_chapter}_beats.md already exists — skipping beats generation.")
    else:
        print()
        print(f"Generating Chapter {next_chapter} beats (streaming):")
        print("-" * 40)
        next_beats_content = stream_llm(user_prompt2, model=get_model("beats"), system=system_prompt2)
        print("-" * 40)
        print()
        with open(next_beats, "w") as f:
            f.write(next_beats_content)
        print(f"✓ chapters/chapter_{next_chapter}_beats.md written")

    print()
    print("Current completed chapters:")
    for line in content.split("\n"):
        if "Completed Chapters" in line:
            print(" ", line)
            break
    print()
    print("Chapter summaries so far:")
    for line in content.split("\n"):
        if line.startswith("### Chapter "):
            print(" ", line)
    print()
    print("Next step:")
    print(f"  python3 generate_chapter.py {next_chapter}")

if __name__ == "__main__":
    main()
