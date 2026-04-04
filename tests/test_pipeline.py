#!/usr/bin/env python3
"""
tests/test_pipeline.py — Deterministic tests for the story pipeline.
Run: python3 tests/test_pipeline.py
"""
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chapter_planning
import build_story_bible
import compile as compile_module
import generate_chapter as generate_chapter_module
import plan_chapters as plan_chapters_module
import summarize_chapter as summarize_chapter_module
import story_utils
from dual_llm import llm_provider
import text_quality
from config import DEFAULT_MODEL, get_model
from paths import (
    CHAPTER_BEATS_TEMPLATE_PATH,
    CURRENT_PROJECT_FILE,
    DEFAULT_PROJECT_NAME,
    DEFAULT_PROJECTS_DIR,
    PROJECT_DIR,
    PROMPTS_DIR,
    RAW_OUTPUTS_DIR,
    ROOT_DIR,
    TEMPLATES_DIR,
)


SAMPLE_STORY_BIBLE = """# **The Silent Garden**

## Story Bible

## 1. METADATA
- **Title:** The Silent Garden
- **Genre:** Literary Thriller
- **POV:** Third Person
- **Tense:** Past

---

# Chapter Outline

1. **Chapter 1 — The Letter** — Mara receives an unsigned letter that unsettles her routine. → ends: she decides to visit her childhood home
2. **Chapter 2 — The Return** — Mara returns home and finds the greenhouse locked from the inside. → ends: she hears movement after midnight
3. **Chapter 3 — Glass Hours** — Mara confronts the truth hidden in the greenhouse. → ends: she chooses whether to stay
"""

SAMPLE_BRIEF = """# Chapter 1 — The Letter

### Beat 1: Disturbance
Mara comes home in the rain, finds an unsigned letter under the door, and recognizes details nobody should know.

### Beat 2: Pressure
She rereads the letter, argues with herself, and calls her estranged brother, who refuses to answer directly.

### Beat 3: Choice
Mara searches an old drawer, finds the greenhouse key, and realizes she has to return home.

### Beat 4: Departure
She packs before dawn and leaves the city, already afraid of what will be waiting.
"""

SAMPLE_SUMMARY = """# Cumulative Story Summary

## Overview

- Total chapters: 3
- Target word count: 9,000
- **Completed Chapters:** 0
"""

REGRESSION_FIXTURES = {
    "beats_with_reasoning_leak": {
        "raw": """<think>
Thinking Process:
- inspect outline
- draft beats

# Chapter 2 — The Return

### Beat 1: Arrival
Mara returns home, studies the greenhouse door, and sees that the bolt is set from the inside.

### Beat 2: Unease
She circles the house, hears movement after midnight, and realizes fear is not distorting the sound.

### Beat 3: Decision
She chooses to investigate before dawn because waiting is making the house feel more dangerous.
""",
        "chapter_number": 2,
        "chapter_title": "The Return",
    },
    "summary_and_cumulative_reasoning_leak": {
        "summary_raw": """<think>
Thinking Process:
- inspect draft

### Chapter 2 — The Return
- Sequence:
  - Mara returns home and finds the greenhouse bolted from the inside.
- Plot facts established:
  - Someone is already on the property.
- Character end states:
  - Mara: outside the greenhouse, tense, committed to investigating.
- Open threads:
  - Who is inside the greenhouse?
""",
        "cumulative_raw": """# Cumulative Story Summary

## Overview

- Total chapters: 3
- Target word count: 9,000
- **Completed Chapters:** 1

Thinking Process:
- inspect previous summary

### Chapter 1 — The Letter
- Sequence:
  - Mara receives an unsigned letter and decides to return home.
""",
    },
    "chapter_draft_with_reasoning_and_legacy_header": {
        "draft_raw": """# Chapter 1 Draft
Generated: 2026-04-04 12:00:00
Method: staged scene-block drafting
Target: 3,000 words
Actual: 2,850 words

---

<think>
Thinking Process:
- continue scene
</think>

Mara crossed the greenhouse and lifted the ledger from the wet bench.
""",
    },
}


class TestConfig(unittest.TestCase):
    def test_default_model_is_set(self):
        self.assertEqual(DEFAULT_MODEL, "openrouter/thedrummer/cydonia-24b-v4.1")

    def test_get_model_returns_default_for_unknown_task(self):
        self.assertEqual(get_model("nonexistent_task"), DEFAULT_MODEL)

    def test_get_model_returns_configured_model(self):
        self.assertIn("openrouter", get_model("write"))

    def test_config_json_is_valid(self):
        cfg_path = os.path.join(ROOT_DIR, "config.json")
        with open(cfg_path) as handle:
            cfg = json.load(handle)
        self.assertIn("models", cfg)
        self.assertIsInstance(cfg["models"], dict)

    def test_get_local_request_overrides_defaults_to_dict(self):
        with patch("config._config_cache", {"models": {}, "story": {}}):
            from config import get_local_request_overrides
            self.assertEqual(get_local_request_overrides(), {})

    def test_get_local_request_overrides_merges_defaults_presets_and_legacy_overrides(self):
        with patch(
            "config._config_cache",
            {
                "models": {
                    "write": "openrouter/example/creative-model",
                    "summarize": "openrouter/example/summary-model",
                },
                "story": {},
                "local_request_defaults": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                "sampling_presets": {
                    "creative_open": {
                        "temperature": 1.0,
                        "top_p": 1.0,
                        "min_p": 0.05,
                        "top_k": 0,
                    },
                    "summary_strict": {
                        "temperature": 0.2,
                        "top_p": 0.8,
                    },
                },
                "task_presets": {
                    "write": "creative_open",
                    "summarize": "summary_strict",
                },
                "model_presets": {
                    "openrouter/example/creative-model": "creative_open",
                },
                "local_task_request_overrides": {
                    "write": {"top_n_sigma": 1.0},
                },
                "local_model_request_overrides": {
                    "openrouter/example/creative-model": {"min_p": 0.08},
                },
                "local_request_overrides": {
                    "chat_template_kwargs": {"enable_thinking": True},
                },
            },
        ):
            from config import get_local_request_overrides

            write_overrides = get_local_request_overrides("write")
            summarize_overrides = get_local_request_overrides("summarize")

        self.assertEqual(write_overrides["temperature"], 1.0)
        self.assertEqual(write_overrides["top_p"], 1.0)
        self.assertEqual(write_overrides["top_k"], 0)
        self.assertEqual(write_overrides["min_p"], 0.08)
        self.assertEqual(write_overrides["top_n_sigma"], 1.0)
        self.assertTrue(write_overrides["chat_template_kwargs"]["enable_thinking"])

        self.assertEqual(summarize_overrides["temperature"], 0.2)
        self.assertEqual(summarize_overrides["top_p"], 0.8)
        self.assertTrue(summarize_overrides["chat_template_kwargs"]["enable_thinking"])


class TestProjectStructure(unittest.TestCase):
    def setUp(self):
        self.root = ROOT_DIR

    def test_all_scripts_exist(self):
        for script in [
            "build_story_bible.py",
            "plan_chapters.py",
            "generate_chapter.py",
            "summarize_chapter.py",
            "repair_beats.py",
            "status.py",
            "config.py",
            "chapter_planning.py",
            "project.py",
        ]:
            self.assertTrue(os.path.exists(os.path.join(self.root, script)), f"Missing: {script}")

    def test_support_dirs_exist(self):
        for path in [PROMPTS_DIR, RAW_OUTPUTS_DIR, TEMPLATES_DIR]:
            self.assertTrue(os.path.isdir(path), f"Missing support dir: {path}")

    def test_default_project_dir_is_workspace_scoped(self):
        self.assertTrue(PROJECT_DIR.startswith(DEFAULT_PROJECTS_DIR + os.sep))
        self.assertTrue(os.path.basename(PROJECT_DIR))

    def test_beats_template_format(self):
        with open(CHAPTER_BEATS_TEMPLATE_PATH) as handle:
            content = handle.read()
        for section in ["### Beat 1:", "### Beat 2:", "### Beat 3:", "### Beat 4:"]:
            self.assertIn(section, content)


class TestStoryUtils(unittest.TestCase):
    def test_split_story_bible_and_outline_prefers_heading(self):
        story_bible, outline = story_utils.split_story_bible_and_outline(SAMPLE_STORY_BIBLE)
        self.assertIn("## Story Bible", story_bible)
        self.assertTrue(outline.startswith("# Chapter Outline"))

    def test_parse_outline_entries_extracts_titles_summaries_and_endings(self):
        _, outline = story_utils.split_story_bible_and_outline(SAMPLE_STORY_BIBLE)
        entries = story_utils.parse_outline_entries(outline)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].number, 1)
        self.assertEqual(entries[0].title, "The Letter")
        self.assertIn("unsigned letter", entries[0].summary)
        self.assertIn("visit her childhood home", entries[0].ending)

    def test_group_beats_into_blocks(self):
        beats = story_utils.parse_beats(SAMPLE_BRIEF)
        blocks = story_utils.group_beats_into_blocks(beats, beats_per_block=2)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["start_beat"], 1)
        self.assertEqual(blocks[0]["end_beat"], 2)
        self.assertEqual(blocks[1]["start_beat"], 3)
        self.assertEqual(blocks[1]["end_beat"], 4)

    def test_parse_beats_accepts_level_two_headings(self):
        brief = """# Chapter Brief — Test

## Beat 1: Arrival
First movement.

## Beat 2: Pressure
Second movement.
"""
        beats = story_utils.parse_beats(brief)
        self.assertEqual(len(beats), 2)
        self.assertEqual(beats[0][0], 1)
        self.assertIn("First movement.", beats[0][1])

    def test_parse_beats_accepts_bold_and_dash_variants(self):
        brief = """# Chapter Brief — Test

#### **Beat 1** - Arrival
First movement.

### Beat 2 — Pressure
Second movement.
"""
        beats = story_utils.parse_beats(brief)
        self.assertEqual([number for number, _ in beats], [1, 2])

    def test_upsert_chapter_summary_replaces_existing_block(self):
        original = (
            SAMPLE_SUMMARY
            + "\n### Chapter 1 — Old Title\nOld summary text.\n"
            + "\n### Chapter 2 — Another\nAnother summary.\n"
        )
        updated = story_utils.upsert_chapter_summary(
            original,
            1,
            "### Chapter 1 — New Title\nFresh summary text.",
        )
        self.assertIn("### Chapter 1 — New Title", updated)
        self.assertNotIn("Old summary text.", updated)
        self.assertIn("### Chapter 2 — Another", updated)

    def test_normalize_summary_block_strips_leading_reasoning(self):
        noisy = (
            "<think>\nThinking Process:\n- inspect draft\n\n"
            "### Chapter 2 — The Return\n"
            "- Sequence:\n"
            "  - Mara comes home.\n"
        )
        normalized = story_utils.normalize_summary_block(noisy, chapter_number=2)
        self.assertTrue(normalized.startswith("### Chapter 2 — The Return"))
        self.assertNotIn("Thinking Process", normalized)

    def test_normalize_cumulative_summary_drops_interstitial_reasoning(self):
        noisy = (
            "# Cumulative Story Summary\n\n"
            "## Overview\n\n"
            "- Total chapters: 3\n"
            "- Target word count: 9,000\n"
            "- **Completed Chapters:** 2\n\n"
            "<think>\nThinking Process:\n- inspect chapter 1\n\n"
            "### Chapter 1 — The Letter\n"
            "- Sequence:\n"
            "  - Mara receives a letter.\n\n"
            "Thinking Process:\n- inspect chapter 2\n\n"
            "### Chapter 2 — The Return\n"
            "- Sequence:\n"
            "  - Mara goes home.\n"
        )
        normalized = story_utils.normalize_cumulative_summary(noisy)
        self.assertIn("- **Completed Chapters:** 2", normalized)
        self.assertIn("### Chapter 1 — The Letter", normalized)
        self.assertIn("### Chapter 2 — The Return", normalized)
        self.assertNotIn("Thinking Process", normalized)

    def test_salvage_beats_document_rebuilds_missing_heading(self):
        noisy = (
            "Thinking Process:\n- plan beats\n\n"
            "### Beat 1: Arrival\nMara enters the greenhouse before dawn and notices the broken lock and disturbed soil.\n\n"
            "### Beat 2: Search\nShe checks the workbench and realizes the ledger is missing from the drawer.\n\n"
            "### Beat 3: Choice\nShe decides to stay until sunrise and confront whoever returns.\n"
        )
        normalized = story_utils.salvage_beats_document(noisy, chapter_number=3, chapter_title="Glass Hours")
        self.assertTrue(normalized.startswith("# Chapter 3 — Glass Hours"))
        self.assertIn("### Beat 2: Search", normalized)

    def test_sanitize_beats_document_removes_thinking_and_restores_heading(self):
        noisy = (
            "<think>\nThinking Process:\n- plan beats\n\n"
            "### Beat 1: Arrival\nMara enters the greenhouse before dawn and notices the broken lock and disturbed soil.\n\n"
            "### Beat 2: Search\nShe checks the workbench and realizes the ledger is missing from the drawer.\n\n"
            "### Beat 3: Choice\nShe decides to stay until sunrise and confront whoever returns.\n"
        )
        cleaned = story_utils.sanitize_beats_document(
            noisy,
            chapter_number=3,
            chapter_title="Glass Hours",
        )
        self.assertTrue(cleaned.startswith("# Chapter 3 — Glass Hours"))
        self.assertNotIn("<think>", cleaned)
        self.assertNotIn("Thinking Process", cleaned)

    def test_sanitize_chapter_draft_document_removes_thinking_tags(self):
        noisy = (
            "<think>\nThinking Process:\n- continue scene\n</think>\n\n"
            "Mara crossed the greenhouse and lifted the ledger from the wet bench."
        )
        cleaned = story_utils.sanitize_chapter_draft_document(noisy)
        self.assertEqual(
            cleaned,
            "Mara crossed the greenhouse and lifted the ledger from the wet bench.",
        )

    def test_analyze_beats_document_flags_placeholders_and_duplicates(self):
        brief = """# Chapter Brief — Test

### Beat 1: Arrival
[Placeholder words]

### Beat 2: Arrival
[Placeholder words]

### Beat 3: Exit
Short note.
"""
        issues = story_utils.analyze_beats_document(brief)
        self.assertTrue(issues)
        self.assertTrue(any("placeholder" in issue.lower() for issue in issues))


class TestChapterPlanning(unittest.TestCase):
    def test_find_chapter_entry(self):
        entry = chapter_planning.find_chapter_entry(SAMPLE_STORY_BIBLE, 2)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.title, "The Return")

    def test_build_chapter_beats_prompt_includes_outline_and_next_hint(self):
        prompt = chapter_planning.build_chapter_beats_prompt(
            SAMPLE_STORY_BIBLE,
            1,
            cumulative_summary=SAMPLE_SUMMARY,
            beats_template="template here",
        )
        self.assertIn("CURRENT CHAPTER TARGET", prompt)
        self.assertIn("Chapter 2 should open from", prompt)
        self.assertIn("template here", prompt)
        self.assertIn("Mara receives an unsigned letter", prompt)

    def test_plan_chapters_regen_beats_passes_full_story_bible_to_prompt_builder(self):
        temp_project = tempfile.mkdtemp(prefix="plan_beats_")
        self.addCleanup(lambda: shutil.rmtree(temp_project, ignore_errors=True))

        story_bible_path = os.path.join(temp_project, "story_bible.md")
        with open(story_bible_path, "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)

        prompt_story_bibles = []

        def fake_build_chapter_beats_prompt(story_bible_text, chapter_number, cumulative_summary="", beats_template=""):
            prompt_story_bibles.append(story_bible_text)
            return f"prompt for chapter {chapter_number}"

        with patch.dict(os.environ, {"BOOK_PROJECT_DIR": temp_project}, clear=False):
            with patch.object(sys, "argv", ["plan_chapters.py", "--regen-beats"]):
                with patch("plan_chapters.build_chapter_beats_prompt", side_effect=fake_build_chapter_beats_prompt):
                    with patch("plan_chapters.stream_llm", return_value=SAMPLE_BRIEF):
                        with patch(
                            "plan_chapters.finalize_beats_document",
                            return_value={
                                "content": SAMPLE_BRIEF,
                                "issues": [],
                                "initial_issues": [],
                                "repaired": False,
                            },
                        ):
                            plan_chapters_module.main()

        self.assertTrue(prompt_story_bibles)
        self.assertTrue(all("# Chapter Outline" in text for text in prompt_story_bibles))

    def test_plan_chapters_stops_after_first_invalid_brief(self):
        temp_project = tempfile.mkdtemp(prefix="plan_beats_fail_")
        self.addCleanup(lambda: shutil.rmtree(temp_project, ignore_errors=True))

        story_bible_path = os.path.join(temp_project, "story_bible.md")
        with open(story_bible_path, "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)

        llm_prompts = []
        finalize_calls = []

        def fake_stream_llm(user_prompt, model=None, system=None, **kwargs):
            llm_prompts.append(user_prompt)
            return SAMPLE_BRIEF

        def fake_finalize(content, chapter_number, chapter_title, current_chapter_target_prompt, llm_call=None, repair_requirements=None):
            finalize_calls.append(int(chapter_number))
            if int(chapter_number) == 2:
                return {
                    "content": content,
                    "issues": ["Beat 5 still contains placeholder-style brackets."],
                    "initial_issues": ["Beat 5 still contains placeholder-style brackets."],
                    "repaired": True,
                    "strict_retry": False,
                }
            return {
                "content": content,
                "issues": [],
                "initial_issues": [],
                "repaired": False,
                "strict_retry": False,
            }

        with patch.dict(os.environ, {"BOOK_PROJECT_DIR": temp_project}, clear=False):
            with patch.object(sys, "argv", ["plan_chapters.py", "--regen-beats"]):
                with patch("plan_chapters.stream_llm", side_effect=fake_stream_llm):
                    with patch("plan_chapters.finalize_beats_document", side_effect=fake_finalize):
                        with self.assertRaises(SystemExit) as exc:
                            plan_chapters_module.main()

        self.assertEqual(exc.exception.code, 1)
        self.assertEqual(finalize_calls, [1, 2])
        self.assertEqual(len(llm_prompts), 2)
        self.assertTrue(os.path.exists(os.path.join(temp_project, "chapters", "chapter_001_beats.md")))
        self.assertFalse(os.path.exists(os.path.join(temp_project, "chapters", "chapter_002_beats.md")))
        self.assertFalse(os.path.exists(os.path.join(temp_project, "chapters", "chapter_003_beats.md")))

    def test_build_scene_block_prompt_includes_continuity(self):
        beats = story_utils.parse_beats(SAMPLE_BRIEF)
        block = story_utils.group_beats_into_blocks(beats, beats_per_block=2)[0]
        prompt = chapter_planning.build_scene_block_prompt(
            SAMPLE_STORY_BIBLE,
            SAMPLE_SUMMARY,
            SAMPLE_BRIEF,
            "SYSTEM PROMPT",
            1,
            block,
            block_target_words=1600,
            prior_blocks_summary="Block 0 summary",
            prior_text_tail="Last line of prior prose.",
            total_blocks=2,
        )
        self.assertIn("Block 1 of 2", prompt)
        self.assertIn("Target length: about 1,600 words", prompt)
        self.assertIn("Last line of prior prose.", prompt)
        self.assertIn("Block 0 summary", prompt)
        self.assertIn("SYSTEM PROMPT", prompt)
        self.assertIn("COMPLETED BEATS (already covered; do not restage):", prompt)
        self.assertIn("UPCOMING BEATS (aim toward these, but do not fully cover them yet):", prompt)
        self.assertIn("Do not replay, paraphrase, or re-stage an earlier beat", prompt)
        self.assertNotIn("FULL CHAPTER BRIEF FOR", prompt)

    def test_build_scene_block_prompt_separates_completed_current_and_upcoming_beats(self):
        beats = story_utils.parse_beats(SAMPLE_BRIEF)
        block = story_utils.group_beats_into_blocks(beats, beats_per_block=2)[1]
        prompt = chapter_planning.build_scene_block_prompt(
            SAMPLE_STORY_BIBLE,
            SAMPLE_SUMMARY,
            SAMPLE_BRIEF,
            "SYSTEM PROMPT",
            1,
            block,
            block_target_words=1600,
            prior_blocks_summary="Block 1 summary",
            prior_text_tail="The train pulled out.",
            total_blocks=2,
        )
        self.assertIn("- Beat 1: Mara comes home in the rain", prompt)
        self.assertIn("- Beat 2: She rereads the letter", prompt)
        self.assertIn("### Beat 3: Choice", prompt)
        self.assertIn("### Beat 4: Departure", prompt)
        self.assertNotIn("(No earlier beats in this chapter.)", prompt)
        self.assertIn("(No later beats.)", prompt)

    def test_build_block_system_prompt_reframes_full_chapter_prompt(self):
        base_prompt = (
            "Write the chapter in an immersive, polished voice that matches the tone described in the story bible, embracing raw sensuality and explicit eroticism whenever intimacy or desire appears.\n\n"
            "RULES:\n"
            "- Begin the chapter immediately: no title cards, no \"Chapter X\" headers, no summaries before the prose\n"
            "- End where the brief says the chapter should end; do not add teaser notes or meta commentary\n\n"
            "WORD COUNT MANDATE:\n"
            "- Target approximately 3,333 words, giving erotic scenes the extra length they need to feel immersive and intense rather than rushed.\n"
            "- If you are ending too early, deepen the active scene (especially intimate ones) with concrete action, dialogue, and interiority rather than padding\n\n"
            "After writing the chapter, output ONLY the chapter text.\n"
        )
        prompt = chapter_planning.build_block_system_prompt(base_prompt, 1600)
        self.assertIn("Write only the current scene block of the chapter", prompt)
        self.assertIn("Continue the chapter from the current moment", prompt)
        self.assertIn("Target approximately 1,600 words for this block", prompt)
        self.assertIn("output ONLY the block prose", prompt)
        self.assertNotIn("Begin the chapter immediately", prompt)
        self.assertNotIn("After writing the chapter", prompt)


class TestBuildStoryBible(unittest.TestCase):
    def test_outline_matches_target_requires_exact_sequence_and_count(self):
        _, outline = story_utils.split_story_bible_and_outline(SAMPLE_STORY_BIBLE)
        entries = story_utils.parse_outline_entries(outline)
        self.assertTrue(build_story_bible._outline_matches_target(entries, 3))
        self.assertFalse(build_story_bible._outline_matches_target(entries, 2))

    def test_ensure_story_bible_has_outline_preserves_existing_outline(self):
        merged, reason = build_story_bible.ensure_story_bible_has_outline(SAMPLE_STORY_BIBLE, 3)
        _, outline = story_utils.split_story_bible_and_outline(merged)
        entries = story_utils.parse_outline_entries(outline)
        self.assertIsNone(reason)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].title, "The Letter")

    def test_ensure_story_bible_has_outline_regenerates_wrong_sized_outline(self):
        wrong_outline_story = SAMPLE_STORY_BIBLE + (
            "4. **Chapter 4 — Extra** — This extra chapter should force regeneration. → ends: none\n"
        )
        generated_outline = """# Chapter Outline

1. **Chapter 1 — The Letter** — Mara receives an unsigned letter that unsettles her routine. → ends: she decides to visit her childhood home
2. **Chapter 2 — The Return** — Mara returns home and finds the greenhouse locked from the inside. → ends: she hears movement after midnight
3. **Chapter 3 — Glass Hours** — Mara confronts the truth hidden in the greenhouse. → ends: she chooses whether to stay
"""
        with patch("build_story_bible.stream_llm", return_value=generated_outline) as mock_stream:
            merged, reason = build_story_bible.ensure_story_bible_has_outline(wrong_outline_story, 3)

        self.assertEqual(mock_stream.call_count, 1)
        _, outline = story_utils.split_story_bible_and_outline(merged)
        entries = story_utils.parse_outline_entries(outline)
        self.assertIn("mismatch", reason)
        self.assertEqual(len(entries), 3)

    def test_ensure_story_bible_has_outline_generates_missing_outline(self):
        story_bible_without_outline, _ = story_utils.split_story_bible_and_outline(SAMPLE_STORY_BIBLE)
        generated_outline = """# Chapter Outline

1. **Chapter 1 — The Letter** — Mara receives an unsigned letter that unsettles her routine. → ends: she decides to visit her childhood home
2. **Chapter 2 — The Return** — Mara returns home and finds the greenhouse locked from the inside. → ends: she hears movement after midnight
3. **Chapter 3 — Glass Hours** — Mara confronts the truth hidden in the greenhouse. → ends: she chooses whether to stay
"""
        with patch("build_story_bible.stream_llm", return_value=generated_outline) as mock_stream:
            merged, reason = build_story_bible.ensure_story_bible_has_outline(story_bible_without_outline, 3)

        self.assertEqual(mock_stream.call_count, 1)
        _, outline = story_utils.split_story_bible_and_outline(merged)
        entries = story_utils.parse_outline_entries(outline)
        self.assertIn("did not contain a parseable chapter outline", reason)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[1].title, "The Return")

    def test_repair_chapter_beats_if_needed_repairs_malformed_brief(self):
        malformed = """Chapter 1 — The Letter

Beat 1: Disturbance
Mara comes home in the rain.
"""
        repaired = """# Chapter 1 — The Letter

### Beat 1: Disturbance
Mara comes home in the rain, finds an unsigned letter under the door, and recognizes details nobody should know.

### Beat 2: Pressure
She rereads the letter, argues with herself, and calls her estranged brother, who refuses to answer directly.

### Beat 3: Choice
Mara searches an old drawer, finds the greenhouse key, and realizes she has to return home.
"""
        with patch("build_story_bible.stream_llm", return_value=repaired) as mock_stream:
            output, issues = build_story_bible.repair_chapter_beats_if_needed(malformed, 1)

        self.assertEqual(mock_stream.call_count, 1)
        self.assertTrue(issues)
        self.assertTrue(output.startswith("# Chapter 1"))


class TempWorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chapters_dir = os.path.join(self.temp_dir, "chapters")
        os.makedirs(self.chapters_dir, exist_ok=True)
        self.story_bible_path = os.path.join(self.temp_dir, "story_bible.md")
        self.summary_path = os.path.join(self.temp_dir, "cumulative_summary.md")
        self.system_prompt_path = os.path.join(self.temp_dir, "system_prompt.txt")
        self.beats_template_path = os.path.join(self.temp_dir, "chapter_beats_TEMPLATE.md")
        self.draft_path = os.path.join(self.chapters_dir, "chapter_001_draft.txt")
        self.log_path = os.path.join(self.chapters_dir, "chapter_001_generation_log.md")
        self.chapter_1_brief_path = os.path.join(self.chapters_dir, "chapter_001_beats.md")
        self.chapter_2_brief_path = os.path.join(self.chapters_dir, "chapter_002_beats.md")

        with open(self.story_bible_path, "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)
        with open(self.summary_path, "w") as handle:
            handle.write(SAMPLE_SUMMARY)
        with open(self.system_prompt_path, "w") as handle:
            handle.write(
                "Write in [PAST_TENSE/PRESENT_TENSE] and [FIRST_PERSON/THIRD_PERSON]. "
                "Target [WORD_COUNT_TARGET] words."
            )
        with open(self.chapter_1_brief_path, "w") as handle:
            handle.write(SAMPLE_BRIEF)
        with open(self.beats_template_path, "w") as handle:
            handle.write("# Chapter 2 — [TITLE]\n\n### Beat 1: A\nx\n\n### Beat 2: B\ny\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def patch_generate_chapter_paths(self):
        return patch.multiple(
            generate_chapter_module,
            STORY_BIBLE_PATH=self.story_bible_path,
            CUMULATIVE_SUMMARY_PATH=self.summary_path,
            SYSTEM_PROMPT_PATH=self.system_prompt_path,
            CHAPTER_BEATS_TEMPLATE_PATH=self.beats_template_path,
            ensure_runtime_dirs=lambda: None,
            chapter_beats_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter:03d}_beats.md"),
            chapter_draft_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter:03d}_draft.txt"),
            chapter_generation_log_path=lambda chapter: os.path.join(
                self.chapters_dir, f"chapter_{chapter:03d}_generation_log.md"
            ),
        )

    def patch_summarize_chapter_paths(self):
        return patch.multiple(
            summarize_chapter_module,
            STORY_BIBLE_PATH=self.story_bible_path,
            CUMULATIVE_SUMMARY_PATH=self.summary_path,
            CHAPTER_BEATS_TEMPLATE_PATH=self.beats_template_path,
            chapter_beats_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter:03d}_beats.md"),
            chapter_draft_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter:03d}_draft.txt"),
        )


class TestGenerateChapterFlow(TempWorkspaceCase):
    def test_prepare_system_prompt_fills_placeholders(self):
        prompt, target = generate_chapter_module.prepare_system_prompt(
            "Use [PAST_TENSE/PRESENT_TENSE], [FIRST_PERSON/THIRD_PERSON], [WORD_COUNT_TARGET].",
            SAMPLE_STORY_BIBLE,
        )
        self.assertGreater(target, 0)
        self.assertIn("past tense", prompt)
        self.assertIn("third person", prompt)
        self.assertNotIn("[WORD_COUNT_TARGET]", prompt)

    def test_generate_chapter_uses_scene_blocks_and_revision(self):
        outputs = [
            "Block one prose with rain, tension, dialogue, memory, motion, and enough concrete detail to read like a real opening scene.",
            "Block two prose with departure, dread, argument, movement, and enough concrete detail to read like a real follow-through scene.",
            "Revised final chapter prose with smoother transitions, concrete action, dialogue, sensory detail, and enough length to satisfy the validator cleanly while staying within the tiny mock target.",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 30)
        ), patch.object(
            generate_chapter_module, "clean_chapter_text", side_effect=lambda text, *args, **kwargs: (text, [])
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream, patch.object(
            generate_chapter_module, "find_quality_issues", return_value=[]
        ), patch.object(
            generate_chapter_module,
            "recover_final_chapter_text",
            return_value="Recovered final chapter prose with smoother transitions, concrete action, dialogue, sensory detail, and enough length to satisfy the validator cleanly while staying within the tiny mock target.",
        ):
            word_count, output_path = generate_chapter_module.generate_chapter(
                1,
                self.temp_dir,
                silent=True,
                beats_per_block=2,
                revise=True,
            )

        self.assertEqual(mock_stream.call_count, 3)
        self.assertEqual(output_path, self.draft_path)
        self.assertGreater(word_count, 0)

        with open(self.draft_path) as handle:
            draft = handle.read()
        self.assertNotIn("Method: staged scene-block drafting", draft)
        self.assertNotIn("Generated:", draft)
        self.assertIn("Revised final chapter prose", draft)

        with open(self.log_path) as handle:
            log = handle.read()
        self.assertIn("Blocks: 2", log)
        self.assertIn("Revision pass: yes", log)

    def test_generate_chapter_without_revision_uses_assembled_blocks(self):
        outputs = [
            "First block prose with enough concrete action, movement, and detail to pass the validator without extra cleanup.",
            "Second block prose with enough concrete action, movement, and detail to pass the validator without extra cleanup.",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 40)
        ), patch.object(
            generate_chapter_module, "clean_chapter_text", side_effect=lambda text, *args, **kwargs: (text, [])
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream:
            _, _ = generate_chapter_module.generate_chapter(
                1,
                self.temp_dir,
                silent=True,
                beats_per_block=2,
                revise=False,
            )

        self.assertEqual(mock_stream.call_count, 2)
        with open(self.draft_path) as handle:
            draft = handle.read()
        self.assertIn("First block prose with enough concrete action", draft)
        self.assertIn("Second block prose with enough concrete action", draft)

    def test_generate_chapter_runs_cleanup_when_revision_is_out_of_range(self):
        outputs = [
            "Block one prose with setup.",
            "Block two prose with payoff.",
            "Too short.",
            (
                "Expanded final prose carries concrete action, dialogue, memory, and interiority. "
                "Elara crosses the room, answers Finn, studies the bottle, and commits to the next step. "
                "She pauses at the window, hears the surf, speaks aloud, and chooses action with "
                "specific movement, feeling, and consequence on the page."
            ),
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 50)
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream:
            _, _ = generate_chapter_module.generate_chapter(
                1,
                self.temp_dir,
                silent=True,
                beats_per_block=2,
                revise=True,
                enforce_length=True,
                cleanup=True,
            )

        self.assertEqual(mock_stream.call_count, 4)
        with open(self.log_path) as handle:
            log = handle.read()
        self.assertIn("Cleanup passes: 1", log)
        self.assertIn("Regeneration events:", log)
        self.assertIn("Cleanup pass 1 triggered:", log)
        self.assertIn("Too short:", log)

    def test_generate_chapter_recovers_when_final_output_leaks_beat_format(self):
        outputs = [
            "Block one prose with setup and enough detail to count as a scene.",
            "Block two prose with payoff and enough detail to count as a scene.",
            "# Chapter 1: Test\n\n## Beat 1 - Bad\nPlanning text.\n\n### Word Count: 50",
        ]
        recovered = (
            "Recovered final prose carries concrete action, dialogue, setting detail, and interiority "
            "without any headings. Mara crosses the kitchen, answers Theo, studies the torn note, "
            "and keeps moving as the wind rattles the greenhouse panes around them while the scene expands into usable chapter prose with sustained movement, reaction, and emotional consequence."
        )

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 40)
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream, patch.object(
            generate_chapter_module, "clean_chapter_text", side_effect=lambda text, *args, **kwargs: (text, [])
        ), patch.object(
            generate_chapter_module, "recover_final_chapter_text", return_value=recovered
        ), patch.object(
            generate_chapter_module, "find_quality_issues", side_effect=[["bad final draft"], []]
        ):
            word_count, _ = generate_chapter_module.generate_chapter(
                1,
                self.temp_dir,
                silent=True,
                beats_per_block=2,
                revise=True,
                cleanup=True,
            )

        self.assertEqual(mock_stream.call_count, 3)
        self.assertGreater(word_count, 0)
        with open(self.draft_path) as handle:
            draft = handle.read()
        self.assertIn("Recovered final prose", draft)
        self.assertNotIn("## Beat 1 - Bad", draft)
        with open(self.log_path) as handle:
            log = handle.read()
        self.assertIn("Final recovery triggered:", log)

    def test_generate_chapter_exits_when_final_output_stays_invalid(self):
        outputs = [
            "Block one prose with setup and enough detail to count as a scene.",
            "Block two prose with payoff and enough detail to count as a scene.",
            "# Chapter 1: Test\n\n## Beat 1 - Bad\nPlanning text.\n\n### Word Count: 50",
            "# Chapter 1: Still Bad\n\n## Beat 1 - Worse\nMore planning text.\n\n### Notes:\n- meta",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 50)
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ), patch.object(
            generate_chapter_module, "clean_chapter_text", side_effect=lambda text, *args, **kwargs: (text, [])
        ):
            with self.assertRaises(SystemExit):
                generate_chapter_module.generate_chapter(
                    1,
                    self.temp_dir,
                    silent=True,
                    beats_per_block=2,
                    revise=True,
                    cleanup=True,
                )

    def test_generate_chapter_writes_permissive_draft_when_cleanup_disabled(self):
        outputs = [
            "Block one prose with setup and enough detail to count as a scene.",
            "Block two prose with payoff and enough detail to count as a scene.",
            "# Chapter 1: Test\n\n## Beat 1 - Bad\nPlanning text.\n\n### Word Count: 50",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "prepare_system_prompt", return_value=("SYSTEM", 40)
        ), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream:
            word_count, _ = generate_chapter_module.generate_chapter(
                1,
                self.temp_dir,
                silent=True,
                beats_per_block=2,
                revise=True,
                cleanup=False,
            )

        self.assertEqual(mock_stream.call_count, 3)
        self.assertGreater(word_count, 0)
        with open(self.draft_path) as handle:
            draft = handle.read()
        self.assertIn("## Beat 1 - Bad", draft)
        with open(self.log_path) as handle:
            log = handle.read()
        self.assertIn("Cleanup enforcement: no", log)

    def test_generate_next_chapter_beats_writes_next_brief(self):
        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module,
            "stream_llm",
            return_value=(
                "# Chapter 2 — The Return\n\n"
                "### Beat 1: Arrival\nMara returns home, studies the greenhouse door, notices the bolt set from inside, and realizes nobody should be there at this hour.\n\n"
                "### Beat 2: Unease\nShe circles the house, hears movement after midnight, checks the dark windows twice, and starts doubting whether fear is distorting her senses.\n\n"
                "### Beat 3: Decision\nShe decides to investigate before dawn rather than wait for help, because hesitation is making the locked greenhouse feel even more threatening.\n"
            ),
        ):
            created = generate_chapter_module.generate_next_chapter_beats(1)

        self.assertEqual(created, self.chapter_2_brief_path)
        with open(self.chapter_2_brief_path) as handle:
            content = handle.read()
        self.assertIn("# Chapter 2 — The Return", content)

    def test_generate_next_chapter_beats_repairs_low_quality_brief_once(self):
        outputs = [
            "# Chapter 2 — The Return\n\n### Beat 1: Arrival\n[TODO]\n\n### Beat 2: Arrival\n[TODO]\n",
            (
                "# Chapter 2 — The Return\n\n"
                "### Beat 1: Arrival\nMara returns home, studies the greenhouse, notices it is locked from inside, and feels immediate dread because nobody should have access.\n\n"
                "### Beat 2: Unease\nShe hears movement after midnight, checks the windows, retraces her steps through the yard, and doubts her own senses as tension keeps building.\n\n"
                "### Beat 3: Decision\nShe chooses to investigate before dawn, despite fear, because waiting will only worsen the dread and leave the mystery controlling her.\n"
            ),
        ]
        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ):
            created = generate_chapter_module.generate_next_chapter_beats(1)

        self.assertEqual(created, self.chapter_2_brief_path)
        with open(self.chapter_2_brief_path) as handle:
            content = handle.read()
        self.assertIn("### Beat 3: Decision", content)

    def test_generate_next_chapter_beats_retries_strictly_when_no_beats(self):
        outputs = [
            "This chapter should focus on tension and atmosphere.",
            "Still bad output with no beat sections at all.",
            (
                "# Chapter 2 — The Return\n\n"
                "### Beat 1: Arrival\nMara returns home after midnight, checks the greenhouse lock, and notices marks that suggest someone entered recently.\n\n"
                "### Beat 2: Unease\nShe circles the house twice, hears movement in the dark, and realizes she can no longer dismiss her fear as imagination.\n\n"
                "### Beat 3: Decision\nShe commits to investigating before dawn despite the risk because waiting would leave the threat in control.\n\n"
                "### Beat 4: Handoff\nShe opens the greenhouse door and steps inside, ending the chapter at the threshold of direct confrontation.\n"
            ),
        ]
        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ):
            created = generate_chapter_module.generate_next_chapter_beats(1)

        self.assertEqual(created, self.chapter_2_brief_path)
        with open(self.chapter_2_brief_path) as handle:
            content = handle.read()
        self.assertIn("### Beat 4: Handoff", content)


class TestCompile(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp()
        self.chapters_dir = os.path.join(self.project_dir, "chapters")
        os.makedirs(self.chapters_dir, exist_ok=True)
        with open(os.path.join(self.project_dir, "story_bible.md"), "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)
        with open(os.path.join(self.chapters_dir, "chapter_001_draft.txt"), "w") as handle:
            handle.write("Chapter one prose.")
        with open(os.path.join(self.chapters_dir, "chapter_002_draft.txt"), "w") as handle:
            handle.write("Chapter two prose.")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_compile_book_writes_markdown_for_explicit_project(self):
        output_dir = tempfile.mkdtemp()
        try:
            with patch.object(compile_module, "write_epub", return_value=(False, "pandoc not found")):
                compile_module.compile_book(project_dir=self.project_dir, output_path=output_dir, dry_run=False)
            project_name = os.path.basename(os.path.normpath(self.project_dir))
            md_path = os.path.join(output_dir, project_name + ".md")
            self.assertTrue(os.path.exists(md_path))
            with open(md_path) as handle:
                content = handle.read()
            self.assertIn("# The Silent Garden", content)
            self.assertIn("## Chapter 1: The Letter", content)
            self.assertNotIn("Generated:", content)
            self.assertNotIn("Method: staged scene-block drafting", content)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_compile_book_strips_legacy_draft_metadata(self):
        with open(os.path.join(self.chapters_dir, "chapter_001_draft.txt"), "w") as handle:
            handle.write(
                "# Chapter 1 Draft\n"
                "Generated: 2026-04-04 12:00:00\n"
                "Method: staged scene-block drafting\n"
                "Target: 3,000 words\n"
                "Actual: 2,850 words\n\n"
                "---\n\n"
                "Chapter one prose.\n"
            )

        compiled_markdown, chapter_count = compile_module.build_compiled_markdown(self.project_dir)

        self.assertEqual(chapter_count, 2)
        self.assertIn("Chapter one prose.", compiled_markdown)
        self.assertNotIn("# Chapter 1 Draft", compiled_markdown)
        self.assertNotIn("Generated:", compiled_markdown)
        self.assertNotIn("Method: staged scene-block drafting", compiled_markdown)

    def test_compile_book_copies_epub_to_repo_directory(self):
        export_root = tempfile.mkdtemp()
        output_dir = tempfile.mkdtemp()
        try:
            def fake_write_epub(md_path, epub_path):
                with open(epub_path, "w") as handle:
                    handle.write("fake epub")
                return True, None

            with patch.object(compile_module, "COMPILED_EPUBS_DIR", export_root), patch.object(
                compile_module, "write_epub", side_effect=fake_write_epub
            ):
                compile_module.compile_book(project_dir=self.project_dir, output_path=output_dir, dry_run=False)

            project_name = os.path.basename(os.path.normpath(self.project_dir))
            copied_epub = os.path.join(export_root, project_name + ".epub")
            self.assertTrue(os.path.exists(copied_epub))
        finally:
            shutil.rmtree(export_root, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_compile_book_dry_run_reports_epub_copy_destination(self):
        output_dir = tempfile.mkdtemp()
        try:
            stdout = io.StringIO()
            with patch.object(compile_module, "COMPILED_EPUBS_DIR", "/tmp/shared_epubs"), patch("sys.stdout", stdout):
                compile_module.compile_book(project_dir=self.project_dir, output_path=output_dir, dry_run=True)

            output = stdout.getvalue()
            self.assertIn("Would also copy EPUB to", output)
            self.assertIn("/tmp/shared_epubs", output)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


class TestLLMProvider(unittest.TestCase):
    def test_merge_payload_allows_nested_local_request_overrides(self):
        merged = llm_provider._merge_payload(
            {
                "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            {
                "chat_template_kwargs": {"enable_thinking": True},
                "top_k": 20,
            },
        )
        self.assertTrue(merged["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(merged["top_k"], 20)

    def test_stream_local_applies_task_specific_request_overrides(self):
        response_lines = iter(
            [
                b'data: {"choices":[{"delta":{"content":"Clean output."}}]}',
                b"data: [DONE]",
            ]
        )

        class FakeResponse:
            status_code = 200
            text = ""

            def iter_lines(self):
                return response_lines

            def close(self):
                return None

        captured = {}

        def fake_post(url, json=None, headers=None, stream=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

        with patch("requests.post", side_effect=fake_post), patch(
            "dual_llm.llm_provider.get_local_endpoint", return_value="http://localhost:8080"
        ), patch(
            "dual_llm.llm_provider.get_local_model", return_value="local"
        ), patch(
            "dual_llm.llm_provider.get_local_request_overrides",
            return_value={
                "temperature": 1.0,
                "top_p": 1.0,
                "min_p": 0.05,
                "top_k": 0,
                "top_n_sigma": 1.0,
            },
        ) as mock_get_overrides:
            result = llm_provider._stream_local(
                "Prompt",
                model="write",
                system="System",
                silent=True,
                max_words=100,
            )

        self.assertEqual(result, "Clean output.")
        self.assertEqual(mock_get_overrides.call_args.args[0], "write")
        self.assertEqual(captured["payload"]["temperature"], 1.0)
        self.assertEqual(captured["payload"]["top_p"], 1.0)
        self.assertEqual(captured["payload"]["min_p"], 0.05)
        self.assertEqual(captured["payload"]["top_k"], 0)
        self.assertEqual(captured["payload"]["top_n_sigma"], 1.0)

    def test_repetition_heuristics_flag_obvious_loop(self):
        text = ("the storm raged on and on and on " * 80).strip()
        self.assertGreaterEqual(text_quality.max_ngram_repetition_ratio(text), 0.18)
        self.assertTrue(text_quality.looks_like_runaway_repetition(text))

    def test_repetition_heuristics_ignore_normal_prose(self):
        text = (
            "Mara crossed the kitchen, opened the letter, read the signature twice, and looked toward the greenhouse. "
            "Rain clicked against the window while Theo searched the hall closet for a flashlight and muttered about the broken lock. "
            "She answered him, folded the paper into her pocket, and stepped onto the porch before she could change her mind."
        )
        self.assertLess(text_quality.max_ngram_repetition_ratio(text), 0.18)
        self.assertFalse(text_quality.looks_like_runaway_repetition(text))

    def test_strip_leading_reasoning_preamble_recovers_heading_after_unclosed_think(self):
        leaked = (
            "<think>\n"
            "Thinking Process:\n"
            "- inspect prompt\n"
            "- plan answer\n\n"
            "# Chapter 3 — Glass Hours\n\n"
            "### Beat 1: Arrival\n"
            "Mara enters the greenhouse and notices the broken pane.\n"
        )
        cleaned = llm_provider._strip_leading_reasoning_preamble(leaked)
        self.assertTrue(cleaned.startswith("# Chapter 3 — Glass Hours"))
        self.assertNotIn("Thinking Process", cleaned)


class TestDraftQuality(unittest.TestCase):
    def test_find_quality_issues_flags_repetitive_looping_text(self):
        text = ("the storm raged on and on and on " * 80).strip()
        issues = generate_chapter_module.find_quality_issues(text, target_words_total=200)
        self.assertTrue(any("repetition" in issue.lower() or "compresses too well" in issue.lower() for issue in issues))

    def test_find_quality_issues_does_not_flag_short_length_by_default(self):
        text = "Mara opened the door, read the letter, and froze."
        issues = generate_chapter_module.find_quality_issues(text, target_words_total=200)
        self.assertFalse(any("too short" in issue.lower() or "too long" in issue.lower() for issue in issues))

    def test_find_quality_issues_can_flag_short_length_when_enabled(self):
        text = "Mara opened the door, read the letter, and froze."
        issues = generate_chapter_module.find_quality_issues(
            text,
            target_words_total=200,
            enforce_length=True,
        )
        self.assertTrue(any("too short" in issue.lower() for issue in issues))


class TestSummarizeChapter(TempWorkspaceCase):
    def test_build_summary_prompt_requests_rough_state_tracking(self):
        prompt = summarize_chapter_module.build_summary_prompt(
            2,
            "Mara returned to the greenhouse and found the lock broken.",
        )
        self.assertIn("rough working summary", prompt)
        self.assertIn("Be literal and compressed, not polished", prompt)
        self.assertIn("### Chapter 2 — [SHORT TITLE]", prompt)
        self.assertIn("- Character end states:", prompt)
        self.assertIn("- Open threads:", prompt)

    def test_summarize_repairs_malformed_next_brief_before_writing(self):
        chapter_2_draft_path = os.path.join(self.chapters_dir, "chapter_002_draft.txt")
        chapter_3_brief_path = os.path.join(self.chapters_dir, "chapter_003_beats.md")
        with open(chapter_2_draft_path, "w") as handle:
            handle.write("Chapter two draft prose with enough detail to summarize.")

        outputs = [
            "### Chapter 2 — Rough State\n- Sequence:\n  - Mara returns home.\n- Plot facts established:\n  - The greenhouse is unlocked.\n- Character end states:\n  - Mara: outside, tense.\n- Open threads:\n  - Who entered the greenhouse?\n",
            (
                "<think>\nThinking Process:\n- analyze prompt\n\n"
                "# Chapter 3 — Glass Hours\n\n"
                "### Beat 1: Arrival\n"
                "Mara steps into the greenhouse before dawn, tracks the draft through broken glass, and realizes someone has already disturbed the room.\n\n"
                "### Beat 2: Search\n"
                "She checks the workbench, studies the disturbed soil, and connects the missing ledger to the unsigned letter from earlier.\n\n"
                "### Beat 3: Confrontation\n"
                "A hidden speaker forces her to face the family secret directly, and she understands why the greenhouse was sealed.\n"
            ),
            (
                "# Chapter 3 — Glass Hours\n\n"
                "### Beat 1: Arrival\n"
                "Mara steps into the greenhouse before dawn, tracks the draft through broken glass, and realizes someone has already disturbed the room.\n\n"
                "### Beat 2: Search\n"
                "She checks the workbench, studies the disturbed soil, and connects the missing ledger to the unsigned letter from earlier.\n\n"
                "### Beat 3: Confrontation\n"
                "A hidden speaker forces her to face the family secret directly, and she understands why the greenhouse was sealed.\n\n"
                "### Beat 4: Choice\n"
                "She decides to stay through sunrise and learn the rest in person, ending the chapter with a deliberate choice to remain inside.\n"
            ),
        ]

        with self.patch_summarize_chapter_paths(), patch.object(
            summarize_chapter_module, "stream_llm", side_effect=outputs
        ), patch.object(
            summarize_chapter_module, "get_total_chapters", return_value=3
        ), patch.object(
            summarize_chapter_module, "get_word_count_target", return_value=9000
        ), patch.object(
            sys, "argv", ["summarize_chapter.py", "2", "--quiet"]
        ):
            summarize_chapter_module.main()

        with open(chapter_3_brief_path) as handle:
            content = handle.read()
        self.assertTrue(content.startswith("# Chapter 3 — Glass Hours"))
        self.assertNotIn("<think>", content)

    def test_salvage_chapter_beats_adds_missing_heading_from_outline(self):
        malformed = (
            "### Beat 1: Arrival\n"
            "Mara steps into the greenhouse before dawn, tracks the draft through broken glass, and realizes someone has already disturbed the room.\n\n"
            "### Beat 2: Search\n"
            "She checks the workbench, studies the disturbed soil, and connects the missing ledger to the unsigned letter from earlier.\n\n"
            "### Beat 3: Choice\n"
            "She decides to remain inside until sunrise so the truth cannot slip away again.\n"
        )

        repaired = story_utils.salvage_beats_document(
            malformed,
            chapter_number=3,
            chapter_title="Glass Hours",
        )

        self.assertTrue(repaired.startswith("# Chapter 3 — Glass Hours"))
        self.assertIn("### Beat 2: Search", repaired)


class TestEndToEndRegressions(TempWorkspaceCase):
    def test_fixture_beats_finalize_without_repair_round_trip(self):
        fixture = REGRESSION_FIXTURES["beats_with_reasoning_leak"]

        llm_calls = []
        repaired_fixture = (
            "# Chapter 2 — The Return\n\n"
            "### Beat 1: Arrival\n"
            "Mara returns home, studies the greenhouse door, and sees that the bolt is set from the inside.\n\n"
            "### Beat 2: Unease\n"
            "She circles the house, hears movement after midnight, and realizes fear is not distorting the sound.\n\n"
            "### Beat 3: Decision\n"
            "She chooses to investigate before dawn because waiting is making the house feel more dangerous.\n\n"
            "### Beat 4: Threshold\n"
            "She takes the key from her pocket and approaches the greenhouse, ending the chapter on the brink of entry.\n"
        )

        def fake_llm_call(user_prompt, system_prompt):
            llm_calls.append((user_prompt, system_prompt))
            return repaired_fixture

        result = story_utils.finalize_beats_document(
            fixture["raw"],
            chapter_number=fixture["chapter_number"],
            chapter_title=fixture["chapter_title"],
            current_chapter_target_prompt="CURRENT CHAPTER TARGET: keep pressure concrete",
            llm_call=fake_llm_call,
        )

        self.assertTrue(result["repaired"])
        self.assertFalse(result["strict_retry"])
        self.assertEqual(len(llm_calls), 1)
        self.assertTrue(result["content"].startswith("# Chapter 2 — The Return"))
        self.assertNotIn("<think>", result["content"])
        self.assertNotIn("Thinking Process", result["content"])
        self.assertIn("### Beat 3: Decision", result["content"])

    def test_fixture_summary_update_round_trip_strips_reasoning_everywhere(self):
        fixture = REGRESSION_FIXTURES["summary_and_cumulative_reasoning_leak"]

        summary_block = story_utils.sanitize_summary_document(
            fixture["summary_raw"],
            chapter_number=2,
            fallback_title="The Return",
        )
        cumulative = story_utils.sanitize_cumulative_summary_document(fixture["cumulative_raw"])
        updated = story_utils.upsert_chapter_summary(cumulative, 2, summary_block)
        updated = story_utils.set_completed_chapters(updated, 2)
        updated = story_utils.sanitize_cumulative_summary_document(updated)

        self.assertIn("### Chapter 1 — The Letter", updated)
        self.assertIn("### Chapter 2 — The Return", updated)
        self.assertIn("- **Completed Chapters:** 2", updated)
        self.assertNotIn("<think>", updated)
        self.assertNotIn("Thinking Process", updated)

    def test_fixture_draft_sanitize_then_compile_round_trip(self):
        fixture = REGRESSION_FIXTURES["chapter_draft_with_reasoning_and_legacy_header"]
        sanitized_draft = story_utils.sanitize_chapter_draft_document(fixture["draft_raw"])
        sanitized_prose = compile_module.extract_draft_prose(sanitized_draft)

        self.assertEqual(
            sanitized_prose,
            "Mara crossed the greenhouse and lifted the ledger from the wet bench.",
        )

        with open(os.path.join(self.chapters_dir, "chapter_001_draft.txt"), "w") as handle:
            handle.write(fixture["draft_raw"])
        with open(os.path.join(self.chapters_dir, "chapter_002_draft.txt"), "w") as handle:
            handle.write("Chapter two prose.")

        compiled_markdown, chapter_count = compile_module.build_compiled_markdown(self.temp_dir)

        self.assertEqual(chapter_count, 2)
        self.assertIn("Mara crossed the greenhouse and lifted the ledger from the wet bench.", compiled_markdown)
        self.assertNotIn("# Chapter 1 Draft", compiled_markdown)
        self.assertNotIn("Generated:", compiled_markdown)
        self.assertNotIn("<think>", compiled_markdown)

    def test_summarize_chapter_regression_pipeline_writes_clean_summary_and_next_brief(self):
        chapter_1_draft_path = os.path.join(self.chapters_dir, "chapter_001_draft.txt")
        with open(chapter_1_draft_path, "w") as handle:
            handle.write(
                "Mara returned home in the rain, found the greenhouse bolted from the inside, "
                "and decided she would not wait until morning to investigate."
            )

        outputs = [
            (
                "<think>\n"
                "Thinking Process:\n"
                "- inspect draft\n\n"
                "### Chapter 1 — The Return\n"
                "- Sequence:\n"
                "  - Mara returns home and finds the greenhouse bolted from the inside.\n"
                "- Plot facts established:\n"
                "  - Someone is already on the property.\n"
                "- Character end states:\n"
                "  - Mara: outside the greenhouse, tense, committed to investigating.\n"
                "- Open threads:\n"
                "  - Who is inside the greenhouse?\n"
            ),
            REGRESSION_FIXTURES["beats_with_reasoning_leak"]["raw"],
            (
                "# Chapter 2 — The Return\n\n"
                "### Beat 1: Arrival\n"
                "Mara returns home, studies the greenhouse door, and sees that the bolt is set from the inside.\n\n"
                "### Beat 2: Unease\n"
                "She circles the house, hears movement after midnight, and realizes fear is not distorting the sound.\n\n"
                "### Beat 3: Decision\n"
                "She chooses to investigate before dawn, pockets the greenhouse key, checks the dark windows one last time, and commits herself because waiting is making the house feel more dangerous.\n\n"
                "### Beat 4: Threshold\n"
                "She takes the key from her pocket, approaches the greenhouse, hears movement behind the glass, and reaches for the lock with the chapter ending on the brink of entry.\n"
            ),
        ]

        with self.patch_summarize_chapter_paths(), patch.object(
            summarize_chapter_module, "stream_llm", side_effect=outputs
        ), patch.object(
            summarize_chapter_module, "get_total_chapters", return_value=3
        ), patch.object(
            summarize_chapter_module, "get_word_count_target", return_value=9000
        ):
            result = summarize_chapter_module.summarize_chapter(1, quiet=True)

        self.assertEqual(result["chapter"], 1)
        self.assertEqual(result["next_chapter"], 2)

        with open(self.summary_path) as handle:
            summary_content = handle.read()
        with open(self.chapter_2_brief_path) as handle:
            next_brief_content = handle.read()

        self.assertIn("### Chapter 1 — The Return", summary_content)
        self.assertNotIn("<think>", summary_content)
        self.assertNotIn("Thinking Process", summary_content)
        self.assertTrue(next_brief_content.startswith("# Chapter 2 — The Return"))
        self.assertNotIn("<think>", next_brief_content)
        self.assertNotIn("Thinking Process", next_brief_content)


class TestCLIWithTempProject(unittest.TestCase):
    def setUp(self):
        self.root = ROOT_DIR
        self.temp_project = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_project, ignore_errors=True)

    def run_cli(self, *args):
        env = os.environ.copy()
        env["BOOK_PROJECT_DIR"] = self.temp_project
        return subprocess.run(
            ["python3", *args],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
        )

    def test_status_runs_against_empty_temp_project(self):
        result = self.run_cli("status.py")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Project dir:", result.stdout)
        self.assertIn(self.temp_project, result.stdout)

    def test_generate_chapter_all_with_no_briefs_exits_cleanly(self):
        result = self.run_cli("generate_chapter.py", "--all")
        self.assertIn("no chapter briefs found", result.stdout.lower() + result.stderr.lower())
        self.assertEqual(result.returncode, 1)

    def test_generate_chapter_all_with_story_bible_and_no_briefs_shows_recovery_options(self):
        with open(os.path.join(self.temp_project, "story_bible.md"), "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)

        result = self.run_cli("generate_chapter.py", "--all")
        output = result.stdout.lower() + result.stderr.lower()
        self.assertIn("an existing story_bible.md was found", output)
        self.assertIn("repair_beats.py --force 1", output)
        self.assertIn("plan_chapters.py --regen-beats", output)
        self.assertEqual(result.returncode, 1)

    def test_help_commands_are_stable(self):
        for script in ["plan_chapters.py", "generate_chapter.py", "project.py"]:
            result = self.run_cli(script, "--help")
            self.assertEqual(result.returncode, 0)
            self.assertIn("usage:", result.stdout.lower())


class TestProjectManagerCLI(unittest.TestCase):
    def setUp(self):
        self.root = ROOT_DIR
        self.temp_home = tempfile.mkdtemp()
        self.temp_projects_dir = os.path.join(self.temp_home, "workspace")

    def tearDown(self):
        shutil.rmtree(self.temp_home, ignore_errors=True)

    def run_project(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = self.root
        command = [
            "python3",
            "-c",
            (
                "import os, runpy, sys; "
                "sys.path.insert(0, os.environ['PYTHONPATH']); "
                "import paths; "
                f"paths.DEFAULT_PROJECTS_DIR = {self.temp_projects_dir!r}; "
                f"paths.CURRENT_PROJECT_FILE = {os.path.join(self.temp_projects_dir, '.current_project')!r}; "
                "sys.argv = ['project.py'] + sys.argv[1:]; "
                f"runpy.run_path({os.path.join(self.root, 'project.py')!r}, run_name='__main__')"
            ),
            *args,
        ]
        return subprocess.run(command, capture_output=True, text=True, cwd=self.root, env=env)

    def test_init_creates_and_switches_project(self):
        result = self.run_project("init", "novel_one")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.temp_projects_dir, "novel_one")))
        with open(os.path.join(self.temp_projects_dir, ".current_project")) as handle:
            self.assertEqual(handle.read().strip(), "novel_one")

    def test_use_switches_existing_project(self):
        os.makedirs(os.path.join(self.temp_projects_dir, "one"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_projects_dir, "two"), exist_ok=True)
        self.run_project("init", "one")
        result = self.run_project("use", "two")
        self.assertEqual(result.returncode, 0)
        with open(os.path.join(self.temp_projects_dir, ".current_project")) as handle:
            self.assertEqual(handle.read().strip(), "two")

    def test_list_marks_current_project(self):
        self.run_project("init", "alpha")
        self.run_project("init", "beta")
        self.run_project("use", "alpha")
        result = self.run_project("list")
        self.assertEqual(result.returncode, 0)
        self.assertIn("* alpha", result.stdout)
        self.assertIn("beta", result.stdout)


class TestErrorPaths(unittest.TestCase):
    def setUp(self):
        self.root = ROOT_DIR
        self.temp_project = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_project, ignore_errors=True)

    def test_generate_chapter_fails_gracefully_on_missing_brief(self):
        env = os.environ.copy()
        env["BOOK_PROJECT_DIR"] = self.temp_project
        result = subprocess.run(
            ["python3", "generate_chapter.py", "99999"],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
