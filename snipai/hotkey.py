"""Global hotkey listener using `keyboard` lib (runs in own thread)."""
from __future__ import annotations
import threading
import keyboard
from PySide6.QtCore import QObject, Signal


class HotkeyListener(QObject):
    """Emits `triggered` signal when hotkey pressed. Thread-safe via Qt signal."""

    triggered = Signal()

    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self._registered = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._registered:
                return
            keyboard.add_hotkey(self.hotkey, self._on_fire, suppress=False)
            self._registered = True

    def stop(self) -> None:
        with self._lock:
            if not self._registered:
                return
            try:
                keyboard.remove_hotkey(self.hotkey)
            except (KeyError, ValueError):
                pass
            self._registered = False

    def _on_fire(self) -> None:
        self.triggered.emit()
