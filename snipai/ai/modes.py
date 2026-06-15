"""Prompt modes — intent presets. Each mode swaps the system prompt + default
question so one snip can be explained, summarized, translated, fixed, etc.

Auto mode picks a sensible default from the foreground app (e.g. VSCode -> Fix-code,
browser -> Explain).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    system: str
    default_prompt: str


_BASE = (
    "You analyze a region the user selected on their screen (text, code, image, "
    "UI, document, anything). Use Markdown. Be accurate. "
)

MODES: dict[str, Mode] = {
    "auto": Mode(
        "auto", "Auto",
        _BASE + "Decide the most useful response for what the selection contains.",
        "Analyze this selection and surface anything useful. Be concise.",
    ),
    "explain": Mode(
        "explain", "Explain",
        _BASE + "Explain clearly what the selection means or does, step by step. "
                "Define jargon. Assume the reader is smart but unfamiliar.",
        "Explain this selection clearly.",
    ),
    "summarize": Mode(
        "summarize", "Summarize",
        _BASE + "Summarize the selection. Lead with a one-line TL;DR, then 3-5 "
                "bullet key points. Drop filler.",
        "Summarize this selection.",
    ),
    "translate": Mode(
        "translate", "Translate",
        _BASE + "Translate the selection's text into English (or, if it's already "
                "English, into the language the user most likely wants — ask if "
                "unclear). Give the translation first, then a short note on nuance.",
        "Translate this selection.",
    ),
    "code": Mode(
        "code", "Fix code",
        _BASE + "Treat the selection as code. Identify bugs, errors, or smells. "
                "Give a corrected version in a code block, then briefly explain "
                "what was wrong and why the fix works.",
        "Review this code, find issues, and give a corrected version.",
    ),
    "eli5": Mode(
        "eli5", "ELI5",
        _BASE + "Explain the selection like I'm five — simple words, everyday "
                "analogies, no jargon. Keep it short and friendly.",
        "Explain this selection in the simplest way possible.",
    ),
}

DEFAULT_MODE = "auto"
ORDER = ["auto", "explain", "summarize", "translate", "code", "eli5"]


def get_mode(key: str) -> Mode:
    return MODES.get(key, MODES[DEFAULT_MODE])


# ── Auto-detect from foreground window ──

_CODE_APPS = ("code", "devenv", "pycharm", "idea", "sublime", "webstorm",
              "rider", "clion", "goland", "studio", "vim", "nvim", "atom")
_BROWSER_APPS = ("chrome", "firefox", "msedge", "edge", "brave", "opera", "safari")


def detect_mode_for_foreground() -> str:
    """Best-effort: pick a mode from the active window's process name (Windows only).

    Returns a mode key. Falls back to 'auto' on any failure or non-Windows.
    """
    try:
        import sys
        if not sys.platform.startswith("win"):
            return DEFAULT_MODE

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return DEFAULT_MODE

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return DEFAULT_MODE

        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return DEFAULT_MODE
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            # QueryFullProcessImageNameW
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = buf.value.lower()
            else:
                return DEFAULT_MODE
        finally:
            kernel32.CloseHandle(h)

        name = exe.rsplit("\\", 1)[-1]
        if any(a in name for a in _CODE_APPS):
            return "code"
        if any(a in name for a in _BROWSER_APPS):
            return "explain"
        return DEFAULT_MODE
    except Exception:
        log.debug("foreground mode detect failed", exc_info=True)
        return DEFAULT_MODE
