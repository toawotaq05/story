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
            _config_cache = {"models": {}}
    return _config_cache

def get_model(task, default=None):
    """Get the model for a given task, e.g. get_model('write')."""
    cfg = get_config()
    return cfg.get("models", {}).get(task, default or DEFAULT_MODEL)
