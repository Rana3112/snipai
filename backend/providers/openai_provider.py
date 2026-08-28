"""OpenAI provider — also handles OpenAI-compatible endpoints (Bluesminds, custom)."""
from __future__ import annotations
import logging
import requests
from typing import Generator

from openai import OpenAI

log = logging.getLogger(__name__)


def stream_chat(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> Generator[str, None, None]:
    """Stream chat completion chunks from an OpenAI-compatible API."""
    client = OpenAI(api_key=api_key, base_url=base_url)
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for ev in stream:
        if not ev.choices:
            continue
        delta = ev.choices[0].delta
        txt = getattr(delta, "content", None)
        if txt:
            yield txt


def _openrouter_live_catalog() -> dict[str, dict]:
    """Fetch OpenRouter's public catalog and return {id: {pricing, modality, vision}}.

    No auth needed. Cache for the process lifetime (providers re-evaluate weekly).
    """
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"User-Agent": "SnipAI/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        out: dict[str, dict] = {}
        for m in (resp.json().get("data") or []):
            mid = m.get("id")
            if not mid:
                continue
            arch = m.get("architecture") or {}
            in_mods = arch.get("input_modalities") or []
            out[mid] = {
                "pricing": m.get("pricing"),
                "modality": arch.get("modality"),
                "vision": "image" in in_mods or "video" in in_mods,
            }
        return out
    except Exception as e:
        log.warning("openrouter live catalog fetch failed: %s", e)
        return {}


def _is_free(pricing: dict | None) -> bool:
    if not pricing:
        return False
    try:
        p = float(pricing.get("prompt", "1") or 1)
        c = float(pricing.get("completion", "1") or 1)
        r = float(pricing.get("request", "0") or 0)
        img = float(pricing.get("image", "0") or 0)
    except (TypeError, ValueError):
        return False
    return p == 0 and c == 0 and r == 0 and img == 0


def fetch_models(api_key: str, base_url: str, provider: str = "openai") -> list[dict]:
    """Fetch available models from an OpenAI-compatible API.

    For provider='openrouter' this also enriches the list with live pricing,
    modality, and vision flags from OpenRouter's public catalog.
    """
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.models.list()
    base = [{"id": m.id, "name": m.id, "free": False, "vision": False,
             "modality": None, "pricing": None} for m in resp.data]

    if provider == "openrouter":
        live = _openrouter_live_catalog()
        for entry in base:
            mid = entry["id"]
            meta = live.get(mid)
            if not meta:
                continue
            entry["pricing"] = meta.get("pricing")
            entry["modality"] = meta.get("modality")
            entry["vision"] = bool(meta.get("vision"))
            entry["free"] = _is_free(meta.get("pricing"))

    return base
