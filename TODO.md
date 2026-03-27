# Story Pipeline — Remaining Tasks

## Testing
- [x] Add unit tests with mocked LLM responses (patch `subprocess.run` / `stream_llm`)
- [ ] Test each script's error paths: missing files, empty prompts, bad config

## CLI / Usability
- [ ] `--force` flag on `summarize_chapter.py` to regenerate next beats even if file exists
- [ ] `story.py` unified CLI with subcommands (`build`, `write`, `next`, `status`)
- [x] `generate_chapter.py --all` to generate all chapters in sequence
- [x] `compile.py` to assemble drafts into a single .md ebook

## Quality-of-Life
- [ ] Auto-retry on LLM failure (common with API timeouts)
- [ ] Token/cost tracking per session
- [ ] `--dry-run` flag to preview prompts without calling LLM
- [x] Configurable word-count target and chapter count

## Documentation
- [ ] Example: show before/after of a full chapter generation
- [ ] Add contributing guidelines

## Nice-to-Have
- [ ] Import/export project as a single zip
- [ ] `--watch` mode: auto-regenerate chapter when beats file changes
- [ ] Language selection in config (currently hardcoded English)
- [ ] `--model` CLI flag to override config per-call (e.g. `generate_chapter.py 1 --model openrouter/...`)
