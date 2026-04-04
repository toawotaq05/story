#!/usr/bin/env python3
"""Shared parsing and state helpers for story pipeline files."""
from dataclasses import dataclass
import re


OUTLINE_HEADING_RE = re.compile(r"(?mi)^#\s+Chapter Outline\b")
OUTLINE_START_RE = re.compile(r"(?m)^\s*1\.\s+\*\*.+?\*\*")
COMPLETED_CHAPTERS_RE = re.compile(r"(?mi)(-?\s*\*?\*?Completed Chapters:?\*?\*?\s*)(\d+)")
SUMMARY_HEADER_RE = re.compile(r"(?mi)^###\s+Chapter\s+(\d+)\s*[—-]\s*(.+?)\s*$")
SUMMARY_BLOCK_RE = re.compile(r"(?ms)^###\s+Chapter\s+(\d+)\s*[—-]\s*(.+?)\s*$.*?(?=^###\s+Chapter\s+\d+\b|\Z)")
TOTAL_CHAPTERS_RE = re.compile(r"(?mi)^-\s+Total chapters:\s*(\d+)\s*$")
TARGET_WORD_COUNT_RE = re.compile(r"(?mi)^-\s+Target word count:\s*([\d,]+)\s*$")
OUTLINE_LINE_RE = re.compile(r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*(.*)$")
CHAPTER_LABEL_RE = re.compile(r"(?i)^chapter\s+(\d+)\s*[-—–:]\s*(.+)$")
ENDS_SPLIT_RE = re.compile(r"\s*(?:→|->|>)\s*ends?:\s*", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"(?m)^#\s+Chapter(?:\s+Brief)?(?:\s+for)?\s+\d+\s*[:—\-]")
BEAT_HEADING_RE = re.compile(
    r"(?im)^#{2,6}\s+\*{0,2}Beat\s+(\d+)\*{0,2}\s*(?:[:\-—]|$)"
)


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
        match = re.match(
            r"^#{2,6}\s+\*{0,2}Beat\s+(\d+)\*{0,2}\s*(?:[:\-—]|$)",
            line.strip(),
            re.IGNORECASE,
        )
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


def group_beats_into_blocks(beats, beats_per_block=2):
    if beats_per_block < 1:
        raise ValueError("beats_per_block must be at least 1")

    blocks = []
    for index in range(0, len(beats), beats_per_block):
        chunk = beats[index:index + beats_per_block]
        start = chunk[0][0]
        end = chunk[-1][0]
        blocks.append(
            {
                "index": len(blocks) + 1,
                "start_beat": start,
                "end_beat": end,
                "beats": chunk,
            }
        )
    return blocks


def is_valid_beats_document(content, min_beats=2):
    if not content or not content.strip().startswith("# Chapter"):
        return False
    return len(parse_beats(content)) >= min_beats


def analyze_beats_document(content, min_beats=3):
    issues = []
    if not content or not content.strip().startswith("# Chapter"):
        issues.append("Document must start with a chapter heading.")
        return issues

    beats = parse_beats(content)
    if len(beats) < min_beats:
        issues.append(f"Expected at least {min_beats} beats, found {len(beats)}.")
        return issues

    numbers = [number for number, _ in beats]
    expected = list(range(1, len(beats) + 1))
    if numbers != expected:
        issues.append(f"Beat numbers must be sequential starting at 1, found {numbers}.")

    seen = set()
    for number, beat_text in beats:
        normalized = " ".join(beat_text.lower().split())
        if "[" in beat_text or "]" in beat_text:
            issues.append(f"Beat {number} still contains placeholder-style brackets.")
        if len(beat_text.split()) < 20:
            issues.append(f"Beat {number} is too thin to draft from directly.")
        if normalized in seen:
            issues.append(f"Beat {number} repeats an earlier beat too closely.")
        seen.add(normalized)

    return issues


def parse_completed_chapters(summary_content):
    match = COMPLETED_CHAPTERS_RE.search(summary_content or "")
    return int(match.group(2)) if match else 0


def _strip_reasoning_artifacts(text):
    if not text:
        return text

    patterns = [
        r"<think>.*?</think>",
        r"<thought>.*?</thought>",
        r"\[thinking\].*?\[/thinking\]",
        r"\[thinking\].*?\[end thinking\]",
        r"(?ms)^\s*Thinking Process:\s*.*?(?=^#\s+Chapter\b|^###\s+(?:Chapter|Beat)\s+\d+\b|\Z)",
    ]

    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.DOTALL | re.IGNORECASE)

    return text


def sanitize_story_bible_document(text):
    return _strip_reasoning_artifacts(text or "").strip()


def sanitize_outline_document(text):
    return _strip_reasoning_artifacts(text or "").strip()


def sanitize_beats_document(text, chapter_number=None, chapter_title=None):
    return salvage_beats_document(
        text,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
    )


def sanitize_summary_document(text, chapter_number=None, fallback_title=None):
    return normalize_summary_block(
        text,
        chapter_number=chapter_number,
        fallback_title=fallback_title,
    )


def sanitize_cumulative_summary_document(text):
    return normalize_cumulative_summary(text)


def sanitize_chapter_draft_document(text):
    return _strip_reasoning_artifacts(text or "").strip()


def finalize_beats_document(
    content,
    chapter_number,
    chapter_title,
    current_chapter_target_prompt,
    llm_call=None,
    repair_requirements=None,
):
    """Sanitize, validate, and optionally repair a chapter brief."""
    chapter_number = int(chapter_number)
    repair_requirements = repair_requirements or [
        "Keep the same planned chapter events and ending direction",
        "Output only the chapter brief document",
        "Start with a '# Chapter N — Title' heading",
        "Use 4-6 concrete '### Beat N: Label' sections",
        "Remove placeholders, duplicated beats, vague filler, and leaked thinking/reasoning text",
    ]

    content = sanitize_beats_document(
        content,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
    )
    issues = analyze_beats_document(content)
    initial_issues = list(issues)
    repaired = False
    strict_retry = False

    if issues and llm_call is not None:
        repair_prompt = (
            f"Rewrite this chapter brief so it is clean and draftable for Chapter {chapter_number}.\n\n"
            f"ISSUES TO FIX:\n" + "\n".join(f"- {issue}" for issue in issues) + "\n\n"
            "REQUIREMENTS:\n" + "\n".join(f"- {item}" for item in repair_requirements) + "\n\n"
            f"CURRENT BRIEF:\n{content}"
        )
        content = sanitize_beats_document(
            llm_call(
                repair_prompt,
                "You repair malformed chapter briefs into clean drafting plans.",
            ),
            chapter_number=chapter_number,
            chapter_title=chapter_title,
        )
        issues = analyze_beats_document(content)
        repaired = True

    if issues and len(parse_beats(content)) == 0 and llm_call is not None:
        strict_prompt = (
            f"Write ONLY a valid chapter brief for Chapter {chapter_number}.\n\n"
            f"CURRENT CHAPTER TARGET:\n{current_chapter_target_prompt}\n\n"
            "OUTPUT CONTRACT:\n"
            f"- First line must be: # Chapter {chapter_number} — {chapter_title}\n"
            "- Include at least 4 sections exactly like: ### Beat N: [Label]\n"
            "- Each beat must contain concrete, draftable scene detail\n"
            "- No commentary, analysis, or reasoning text\n"
        )
        content = sanitize_beats_document(
            llm_call(
                strict_prompt,
                "You output only clean chapter brief markdown.",
            ),
            chapter_number=chapter_number,
            chapter_title=chapter_title,
        )
        issues = analyze_beats_document(content)
        strict_retry = True

    return {
        "content": content,
        "issues": issues,
        "initial_issues": initial_issues,
        "repaired": repaired,
        "strict_retry": strict_retry,
    }


def normalize_summary_block(summary_block, chapter_number=None, fallback_title=None):
    text = _strip_reasoning_artifacts(summary_block or "").strip()
    if not text:
        return ""

    header_match = SUMMARY_HEADER_RE.search(text)
    if header_match:
        return text[header_match.start():].strip()

    if chapter_number is None:
        return text

    title = (fallback_title or f"Chapter {int(chapter_number)}").strip()
    if re.search(r"(?mi)^-\s+Sequence:\s*$", text):
        return f"### Chapter {int(chapter_number)} — {title}\n{text}".strip()
    return text


def normalize_cumulative_summary(summary_content):
    original = summary_content or ""
    cleaned = _strip_reasoning_artifacts(original)

    total_match = TOTAL_CHAPTERS_RE.search(cleaned) or TOTAL_CHAPTERS_RE.search(original)
    target_match = TARGET_WORD_COUNT_RE.search(cleaned) or TARGET_WORD_COUNT_RE.search(original)
    total_chapters = int(total_match.group(1)) if total_match else 0
    target_word_count = int(target_match.group(1).replace(",", "")) if target_match else 0
    completed = parse_completed_chapters(cleaned or original)

    if total_chapters and target_word_count:
        normalized = build_initial_cumulative_summary(total_chapters, target_word_count)
    else:
        normalized = cleaned.strip() + ("\n" if cleaned.strip() else "")

    if completed:
        normalized = set_completed_chapters(normalized, completed)

    blocks_by_number = {}
    order = []
    for match in SUMMARY_BLOCK_RE.finditer(cleaned):
        number = int(match.group(1))
        block = normalize_summary_block(match.group(0), chapter_number=number, fallback_title=match.group(2))
        if not block:
            continue
        if number not in blocks_by_number:
            order.append(number)
        blocks_by_number[number] = block

    if blocks_by_number:
        normalized = normalized.rstrip() + "\n\n" + "\n\n".join(
            blocks_by_number[number].strip() for number in order
        )

    return normalized.rstrip() + "\n"


def salvage_beats_document(beats_content, chapter_number=None, chapter_title=None):
    text = _strip_reasoning_artifacts(beats_content or "").strip()
    if not text:
        return ""

    chapter_heading_match = re.search(r"(?m)^#\s*Chapter\b", text)
    if chapter_heading_match:
        return text[chapter_heading_match.start():].strip()

    beats = parse_beats(text)
    if len(beats) < 2 or chapter_number is None:
        return text

    title = (chapter_title or f"Chapter {int(chapter_number)}").strip()
    sections = "\n\n".join(beat_text.strip() for _, beat_text in beats if beat_text.strip())
    if not sections:
        return text
    return f"# Chapter {int(chapter_number)} — {title}\n\n{sections}".strip()


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
    summary_content = normalize_cumulative_summary(summary_content)
    summary_block = normalize_summary_block(summary_block, chapter_number=chapter_number)
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
