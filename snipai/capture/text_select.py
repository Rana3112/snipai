"""Grab currently-selected text via the clipboard (Ctrl+C trick).

When the user has text selected in any app and triggers the hotkey, we
simulate a system-wide Ctrl+C via Win32 SendInput, then poll the
clipboard, then restore prior contents. Must run on the Qt main thread
(touches QClipboard).
"""
from __future__ import annotations
import time
import ctypes
import logging

import keyboard
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)


_USER32 = ctypes.windll.user32
_KEYBOARD_EVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_C = 0x43


# Windows INPUT struct — must include MOUSEINPUT in the union so that
# sizeof(_INPUT) == 40 bytes (64-bit) matching what SendInput expects.
# Using only KEYBDINPUT gives 28 bytes → SendInput rejects it silently.

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("_u",   _INPUT_UNION),
    ]


def _send_ctrl_c_via_sendinput() -> None:
    """Send Ctrl+C as one atomic SendInput batch."""
    ki = lambda vk, flags=0: _INPUT(
        type=1,
        _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None))
    )
    inputs = (_INPUT * 4)(
        ki(_VK_CONTROL),
        ki(_VK_C),
        ki(_VK_C, _KEYBOARD_EVENTF_KEYUP),
        ki(_VK_CONTROL, _KEYBOARD_EVENTF_KEYUP),
    )
    sent = _USER32.SendInput(4, inputs, ctypes.sizeof(_INPUT))
    if sent != 4:
        err = ctypes.GetLastError()
        raise RuntimeError(f"SendInput sent {sent}/4 events (WinError {err})")


def _release_all_modifiers() -> None:
    """Release any modifier keys held by the hotkey chord."""
    for k in ("space", "g", "q", "alt", "ctrl", "shift", "win"):
        try:
            keyboard.release(k)
        except Exception:
            pass


def grab_selected_text(timeout: float = 0.4) -> str:
    """Copy current selection, return it, and restore prior clipboard.

    Returns "" if nothing was selected.
    """
    cb = QGuiApplication.clipboard()
    prev = cb.text()

    cb.clear()
    # No processEvents() here — it re-enters Qt loop and can steal focus.

    _release_all_modifiers()
    time.sleep(0.10)

    try:
        _send_ctrl_c_via_sendinput()
    except Exception as e:
        log.warning("SendInput ctrl+c failed, falling back to keyboard.send: %s", e)
        try:
            keyboard.send("ctrl+c")
        except Exception:
            pass

    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = cb.text()
        if text:
            break
        time.sleep(0.02)

    if prev:
        cb.setText(prev)

    return text.strip()
