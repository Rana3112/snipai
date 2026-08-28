"""Global hotkey listener. Uses native Windows RegisterHotKey on Win32, falls back to `keyboard` on other platforms."""
from __future__ import annotations
import sys
import time
import ctypes
import threading
from PySide6.QtCore import QObject, Signal, QAbstractNativeEventFilter, QCoreApplication

# Fallback keyboard import for non-Windows
try:
    import keyboard
except ImportError:
    keyboard = None

if sys.platform == "win32":
    import ctypes.wintypes

    WM_HOTKEY = 0x0312

    class WinHotkeyFilter(QAbstractNativeEventFilter):
        def __init__(self, hwnd, hotkey_id, callback):
            super().__init__()
            self.hwnd = hwnd
            self.hotkey_id = hotkey_id
            self.callback = callback

        def nativeEventFilter(self, eventType, message):
            if eventType == b"windows_generic_MSG":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.callback()
                    return True, 0
            return False, 0


def _parse_hotkey_win32(hotkey_str: str) -> tuple[int, int]:
    """Parse hotkey string (e.g. 'ctrl+shift+space') into (modifiers, vk_code)."""
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    modifiers = 0
    vk = 0
    for p in parts:
        if p in ("ctrl", "control"):
            modifiers |= 0x0002  # MOD_CONTROL
        elif p == "alt":
            modifiers |= 0x0001  # MOD_ALT
        elif p == "shift":
            modifiers |= 0x0004  # MOD_SHIFT
        elif p in ("win", "super", "command"):
            modifiers |= 0x0008  # MOD_WIN
        elif p == "space":
            vk = 0x20  # VK_SPACE
        elif p == "enter":
            vk = 0x0D  # VK_RETURN
        elif p == "tab":
            vk = 0x09  # VK_TAB
        elif p in ("escape", "esc"):
            vk = 0x1B  # VK_ESCAPE
        elif len(p) == 1:
            if "a" <= p <= "z":
                vk = ord(p.upper())
            elif "0" <= p <= "9":
                vk = ord(p)
        elif p.startswith("f") and p[1:].isdigit():
            f_num = int(p[1:])
            if 1 <= f_num <= 12:
                vk = 0x6F + f_num
    return modifiers, vk


class HotkeyListener(QObject):
    """Emits `triggered` signal when hotkey pressed. Native on Win32, keyboard lib on other OS."""

    triggered = Signal()
    _id_counter = 1
    _counter_lock = threading.Lock()

    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self._registered = False
        self._lock = threading.Lock()

        if sys.platform == "win32":
            with HotkeyListener._counter_lock:
                self._hotkey_id = HotkeyListener._id_counter
                HotkeyListener._id_counter += 1
            self._filter = None
        else:
            self._hotkey_id = None

    def start(self) -> None:
        with self._lock:
            if self._registered:
                return

            if sys.platform == "win32":
                modifiers, vk = _parse_hotkey_win32(self.hotkey)
                if vk == 0:
                    raise ValueError(f"Unsupported hotkey: {self.hotkey}")

                MOD_NOREPEAT = 0x4000
                ok = ctypes.windll.user32.RegisterHotKey(
                    None, self._hotkey_id, modifiers | MOD_NOREPEAT, vk
                )
                if not ok:
                    err = ctypes.GetLastError()
                    raise RuntimeError(
                        f"RegisterHotKey failed for '{self.hotkey}' "
                        f"(Windows error {err}). "
                        "Another app (IME, AutoHotkey, etc.) may own this shortcut."
                    )

                self._filter = WinHotkeyFilter(None, self._hotkey_id, self._on_fire)
                QCoreApplication.instance().installNativeEventFilter(self._filter)
                self._registered = True
            else:
                if keyboard:
                    keyboard.add_hotkey(self.hotkey, self._on_fire, suppress=False)
                    self._registered = True
                else:
                    raise RuntimeError("keyboard module not installed, cannot register hotkey")

    def stop(self) -> None:
        with self._lock:
            if not self._registered:
                return

            if sys.platform == "win32":
                ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)
                if self._filter:
                    QCoreApplication.instance().removeNativeEventFilter(self._filter)
                    self._filter = None
                self._registered = False
            else:
                if keyboard:
                    try:
                        keyboard.remove_hotkey(self.hotkey)
                    except (KeyError, ValueError):
                        pass
                    self._registered = False

    def _on_fire(self) -> None:
        self.triggered.emit()


def _read_clipboard_ctypes() -> str:
    """Read clipboard text via Win32 ctypes — safe to call from any thread."""
    CF_UNICODETEXT = 13
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    if not u32.OpenClipboard(None):
        return ""
    try:
        handle = u32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = k32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr).strip()
        finally:
            k32.GlobalUnlock(handle)
    finally:
        u32.CloseClipboard()


class TextGrabHotkeyListener(QObject):
    """Kernel-level hotkey for text grab.

    Uses keyboard.add_hotkey(suppress=True) so the hook fires while the
    source window still has keyboard focus and text selection intact.
    Immediately sends Ctrl+C via the same low-level channel, reads the
    clipboard via ctypes (thread-safe), then emits grabbed(text) on the
    Qt main thread via a queued signal.
    """

    grabbed = Signal(str)   # emits the captured text (non-empty)
    failed = Signal()       # emits when nothing was selected

    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self._registered = False

    def start(self) -> None:
        if not keyboard:
            raise RuntimeError("keyboard module not available")
        keyboard.add_hotkey(self.hotkey, self._on_fire, suppress=True)
        self._registered = True

    def stop(self) -> None:
        if self._registered and keyboard:
            try:
                keyboard.remove_hotkey(self.hotkey)
            except (KeyError, ValueError):
                pass
            self._registered = False

    def _on_fire(self) -> None:
        # Runs in keyboard hook thread. Source window still has focus here.
        # Wait for user to physically release the hotkey keys.
        time.sleep(0.08)
        # Save current clipboard so we can restore it later.
        prev = _read_clipboard_ctypes()
        # Clear clipboard so we can detect a new copy.
        ctypes.windll.user32.OpenClipboard(None)
        ctypes.windll.user32.EmptyClipboard()
        ctypes.windll.user32.CloseClipboard()
        # Send Ctrl+C to the focused window (still the source app).
        keyboard.send("ctrl+c")
        # Poll for clipboard to be populated.
        deadline = time.monotonic() + 0.5
        text = ""
        while time.monotonic() < deadline:
            time.sleep(0.02)
            text = _read_clipboard_ctypes()
            if text:
                break
        # Restore previous clipboard content.
        if prev and not text:
            # nothing new copied — restore silently
            pass
        if text:
            self.grabbed.emit(text)
        else:
            self.failed.emit()
