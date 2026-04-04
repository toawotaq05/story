#!/usr/bin/env python3
"""Shared config — all scripts import model settings from here."""
import json
import os

from paths import CONFIG_PATH

DEFAULT_MODEL = "openrouter/thedrummer/cydonia-24b-v4.1"

_config_cache = None


def _merge_dicts(base, overrides):
    merged = dict(base or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

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

def get_local_request_overrides(task_or_model=None):
    """Get merged local request overrides for a task/model, preserving legacy behavior."""
    cfg = get_config()
    presets = cfg.get("sampling_presets", {})
    task_presets = cfg.get("task_presets", {})
    model_presets = cfg.get("model_presets", {})
    task_overrides = cfg.get("local_task_request_overrides", {})
    model_overrides = cfg.get("local_model_request_overrides", {})

    merged = {}

    defaults = cfg.get("local_request_defaults", {})
    if isinstance(defaults, dict):
        merged = _merge_dicts(merged, defaults)

    resolved_model = None
    if task_or_model:
        models = cfg.get("models", {})
        if isinstance(models, dict):
            resolved_model = models.get(task_or_model, task_or_model)
        else:
            resolved_model = task_or_model

        preset_name = task_presets.get(task_or_model)
        if isinstance(preset_name, str):
            preset = presets.get(preset_name, {})
            if isinstance(preset, dict):
                merged = _merge_dicts(merged, preset)

        model_preset_name = model_presets.get(resolved_model)
        if isinstance(model_preset_name, str):
            preset = presets.get(model_preset_name, {})
            if isinstance(preset, dict):
                merged = _merge_dicts(merged, preset)

        task_override = task_overrides.get(task_or_model, {})
        if isinstance(task_override, dict):
            merged = _merge_dicts(merged, task_override)

        model_override = model_overrides.get(resolved_model, {})
        if isinstance(model_override, dict):
            merged = _merge_dicts(merged, model_override)

    overrides = cfg.get("local_request_overrides", {})
    if isinstance(overrides, dict):
        merged = _merge_dicts(merged, overrides)

    return merged


def is_pacing_enabled():
    """Check if dynamic chapter pacing (weighted word counts) is enabled."""
    cfg = get_config()
    return cfg.get("story", {}).get("dynamic_pacing", False)
