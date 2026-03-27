#!/usr/bin/env python3
"""Shared config — all scripts import model settings from here."""
import os, json

DEFAULT_MODEL = "openrouter/thedrummer/cydonia-24b-v4.1"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_config_cache = None

def get_config():
    global _config_cache
    if _config_cache is None:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {"models": {}, "story": {}, "local_mode": False}
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

def is_local_mode():
    """Return True if local_mode is enabled in config.json."""
    return get_config().get("local_mode", False)

def get_local_endpoint():
    """Return the local llama.cpp server endpoint URL."""
    return get_config().get("local_endpoint", "http://localhost:8080")

def get_local_model():
    """Return the model name to use with the local server."""
    return get_config().get("local_model", "qwen3.5-4b")
