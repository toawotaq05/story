#!/usr/bin/env python3
"""
generate_chapter.py — Generate a chapter (or all chapters) using per-beat expansion for maximum word count.

Usage:
    python3 generate_chapter.py 1              # generate chapter 1 using per-beat expansion
    python3 generate_chapter.py --all         # generate all chapters sequentially
    python3 generate_chapter.py --all --no-skip # overwrite existing drafts
    
Additional options:
    --separator SEPARATOR    Scene separator between beats (default: "***")
    --no-separator           Disable scene separators
    --raw-targets            Use raw word targets without overshoot adjustment
    --overshoot-factor FLOAT Overshoot factor adjustment (default: 1.5)
    --silent                 Suppress streaming output
    --no-previous-context    Disable including previous beat in context (for testing transitions)
"""
import os
import sys
import re
import argparse
import glob
import subprocess
from datetime import datetime

from dual_llm import stream_llm
from config import get_word_count_target, get_default_chapters
from paths import (
    CHAPTERS_DIR,
    CUMULATIVE_SUMMARY_PATH,
    STORY_BIBLE_PATH,
    SYSTEM_PROMPT_PATH,
    chapter_beats_path,
    chapter_draft_path,
    chapter_generation_log_path,
    chapter_polished_path,
    ensure_runtime_dirs,
)
from story_utils import has_summary_for_chapter, parse_beats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_story_bible(content):
    """Extract POV and Tense from story bible metadata."""
    pov_match = re.search(r'- \*\*POV:\*\* (.+)', content)
    tense_match = re.search(r'- \*\*Tense:\*\* (.+)', content)
    pov = pov_match.group(1).strip() if pov_match else None
    tense = tense_match.group(1).strip() if tense_match else None
    return pov, tense


def generate_beat_scene(chapter, beat_num, beat_text, story_bible_text,
                        cumulative_content, target_words_per_beat, sys_prompt,
                        is_first=False, is_last=False, previous_scene=None):
    """Generate a single beat scene with improved prompting.

    Args:
        previous_scene: The generated text from the previous beat (for continuity)
    """
    
    beat_position = ""
    if is_first:
        beat_position = " (CHAPTER OPENING)"
    elif is_last:
        beat_position = " (CHAPTER CONCLUSION)"
    
    expansion_emphasis = "VERY IMPORTANT: You MUST expand this beat to approximately " + \
                        f"{target_words_per_beat:,} words. Do NOT summarize."
    
    # Vary expansion techniques based on beat position
    if is_first:
        expansion_techniques = """
- Start with strong sensory details (sight, sound, smell, texture)
- Establish mood and atmosphere immediately
- Introduce character through action and internal thoughts
- Use vivid metaphors and descriptive language
- Show, don't tell - demonstrate character traits through behavior
"""
    elif is_last:
        expansion_techniques = """
- Build toward a satisfying conclusion or cliffhanger
- Resolve or heighten tension from previous beats
- Include character reflection and emotional payoff
- Use impactful final sentences that linger
- Leave reader eager for next chapter
"""
    else:
        expansion_techniques = """
- Develop character relationships and interactions
- Advance plot with meaningful actions
- Include dialogue that reveals subtext
- Show character growth or change
- Use sensory details to immerse reader
"""
    
    prompt = f"""{sys_prompt}

STORY BIBLE:
{story_bible_text}

CURRENT STORY CONTEXT (from cumulative_summary.md):
{cumulative_content}

{("PREVIOUS SCENE (for continuity - ensure seamless transition):\n" + previous_scene + "\n") if previous_scene else ""}
BEAT {beat_num}{beat_position} FOR CHAPTER {chapter}:
{beat_text}

{expansion_emphasis}

EXPANSION TECHNIQUES FOR THIS BEAT:
{expansion_techniques}

SPECIFIC EXPANSION REQUIREMENTS (NSFW FOCUS):
1. Sensory Details: Describe at least 5 different sensory elements with extreme erotic focus (visual: glistening skin, swollen cock, dripping pussy; auditory: wet slapping, moans, gasps; olfactory: musk, sweat, cum; tactile: heat, slickness, throbbing, stretching; taste: salty pre-cum, sweet arousal).
2. Internal Monologue: Dive deep into raw, filthy thoughts — lust, desperation, shame, dominance, submission, dirty fantasies.
3. Dialogue & Subtext: Write dirty, explicit dialogue full of filthy talk, begging, degrading praise, commands. Layer heavy subtext of desire and power.
4. Character Actions: Show explicit physical movements — spreading legs, stroking cock, fingering, thrusting, gripping, licking, sucking, grinding, climaxing with visible spasms and fluids.
5. Setting Enrichment: Make the environment heighten the filth (sheets soaked with sweat and cum, mirrors reflecting the act, risk of being caught, etc.).
6. Pacing Control: Mix short, punchy, vulgar sentences ("His cock slammed into her. She screamed.") with long, flowing, overwhelming descriptions of sensation.
7. Explicitness Mandate: Be maximally graphic. Never summarize sex. Never say “they made love.” Show every thrust, every wet sound, every spurt of cum, every clench and quiver in pornographic detail.

WORD COUNT TARGET: Approximately {target_words_per_beat:,} words.

{"CHAPTER OPENING NOTE: Start strong and hook the reader immediately." if is_first else ""}
{"CHAPTER CONCLUSION NOTE: Provide a satisfying ending that completes this chapter's arc." if is_last else ""}

Output ONLY the scene text for this beat (no preamble, no commentary, no beat markers, no disclaimers). Write in a continuous, extremely explicit narrative style dripping with raw sexuality and filth.
Write in a continuous narrative style appropriate for this beat.

---

BEAT {beat_num} SCENE:
"""
    return prompt


def generate_chapter(chapter, script_dir, silent=False, output_file=None,
                              scene_separator="***", adjust_overshoot=True, overshoot_factor=1.5,
                              previous_context=True):
    """
    Generate chapter using per-beat expansion for maximum word count.
    """
    ensure_runtime_dirs()
    story_bible = STORY_BIBLE_PATH
    cumulative = CUMULATIVE_SUMMARY_PATH
    chapter_beats = chapter_beats_path(chapter)
    system_prompt_file = SYSTEM_PROMPT_PATH

    for f in [story_bible, cumulative, chapter_beats, system_prompt_file]:
        if not os.path.exists(f):
            print(f"ERROR: Missing required file: {f}")
            sys.exit(1)

    with open(story_bible) as f:
        story_bible_text = f.read()
    with open(cumulative) as f:
        cumulative_content = f.read()
    with open(chapter_beats) as f:
        beats_content = f.read()
    with open(system_prompt_file) as f:
        system_prompt = f.read()

    target_words_total = get_word_count_target() // get_default_chapters()
    
    # Parse POV and Tense
    pov, tense = parse_story_bible(story_bible_text)
    if tense and tense.lower() == 'past':
        tense_placeholder = 'past tense'
    elif tense and tense.lower() == 'present':
        tense_placeholder = 'present tense'
    else:
        tense_placeholder = tense or 'past tense'
    if pov and 'first person' in pov.lower():
        pov_placeholder = 'first person'
    elif pov and 'third person' in pov.lower():
        pov_placeholder = 'third person'
    else:
        pov_placeholder = pov or 'third person'
    
    # Replace placeholders in system prompt
    sys_prompt = system_prompt.replace('[WORD_COUNT_TARGET]', str(target_words_total))
    sys_prompt = sys_prompt.replace('[PAST_TENSE/PRESENT_TENSE]', tense_placeholder)
    sys_prompt = sys_prompt.replace('[FIRST_PERSON/THIRD_PERSON]', pov_placeholder)

    # Parse beats
    beats = parse_beats(beats_content)
    if not beats:
        print(f"ERROR: Could not parse beats for chapter {chapter}.")
        sys.exit(1)
    
    num_beats = len(beats)
    target_per_beat = target_words_total // num_beats

    # Calculate max_words for LLM to prevent runaway generation
    # Allow up to 2.5x the target per beat, plus 500-word buffer, capped at 8000
    max_words_for_llm = min(int(target_per_beat * 2.5) + 500, 8000)
    
    # Adjust for observed overshoot (factor ~1.7 by default). To get target_total actual,
    # we aim lower. Set adjust_overshoot=False to use raw targets.
    if adjust_overshoot:
        # Use the provided overshoot_factor parameter
        adjusted_target_per_beat = int(target_per_beat / overshoot_factor)
    else:
        adjusted_target_per_beat = target_per_beat
        overshoot_factor = 1.0
    
    if not silent:
        print(f"\n{'='*70}")
        print(f"  GENERATING CHAPTER {chapter} (Per-Beat, Maximum Word Count)")
        print(f"{'='*70}")
        print(f"Number of beats: {num_beats}")
        print(f"Target total: {target_words_total:,} words")
        print(f"Target per beat (adjusted): {adjusted_target_per_beat:,} words")
        print(f"Expected total: ~{int(adjusted_target_per_beat * num_beats * overshoot_factor):,} words")
        if scene_separator:
            print(f"Scene separator: '{scene_separator}'")
        print(f"{'='*70}\n")
    
    scenes = []
    beat_word_counts = []
    
    for idx, (beat_num, beat_text) in enumerate(beats):
        is_first = (idx == 0)
        is_last = (idx == len(beats) - 1)
        
        previous_scene = scenes[-1] if (previous_context and scenes) else None
        prompt = generate_beat_scene(
            chapter, beat_num, beat_text, story_bible_text,
            cumulative_content, adjusted_target_per_beat, sys_prompt,
            is_first=is_first, is_last=is_last,
            previous_scene=previous_scene
        )
        
        if not silent:
            print(f"  Generating Beat {beat_num}{' (Opening)' if is_first else ''}{' (Conclusion)' if is_last else ''}...")
        
        scene = stream_llm(prompt, model='write', system='', silent=silent,
                           max_words=max_words_for_llm, loop_detection=True)
        scenes.append(scene)
        
        # Save intermediate beat scene
        beat_path = chapter_polished_path(chapter, beat_num)
        with open(beat_path, 'w') as f:
            f.write(scene)
        
        wc = len(scene.split())
        beat_word_counts.append(wc)
        
        if not silent:
            print(f"    {wc:,} words (target: {adjusted_target_per_beat:,})")
            if wc < adjusted_target_per_beat * 0.8:
                print(f"    ⚠️  Below target")
            elif wc > adjusted_target_per_beat * 1.3:
                print(f"    ✅ Above target")
    
    # Combine scenes with separators
    if scene_separator:
        combined = f"\n\n{scene_separator}\n\n".join(scenes)
    else:
        combined = '\n\n'.join(scenes)
    
    # Add metadata header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = f"""# Chapter {chapter} Draft
Generated: {timestamp}
Method: Per-beat expansion (maximum word count)
Scene separator: '{scene_separator if scene_separator else "none"}'
Word counts per beat: {', '.join(f'Beat {i+1}: {wc:,}' for i, wc in enumerate(beat_word_counts))}
Total words: {sum(beat_word_counts):,}
Target: {target_words_total:,} words

---

"""
    full_draft = metadata + combined
    
    if output_file:
        output_path = os.path.join(script_dir, output_file)
    else:
        output_path = chapter_draft_path(chapter)
    
    with open(output_path, "w") as f:
        f.write(full_draft)
    
    total_words = sum(beat_word_counts)
    
    # Save summary log
    log_path = chapter_generation_log_path(chapter)
    with open(log_path, "w") as f:
        f.write(f"""# Generation Log - Chapter {chapter}
Timestamp: {timestamp}
Method: Per-beat polished
Target total: {target_words_total:,} words
Target per beat: {target_per_beat:,} words
Adjusted target per beat: {adjusted_target_per_beat:,} words
Overshoot factor: {overshoot_factor:.1f}

## Results
{chr(10).join(f'- Beat {i+1}: {wc:,} words' for i, wc in enumerate(beat_word_counts))}
- **Total**: {total_words:,} words
- **Target achieved**: {total_words/target_words_total*100:.1f}%

## Analysis
- Average words per beat: {total_words/len(beat_word_counts):.1f}
- Min/Max: {min(beat_word_counts):,} / {max(beat_word_counts):,}
- Beat variability: {(max(beat_word_counts)-min(beat_word_counts))/total_words*100:.1f}%

## Files
- Full draft: `{os.path.basename(output_path)}`
- Individual beats: `chapter_{chapter}_beat[1-{len(beats)}]_polished.txt`
""")
    
    return total_words, output_path, beat_word_counts


def generate_all_sequential(script_dir, skip_existing=True, silent=False,
                         scene_separator="***", adjust_overshoot=True, overshoot_factor=1.5,
                         previous_context=True):
    """
    Generate all chapters sequentially using per-beat expansion.
    Follows the same workflow as original generate_chapter.py --all:
      1. Generate chapter draft
      2. Run summarize_chapter.py
      3. Generate next beats (if needed)
    """
    chapters_dir = CHAPTERS_DIR
    beats_files = sorted(
        glob.glob(os.path.join(chapters_dir, "chapter_*_beats.md")),
        key=lambda p: int(re.search(r"chapter_(\d+)_beats", p).group(1)),
    )
    
    if not beats_files:
        print("No chapter beats found in chapters/. Run plan_chapters.py --beats first.")
        sys.exit(1)
    
    chapter_nums = []
    for bf in beats_files:
        m = re.search(r"chapter_(\d+)_beats", bf)
        if m:
            chapter_nums.append(int(m.group(1)))
    
    if not chapter_nums:
        print("Could not parse chapter numbers from beats filenames.")
        sys.exit(1)
    
    min_c, max_c = min(chapter_nums), max(chapter_nums)
    total_chapters = get_default_chapters()
    print(f"\n{'='*70}")
    print(f"  PER-BEAT SEQUENTIAL GENERATION")
    print(f"{'='*70}")
    print(f"Found beats for chapters {min_c}–{max_c} ({len(chapter_nums)} chapters)")
    print(f"Configured total: {total_chapters} chapters")
    print()
    print("Workflow: Generate (per-beat) → Summarize → Next Beats")
    print(f"{'='*70}\n")
    
    # Use a dynamic loop: after processing chapter N, check if chapter N+1
    # now has beats (possibly generated by summarize_chapter.py). Keep going
    # until we reach a chapter with no beats, OR we hit the configured total.
    ch = min_c
    while ch <= total_chapters:
        ch_str = str(ch)
        draft_path = chapter_draft_path(ch_str)
        beats_path = chapter_beats_path(ch_str)
        
        if not os.path.exists(beats_path):
            # No beats for this chapter — story is complete
            break
        
        # Check if this chapter has already been summarized
        cumulative_path = CUMULATIVE_SUMMARY_PATH
        chapter_summarized = False
        if os.path.exists(cumulative_path):
            with open(cumulative_path) as f:
                cum_text = f.read()
            chapter_summarized = has_summary_for_chapter(cum_text, ch)
        
        if os.path.exists(draft_path) and chapter_summarized:
            # Fully done — skip entirely
            if skip_existing:
                print(f"[{ch_str}] Skipping chapter {ch_str} — draft exists and is summarized")
                ch += 1
                continue
        elif os.path.exists(draft_path) and not chapter_summarized:
            # Draft exists but never summarized — summarize only, don't regenerate
            print(f"[{ch_str}] Draft exists but not yet summarized — summarizing...")
        elif not os.path.exists(draft_path):
            # No draft — generate it using per-beat method
            print(f"\n[{ch_str}] Generating chapter {ch_str} (per-beat)...")
            wc, path, beat_counts = generate_chapter(
                ch_str, script_dir, silent=silent,
                output_file=f"chapters/chapter_{ch_str}_draft.txt",  # Standard filename for pipeline
                scene_separator=scene_separator,
                adjust_overshoot=adjust_overshoot,
                overshoot_factor=overshoot_factor,
                previous_context=previous_context
            )
            print(f"  ✓ chapter_{ch_str}_draft.txt written ({wc:,} words)")
            print(f"  Beat counts: {', '.join(f'{c:,}' for c in beat_counts)}")
        
        # Summarize + generate next beats via the existing summarize_chapter.py script
        print(f"  → Summarizing chapter {ch_str}...")
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "summarize_chapter.py"), ch_str, "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  ✗ summarize_chapter.py FAILED (exit code {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr.strip()[:500]}")
            if result.stdout:
                print(f"  stdout: {result.stdout.strip()[:500]}")
            print(f"  ⚠ Cumulative summary NOT updated for chapter {ch_str}")
            print(f"  ⚠ Next beats may not have been generated")
            print()
            print("  Stopping — fix the error above and rerun with --no-skip to retry.")
            sys.exit(1)
        else:
            print(f"  ✓ chapter {ch_str} summarized, cumulative_summary.md updated")
        
        # Generate next-beats directly (summarize_chapter.py may have already done this)
        # Skip for the last chapter — no beats needed beyond total_chapters
        if ch >= total_chapters:
            pass  # Final chapter, no next beats
        else:
            next_beats_path = chapter_beats_path(ch + 1)
            if os.path.exists(next_beats_path):
                print(f"  ✓ chapter_{ch+1}_beats.md already exists")
            else:
                print(f"  → Generating chapter_{ch+1}_beats.md...")
                try:
                    # Import here to avoid circular imports
                    bp = generate_next_chapter_beats(ch_str, script_dir)
                    if bp:
                        print(f"  ✓ chapter_{ch+1}_beats.md written")
                except Exception as e:
                    print(f"  ⚠ Could not generate next beats: {e}")
        
        print()
        ch += 1
    
    if ch > total_chapters:
        print(f"{'='*70}")
        print(f"All {total_chapters} chapters complete!")
    else:
        print(f"{'='*70}")
        print(f"Stopped at chapter {ch} — no beats found.")
    print(f"Check chapters/ for drafts and cumulative_summary.md for the story so far.")


def generate_next_chapter_beats(chapter, script_dir):
    """Generate chapter N+1 beats if they don't already exist. Returns beats path or None."""
    next_chapter  = str(int(chapter) + 1)
    next_beats = chapter_beats_path(next_chapter)

    if os.path.exists(next_beats):
        return None

    with open(STORY_BIBLE_PATH) as f:
        story_bible = f.read()
    with open(CUMULATIVE_SUMMARY_PATH) as f:
        summary_content = f.read()
    with open(chapter_beats_path(chapter)) as f:
        beats_format = f.read()

    system_prompt = "You are a story architect."
    user_prompt = f"""Based on the story so far, write detailed beats for Chapter {next_chapter}.

STORY BIBLE (do not change these established facts):
{story_bible}

STORY SO FAR (cumulative summary):
{summary_content}

CHAPTER {next_chapter} BEATS TEMPLATE (follow this format):
{beats_format}

INSTRUCTIONS:
- Continue the story from where Chapter {chapter} left off
- Follow the same level of detail as the template above
- Be specific: name characters, describe scenes, give dialogue cues
- Plant seeds for future chapters in "Open Threads / Loose Ends"
- Do not include any preamble or commentary — output only the beats document"""

    content = stream_llm(user_prompt, model="beats", system=system_prompt)

    if not content or len(content.strip()) < 50:
        print(f"  ERROR: Beats output is empty or too short ({len(content.strip()) if content else 0} chars)", file=sys.stderr)
        return None

    with open(next_beats, "w") as f:
        f.write(content)

    return next_beats


# ── --all sequential workflow ────────────────────────────────────────────────

def main():
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="Generate chapter using per-beat expansion for maximum word count",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 2                    # Generate Chapter 2 with default settings
  %(prog)s 3 --no-separator     # Generate without scene separators
  %(prog)s 1 --raw-targets      # Use raw targets without overshoot adjustment
  %(prog)s 2 -o custom.txt      # Write to custom output file
  %(prog)s 2 --separator "###"  # Use custom scene separator
  %(prog)s --all                # Generate all chapters sequentially (full pipeline)
  %(prog)s --all --no-skip      # Regenerate all chapters even if drafts exist
  %(prog)s --all --separator "" # Generate all without scene separators
  %(prog)s 2 --no-previous-context # Disable previous beat context for testing transitions
"""
    )
    parser.add_argument("chapter", nargs="?", help="Chapter number to generate (or omit with --all)")
    parser.add_argument("--all", action="store_true", help="Generate all chapters sequentially")
    parser.add_argument("--silent", action="store_true", help="Suppress streaming output")
    parser.add_argument("-o", "--output", help="Custom output path")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                       help="Skip chapters that already have drafts and summaries (default: True)")
    parser.add_argument("--no-skip", action="store_false", dest="skip_existing",
                       help="Regenerate even if draft exists")
    parser.add_argument("--separator", default="***", help="Scene separator (default: '***', use '' for none)")
    parser.add_argument("--no-separator", action="store_true", dest="no_sep", help="Disable scene separator")
    parser.add_argument("--raw-targets", action="store_false", dest="adjust", 
                       help="Use raw word targets without overshoot adjustment")
    parser.add_argument("--overshoot-factor", type=float, default=1.5,
                       help="Overshoot factor adjustment (default: 1.5)")
    parser.add_argument("--no-previous-context", action="store_false", dest="previous_context",
                       help="Disable including previous beat in context (for testing transitions)")
    parser.set_defaults(previous_context=True)

    args = parser.parse_args()
    
    # Handle separator
    if args.no_sep:
        scene_separator = ""
    elif args.separator != "***":
        scene_separator = args.separator
    else:
        scene_separator = "***"
    
    if args.all:
        # Generate all chapters sequentially using per-beat expansion
        generate_all_sequential(
            SCRIPT_DIR,
            skip_existing=args.skip_existing,
            silent=args.silent,
            scene_separator=scene_separator,
            adjust_overshoot=args.adjust,
            overshoot_factor=args.overshoot_factor,
            previous_context=args.previous_context
        )
        return
    
    if not args.chapter:
        parser.print_help()
        sys.exit(1)
    
    # Single chapter generation
    total_words, output_path, beat_counts = generate_chapter(
        args.chapter, SCRIPT_DIR,
        silent=args.silent,
        output_file=args.output,
        scene_separator=scene_separator,
        adjust_overshoot=args.adjust,
        overshoot_factor=args.overshoot_factor,
        previous_context=args.previous_context
    )
    
    target = get_word_count_target() // get_default_chapters()
    
    print(f"\n{'='*70}")
    print(f"  CHAPTER {args.chapter} GENERATION COMPLETE")
    print(f"{'='*70}")
    print(f"Output: {output_path}")
    print(f"Total words: {total_words:,}")
    print(f"Target: {target:,} words")
    print(f"Achievement: {total_words/target*100:.1f}%")
    print(f"\nBeat breakdown:")
    for i, wc in enumerate(beat_counts):
        print(f"  Beat {i+1}: {wc:,} words")
    print(f"\nScene separator: '{scene_separator if scene_separator else 'none'}'" )
    
    if total_words < target * 0.8:
        print(f"\n⚠️  WARNING: Word count significantly below target.")
        print(f"   Consider using --raw-targets flag or adjusting prompts.")
    elif total_words > target * 1.5:
        print(f"\n📝 NOTE: Word count exceeds target by >50%.")
        print(f"   Consider reducing overshoot factor or using --raw-targets.")
    else:
        print(f"\n✅ SUCCESS: Close to target!")
    
    print(f"\nNext steps:")
    print(f"  1. Review: {output_path}")
    print(f"  2. python3 summarize_chapter.py {args.chapter}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
