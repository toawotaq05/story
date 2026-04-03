#!/usr/bin/env python3
"""Shared chapter planning helpers and prompt builders."""
import re

from config import get_default_chapters, get_word_count_target, is_pacing_enabled
from story_utils import parse_beats, parse_outline_entries, split_story_bible_and_outline


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


def _load_pacing_weights():
    """Load pacing weights from the project's pacing_weights.json file.
    
    Returns a dict mapping chapter number -> weight factor, or None if not found.
    A weight of 1.0 is flat, 1.4 means 40% more words, 0.7 means 30% fewer.
    """
    import json
    import os
    from paths import PROJECT_DIR
    
    pacing_path = os.path.join(PROJECT_DIR, "pacing_weights.json")
    if not os.path.exists(pacing_path):
        return None
    
    try:
        with open(pacing_path) as f:
            data = json.load(f)
        weights = data.get("chapter_weights", {})
        # Convert string keys to int
        return {int(k): v for k, v in weights.items()}
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def get_target_words_for_chapter(story_bible_text, chapter_number):
    """Get a chapter-specific word target, optionally adjusted by pacing weights.
    
    When dynamic_pacing is enabled in config.json, looks up the chapter's weight
    factor from pacing_weights.json and adjusts the word count accordingly.
    Falls back to the flat division if weights aren't available.
    """
    flat_target = get_target_words_per_chapter(story_bible_text)
    
    if not is_pacing_enabled():
        return flat_target
    
    weights = _load_pacing_weights()
    if weights is None:
        return flat_target
    
    chapter_number = int(chapter_number)
    weight = weights.get(chapter_number, 1.0)
    return max(int(flat_target * weight), 1)


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


def _compress_beat_text(beat_text, word_limit=24):
    lines = [line.strip() for line in beat_text.splitlines() if line.strip()]
    if not lines:
        return ""

    body_lines = lines[1:] if lines[0].startswith("### Beat ") else lines
    body = " ".join(body_lines).strip()
    if not body:
        return lines[0]

    words = body.split()
    if len(words) <= word_limit:
        return body
    return " ".join(words[:word_limit]).strip() + " ..."


def _build_block_beat_context(chapter_beats_text, block):
    all_beats = parse_beats(chapter_beats_text)
    if not all_beats:
        return "(No chapter beats parsed.)", "", "(No later beats.)"

    start_beat = int(block["start_beat"])
    end_beat = int(block["end_beat"])

    completed_lines = []
    current_lines = []
    upcoming_lines = []

    for beat_number, beat_text in all_beats:
        summary = _compress_beat_text(beat_text)
        line = f"- Beat {beat_number}: {summary}"
        if beat_number < start_beat:
            completed_lines.append(line)
        elif beat_number > end_beat:
            upcoming_lines.append(line)
        else:
            current_lines.append(beat_text.strip())

    completed_text = "\n".join(completed_lines) or "(No earlier beats in this chapter.)"
    current_text = "\n\n".join(current_lines).strip()
    upcoming_text = "\n".join(upcoming_lines) or "(No later beats.)"
    return completed_text, current_text, upcoming_text


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
- Include specific settings, sexual acts, reversals, and emotional shifts
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


def build_block_system_prompt(system_prompt, block_target_words):
    prompt = system_prompt
    replacements = [
        (
            "Write the chapter in an immersive, polished voice that matches the tone described in the story bible, embracing raw sensuality and explicit eroticism whenever intimacy or desire appears.",
            "Write only the current scene block of the chapter in an immersive, polished voice that matches the tone described in the story bible, embracing raw sensuality and explicit eroticism whenever intimacy or desire appears.",
        ),
        (
            "- Begin the chapter immediately: no title cards, no \"Chapter X\" headers, no summaries before the prose",
            "- Continue the chapter from the current moment: no restarts, no title cards, no \"Chapter X\" headers, no summaries before the prose",
        ),
        (
            "- End where the brief says the chapter should end; do not add teaser notes or meta commentary",
            "- End this block at a natural continuation point unless the user prompt says this is the final block; do not add teaser notes or meta commentary",
        ),
        (
            "After writing the chapter, output ONLY the chapter text.",
            "After writing this block, output ONLY the block prose.",
        ),
    ]
    for old, new in replacements:
        prompt = prompt.replace(old, new)

    prompt = re.sub(
        r"(?m)^- Target approximately .* words,.*$",
        (
            f"- Target approximately {block_target_words:,} words for this block, "
            "expanding only the scenes that belong in this block."
        ),
        prompt,
    )
    prompt = re.sub(
        r"(?m)^- If you are ending too early,.*$",
        (
            "- If you are ending too early, deepen only the active scene material for this "
            "block with concrete action, dialogue, and interiority rather than restarting "
            "earlier chapter material."
        ),
        prompt,
    )
    return prompt


def build_scene_block_prompt(
    story_bible_text,
    cumulative_summary,
    chapter_beats_text,
    system_prompt,
    chapter_number,
    block,
    block_target_words=None,
    prior_blocks_summary="",
    prior_text_tail="",
    total_blocks=1,
):
    entry = find_chapter_entry(story_bible_text, chapter_number)
    chapter_label = (
        f"Chapter {entry.number} — {entry.title}" if entry else f"Chapter {chapter_number}"
    )

    completed_beats_text, block_beats_text, upcoming_beats_text = _build_block_beat_context(
        chapter_beats_text,
        block,
    )
    continuity_summary = prior_blocks_summary.strip() or "(This is the opening block.)"
    prior_tail = prior_text_tail.strip() or "(No prior prose yet.)"

    return f"""{system_prompt}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT:
{cumulative_summary}

OUTLINE SNAPSHOT:
{build_outline_context(story_bible_text, chapter_number, window=1)}

CHAPTER ROADMAP FOR {chapter_label}:
COMPLETED BEATS (already covered; do not restage):
{completed_beats_text}

CURRENT BLOCK:
- Block {block["index"]} of {total_blocks}
- Covers beats {block["start_beat"]}-{block["end_beat"]}
{"- Target length: about " + format(block_target_words, ",") + " words" if block_target_words else ""}

BLOCK BEATS:
{block_beats_text}

UPCOMING BEATS (aim toward these, but do not fully cover them yet):
{upcoming_beats_text}

ALREADY WRITTEN IN THIS CHAPTER:
{continuity_summary}

TAIL OF PREVIOUS BLOCK PROSE:
{prior_tail}

WRITING INSTRUCTIONS:
- Write only this block's prose
- Start smoothly from the current chapter state; do not restart the chapter
- Assume completed beats have already happened in prior prose; mention them only as aftermath or memory if needed
- Cover the required turns from these beats, but write natural scene flow instead of beat labels
- Do not replay, paraphrase, or re-stage an earlier beat as if it is happening for the first time
- Do not pull a full upcoming beat forward; at most, set it up lightly
- Preserve continuity with the prior prose and aim toward the later beats in the roadmap
- End this block at a strong handoff point for the next block unless this is the final block

Output ONLY the prose for this block.
"""


def build_chapter_revision_prompt(
    story_bible_text,
    cumulative_summary,
    chapter_beats_text,
    system_prompt,
    chapter_number,
    assembled_text,
):
    entry = find_chapter_entry(story_bible_text, chapter_number)
    chapter_label = (
        f"Chapter {entry.number} — {entry.title}" if entry else f"Chapter {chapter_number}"
    )

    return f"""{system_prompt}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT:
{cumulative_summary}

CHAPTER BRIEF FOR {chapter_label}:
{chapter_beats_text}

ASSEMBLED CHAPTER DRAFT:
{assembled_text}

REVISION INSTRUCTIONS:
- Revise this assembled draft into one smooth, coherent chapter
- Preserve the established events, ordering, and ending
- Improve transitions, continuity, repetition, and pacing
- Do not add title cards, notes, or commentary
- Keep the chapter at roughly the same length unless a small adjustment improves flow

Output ONLY the revised chapter text.
"""


def build_chapter_cleanup_prompt(
    story_bible_text,
    cumulative_summary,
    chapter_beats_text,
    system_prompt,
    chapter_number,
    chapter_text,
    target_words,
    min_words,
    max_words,
    issues,
):
    entry = find_chapter_entry(story_bible_text, chapter_number)
    chapter_label = (
        f"Chapter {entry.number} — {entry.title}" if entry else f"Chapter {chapter_number}"
    )
    issues_text = "\n".join(f"- {issue}" for issue in issues) or "- General cleanup"

    return f"""{system_prompt}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT:
{cumulative_summary}

CHAPTER BRIEF FOR {chapter_label}:
{chapter_beats_text}

CURRENT CHAPTER DRAFT:
{chapter_text}

TARGET BAND:
- Ideal target: about {target_words:,} words
- Acceptable range: {min_words:,}-{max_words:,} words

ISSUES TO FIX:
{issues_text}

CLEANUP INSTRUCTIONS:
- Keep the same core events, order, character turns, and ending
- Rewrite into clean final prose, not notes or summary
- Remove repeated beats, repeated paragraphs, and repeated emotional conclusions
- Replace meta narration such as "the chapter ends/concludes" with in-scene storytelling
- If the draft is too long, compress by cutting repetition and summary-like padding first
- If the draft is too short, expand active scenes with concrete action, dialogue, and interiority
- Land inside the acceptable range unless a very small miss is unavoidable

Output ONLY the cleaned chapter text.
"""


def build_pacing_prompt(story_bible_text, outline_section, num_chapters):
    """Build a prompt asking the LLM to assign relative pacing weights to each chapter.

    The LLM receives the full story bible and outline, then assigns a weight factor
    to each chapter based on narrative importance, action density, emotional weight,
    and expected content volume. Weights are normalized so the average remains 1.0,
    meaning the total word budget is preserved.
    """
    return f"""You are a story editor analyzing the narrative pacing of a book project.

Below is the complete story bible and chapter outline for a story.

TASK
Assign a relative pacing weight to each chapter from 1 to {num_chapters}.

A pacing weight determines how many words that chapter should get:
- Weight 1.0 = normal chapter length (baseline)
- Weight 1.3-1.5 = important chapter that deserves more detail (climax, turning point,
  heavy action, or complex emotional development)
- Weight 0.6-0.8 = lighter or transitional chapter (setup, aftermath, quick plot bridge)

GUIDELINES FOR ASSIGNING WEIGHTS
- Climax chapter(s): 1.3-1.5 (the emotional or action peak of the story)
- Resolution chapter: 1.2-1.4 (tying up plot threads, emotional closure)
- Inciting incident / first plot point: 1.1-1.3 (needs room to establish turning point)
- Midpoint chapter: 1.2-1.3 (major story turn, reversal, revelation)
- Transition/bridge chapters: 0.7-0.85 (move characters between major events)
- Setup/aftermath chapters: 0.7-0.9 (lower action density)
- Standard chapters: 0.9-1.1 (normal narrative progression)

IMPORTANT CONSTRAINTS
- Aim for an average weight of about 1.0 across all chapters
- The highest weight and lowest weight should differ by at least 0.5
- At least 2-3 chapters should be noticeably above 1.1
- At least 2-3 chapters should be noticeably below 0.9
- Do NOT give every chapter the same weight
- Weights must be between 0.5 and 1.6

STORY BIBLE:
{story_bible_text}

CHAPTER OUTLINE:
{outline_section}

OUTPUT FORMAT
Output ONLY a valid JSON object with this exact structure. No preamble, no explanation:

{{"chapter_weights": {{"1": 1.1, "2": 0.8, "3": 1.4, "4": 0.9, ...}}}}
"""


