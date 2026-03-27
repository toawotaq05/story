"""dual_llm — local/remote LLM routing via a single stream_llm() function."""
from .llm_provider import stream_llm

__all__ = ["stream_llm"]
