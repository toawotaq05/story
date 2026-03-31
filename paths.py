#!/usr/bin/env python3
"""Shared project paths for the story pipeline."""
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CHAPTERS_DIR = os.path.join(ROOT_DIR, "chapters")
ARTIFACTS_DIR = os.path.join(ROOT_DIR, "artifacts")
RAW_OUTPUTS_DIR = os.path.join(ARTIFACTS_DIR, "raw")
PROMPTS_DIR = os.path.join(ROOT_DIR, "prompts")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")

CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
STORY_BIBLE_PATH = os.path.join(ROOT_DIR, "story_bible.md")
CUMULATIVE_SUMMARY_PATH = os.path.join(ROOT_DIR, "cumulative_summary.md")
BOOK_OUTPUT_PATH = os.path.join(ROOT_DIR, "book.md")
STORY_BIBLE_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "story_bible_TEMPLATE.md")
CHAPTER_BEATS_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "chapter_beats_TEMPLATE.md")
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, "system_prompt.txt")


def ensure_runtime_dirs():
    os.makedirs(CHAPTERS_DIR, exist_ok=True)
    os.makedirs(RAW_OUTPUTS_DIR, exist_ok=True)


def raw_output_path(filename):
    ensure_runtime_dirs()
    return os.path.join(RAW_OUTPUTS_DIR, filename)


def chapter_beats_path(chapter):
    return os.path.join(CHAPTERS_DIR, f"chapter_{chapter}_beats.md")


def chapter_draft_path(chapter):
    return os.path.join(CHAPTERS_DIR, f"chapter_{chapter}_draft.txt")


def chapter_polished_path(chapter, beat_num):
    return os.path.join(CHAPTERS_DIR, f"chapter_{chapter}_beat{beat_num}_polished.txt")


def chapter_generation_log_path(chapter):
    return os.path.join(CHAPTERS_DIR, f"chapter_{chapter}_generation_log.md")
