# Story Pipeline

LLM-driven iterative story writing pipeline.

---

## Quick Start

```sh
# 1. Generate story bible + chapter outline from a concept
python3 build_story_bible.py "your story concept"

# 2. Review the full arc — edit chapter outline in story_bible.md if needed

# 3. Generate all chapter beats upfront (recommended)
python3 plan_chapters.py --beats

# 4. Write chapters in order
python3 generate_chapter.py 1
python3 generate_chapter.py 2
# ... etc
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `build_story_bible.py` | Fill story_bible.md from a concept |
| `plan_chapters.py` | Generate full chapter outline; optionally all beats |
| `generate_chapter.py` | Write a chapter draft |
| `summarize_chapter.py` | Summarize chapter, update history, auto-generate next beats |
| `status.py` | Show chapter progress, word counts, story title |

---

## Workflows

### Full upfront (recommended for structured stories)
```sh
python3 build_story_bible.py "concept"
# review story_bible.md
python3 plan_chapters.py --beats          # outline + all beats at once
python3 generate_chapter.py 1
python3 generate_chapter.py 2
# ...
```

### Iterative (chapter-by-chapter)
```sh
python3 build_story_bible.py "concept"
python3 generate_chapter.py 1
python3 summarize_chapter.py 1   # auto-generates next beats
python3 generate_chapter.py 2
# ...
```

---

## plan_chapters.py Options

```sh
python3 plan_chapters.py "my concept"           # outline only
python3 plan_chapters.py --beats                # outline + all beats
python3 plan_chapters.py --beats --chapters 8   # 8 chapters (default: 10)
python3 plan_chapters.py --regen-beats         # regenerate all beats
python3 plan_chapters.py --regen-outline       # regenerate outline
```

---

## The Three Inputs Every Chapter Gets

1. **story_bible.md** — static reference: characters, world, tone, themes (never changes)
2. **cumulative_summary.md** — grows after each chapter; running story history
3. **chapters/chapter_N_beats.md** — what happens in this specific chapter

---

## Tips

- **Edit the chapter outline** in `story_bible.md` before generating beats — reorder chapters, change a one-line summary, cull a chapter
- **Edit any beats file** before generating its chapter — beats are just prompts
- **`--regen-beats`** regenerates all beats from the outline (good after outline edits)
- **Streaming output** — all scripts stream LLM text in real-time to your terminal
- **`python3 status.py`** — see what's done, what's planned, word counts
- To **regenerate a chapter**: delete `chapter_N_draft.txt`, edit beats, rerun `generate_chapter.py N`
- To **re-summarize**: remove the chapter's entry from `cumulative_summary.md`, rerun `summarize_chapter.py N`

---

## Word Count Target

| Chapters | Words/chapter | Total     |
|----------|--------------|-----------|
| 8        | 2,500–3,750  | 20–30k    |
| 10       | 2,000–3,000  | 20–30k    |
| 12       | 1,700–2,500  | 20–30k    |
