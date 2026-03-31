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
import generate_chapter as generate_chapter_module
import story_utils
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
        expected = os.path.join(DEFAULT_PROJECTS_DIR, DEFAULT_PROJECT_NAME)
        self.assertEqual(PROJECT_DIR, expected)

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
            prior_blocks_summary="Block 0 summary",
            prior_text_tail="Last line of prior prose.",
            total_blocks=2,
        )
        self.assertIn("Block 1 of 2", prompt)
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
            "Block one prose with rain and tension.",
            "Block two prose with departure and dread.",
            "Revised final chapter prose with smoother transitions.",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module, "stream_llm", side_effect=outputs
        ) as mock_stream:
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
            "First block prose.",
            "Second block prose.",
        ]

        with self.patch_generate_chapter_paths(), patch.object(
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
        self.assertIn("First block prose.", draft)
        self.assertIn("Second block prose.", draft)

    def test_generate_next_chapter_beats_writes_next_brief(self):
        with self.patch_generate_chapter_paths(), patch.object(
            generate_chapter_module,
            "stream_llm",
            return_value="# Chapter 2 — The Return\n\n### Beat 1: Arrival\nx\n\n### Beat 2: Unease\ny\n",
        ):
            created = generate_chapter_module.generate_next_chapter_beats(1)

        self.assertEqual(created, self.chapter_2_brief_path)
        with open(self.chapter_2_brief_path) as handle:
            content = handle.read()
        self.assertIn("# Chapter 2 — The Return", content)


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
