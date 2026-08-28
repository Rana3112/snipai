"""Tier 2 free-model whitelist — per-provider curated lists.

This is the fallback for providers that don't expose pricing in their /models
response (OpenAI, Anthropic, Google, Groq, NVIDIA, Bluesminds, OpenCode Zen).
OpenRouter is handled live via Tier 1.

When a provider rotates its free lineup, edit PROVIDER_FREE_MODELS.
"""
from __future__ import annotations

# Provider -> list of {id, vision} entries that are currently free.
PROVIDER_FREE_MODELS: dict[str, list[dict]] = {
    "google": [
        {"id": "gemini-2.0-flash", "vision": True},
        {"id": "gemini-2.0-flash-lite", "vision": True},
    ],
    "groq": [
        # Groq retired llama-4-scout and the vision previews (404
        # model_not_found); the current free lineup is text-only
        # (verified against the live /models catalog).
        {"id": "llama-3.3-70b-versatile", "vision": False},
        {"id": "llama-3.1-8b-instant", "vision": False},
        {"id": "openai/gpt-oss-120b", "vision": False},
        {"id": "openai/gpt-oss-20b", "vision": False},
        {"id": "qwen/qwen3.6-27b", "vision": False},
        {"id": "groq/compound", "vision": False},
        {"id": "groq/compound-mini", "vision": False},
    ],
    "nvidia": [
        {"id": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1", "vision": True},
        {"id": "meta/llama-3.2-11b-vision-instruct", "vision": True},
        {"id": "meta/llama-3.2-90b-vision-instruct", "vision": True},
    ],
    "bluesminds": [
        {"id": "meta/llama-3.2-11b-vision-instruct", "vision": True},
    ],
    "openai": [],
    "anthropic": [],
    "opencode_zen": [],
    "openrouter": [],   # Tier 1 handles OpenRouter
    "custom": [],
}


def is_free(provider: str, model_id: str) -> bool | None:
    """True/False if the model is whitelisted as free. None if not in list."""
    for entry in PROVIDER_FREE_MODELS.get(provider, []):
        if entry["id"] == model_id:
            return True
    return None


def vision_for(provider: str, model_id: str) -> bool | None:
    """Return vision flag from whitelist, or None if not in list."""
    for entry in PROVIDER_FREE_MODELS.get(provider, []):
        if entry["id"] == model_id:
            return entry.get("vision", False)
    return None


def any_free_vision(provider: str) -> str | None:
    """First free+vision model id for the provider, or None."""
    for entry in PROVIDER_FREE_MODELS.get(provider, []):
        if entry.get("vision"):
            return entry["id"]
    return None
