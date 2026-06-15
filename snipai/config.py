"""Config system — reads/writes JSON config at ~/.snipai/config.json.

First run: config.json doesn't exist -> setup wizard creates it.
After setup: app reads from this file.

Fallback: if no JSON config exists, tries to read from .env (legacy).
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".snipai"
CONFIG_PATH = CONFIG_DIR / "config.json"

LEGACY_ROOT = Path(__file__).parent.parent

# Default backend URL — can be overridden by SNIPAI_BACKEND_URL env var
# or by the setup wizard.
DEFAULT_BACKEND_URL = os.getenv(
    "SNIPAI_BACKEND_URL",
    "https://snipai-backend-iev1.onrender.com"
)

# Default fallback order for cross-provider failover. Users can reorder in
# the Settings → Providers tab.
DEFAULT_FALLBACK_ORDER: list[str] = [
    "groq",
    "bluesminds",
    "openrouter",
    "google",
    "nvidia",
    "openai",
    "anthropic",
    "opencode_zen",
]


@dataclass
class ThemeConfig:
    accent: str = "#5b6aff"
    bg_primary: str = "#0f1117"
    bg_secondary: str = "#161d2c"
    text_primary: str = "#e2e8f0"
    text_secondary: str = "#8b9aff"


@dataclass
class CustomProvider:
    """User-defined OpenAI-compatible provider (e.g. Local Ollama, Together)."""
    name: str          # user-visible label, also used as the id suffix
    base_url: str      # e.g. "http://localhost:11434/v1"
    api_key: str = ""
    model: str = ""
    vision: bool = True


@dataclass
class AppConfig:
    setup_complete: bool = False
    provider: str = "bluesminds"
    api_key: str = ""
    base_url: str = ""
    model: str = "meta/llama-3.2-11b-vision-instruct"
    hotkey: str = "ctrl+shift+space"
    text_hotkey: str = "ctrl+alt+g"
    backend_url: str = DEFAULT_BACKEND_URL
    theme: ThemeConfig = None

    # ── Multi-provider support ──
    # Per-preset API keys, keyed by provider id (e.g. "groq", "openrouter").
    provider_keys: dict[str, str] = field(default_factory=dict)
    # User-added custom providers (list of CustomProvider as dicts).
    custom_providers: list[dict] = field(default_factory=list)
    # User-defined failover order. Provider ids and "custom:<name>" entries.
    fallback_order: list[str] = field(default_factory=lambda: list(DEFAULT_FALLBACK_ORDER))

    def __post_init__(self):
        if self.theme is None:
            self.theme = ThemeConfig()


def _load_legacy_env() -> dict:
    """Fallback: read from .env if JSON config doesn't exist."""
    env_path = LEGACY_ROOT / ".env"
    if not env_path.exists():
        return {}
    config = {}
    try:
        from dotenv import dotenv_values
        env = dotenv_values(env_path)
        if env.get("BLUESMINDS_API_KEY"):
            config["api_key"] = env["BLUESMINDS_API_KEY"]
            config["provider"] = "bluesminds"
        if env.get("BLUESMINDS_BASE_URL"):
            config["base_url"] = env["BLUESMINDS_BASE_URL"]
        if env.get("MODEL"):
            config["model"] = env["MODEL"]
        if env.get("HOTKEY"):
            config["hotkey"] = env["HOTKEY"]
        if env.get("TEXT_HOTKEY"):
            config["text_hotkey"] = env["TEXT_HOTKEY"]
    except Exception:
        pass
    return config


def _normalize_fallback_order(order: list[str] | None) -> list[str]:
    """Filter unknown ids, dedupe, preserve order, fall back to default."""
    if not order:
        return list(DEFAULT_FALLBACK_ORDER)
    seen: set[str] = set()
    out: list[str] = []
    for pid in order:
        if pid and pid not in seen:
            out.append(pid)
            seen.add(pid)
    return out if out else list(DEFAULT_FALLBACK_ORDER)


def load_config() -> AppConfig:
    """Load config from JSON file, fallback to .env."""
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            theme_data = data.get("theme", {})
            theme = ThemeConfig(**theme_data) if theme_data else ThemeConfig()
            return AppConfig(
                setup_complete=data.get("setup_complete", False),
                provider=data.get("provider", "bluesminds"),
                api_key=data.get("api_key", ""),
                base_url=data.get("base_url", ""),
                model=data.get("model", "meta/llama-3.2-11b-vision-instruct"),
                hotkey=data.get("hotkey", "ctrl+shift+space"),
                text_hotkey=data.get("text_hotkey", "ctrl+alt+g"),
                backend_url=data.get("backend_url", DEFAULT_BACKEND_URL),
                theme=theme,
                provider_keys=data.get("provider_keys") or {},
                custom_providers=data.get("custom_providers") or [],
                fallback_order=_normalize_fallback_order(data.get("fallback_order")),
            )
        except Exception:
            pass

    # Fallback: legacy .env
    legacy = _load_legacy_env()
    if legacy.get("api_key"):
        return AppConfig(
            setup_complete=True,
            provider=legacy.get("provider", "bluesminds"),
            api_key=legacy.get("api_key", ""),
            base_url=legacy.get("base_url", ""),
            model=legacy.get("model", "meta/llama-3.2-11b-vision-instruct"),
            hotkey=legacy.get("hotkey", "ctrl+shift+space"),
            text_hotkey=legacy.get("text_hotkey", "ctrl+alt+g"),
        )

    return AppConfig()


def save_config(cfg: AppConfig) -> None:
    """Persist config to disk and refresh the in-memory singleton so any
    worker thread reading `config.X` immediately sees the updated values
    (no manual `config.reload()` call required).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    global _config
    _config = cfg


# Module-level singleton — reloaded on save_config()
_config: AppConfig | None = None


def _get_config() -> AppConfig:
    """Get config, auto-loading if needed. Safe to call at import time."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def custom_provider_id(custom: dict) -> str:
    """Stable id used by the worker for a custom provider entry."""
    return f"custom:{custom.get('name', '').strip()}"


def find_custom_provider(name: str) -> dict | None:
    """Look up a custom provider dict by its display name."""
    cfg = _get_config()
    for cp in cfg.custom_providers:
        if cp.get("name", "").strip() == name.strip():
            return cp
    return None


class Config:
    """Dynamic config proxy — reads from current _config singleton."""

    @property
    def SETUP_COMPLETE(self) -> bool:
        return _get_config().setup_complete

    @property
    def PROVIDER(self) -> str:
        return _get_config().provider

    @property
    def API_KEY(self) -> str:
        return _get_config().api_key

    @property
    def BASE_URL(self) -> str:
        return _get_config().base_url

    @property
    def MODEL(self) -> str:
        return _get_config().model

    @property
    def HOTKEY(self) -> str:
        return _get_config().hotkey

    @property
    def TEXT_HOTKEY(self) -> str:
        return _get_config().text_hotkey

    @property
    def BACKEND_URL(self) -> str:
        return _get_config().backend_url

    @property
    def THEME(self) -> ThemeConfig:
        return _get_config().theme

    @property
    def APP_NAME(self) -> str:
        return "SnipAI"

    # ── Multi-provider accessors ──
    @property
    def PROVIDER_KEYS(self) -> dict[str, str]:
        return dict(_get_config().provider_keys)

    @property
    def CUSTOM_PROVIDERS(self) -> list[dict]:
        return list(_get_config().custom_providers)

    @property
    def FALLBACK_ORDER(self) -> list[str]:
        return list(_get_config().fallback_order)

    def provider_key(self, provider_id: str) -> str:
        """Return the API key for a provider id. Falls back to legacy api_key
        for the active provider if no per-provider key is set.
        """
        cfg = _get_config()
        key = cfg.provider_keys.get(provider_id, "")
        if key:
            return key
        if provider_id == cfg.provider:
            return cfg.api_key
        return ""

    def custom_provider_for(self, custom_id: str) -> dict | None:
        """Resolve a 'custom:<name>' id to its dict, or None."""
        if not custom_id.startswith("custom:"):
            return None
        name = custom_id[len("custom:"):]
        return find_custom_provider(name)

    def custom_provider_base_url(self, custom_id: str) -> str:
        cp = self.custom_provider_for(custom_id)
        return cp.get("base_url", "") if cp else ""

    def custom_provider_api_key(self, custom_id: str) -> str:
        cp = self.custom_provider_for(custom_id)
        return cp.get("api_key", "") if cp else ""

    def custom_provider_default_model(self, custom_id: str) -> str:
        cp = self.custom_provider_for(custom_id)
        return cp.get("model", "") if cp else ""

    def is_preset(self, provider_id: str) -> bool:
        return not provider_id.startswith("custom:")

    @classmethod
    def validate(cls) -> tuple[bool, str]:
        cfg = _get_config()
        if not cfg.api_key and not cfg.provider_keys:
            return False, "API key not configured. Run setup wizard or set keys in Settings."
        return True, ""

    @classmethod
    def reload(cls) -> None:
        """Reload from disk."""
        global _config
        _config = load_config()


def init_config() -> AppConfig:
    """Initialize the global config. Call once at app startup."""
    global _config
    _config = load_config()
    return _config


def get_config() -> AppConfig:
    """Get the current config (loads if not already loaded)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


config = Config()
