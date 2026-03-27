# Story Pipeline

LLM-driven iterative story writing pipeline. Configure once, generate chapters iteratively.

---

## Setup

```sh
git clone git@github.com:toawotaq05/story.git
cd story
```

All scripts are Python 3. Required: `llm` CLI with OpenRouter plugin configured.

---

## Configuration

Edit `config.json` to set models per task and story targets:

```json
{
    "models": {
        "story_bible": "openrouter/thedrummer/cydonia-24b-v4.1",
        "outline":     "openrouter/thedrummer/cydonia-24b-v4.1",
        "beats":       "openrouter/thedrummer/cydonia-24b-v4.1",
        "write":       "openrouter/thedrummer/cydonia-24b-v4.1",
        "summarize":   "openrouter/thedrummer/cydonia-24b-v4.1"
    },
    "story": {
        "default_chapters": 10,
        "word_count_target": 25000
    }
}
```

Each task can use a different model. Targets are advisory — `status.py` tracks progress against them.

---

## Quick Start

```sh
# 1. Generate story bible + chapter 1 beats from a concept
python3 build_story_bible.py "your story concept here"

# 2. Review story_bible.md — verify characters, world, tone, outline

# 3. Generate all chapter beats upfront (recommended)
python3 plan_chapters.py --beats

# 4. Write chapters — all output streams live to your terminal
python3 generate_chapter.py 1
python3 generate_chapter.py 2
# ... continue in order

# Check progress anytime
python3 status.py
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `build_story_bible.py` | Generate story bible + chapter 1 beats from a concept |
| `plan_chapters.py` | Generate chapter outline; optionally all beats upfront |
| `generate_chapter.py` | Write a chapter draft (streaming output) |
| `summarize_chapter.py` | Summarize chapter, update history, auto-generate next beats |
| `status.py` | Show chapter progress, word counts, story title |
| `config.py` | Shared config reader — all scripts import from here |

---

## Workflows

### Full upfront (recommended)

```sh
python3 build_story_bible.py "concept"
# review/edit story_bible.md
python3 plan_chapters.py --beats    # outline + all beats in one shot
python3 generate_chapter.py 1
python3 generate_chapter.py 2
# ... each streams live to your terminal
```

### Iterative (chapter-by-chapter)

```sh
python3 build_story_bible.py "concept"
python3 generate_chapter.py 1
python3 summarize_chapter.py 1   # summarizes + generates next beats
python3 generate_chapter.py 2
# ...
```

The iterative flow is slower but lets you course-correct each chapter before the next is planned.

---

## plan_chapters.py Options

```sh
python3 plan_chapters.py --beats                # outline + all beats (default chapters from config)
python3 plan_chapters.py --beats --chapters 8  # override chapter count
python3 plan_chapters.py --regen-outline        # regenerate outline only
python3 plan_chapters.py --regen-beats          # regenerate all beats from current outline
```

---

## The Three Inputs Every Chapter Gets

1. **story_bible.md** — static reference: characters, world, tone, themes. Never changes after creation.
2. **cumulative_summary.md** — grows after each chapter. Running story history.
3. **chapters/chapter_N_beats.md** — what happens in this chapter. Edit before generating.

---

## Tips

- **Edit the chapter outline** in `story_bible.md` before generating beats — reorder chapters, change summaries, cull chapters. Then run `--regen-beats`.
- **Edit any beats file** before generating its chapter — beats are prompts, not contracts.
- **`--regen-beats`** regenerates all beats from the current outline without changing the outline itself.
- Streaming output on all LLM calls — text appears live, no waiting in silence.
- **Regenerate a chapter**: delete `chapter_N_draft.txt`, edit beats, rerun `generate_chapter.py N`.
- **Re-summarize**: remove the chapter's entry from `cumulative_summary.md`, rerun `summarize_chapter.py N`.

---

## Running Tests

```sh
python3 tests/test_pipeline.py
```

12 tests covering: config loading, project structure, CLI smoke, error paths, mocked LLM calls. No real API calls.

---

## Word Count

Target is advisory. `status.py` shows progress:

```
Total draft words: 12,400 / 25,000 (49%)
```

| Chapters | Words/chapter | Total |
|----------|--------------|-------|
| 8        | 2,500–3,750  | 20–30k |
| 10       | 2,000–3,000  | 20–30k |
| 12       | 1,700–2,500  | 20–30k |
