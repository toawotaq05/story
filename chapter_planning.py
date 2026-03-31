#!/usr/bin/env python3
"""Shared chapter planning helpers and prompt builders."""
from config import get_default_chapters, get_word_count_target
from story_utils import parse_outline_entries, split_story_bible_and_outline


def get_outline_entries_from_story_bible(story_bible_text):
    _, outline_section = split_story_bible_and_outline(story_bible_text)
    return parse_outline_entries(outline_section)


def find_chapter_entry(story_bible_text, chapter_number):
    chapter_number = int(chapter_number)
    for entry in get_outline_entries_from_story_bible(story_bible_text):
        if entry.number == chapter_number:
            return entry
    return None


def get_total_chapters(story_bible_text):
    entries = get_outline_entries_from_story_bible(story_bible_text)
    return len(entries) if entries else get_default_chapters()


def get_target_words_per_chapter(story_bible_text):
    total_chapters = max(get_total_chapters(story_bible_text), 1)
    return max(get_word_count_target() // total_chapters, 1)


def build_outline_context(story_bible_text, chapter_number, window=2):
    entries = get_outline_entries_from_story_bible(story_bible_text)
    chapter_number = int(chapter_number)
    if not entries:
        return "(No chapter outline found in story_bible.md)"

    lines = []
    for entry in entries:
        if abs(entry.number - chapter_number) > window and entry.number != chapter_number:
            continue
        marker = "CURRENT" if entry.number == chapter_number else "NEARBY"
        ending = f" | ends: {entry.ending}" if entry.ending else ""
        lines.append(
            f"- [{marker}] Chapter {entry.number} — {entry.title}: {entry.summary}{ending}"
        )
    return "\n".join(lines)


def build_previous_outline_context(story_bible_text, chapter_number):
    chapter_number = int(chapter_number)
    entries = get_outline_entries_from_story_bible(story_bible_text)
    previous = [entry for entry in entries if entry.number < chapter_number]
    if not previous:
        return "(No prior chapters in outline)"

    lines = []
    for entry in previous:
        ending = f" | ends: {entry.ending}" if entry.ending else ""
        lines.append(f"- Chapter {entry.number} — {entry.title}: {entry.summary}{ending}")
    return "\n".join(lines)


def build_chapter_beats_prompt(
    story_bible_text,
    chapter_number,
    cumulative_summary="",
    beats_template="",
):
    entry = find_chapter_entry(story_bible_text, chapter_number)
    if not entry:
        raise ValueError(f"Chapter {chapter_number} not found in story outline")

    chapter_number = int(chapter_number)
    next_entry = find_chapter_entry(story_bible_text, chapter_number + 1)
    next_hint = (
        f"Chapter {next_entry.number} should open from: {next_entry.summary}"
        if next_entry
        else "This is the final planned chapter, so close the main arc cleanly."
    )

    summary_context = cumulative_summary.strip() or "(No completed chapters yet)"
    template_section = ""
    if beats_template.strip():
        template_section = f"\nCHAPTER BEATS TEMPLATE:\n{beats_template.strip()}\n"

    return f"""Write a concise but concrete chapter brief for Chapter {chapter_number}.

CURRENT CHAPTER TARGET:
- Chapter {entry.number} — {entry.title}
- Core action: {entry.summary}
- Ending/setup: {entry.ending or "Resolve the chapter cleanly with a natural handoff"}

STORY BIBLE (authoritative canon):
{story_bible_text}

OUTLINE CONTEXT:
{build_outline_context(story_bible_text, chapter_number, window=2)}

PREVIOUS OUTLINE CONTEXT:
{build_previous_outline_context(story_bible_text, chapter_number)}

STORY SO FAR:
{summary_context}
{template_section}
INSTRUCTIONS:
- Output only the chapter brief document
- Keep it concrete enough to draft prose from directly
- Use 4-6 beats if needed, but combine or compress where pacing wants it
- Each beat should describe intent, escalation, and important character turns
- Include specific settings, reversals, and emotional shifts
- Do not reuse the previous chapter's formatting quirks verbatim
- Align the final beat with this handoff: {next_hint}
"""


def build_chapter_draft_prompt(
    story_bible_text,
    cumulative_summary,
    chapter_beats_text,
    system_prompt,
    chapter_number,
):
    entry = find_chapter_entry(story_bible_text, chapter_number)
    chapter_label = (
        f"Chapter {entry.number} — {entry.title}" if entry else f"Chapter {chapter_number}"
    )
    target_words = get_target_words_per_chapter(story_bible_text)
    prompt_template = system_prompt.replace("[WORD_COUNT_TARGET]", f"{target_words:,}")

    return f"""{prompt_template}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT:
{cumulative_summary}

CHAPTER BRIEF FOR {chapter_label}:
{chapter_beats_text}

OUTLINE SNAPSHOT:
{build_outline_context(story_bible_text, chapter_number, window=1)}

WRITING INSTRUCTIONS:
- Write one coherent chapter, not separate beat snippets
- Treat the chapter brief as planning guidance, not as mandatory scene boundaries
- Preserve pacing and transitions between moments naturally
- Hit the important turns from the chapter brief, but merge or expand scenes where it improves flow
- End where the chapter brief and outline say this chapter should end

Output ONLY the chapter text.
"""
