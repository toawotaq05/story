"""
LLM provider — single stream_llm() function that routes to local or remote.

Local mode:  POST to a llama.cpp server (http://localhost:8080/v1/chat/completions)
Remote mode: uses `llm` CLI subprocess (same as the original working scripts)
"""
import subprocess
import sys
import threading
import json as _json
import os

# Add parent dir to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import is_local_mode, get_local_endpoint, get_local_model


def stream_llm(prompt, model=None, system="", silent=False):
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

    Returns:
        The full generated text string.
    """
    if is_local_mode():
        return _stream_local(prompt, model=model, system=system, silent=silent)
    else:
        return _stream_remote(prompt, model=model, system=system, silent=silent)


def _stream_local(prompt, model=None, system="", silent=False):
    """Call the local llama.cpp server via HTTP with streaming output."""
    import requests

    endpoint = get_local_endpoint()
    model_id = get_local_model()

    url = f"{endpoint}/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 16384,
        "stream": True,
    }

    if not silent:
        print(f"[local] POST {url}  model={model_id}")

    r = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        stream=True,
        timeout=300,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Local LLM request failed ({r.status_code}): {r.text[:500]}")

    output = []
    for line in r.iter_lines():
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
            content = delta.get("content", "")
            if content:
                if not silent:
                    sys.stdout.write(content)
                    sys.stdout.flush()
                output.append(content)
        except Exception:
            continue

    if not silent:
        sys.stdout.flush()

    return "".join(output)


def _stream_remote(prompt, model=None, system="", silent=False):
    """Call the remote LLM via `llm` CLI subprocess with streaming output."""
    # Resolve model alias (e.g. "story_bible" → "openrouter/qwen/qwen3-235b-a22b")
    # Import here to avoid circular imports with config.py
    from config import get_model
    if model is not None:
        resolved = get_model(model)
    else:
        resolved = get_model("write")

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
        raise RuntimeError(f"`llm` CLI failed (code {proc.returncode}): {stderr}")

    return "".join(output)
