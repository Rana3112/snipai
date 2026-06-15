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
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)


# ── Win32 SendInput for reliable keystroke delivery ──────────────────────
_USER32 = ctypes.windll.user32
_KEYBOARD_EVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_C = 0x43


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ki", _KEYBDINPUT)]


def _send_ctrl_c_via_sendinput() -> None:
    """Send a real system-wide Ctrl+C through Win32 SendInput.

    More reliable than `keyboard.send("ctrl+c")` because the OS dispatches
    the synthetic event to whichever window currently has focus, exactly
    like a real keypress.
    """
    # Press Ctrl
    down = _INPUT(type=1, ki=_KEYBDINPUT(_VK_CONTROL, 0, 0, 0, None))
    # Press C
    down_c = _INPUT(type=1, ki=_KEYBDINPUT(_VK_C, 0, 0, 0, None))
    # Release C
    up_c = _INPUT(type=1, ki=_KEYBDINPUT(_VK_C, 0, _KEYBOARD_EVENTF_KEYUP, 0, None))
    # Release Ctrl
    up = _INPUT(type=1, ki=_KEYBDINPUT(_VK_CONTROL, 0, _KEYBOARD_EVENTF_KEYUP, 0, None))
    _USER32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    time.sleep(0.01)
    _USER32.SendInput(1, ctypes.byref(down_c), ctypes.sizeof(_INPUT))
    time.sleep(0.02)
    _USER32.SendInput(1, ctypes.byref(up_c), ctypes.sizeof(_INPUT))
    time.sleep(0.01)
    _USER32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))


def _release_all_modifiers() -> None:
    """Best-effort release of every modifier and trigger key.

    The global hotkey leaves its keys logically held in the OS state
    machine. Without this release, ctrl+c is sent as a chord like
    ctrl+alt+c which most apps ignore.
    """
    for k in ("space", "g", "alt", "ctrl", "shift", "win"):
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

    # Clear first so we can tell whether ctrl+c actually copied a selection.
    cb.clear()
    QGuiApplication.processEvents()

    # Release any held modifier / hotkey keys so ctrl+c is sent clean.
    _release_all_modifiers()
    time.sleep(0.10)

    # Dispatch the system-wide copy via real OS key event, not the
    # `keyboard` lib's higher-level send. The OS will deliver ctrl+c to
    # whatever window currently has focus, which is the user's source
    # app with the selection.
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
        QGuiApplication.processEvents()
        text = cb.text()
        if text:
            break
        time.sleep(0.02)

    if prev:
        cb.setText(prev)

    return text.strip()
