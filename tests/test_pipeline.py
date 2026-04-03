#!/usr/bin/env python3
"""
tests/test_pipeline.py — Deterministic tests for the story pipeline.
Run: python3 tests/test_pipeline.py
"""
import json
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
        self.draft_path = os.path.join(self.chapters_dir, "chapter_1_draft.txt")
        self.log_path = os.path.join(self.chapters_dir, "chapter_1_generation_log.md")
        self.chapter_1_brief_path = os.path.join(self.chapters_dir, "chapter_1_beats.md")
        self.chapter_2_brief_path = os.path.join(self.chapters_dir, "chapter_2_beats.md")

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
            chapter_beats_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter}_beats.md"),
            chapter_draft_path=lambda chapter: os.path.join(self.chapters_dir, f"chapter_{chapter}_draft.txt"),
            chapter_generation_log_path=lambda chapter: os.path.join(
                self.chapters_dir, f"chapter_{chapter}_generation_log.md"
            ),
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
        self.assertIn("Method: staged scene-block drafting", draft)
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


class TestCompile(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp()
        self.chapters_dir = os.path.join(self.project_dir, "chapters")
        os.makedirs(self.chapters_dir, exist_ok=True)
        with open(os.path.join(self.project_dir, "story_bible.md"), "w") as handle:
            handle.write(SAMPLE_STORY_BIBLE)
        with open(os.path.join(self.chapters_dir, "chapter_1_draft.txt"), "w") as handle:
            handle.write("Chapter one prose.")
        with open(os.path.join(self.chapters_dir, "chapter_2_draft.txt"), "w") as handle:
            handle.write("Chapter two prose.")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_compile_book_writes_markdown_for_explicit_project(self):
        output_dir = tempfile.mkdtemp()
        try:
            with patch.object(compile_module, "write_epub", return_value=(False, "pandoc not found")):
                compile_module.compile_book(project_dir=self.project_dir, output_path=output_dir, dry_run=False)
            md_path = os.path.join(output_dir, "book.md")
            self.assertTrue(os.path.exists(md_path))
            with open(md_path) as handle:
                content = handle.read()
            self.assertIn("# The Silent Garden", content)
            self.assertIn("## Chapter 1: The Letter", content)
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


class TestSummarizeChapter(unittest.TestCase):
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
        self.assertIn("no chapter beats found", result.stdout.lower() + result.stderr.lower())

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
