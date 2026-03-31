#!/usr/bin/env python3
"""Shared parsing and state helpers for story pipeline files."""
from dataclasses import dataclass
import re


OUTLINE_HEADING_RE = re.compile(r"(?mi)^#\s+Chapter Outline\b")
OUTLINE_START_RE = re.compile(r"(?m)^\s*1\.\s+\*\*.+?\*\*")
COMPLETED_CHAPTERS_RE = re.compile(r"(?mi)(-?\s*\*?\*?Completed Chapters:?\*?\*?\s*)(\d+)")
SUMMARY_HEADER_RE = re.compile(r"(?mi)^###\s+Chapter\s+(\d+)\s*[—-]\s*(.+?)\s*$")
OUTLINE_LINE_RE = re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$")
CHAPTER_LABEL_RE = re.compile(r"(?i)^chapter\s+(\d+)\s*[-—–:]\s*(.+)$")
ENDS_SPLIT_RE = re.compile(r"\s*(?:→|->|>)\s*ends?:\s*", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"(?m)^#\s+Chapter\s+\d+\s*[:—\-]")
BEAT_HEADING_RE = re.compile(r"^###\s+Beat\s+(\d+):", re.MULTILINE)


@dataclass(frozen=True)
class OutlineEntry:
    number: int
    title: str
    summary: str
    ending: str = ""
    raw_line: str = ""


def count_words(text):
    return len(text.split())


def extract_story_title(text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            title = stripped[2:].strip()
            title = re.sub(r"^\*\*(.+)\*\*$", r"\1", title)
            return title
    return "Untitled Story"


def split_output_story_bible_and_beats(output):
    marker = "@@@STORY_BIBLE_END_MARKER@@@"
    if marker in output:
        story_bible, chapter_beats = output.split(marker, 1)
        return story_bible.strip(), chapter_beats.strip()

    match = CHAPTER_HEADING_RE.search(output)
    if match:
        return output[:match.start()].strip(), output[match.start():].strip()

    raise ValueError(
        "Could not parse LLM output into story bible and chapter beats."
    )


def split_story_bible_and_outline(document):
    match = OUTLINE_HEADING_RE.search(document)
    if match:
        story_bible = document[:match.start()].rstrip()
        story_bible = re.sub(r"(?:\n\s*---\s*)+$", "", story_bible).rstrip()
        outline = document[match.start():].strip()
        return story_bible, outline

    legacy_match = OUTLINE_START_RE.search(document)
    if not legacy_match:
        return document.strip(), ""

    story_bible = document[:legacy_match.start()].rstrip()
    story_bible = re.sub(r"(?:\n\s*---\s*)+$", "", story_bible).rstrip()
    outline_lines = []
    for line in document[legacy_match.start():].splitlines():
        stripped = line.strip()
        if not stripped and outline_lines:
            break
        if OUTLINE_LINE_RE.match(stripped):
            outline_lines.append(stripped)
        elif outline_lines:
            break

    if not outline_lines:
        return document.strip(), ""
    outline = "# Chapter Outline\n\n" + "\n".join(outline_lines)
    return story_bible, outline


def merge_story_bible_and_outline(story_bible, outline):
    story_bible = story_bible.strip()
    outline = outline.strip()
    if not outline:
        return story_bible + "\n"
    return f"{story_bible}\n\n---\n\n{outline}\n"


def parse_outline_entries(text):
    entries = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        match = OUTLINE_LINE_RE.match(line)
        if not match:
            continue

        ordinal = int(match.group(1))
        chapter_label = match.group(2).strip()
        remainder = match.group(3).strip()

        chapter_match = CHAPTER_LABEL_RE.match(chapter_label)
        if chapter_match:
            chapter_num = int(chapter_match.group(1))
            title = chapter_match.group(2).strip()
        else:
            chapter_num = ordinal
            title = chapter_label.strip()

        remainder = re.sub(r"^\s*[-—–:]\s*", "", remainder)
        ending = ""
        summary = remainder
        parts = ENDS_SPLIT_RE.split(remainder, maxsplit=1)
        if len(parts) == 2:
            summary, ending = parts[0].strip(), parts[1].strip()

        entries.append(
            OutlineEntry(
                number=chapter_num,
                title=title,
                summary=summary.strip(),
                ending=ending,
                raw_line=raw_line,
            )
        )

    return entries


def format_outline_entry(entry):
    line = f"{entry.number}. **Chapter {entry.number} — {entry.title}** — {entry.summary}"
    if entry.ending:
        line += f" → ends: {entry.ending}"
    return line


def build_outline_section(entries):
    lines = ["# Chapter Outline", ""]
    lines.extend(format_outline_entry(entry) for entry in entries)
    return "\n".join(lines).strip()


def parse_beats(beats_content):
    beats = []
    lines = beats_content.splitlines()
    current_beat = None
    current_text = []
    for line in lines:
        match = re.match(r"^### Beat (\d+):", line.strip())
        if match:
            if current_beat is not None:
                beats.append((current_beat, "\n".join(current_text).strip()))
            current_beat = int(match.group(1))
            current_text = [line]
        elif current_beat is not None:
            current_text.append(line)
    if current_beat is not None:
        beats.append((current_beat, "\n".join(current_text).strip()))
    return beats


def is_valid_beats_document(content, min_beats=2):
    if not content or not content.strip().startswith("# Chapter"):
        return False
    return len(parse_beats(content)) >= min_beats


def parse_completed_chapters(summary_content):
    match = COMPLETED_CHAPTERS_RE.search(summary_content or "")
    return int(match.group(2)) if match else 0


def set_completed_chapters(summary_content, chapter_number):
    if COMPLETED_CHAPTERS_RE.search(summary_content):
        return COMPLETED_CHAPTERS_RE.sub(rf"\g<1>{chapter_number}", summary_content, count=1)
    return summary_content.rstrip() + f"\n\n- **Completed Chapters:** {chapter_number}\n"


def extract_summary_headers(summary_content):
    return [
        (int(match.group(1)), match.group(2).strip())
        for match in SUMMARY_HEADER_RE.finditer(summary_content or "")
    ]


def has_summary_for_chapter(summary_content, chapter_number):
    target = int(chapter_number)
    return any(number == target for number, _ in extract_summary_headers(summary_content))


def upsert_chapter_summary(summary_content, chapter_number, summary_block):
    pattern = re.compile(
        rf"(?ms)^###\s+Chapter\s+{int(chapter_number)}\b.*?(?=^###\s+Chapter\s+\d+\b|\Z)"
    )
    replacement = summary_block.strip() + "\n"
    if pattern.search(summary_content):
        updated = pattern.sub(replacement, summary_content, count=1)
    else:
        updated = summary_content.rstrip() + "\n\n" + replacement
    return updated.rstrip() + "\n"


def build_initial_cumulative_summary(total_chapters, target_word_count):
    return (
        "# Cumulative Story Summary\n\n"
        "## Overview\n\n"
        f"- Total chapters: {int(total_chapters)}\n"
        f"- Target word count: {int(target_word_count):,}\n"
        "- **Completed Chapters:** 0\n"
    )
