# Story Pipeline

LLM-driven book generation pipeline with explicit project workspaces and a cleaner separation between planning artifacts and drafted prose.

## Runtime Layout

Runtime data is always project-scoped now.

- Named projects live under `workspace/`
- The active project is tracked in `workspace/.current_project`
- Override project path completely with `BOOK_PROJECT_DIR=/abs/path/to/project`

There is no automatic fallback to repo-root `story_bible.md` or `chapters/`. All active story data lives in the project workspace.

For frequent use, manage projects with:

```sh
python3 project.py init my_new_story
python3 project.py use my_new_story
python3 project.py list
python3 project.py current
python3 project.py path
```

If you do nothing, the active project defaults to `workspace/default/`.

## Core Flow

1. `build_story_bible.py "concept"` creates the story bible, initializes `cumulative_summary.md`, and generates Chapter 1's chapter brief.
2. `generate_chapter.py --all` runs the sequential drafting loop: draft chapter, summarize it, generate the next chapter brief, and continue.
3. `plan_chapters.py --beats` is optional when you want an upfront planning pass that fills or refreshes the outline and generates chapter briefs for every planned chapter before drafting.
4. `generate_chapter.py N` writes one coherent chapter draft from the story bible, cumulative summary, and `chapter_N_beats.md`.
5. `summarize_chapter.py N` records story state and generates the next chapter brief if needed.
6. `compile.py` assembles drafted chapters into `<project>.md` and, when `pandoc` is available, `<project>.epub`.

## Recommended Workflow

Default quickstart:

1. `python3 build_story_bible.py "your concept"`
2. `python3 generate_chapter.py --all`

That is the recommended end-to-end workflow for actual drafting.

- `build_story_bible.py` creates the story bible, outline, cumulative summary scaffold, and Chapter 1 brief.
- `generate_chapter.py --all` then uses the sequential loop, which is usually the best quality path because each next brief is generated from the cumulative summary of what was actually written.
- This means you do not need `plan_chapters.py --beats` for normal drafting.

Use `plan_chapters.py --beats` only when you want an upfront planning/review pass.

- Upfront chapter briefs from `plan_chapters.py --beats` are outline-driven planning artifacts.
- Sequential briefs generated during drafting are usually the better authoritative source because they also use the cumulative summary.
- A good optional workflow is: run `plan_chapters.py --beats`, review or edit the outline/briefs, then still draft with `generate_chapter.py --all`.

If a chapter brief fails validation during `plan_chapters.py --beats`, the run now stops on that chapter and exits nonzero instead of continuing into a partial-error batch.

### Dynamic Chapter Pacing

Not every chapter deserves the same word count. The pipeline supports weighted chapter lengths so the LLM naturally varies chapter size based on narrative importance.

To enable it, add `"dynamic_pacing": true` to the `story` block in `config.json`:

```json
{
  "story": {
    "default_chapters": 14,
    "word_count_target": 45000,
    "enforce_chapter_length": false,
    "dynamic_pacing": true
  }
}
```

When pacing is enabled, the pipeline looks for `pacing_weights.json` in the project directory. This file maps chapter numbers to relative weight factors:

```json
{
  "chapter_weights": {
    "1": 0.8,
    "2": 1.0,
    "3": 1.4,
    "4": 0.75,
    "5": 1.0,
    "6": 0.85,
    "7": 1.2,
    "8": 1.3
  }
}
```

- Weight 1.0 = baseline chapter length
- Weight 1.4 = 40% more words (climax, turning point, heavy action)
- Weight 0.7 = 30% fewer words (transition, bridge, setup)

The `pacing_weights.json` file can be generated automatically in three ways:

1. `plan_chapters.py --pacing` analyzes your outline and generates weights (one LLM call after the outline exists)
2. `generate_chapter.py --all` auto-generates weights on first run if they don't exist and pacing is enabled
3. Manually create/edit the file with your own weight assignments

When pacing is disabled (the default), chapters divide the total word budget evenly as before — zero behavior change.

The `.md` files under `chapters/` still use the `chapter_N_beats.md` name, but they now act as chapter briefs, not rigid scene-by-scene expansion contracts.

Chapter briefs are validated before use. If a generated brief is structurally valid but obviously weak, the pipeline allows one repair pass rather than looping indefinitely.

## Why The Strategy Changed

The old drafting path expanded each `### Beat N:` block in a separate LLM call and stitched the outputs together. That made continuity, pacing, and chapter-level flow worse than it needed to be.

The current flow keeps beats as planning scaffolding but drafts the chapter in staged blocks:

- beats define intent, reversals, and ending targets
- the writer combines multiple beats into a larger scene block
- each block is generated with carry-forward context from earlier blocks
- optional revision and cleanup passes can smooth transitions or repair malformed output

This keeps the planning layer useful without forcing the prose layer into artificial chunks.

## Commands

```sh
python3 project.py init haunted_greenhouse
python3 build_story_bible.py "your concept"
python3 generate_chapter.py --all
python3 plan_chapters.py --beats
python3 generate_chapter.py 1
python3 generate_chapter.py 1 --revise
python3 generate_chapter.py 1 --cleanup
python3 summarize_chapter.py 1
python3 status.py
python3 compile.py --dry-run
python3 compile.py --project-dir /abs/path/to/project
```

Drafting controls:

```sh
python3 generate_chapter.py 1 --beats-per-block 2
python3 generate_chapter.py 1 --beats-per-block 1
python3 generate_chapter.py 1 --beats-per-block 2 --revise
python3 generate_chapter.py 1 --beats-per-block 2 --cleanup --enforce-length
```

Generate all sequentially:

```sh
python3 generate_chapter.py --all
```

Compile outputs:

```sh
python3 compile.py
python3 compile.py --project-dir /abs/path/to/project
python3 compile.py --project-dir /abs/path/to/project --output /abs/path/to/book.md
```

Notes:

- `compile.py` reads drafts from the active project by default
- `--output` controls where the compiled Markdown is written; if you pass a directory, it writes `book.md` inside it
- If `pandoc` is installed on `PATH`, the compiler also writes a sibling `.epub`
- `compile.py` also copies each generated `.epub` into [`workspace/compiled_epubs/`](/home/aastro/books/book_generation/workspace/compiled_epubs)

That drafting loop means:

1. draft chapter
2. summarize it
3. generate the next chapter brief if missing

## Thinking Models

The local OpenAI-compatible path can work with thinking-capable models, including Qwen variants, as long as your server exposes the needed request flags.

- Set `local_mode` to `true`
- Point `local_model` at the model your server has loaded
- Use local sampling presets when a model wants specific sampler settings
- Keep `local_request_overrides` for final provider-specific overrides that should always win

Resolution order for local request fields is:

1. `local_request_defaults`
2. `sampling_presets`
3. `task_presets`
4. `model_presets`
5. `local_task_request_overrides`
6. `local_model_request_overrides`
7. `local_request_overrides`

Minimal example:

```json
{
  "local_mode": true,
  "local_endpoint": "http://localhost:8080",
  "local_model": "qwen3-32b-thinking",
  "local_request_defaults": {
    "chat_template_kwargs": {
      "enable_thinking": true
    }
  },
  "sampling_presets": {
    "creative_open": {
      "temperature": 1.0,
      "top_p": 1.0,
      "min_p": 0.05,
      "top_k": 0,
      "top_n_sigma": 1.0
    },
    "summary_strict": {
      "temperature": 0.2,
      "top_p": 0.8
    }
  },
  "task_presets": {
    "write": "creative_open",
    "beats": "creative_open",
    "summarize": "summary_strict"
  },
  "local_request_overrides": {
    "chat_template_kwargs": {
      "enable_thinking": true
    }
  }
}
```

That lets you keep model-tuning out of code. For example, if one prose model likes `temperature: 1.0`, `top_p: 1.0`, `min_p: 0.05`, and `top_k: 0`, define that once as a preset and point `write` and `beats` at it.

If you swap actual model IDs often, you can also bind a preset directly to the configured model string:

```json
{
  "model_presets": {
    "openrouter/some-model": "creative_open"
  }
}
```

Use task presets for most tuning. Add model presets only when the same task may run on different models that need different sampler settings.

The pipeline already strips `<think>`-style blocks from saved outputs and prefers the final answer text when the server streams reasoning separately.

## Quality Guardrails

- Chapter drafts target roughly 80%-120% of the configured per-chapter word count
- Final chapter cleanup checks for major length drift, repeated long sections, and meta-summary phrasing
- Chapter brief generation uses a single bounded repair attempt when the first output is malformed or too weak to draft from directly
- The pipeline does not retry indefinitely if the model keeps missing the target

## Important Files

- `paths.py`: project/workspace path definitions
- `project.py`: create and switch named projects under `workspace/`
- `story_utils.py`: shared parsing and summary/state helpers
- `chapter_planning.py`: outline lookup plus prompt builders for chapter briefs and chapter drafting
- `prompts/system_prompt.txt`: chapter-writing system prompt
- `templates/story_bible_TEMPLATE.md`: story bible scaffold
- `templates/chapter_beats_TEMPLATE.md`: chapter brief scaffold

## Tests

```sh
python3 tests/test_pipeline.py
```
