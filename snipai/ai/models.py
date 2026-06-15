"""Model list fetcher. Caches enriched records per provider id.

Records: list of dicts with {id, name, free, vision, modality, pricing}.
Cache is keyed by provider id so multiple providers can be queried without
clobbering each other.
"""
from __future__ import annotations
import logging
import httpx
from PySide6.QtCore import QThread, Signal

from ..config import config

log = logging.getLogger(__name__)

# provider_id -> [records]
_RECORDS_CACHE: dict[str, list[dict]] = {}

# Builtin ID patterns that suggest vision capability.
_VISION_HINTS = (
    "vision", "vl", "scout", "4v", "gpt-4o", "claude-3", "claude-fable",
    "gemini", "pixtral", "llava", "qwen-vl", "qvq", "minicpm-v",
)


def _looks_like_vision(model_id: str) -> bool:
    mid = model_id.lower()
    return any(h in mid for h in _VISION_HINTS)


def get_cached_records(provider_id: str | None = None) -> list[dict] | None:
    pid = provider_id or config.PROVIDER
    return _RECORDS_CACHE.get(pid)


def get_cached_models(provider_id: str | None = None) -> list[str] | None:
    """Back-compat: return just ids from cache for the given provider."""
    records = get_cached_records(provider_id)
    if records is None:
        return None
    return [m["id"] for m in records]


def set_cache(provider_id: str, records: list[dict]) -> None:
    _RECORDS_CACHE[provider_id] = records


def clear_cache(provider_id: str | None = None) -> None:
    if provider_id:
        _RECORDS_CACHE.pop(provider_id, None)
    else:
        _RECORDS_CACHE.clear()


def fetch_models_sync(provider_id: str | None = None) -> list[dict]:
    """Blocking fetch via backend /v1/models. Returns enriched records.

    For custom provider ids ("custom:<name>"), we still hit the backend with
    provider="custom" and pass the resolved base_url/api_key.
    """
    pid = provider_id or config.PROVIDER
    if pid.startswith("custom:"):
        base_url = config.custom_provider_base_url(pid)
        api_key = config.custom_provider_api_key(pid)
        prov_for_backend = "custom"
    else:
        base_url = config.BASE_URL if pid == "custom" else None
        if pid == config.PROVIDER:
            api_key = config.API_KEY
        else:
            api_key = config.provider_key(pid)
        prov_for_backend = pid

    resp = httpx.post(
        f"{config.BACKEND_URL}/v1/models",
        json={
            "provider": prov_for_backend,
            "api_key": api_key,
            "base_url": base_url,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("models") or []
    records: list[dict] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("name")
        if not mid:
            continue
        is_vision = bool(m.get("vision", False))
        if not is_vision:
            is_vision = _looks_like_vision(mid)
        records.append({
            "id": mid,
            "name": m.get("name") or mid,
            "free": bool(m.get("free", False)),
            "vision": is_vision,
            "modality": m.get("modality"),
            "pricing": m.get("pricing"),
        })
    set_cache(pid, records)
    return records


def pick_free_vision(provider_id: str | None = None,
                     blocked: set[str] | None = None) -> dict | None:
    """Return the first free+vision model record for the provider, or None.

    If the provider has no free+vision models but a default model is configured
    (e.g. for a custom provider), return that as a fallback.
    """
    records = get_cached_records(provider_id) or []
    blocked = blocked or set()
    for r in records:
        if r.get("free") and r.get("vision") and r["id"] not in blocked:
            return r
    # Fallback: any vision model not yet blocked.
    for r in records:
        if r.get("vision") and r["id"] not in blocked:
            return r
    # Last resort: any model not blocked.
    for r in records:
        if r["id"] not in blocked:
            return r
    return None


class ModelsFetcher(QThread):
    """Async wrapper around fetch_models_sync. Emits full records list."""

    fetched = Signal(list)   # list[dict]
    failed = Signal(str)

    def __init__(self, provider_id: str | None = None, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id or config.PROVIDER

    def run(self) -> None:
        try:
            records = fetch_models_sync(self.provider_id)
            self.fetched.emit(records)
        except Exception as e:
            log.exception("models list failed for %s", self.provider_id)
            self.failed.emit(str(e))
