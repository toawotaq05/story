#!/usr/bin/env python3
"""Shared config — all scripts import model settings from here."""
import json
import os

from paths import CONFIG_PATH

DEFAULT_MODEL = "openrouter/thedrummer/cydonia-24b-v4.1"

_config_cache = None

def get_config():
    global _config_cache
    if _config_cache is None:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {"models": {}, "story": {}}
    return _config_cache

def get_model(task, default=None):
    """Get the model for a given task, e.g. get_model('write')."""
    cfg = get_config()
    return cfg.get("models", {}).get(task, default or DEFAULT_MODEL)

def get_default_chapters():
    cfg = get_config()
    return cfg.get("story", {}).get("default_chapters", 10)

def get_word_count_target():
    cfg = get_config()
    return cfg.get("story", {}).get("word_count_target", 25000)

def is_chapter_length_enforced():
    cfg = get_config()
    return bool(cfg.get("story", {}).get("enforce_chapter_length", False))

def is_local_mode():
    """Check if we're using local llama.cpp server."""
    cfg = get_config()
    return cfg.get("local_mode", False)

def get_local_endpoint():
    """Get the local llama.cpp server endpoint."""
    cfg = get_config()
    return cfg.get("local_endpoint", "http://localhost:8080")

def get_local_model():
    """Get the local model identifier."""
    cfg = get_config()
    return cfg.get("local_model", "local")

def get_local_request_overrides():
    """Get extra JSON fields to merge into local chat-completions payloads."""
    cfg = get_config()
    overrides = cfg.get("local_request_overrides", {})
    return overrides if isinstance(overrides, dict) else {}
