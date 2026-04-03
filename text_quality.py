#!/usr/bin/env python3
"""Cheap text-quality heuristics for repetition and compression-based loop detection."""
import re
import zlib


def normalized_words(text, max_words=240):
    if not text:
        return []
    words = re.findall(r"[a-z0-9']+", text.lower())
    if max_words and len(words) > max_words:
        return words[-max_words:]
    return words


def max_ngram_repetition_ratio(text, n=3, max_words=240):
    words = normalized_words(text, max_words=max_words)
    if len(words) < max(n * 4, 12):
        return 0.0

    counts = {}
    total = 0
    for index in range(len(words) - n + 1):
        gram = tuple(words[index:index + n])
        counts[gram] = counts.get(gram, 0) + 1
        total += 1
    if total == 0:
        return 0.0
    return max(counts.values()) / total


def compression_ratio(text, max_chars=4000):
    if not text:
        return 1.0
    trimmed = text[-max_chars:] if max_chars and len(text) > max_chars else text
    normalized = " ".join(normalized_words(trimmed, max_words=800))
    if len(normalized) < 200:
        return 1.0

    raw = normalized.encode("utf-8", errors="ignore")
    compressed = zlib.compress(raw, level=1)
    return len(compressed) / max(len(raw), 1)


def looks_like_runaway_repetition(text):
    ratio = max_ngram_repetition_ratio(text, n=3, max_words=240)
    compression = compression_ratio(text, max_chars=4000)
    if ratio >= 0.20:
        return True
    return ratio >= 0.12 and compression <= 0.38
