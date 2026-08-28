"""Provider router — dispatches to the correct provider adapter."""
from __future__ import annotations
import logging
from typing import Generator

from .openai_provider import stream_chat as openai_stream, fetch_models as openai_models
from .anthropic_provider import stream_chat as anthropic_stream, fetch_models as anthropic_models
from .google_provider import stream_chat as google_stream, fetch_models as google_models
from .free_models import PROVIDER_FREE_MODELS, is_free, vision_for

log = logging.getLogger(__name__)

# Provider base URLs (all OpenAI-compatible except anthropic/google)
BLUESMINDS_BASE_URL = "https://api.bluesminds.com/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"


def stream_chat(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict],
    base_url: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> Generator[str, None, None]:
    """Route to the correct provider and stream response."""
    if provider == "anthropic":
        yield from anthropic_stream(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == "google":
        yield from google_stream(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == "bluesminds":
        yield from openai_stream(
            api_key=api_key, base_url=BLUESMINDS_BASE_URL, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "groq":
        yield from openai_stream(
            api_key=api_key, base_url=GROQ_BASE_URL, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "nvidia":
        yield from openai_stream(
            api_key=api_key, base_url=NVIDIA_NIM_BASE_URL, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "openrouter":
        yield from openai_stream(
            api_key=api_key, base_url=OPENROUTER_BASE_URL, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "opencode_zen":
        yield from openai_stream(
            api_key=api_key, base_url=OPENCODE_ZEN_BASE_URL, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "openai":
        yield from openai_stream(
            api_key=api_key, base_url=base_url or "https://api.openai.com/v1",
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "custom":
        if not base_url:
            raise ValueError("base_url is required for custom provider")
        yield from openai_stream(
            api_key=api_key, base_url=base_url, model=model,
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _apply_tier2_whitelist(provider: str, models: list[dict]) -> None:
    """Mark models as free+vision if they're in the per-provider whitelist.
    Mutates the list in place.
    """
    whitelist = PROVIDER_FREE_MODELS.get(provider, [])
    if not whitelist:
        return
    by_id = {e["id"]: e for e in whitelist}
    for m in models:
        entry = by_id.get(m["id"])
        if not entry:
            continue
        m["free"] = True
        if entry.get("vision"):
            m["vision"] = True


def fetch_models(
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> list[dict]:
    """Fetch available models for a provider, enriched with free+vision flags."""
    if provider == "anthropic":
        models = anthropic_models(api_key=api_key)
    elif provider == "google":
        models = google_models(api_key=api_key)
    elif provider == "bluesminds":
        models = openai_models(api_key=api_key, base_url=BLUESMINDS_BASE_URL, provider="bluesminds")
    elif provider == "groq":
        models = openai_models(api_key=api_key, base_url=GROQ_BASE_URL, provider="groq")
    elif provider == "nvidia":
        models = openai_models(api_key=api_key, base_url=NVIDIA_NIM_BASE_URL, provider="nvidia")
    elif provider == "openrouter":
        models = openai_models(api_key=api_key, base_url=OPENROUTER_BASE_URL, provider="openrouter")
    elif provider == "opencode_zen":
        models = openai_models(api_key=api_key, base_url=OPENCODE_ZEN_BASE_URL, provider="opencode_zen")
    elif provider == "openai":
        models = openai_models(api_key=api_key, base_url=base_url or "https://api.openai.com/v1", provider="openai")
    elif provider == "custom":
        if not base_url:
            raise ValueError("base_url is required for custom provider")
        models = openai_models(api_key=api_key, base_url=base_url, provider="custom")
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # OpenRouter: live pricing already applied by openai_provider.
    # For everything else (or as a safety net for OpenRouter), apply the
    # Tier 2 whitelist so free flags are never lost.
    _apply_tier2_whitelist(provider, models)

    # Sort: free first, then by id.
    models.sort(key=lambda m: (not m.get("free", False), m["id"]))
    return models
