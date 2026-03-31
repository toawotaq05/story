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
2. `plan_chapters.py --beats` fills or refreshes the chapter outline and generates chapter briefs for every planned chapter.
3. `generate_chapter.py N` writes one coherent chapter draft from the story bible, cumulative summary, and `chapter_N_beats.md`.
4. `summarize_chapter.py N` records story state and generates the next chapter brief if needed.
5. `compile.py` assembles drafted chapters into `book.md`.

The `.md` files under `chapters/` still use the `chapter_N_beats.md` name, but they now act as chapter briefs, not rigid scene-by-scene expansion contracts.

## Why The Strategy Changed

The old drafting path expanded each `### Beat N:` block in a separate LLM call and stitched the outputs together. That made continuity, pacing, and chapter-level flow worse than it needed to be.

The current flow keeps beats as planning scaffolding but drafts the chapter in staged blocks:

- beats define intent, reversals, and ending targets
- the writer combines multiple beats into a larger scene block
- each block is generated with carry-forward context from earlier blocks
- an optional final revision pass smooths transitions and repetition

This keeps the planning layer useful without forcing the prose layer into artificial chunks.

## Commands

```sh
python3 project.py init haunted_greenhouse
python3 build_story_bible.py "your concept"
python3 plan_chapters.py --beats
python3 generate_chapter.py 1
python3 summarize_chapter.py 1
python3 status.py
python3 compile.py --dry-run
```

Drafting controls:

```sh
python3 generate_chapter.py 1 --beats-per-block 2
python3 generate_chapter.py 1 --beats-per-block 1 --no-revise
```

Generate all sequentially:

```sh
python3 generate_chapter.py --all
```

That workflow now means:

1. draft chapter
2. summarize it
3. generate the next chapter brief if missing

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
