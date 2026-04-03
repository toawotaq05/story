"""
LLM provider — single stream_llm() function that routes to local or remote.

Local mode:  POST to a llama.cpp server (http://localhost:8080/v1/chat/completions)
Remote mode: uses `llm` CLI subprocess (same as the original working scripts)
"""
import subprocess
import sys
import threading
import time
import json as _json
import os
import re

# Add parent dir to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    get_local_endpoint,
    get_local_model,
    get_local_request_overrides,
    is_local_mode,
)
from text_quality import looks_like_runaway_repetition


def _strip_thinking_tags(text):
    """
    Remove thinking/reasoning tags from LLM output to keep only the final content.
    Handles:
      -  ... </think>
      - <thought> ... </thought>
      - [thinking] ... [/thinking]
      - [thinking] ... [end thinking]  (alternative closing)
    """
    if not text:
        return text

    patterns = [
        r'<think>.*?</think>',        # Standard thinking tags
        r'<thought>.*?</thought>',   # Alternative thought tags
        r'\[thinking\].*?\[/thinking\]',  # BBCode-style
        r'\[thinking\].*?\[end thinking\]',  # End style
    ]

    for pattern in patterns:
        # re.DOTALL makes '.' match newlines, so multi-line thinking blocks are removed
        text = re.sub(pattern, '', text, flags=re.DOTALL)

    return text


def _new_loop_detector():
    return {"triggers": 0, "words_seen": 0, "next_check": 160}


def _update_loop_detector(loop_detector, content, output_chunks, max_words):
    if not loop_detector or not max_words:
        return False

    loop_detector["words_seen"] += len(content.split())
    if loop_detector["words_seen"] < loop_detector["next_check"]:
        return False

    recent_text = "".join(output_chunks)[-8000:]
    looks_repetitive = looks_like_runaway_repetition(recent_text)
    if looks_repetitive:
        loop_detector["triggers"] += 2
    if loop_detector["words_seen"] > max_words * 2.0 and looks_repetitive:
        loop_detector["triggers"] += 4
    elif loop_detector["words_seen"] > max_words * 2.5:
        loop_detector["triggers"] += 4

    loop_detector["next_check"] += 80
    return loop_detector["triggers"] >= 10


def stream_llm(prompt, model=None, system="", silent=False, max_words=None, loop_detection=True):
    """
    Generate a completion with streaming output to stdout.

    When local_mode=True in config.json: routes to the local llama.cpp server.
    Otherwise: uses `llm` CLI subprocess (OpenRouter or other configured backend).

    Args:
        prompt:   The user prompt string.
        model:    Model key from config.json models dict (e.g. "write", "summarize").
                  For local mode this is ignored; the model's display name is used as-is.
        system:   System prompt string.
        silent:   If True, suppress streaming to stdout and only return the text.
        max_words: If provided (and using local mode), sets a dynamic max_tokens limit
                  to prevent runaway generation. Uses 2.25x tokens-per-word + cap at 8192.
        loop_detection: If True (and using local mode with max_words), monitors for
                  repetitive n-gram loops and stops early.

    Returns:
        The full generated text string.
    """
    if is_local_mode():
        return _stream_local(prompt, model=model, system=system, silent=silent,
                             max_words=max_words, loop_detection=loop_detection)
    else:
        return _stream_remote(prompt, model=model, system=system, silent=silent)


def _merge_payload(base, overrides):
    """Recursively merge config-provided local request overrides into a payload."""
    merged = dict(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_payload(merged[key], value)
        else:
            merged[key] = value
    return merged


def _stream_local(prompt, model=None, system="", silent=False, retries=3, backoff=2,
                  max_words=None, loop_detection=True):
    """Call the local llama.cpp server via HTTP with streaming output.

    Args:
        max_words: If provided, sets max_tokens dynamically (words * TOKENS_PER_WORD * safety_margin)
        loop_detection: If True, monitors for repetitive n-gram loops and stops early
    """
    import requests
    endpoint = get_local_endpoint()
    model_id = get_local_model()

    url = f"{endpoint}/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Calculate sensible max_tokens if we have a word target
    # Average: 1 word ≈ 1.3-1.5 tokens. Add 50% buffer for overshoot + safety margin.
    if max_words:
        # Conservative: 1.5 tokens per word, plus 50% buffer = 2.25 tokens/word
        # But cap at reasonable upper bound (e.g., 8192) to prevent runaway
        calculated = int(max_words * 2.25)
        max_tokens = min(calculated, 8192)  # Hard cap at 8k tokens
    else:
        max_tokens = 4096  # Safer default than 32768

    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": True,
    }
    payload = _merge_payload(payload, get_local_request_overrides())

    for attempt in range(retries):
        if attempt > 0:
            wait_time = backoff * (2 ** (attempt - 1))  # Exponential backoff
            if not silent:
                print(f"[local] Retry {attempt + 1}/{retries} after {wait_time}s...")
            time.sleep(wait_time)

        if not silent:
            print(f"[local] POST {url}  model={model_id}")

        try:
            r = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                stream=True,
                timeout=300,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Local LLM request failed ({r.status_code}): {r.text[:500]}")

            # Process response with loop detection
            output = []
            reasoning = []  # Track reasoning separately — don't include in final output
            loop_detector = _new_loop_detector() if loop_detection else None

            loop_detected_flag = False
            for line in r.iter_lines():
                if loop_detected_flag:
                    break
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line.strip() == "[DONE]":
                    break
                try:
                    chunk = _json.loads(line)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content") or ""
                    reason = delta.get("reasoning_content") or ""
                    if content:
                        if not silent:
                            sys.stdout.write(content)
                            sys.stdout.flush()
                        output.append(content)

                        # Loop detection
                        if _update_loop_detector(loop_detector, content, output, max_words):
                            if not silent:
                                print("\n[!] Loop detected - stopping generation early")
                            loop_detected_flag = True
                            r.close()
                            break
                    elif reason:
                        reasoning.append(reason)
                except Exception:
                    continue

            if not silent:
                sys.stdout.flush()

            # If loop was detected, raise to trigger retry
            if loop_detected_flag:
                raise RuntimeError("Loop detected - generation produced repetitive output")

            # Success - return result
            result = "".join(output)
            if not result.strip():
                result = "".join(reasoning)
            result = _strip_thinking_tags(result)
            return result

        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Local LLM failed after {retries} attempts: {e}")
            continue


def _stream_remote(prompt, model=None, system="", silent=False, retries=3, backoff=2, **kwargs):
    """Call the remote LLM via `llm` CLI subprocess with streaming output.

    Note: max_words and loop_detection are ignored for remote mode (handled by the API).
    """
    # Resolve model alias (e.g. "story_bible" → "openrouter/qwen/qwen3-235b-a22b")
    # Import here to avoid circular imports with config.py
    from config import get_model
    if model is not None:
        resolved = get_model(model)
    else:
        resolved = get_model("write")

    for attempt in range(retries):
        if attempt > 0:
            wait_time = backoff * (2 ** (attempt - 1))  # Exponential backoff
            if not silent:
                print(f"[remote] Retry {attempt + 1}/{retries} after {wait_time}s...")
            time.sleep(wait_time)
        
        cmd = ["llm", "-m", resolved]
        if system:
            cmd += ["-s", system]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        output = []

        def pump():
            try:
                for char in iter(lambda: proc.stdout.read(1), ""):
                    if char:
                        if not silent:
                            sys.stdout.write(char)
                            sys.stdout.flush()
                        output.append(char)
            except Exception:
                pass

        t = threading.Thread(target=pump)
        t.start()

        # Write prompt, close stdin to signal end of input
        proc.stdin.write(prompt)
        proc.stdin.flush()
        proc.stdin.close()

        proc.wait()
        t.join(timeout=5)

        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            if attempt == retries - 1:
                raise RuntimeError(f"`llm` CLI failed after {retries} attempts (code {proc.returncode}): {stderr}")
            continue
        
        # Success
        break

    result = "".join(output)
    # Strip thinking tags to avoid clutter in saved outputs
    result = _strip_thinking_tags(result)
    return result
