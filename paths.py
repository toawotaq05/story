#!/usr/bin/env python3
"""Shared project paths for the story pipeline."""
from dataclasses import dataclass
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(ROOT_DIR, "prompts")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
DEFAULT_PROJECTS_DIR = os.path.join(ROOT_DIR, "workspace")
DEFAULT_PROJECT_NAME = "default"
CURRENT_PROJECT_FILE = os.path.join(DEFAULT_PROJECTS_DIR, ".current_project")


def _valid_project_name(name):
    if not name:
        return False
    if name in {".", ".."}:
        return False
    return all(char.isalnum() or char in {"-", "_"} for char in name)


def _load_current_project_name():
    env_name = os.environ.get("BOOK_PROJECT_NAME")
    if env_name:
        return env_name

    if os.path.exists(CURRENT_PROJECT_FILE):
        with open(CURRENT_PROJECT_FILE) as handle:
            name = handle.read().strip()
        if name:
            return name
    return DEFAULT_PROJECT_NAME


def _resolve_project_name():
    override = os.environ.get("BOOK_PROJECT_DIR")
    if override:
        return os.path.abspath(override)
    project_name = _load_current_project_name()
    if not _valid_project_name(project_name):
        project_name = DEFAULT_PROJECT_NAME
    return os.path.join(DEFAULT_PROJECTS_DIR, project_name)


def set_current_project_name(name):
    if not _valid_project_name(name):
        raise ValueError(
            "Project name must contain only letters, numbers, hyphens, and underscores."
        )
    os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
    with open(CURRENT_PROJECT_FILE, "w") as handle:
        handle.write(name + "\n")


def get_current_project_name():
    if os.environ.get("BOOK_PROJECT_DIR"):
        return os.path.basename(PROJECT_DIR.rstrip(os.sep))
    name = _load_current_project_name()
    if _valid_project_name(name):
        return name
    return DEFAULT_PROJECT_NAME


@dataclass(frozen=True)
class ProjectPaths:
    project_dir: str

    @property
    def chapters_dir(self):
        return os.path.join(self.project_dir, "chapters")

    @property
    def artifacts_dir(self):
        return os.path.join(self.project_dir, "artifacts")

    @property
    def raw_outputs_dir(self):
        return os.path.join(self.artifacts_dir, "raw")

    @property
    def story_bible_path(self):
        return os.path.join(self.project_dir, "story_bible.md")

    @property
    def cumulative_summary_path(self):
        return os.path.join(self.project_dir, "cumulative_summary.md")

    @property
    def book_output_path(self):
        return os.path.join(self.project_dir, "book.md")

    def chapter_beats_path(self, chapter):
        return os.path.join(self.chapters_dir, f"chapter_{int(chapter):03d}_beats.md")

    def chapter_draft_path(self, chapter):
        return os.path.join(self.chapters_dir, f"chapter_{int(chapter):03d}_draft.txt")

    def chapter_polished_path(self, chapter, beat_num):
        return os.path.join(self.chapters_dir, f"chapter_{int(chapter):03d}_beat{beat_num}_polished.txt")

    def chapter_generation_log_path(self, chapter):
        return os.path.join(self.chapters_dir, f"chapter_{int(chapter):03d}_generation_log.md")

    def raw_output_path(self, filename):
        return os.path.join(self.raw_outputs_dir, filename)


def get_project_dir():
    return _resolve_project_name()


def get_project_paths():
    return ProjectPaths(get_project_dir())


PROJECT_DIR = get_project_dir()
CHAPTERS_DIR = os.path.join(PROJECT_DIR, "chapters")
ARTIFACTS_DIR = os.path.join(PROJECT_DIR, "artifacts")
RAW_OUTPUTS_DIR = os.path.join(ARTIFACTS_DIR, "raw")

CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
STORY_BIBLE_PATH = os.path.join(PROJECT_DIR, "story_bible.md")
CUMULATIVE_SUMMARY_PATH = os.path.join(PROJECT_DIR, "cumulative_summary.md")
BOOK_OUTPUT_PATH = os.path.join(PROJECT_DIR, "book.md")
STORY_BIBLE_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "story_bible_TEMPLATE.md")
CHAPTER_BEATS_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "chapter_beats_TEMPLATE.md")
SYSTEM_PROMPT_PATH = os.path.join(PROMPTS_DIR, "system_prompt.txt")


def ensure_runtime_dirs():
    runtime_paths = get_project_paths()
    os.makedirs(runtime_paths.project_dir, exist_ok=True)
    os.makedirs(runtime_paths.chapters_dir, exist_ok=True)
    os.makedirs(runtime_paths.raw_outputs_dir, exist_ok=True)


def raw_output_path(filename):
    ensure_runtime_dirs()
    return get_project_paths().raw_output_path(filename)


def chapter_beats_path(chapter):
    ensure_runtime_dirs()
    return get_project_paths().chapter_beats_path(chapter)


def chapter_draft_path(chapter):
    ensure_runtime_dirs()
    return get_project_paths().chapter_draft_path(chapter)


def chapter_polished_path(chapter, beat_num):
    ensure_runtime_dirs()
    return get_project_paths().chapter_polished_path(chapter, beat_num)


def chapter_generation_log_path(chapter):
    ensure_runtime_dirs()
    return get_project_paths().chapter_generation_log_path(chapter)


ensure_runtime_dirs()
