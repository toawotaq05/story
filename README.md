# Story Pipeline

LLM-driven iterative story writing pipeline. Configure once, generate chapters iteratively.

Project layout is intentionally split by role:

- `templates/` holds reusable authoring templates
- `prompts/` holds shared system prompts
- `workspace/default/` holds runtime story data for new projects
- `workspace/default/chapters/` holds beats, drafts, and per-chapter logs
- `workspace/default/artifacts/raw/` holds raw LLM dumps for debugging

---

## Setup

```sh
git clone git@github.com:toawotaq05/story.git
cd story
```

All scripts are Python 3. Required: `llm` CLI with OpenRouter plugin configured for remote models, or a local llama.cpp server for local inference.

---

## Configuration

Edit `config.json` to set models per task and story targets:

```json
{
    "models": {
        "story_bible": "openrouter/qwen/qwen3-235b-a22b",
        "outline":     "openrouter/qwen/qwen3-235b-a22b",
        "beats":       "openrouter/qwen/qwen3-235b-a22b",
        "write":       "openrouter/thedrummer/cydonia-24b-v4.1",
        "summarize":   "openrouter/qwen/qwen3-235b-a22b"
    },
    "story": {
        "default_chapters": 8,
        "word_count_target": 20000
    },
    "local_mode": true,
    "local_endpoint": "http://localhost:8080",
    "local_model": "local"
}
```

Each task can use a different model. Set `local_mode: true` to use a local llama.cpp server (faster, cheaper) or false for remote APIs. Targets are advisory — `status.py` tracks progress against them.

Runtime data is project-scoped. By default, fresh runs use `workspace/default/`. To point the pipeline at a different book workspace, set `BOOK_PROJECT_DIR=/abs/path/to/project`. If you already have root-level `story_bible.md` / `chapters/` data from older runs, the scripts will keep using that legacy layout automatically.

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
| `generate_chapter.py` | Write a chapter draft using **per‑beat expansion** for maximum word count (streaming output) |
| `summarize_chapter.py` | Summarize chapter, update history, auto‑generate next beats |
| `status.py` | Show chapter progress, word counts, story title |
| `compile.py` | Assemble all chapter drafts into a single .md ebook |

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

### Iterative (chapter‑by‑chapter)

```sh
python3 build_story_bible.py "concept"
python3 generate_chapter.py 1
python3 summarize_chapter.py 1   # summarizes + generates next beats
python3 generate_chapter.py 2
# ...
```

The iterative flow is slower but lets you course‑correct each chapter before the next is planned.

---

## `generate_chapter.py` – Per‑Beat Expansion

`generate_chapter.py` now uses **per‑beat expansion** by default to maximize word count and narrative detail:

- **Four beats per chapter** (configurable in beats files)
- **Each beat expanded separately** with targeted word‑count instructions
- **Clear scene separation** with `***` markers (configurable)
- **Smart overshoot management** – local models tend to write ~1.5× requested length

### Options

```sh
python3 generate_chapter.py 1                     # default settings
python3 generate_chapter.py 1 --no-separator      # no scene separators
python3 generate_chapter.py 1 --separator "###"   # custom separator
python3 generate_chapter.py 1 --raw-targets       # use raw word targets (no overshoot adjustment)
python3 generate_chapter.py 1 --overshoot-factor 1.3  # adjust expansion factor
python3 generate_chapter.py 1 --silent            # suppress streaming output
```

**Word‑count results**: Expect ~120‑150% of target word count with default settings (overshoot‑factor 1.5). Use `--overshoot‑factor 1.3` for tighter control, `--raw‑targets` for raw model behavior.

---

## plan_chapters.py Options

```sh
python3 plan_chapters.py --beats                # outline + all beats (default chapters from config)
python3 plan_chapters.py --beats --chapters 8  # override chapter count
python3 plan_chapters.py --regen-outline        # regenerate outline only
python3 plan_chapters.py --regen-beats          # regenerate all beats from current outline
```

Beats are generated in the `### Beat N:` format required by the per‑beat expansion pipeline.

---

## The Three Inputs Every Chapter Gets

1. **story_bible.md** — static reference: characters, world, tone, themes. Never changes after creation.
2. **cumulative_summary.md** — grows after each chapter. Running story history.
3. **chapters/chapter_N_beats.md** — what happens in this chapter. Edit before generating.

---

### Generate All (lazy mode) — ENHANCED

```sh
python3 generate_chapter.py --all
```

**BEHAVIOR:** The `--all` flag now runs the complete sequential workflow using **per‑beat expansion**:

1. **Generates all chapter drafts** from `chapter_N_beats.md` files (per‑beat expansion)
2. **Automatically updates** `cumulative_summary.md` with chapter summaries
3. **Tracks completed chapters** and generates next chapter beats as needed
4. **Streams output live** to the terminal for real‑time visibility

When you run `--all`, it performs the following steps:
- Processes all chapters from 1 to N (where N is defined in your beats files)
- Uses per‑beat expansion for maximum word count
- Calls summarization logic after generating each chapter draft
- Updates the cumulative story history with key plot points, character status, and open threads
- Generates beats for the next chapter if they don't already exist

This eliminates the need for a separate `summarize_chapter.py` call when using `--all`, making it a true "one‑command" solution for complete book generation.

```sh
python3 generate_chapter.py --all --no-skip   # overwrite existing drafts
python3 generate_chapter.py --all --separator ""  # generate without scene separators
python3 generate_chapter.py --all --overshoot-factor 1.3  # tighter word‑count control
```

### Assemble into a Book

```sh
python3 compile.py --dry-run        # preview to stdout
python3 compile.py                   # writes book.md
python3 compile.py --output full.md  # custom output path
```

`compile.py` extracts chapter titles from the outline, adds word‑count annotations per chapter, and produces a clean `.md` file ready for pandoc or similar.

## Repo Layout

```text
.
├── dual_llm/                   # LLM routing/provider code
├── prompts/
├── templates/
├── workspace/default/          # default runtime project data
├── workspace/default/chapters/
├── workspace/default/artifacts/raw/
├── prompts/system_prompt.txt   # shared chapter-writing system prompt
├── templates/chapter_beats_TEMPLATE.md
├── templates/story_bible_TEMPLATE.md
├── story_utils.py              # shared parsing/state helpers
├── paths.py                    # shared project path constants/helpers
└── *.py                        # workflow entry points
```

## Tips

- **Edit the chapter outline** in `story_bible.md` before generating beats — reorder chapters, change summaries, cull chapters. Then run `--regen‑beats`.
- **Edit any beats file** before generating its chapter — beats are prompts, not contracts.
- **`--regen‑beats`** regenerates all beats from the current outline without changing the outline itself.
- Streaming output on all LLM calls — text appears live, no waiting in silence.
- **Regenerate a chapter**: delete `chapter_N_draft.txt`, edit beats, rerun `generate_chapter.py N`.
- **Re‑summarize**: remove the chapter's entry from `cumulative_summary.md`, rerun `summarize_chapter.py N`.
- **Control word count**: Use `--overshoot‑factor` (default 1.5) to adjust expansion. Lower values = closer to target.
- **Scene transitions**: Default `***` separators make beat boundaries clear. Use `--separator ""` for seamless joins.
- Raw LLM transcripts are written to the active project's `artifacts/raw/` instead of cluttering the repo root.

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

**Per‑beat expansion typically yields 120‑150% of target word count** due to local model verbosity. Adjust with `--overshoot‑factor`:

| Factor | Result |
|--------|--------|
| 1.5 (default) | ~120‑150% of target |
| 1.3 | ~100‑120% of target |
| 1.0 (--raw‑targets) | ~80‑100% of target |

Example: 2,500‑word chapter target yields:
- Default: 3,000‑3,750 words
- `--overshoot‑factor 1.3`: 2,500‑3,000 words
- `--raw‑targets`: 2,000‑2,500 words

| Chapters | Words/chapter | Total |
|----------|--------------|-------|
| 8        | 2,500–3,750  | 20–30k |
| 10       | 2,000–3,000  | 20–30k |
| 12       | 1,700–2,500  | 20–30k |
