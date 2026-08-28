"""App lifecycle. Wires tray + hotkeys + overlay + response window.

Features:
  - crop snip (overlay -> vision)
  - text snip (clipboard grab -> text analysis)
  - multi-snip stack (collect crops/texts, analyze together)
  - region watch (pin a region, alert on change)
  - history (searchable past snips)
"""
from __future__ import annotations
import logging
import sys
import time
from PySide6.QtCore import QObject, QRect, Slot, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .api.worker import GeminiWorker
from .capture.overlay import CaptureOverlay
from .capture.screenshot import grab_virtual_desktop, Snapshot
from .capture.text_select import grab_selected_text
from .config import config, init_config, Config
from .hotkey import HotkeyListener, TextGrabHotkeyListener
from .tray import Tray
from .ui.response_window import ResponseWindow
from .ui.history_window import HistoryWindow
from . import store
from . import watch as watchmod

log = logging.getLogger(__name__)

COOLDOWN_S = 0.4


class SnipAIApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.qapp.setQuitOnLastWindowClosed(False)

        self.tray = Tray(qapp)
        self.hotkey: HotkeyListener | None = None
        self.text_hotkey: HotkeyListener | None = None

        self._overlay: CaptureOverlay | None = None
        self._overlay_purpose: str = "crop"   # "crop" | "stack" | "watch"
        self._overlay_snap: Snapshot | None = None
        self._windows: list[ResponseWindow] = []
        self._history_win: HistoryWindow | None = None
        self._watchers: list[watchmod.RegionWatcher] = []
        self._stack: list[dict] = []
        self._busy = False
        self._last_end_t: float = 0.0

        self.tray.snip_requested.connect(self.on_snip)
        self.tray.text_requested.connect(lambda: self.on_text_snip(from_tray=True))
        self.tray.stack_add_requested.connect(self.on_stack_add)
        self.tray.stack_analyze_requested.connect(self.on_stack_analyze)
        self.tray.watch_requested.connect(self.on_watch)
        self.tray.history_requested.connect(self.on_history)
        self.tray.settings_requested.connect(self.on_settings)
        self.tray.quit_requested.connect(self.on_quit)

    def start(self) -> int:
        # Initialize config from disk
        init_config()

        # First-run: launch setup wizard
        if not config.SETUP_COMPLETE:
            from .ui.setup_wizard import SetupWizard
            wizard = SetupWizard()
            if not wizard.exec():
                log.info("Setup cancelled, exiting")
                return 0
            # Reload config after wizard
            init_config()

        ok, err = config.validate()
        if not ok:
            log.warning("config invalid: %s", err)

        store.init_db()
        self.tray.show()
        self._start_hotkeys()
        self.tray.notify(
            "SnipAI running",
            f"Crop: {config.HOTKEY}   Text: {config.TEXT_HOTKEY}",
        )
        log.info("SnipAI started; crop=%s text=%s", config.HOTKEY, config.TEXT_HOTKEY)
        return self.qapp.exec()

    def _start_hotkeys(self):
        """Start hotkey listeners. Called after config is loaded."""
        self.hotkey = HotkeyListener(config.HOTKEY)
        # TextGrabHotkeyListener uses kernel-level hook — fires before source window
        # loses focus, immediately sends Ctrl+C while selection is still intact.
        self.text_hotkey = TextGrabHotkeyListener(config.TEXT_HOTKEY)
        self.hotkey.triggered.connect(self.on_snip)
        self.text_hotkey.grabbed.connect(self._on_text_grabbed)
        self.text_hotkey.failed.connect(
            lambda: self.tray.notify("SnipAI", "No text selected — highlight text first.")
        )
        failed = []
        try:
            self.hotkey.start()
            log.info("Hotkey registered: %s", config.HOTKEY)
        except RuntimeError as e:
            log.error("Hotkey registration failed: %s", e)
            failed.append(str(e))
        try:
            self.text_hotkey.start()
            log.info("Text grab hotkey registered: %s", config.TEXT_HOTKEY)
        except RuntimeError as e:
            log.error("Text grab hotkey registration failed: %s", e)
            failed.append(str(e))
        if failed:
            self.tray.notify(
                "SnipAI — hotkey conflict",
                "\n".join(failed[:2]) + "\nUse tray menu or change hotkeys in Settings.",
            )

    @Slot(str)
    def _on_text_grabbed(self, text: str):
        """Called on Qt main thread after kernel hook grabbed the text."""
        if not self._ready():
            return
        log.info("Text grab hotkey: got %d chars", len(text))
        self._open_text_window(text)

    # ── Guards ──
    def _ready(self) -> bool:
        if self._busy or self._overlay is not None:
            log.info("ignored — already in progress")
            return False
        if (time.monotonic() - self._last_end_t) < COOLDOWN_S:
            log.info("ignored — cooldown")
            return False
        return True

    # ── Crop ──
    @Slot()
    def on_snip(self):
        if not self._ready():
            return
        # Close any existing response windows so the overlay can be seen
        # on top of them. Otherwise the user thinks the new snip didn't
        # open anything because the old popup is still covering the screen.
        for w in list(self._windows):
            try:
                w.close()
            except Exception:
                pass
        self._overlay_purpose = "crop"
        QTimer.singleShot(0, self._open_overlay)

    # ── Text ──
    @Slot()
    def on_text_snip(self, from_tray: bool = False):
        if not self._ready():
            return
        for w in list(self._windows):
            try:
                w.close()
            except Exception:
                pass
        QTimer.singleShot(0, lambda: self._dispatch_text_snip(from_tray=from_tray))

    def _dispatch_text_snip(self, from_tray: bool = False):
        text = ""
        if from_tray:
            # Tray click loses source-window focus and blocks SendInput via UIPI.
            # Read clipboard directly — user should Ctrl+C their text first.
            from PySide6.QtGui import QGuiApplication
            text = QGuiApplication.clipboard().text().strip()
            log.info("Text snip dispatch (clipboard-direct): got %d chars", len(text))
            if not text:
                self.tray.notify(
                    "SnipAI — no text",
                    "Copy text first (Ctrl+C in any app), then use Grab selected text.",
                )
                self._last_end_t = time.monotonic()
                return
        else:
            # Hotkey path: source window still has focus, Ctrl+C simulation works.
            try:
                text = grab_selected_text()
            except Exception:
                log.exception("text grab failed")
            log.info("Text snip dispatch (hotkey): got %d chars", len(text))
            if not text:
                self.tray.notify("SnipAI", "No text selected — highlight text first.")
                self._last_end_t = time.monotonic()
                return

        self._open_text_window(text)

    def _open_text_window(self, text: str):
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        anchor = QRect(pos.x(), pos.y(), 1, 1)
        try:
            win = ResponseWindow(anchor, selected_text=text)
            win.closed.connect(lambda w=win: self._cleanup_window(w))
            self._windows.append(win)
            win.show(); win.raise_(); win.activateWindow()
            log.info("Text ResponseWindow shown visible=%s windows=%d", win.isVisible(), len(self._windows))
        except Exception as e:
            log.exception("text response window failed")
            self.tray.notify("Popup failed", str(e)[:180])
        self._last_end_t = time.monotonic()

    # ── Stack ──
    @Slot()
    def on_stack_add(self):
        """Add the next snip (crop or text) to the stack instead of analyzing."""
        if not self._ready():
            return
        # Prefer selected text; fall back to crop overlay.
        text = ""
        try:
            text = grab_selected_text()
        except Exception:
            log.exception("text grab failed")
        if text:
            self._stack.append({"text": text})
            self.tray.set_stack_count(len(self._stack))
            self.tray.notify("Added to stack", f"{len(self._stack)} item(s). Add more or Analyze.")
            self._last_end_t = time.monotonic()
        else:
            self._overlay_purpose = "stack"
            QTimer.singleShot(0, self._open_overlay)

    @Slot()
    def on_stack_analyze(self):
        if not self._stack:
            self.tray.notify("SnipAI", "Stack is empty.")
            return
        items = list(self._stack)
        self._stack.clear()
        self.tray.set_stack_count(0)
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        anchor = QRect(pos.x(), pos.y(), 1, 1)
        try:
            win = ResponseWindow(anchor, stack_items=items)
            win.closed.connect(lambda w=win: self._cleanup_window(w))
            self._windows.append(win)
            win.show(); win.raise_(); win.activateWindow()
        except Exception as e:
            log.exception("stack response window failed")
            self.tray.notify("Popup failed", str(e)[:180])
        self._last_end_t = time.monotonic()

    # ── Watch ──
    @Slot()
    def on_watch(self):
        if not self._ready():
            return
        self._overlay_purpose = "watch"
        QTimer.singleShot(0, self._open_overlay)

    # ── History ──
    @Slot()
    def on_history(self):
        if self._history_win is not None:
            self._history_win.raise_()
            self._history_win.activateWindow()
            return
        self._history_win = HistoryWindow()
        self._history_win.closed.connect(self._on_history_closed)
        self._history_win.show()
        self._history_win.raise_()
        self._history_win.activateWindow()

    def _on_history_closed(self):
        self._history_win = None

    # ── Settings ──
    @Slot()
    def on_settings(self):
        from .ui.settings_panel import SettingsPanel
        panel = SettingsPanel()
        panel.exec()

    # ── Overlay ──
    def _open_overlay(self):
        # Defensive: release any modifier keys that the `keyboard` library
        # may still consider held from a previous hotkey press. Without this,
        # the second press of the same hotkey can be missed.
        try:
            import keyboard
            for k in ("space", "ctrl", "shift", "alt", "win", "g"):
                try:
                    keyboard.release(k)
                except Exception:
                    pass
        except Exception:
            pass

        self._busy = True
        self._overlay = None
        try:
            snap = grab_virtual_desktop()
            self._overlay_snap = snap
            ov = CaptureOverlay(snap)
            ov.selected.connect(self._on_selected)
            ov.cancelled.connect(self._on_cancelled)
            # The QThread that the keyboard lib callback runs on is NOT the
            # Qt main thread. Use QueuedConnection to marshal signals back.
            ov.show()
            ov.raise_()
            ov.activateWindow()
            self._overlay = ov
        except Exception as e:
            log.exception("overlay failed")
            self.tray.notify("Snip failed", str(e))
            self._busy = False
            self._overlay = None

    @Slot(QRect, bytes)
    def _on_selected(self, rect: QRect, png: bytes):
        purpose = self._overlay_purpose
        snap = self._overlay_snap
        log.info("Selection %dx%d (%s), %d bytes", rect.width(), rect.height(), purpose, len(png))
        self._overlay = None
        self._busy = False

        if purpose == "stack":
            self._stack.append({"png": png})
            self.tray.set_stack_count(len(self._stack))
            self.tray.notify("Added to stack", f"{len(self._stack)} item(s). Add more or Analyze.")
            self._last_end_t = time.monotonic()
            return

        if purpose == "watch":
            self._start_watch(rect, snap)
            self._last_end_t = time.monotonic()
            return

        # default: crop -> analyze
        try:
            log.info("Creating ResponseWindow for crop selection")
            win = ResponseWindow(rect, png)
            win.closed.connect(lambda w=win: self._cleanup_window(w))
            self._windows.append(win)
            win.show(); win.raise_(); win.activateWindow()
            log.info(
                "ResponseWindow shown visible=%s pos=%s size=%s windows=%d",
                win.isVisible(), win.pos(), win.size(), len(self._windows),
            )
        except Exception as e:
            log.exception("response window failed")
            self.tray.notify("Popup failed", str(e)[:180])
        finally:
            self._last_end_t = time.monotonic()

    @Slot()
    def _on_cancelled(self):
        log.info("Selection cancelled")
        self._overlay = None
        self._busy = False
        self._last_end_t = time.monotonic()

    # ── Watch wiring ──
    def _start_watch(self, rect: QRect, snap: Snapshot):
        try:
            box = watchmod.logical_rect_to_box(rect, snap)
            w = watchmod.RegionWatcher(box, interval=5.0, label=f"{rect.width()}x{rect.height()}")
            w.changed.connect(self._on_region_changed)
            w.error.connect(lambda e: self.tray.notify("Watch error", e))
            w.finished.connect(lambda ww=w: self._cleanup_watcher(ww))
            self._watchers.append(w)
            w.start()
            self.tray.notify("Watching region", "You'll be alerted when it changes.")
        except Exception as e:
            log.exception("start watch failed")
            self.tray.notify("Watch failed", str(e))

    @Slot(bytes)
    def _on_region_changed(self, png: bytes):
        self.tray.notify("Region changed", "Opening analysis…")
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        anchor = QRect(pos.x(), pos.y(), 1, 1)
        win = None
        try:
            win = ResponseWindow(anchor, png=png)
            win.closed.connect(lambda w=win: self._cleanup_window(w))
            self._windows.append(win)
            win.show(); win.raise_(); win.activateWindow()
        except Exception as e:
            log.exception("watch response window failed")
            self.tray.notify("Popup failed", str(e)[:180])

    def _cleanup_watcher(self, w):
        try:
            self._watchers.remove(w)
        except ValueError:
            pass

    def _cleanup_window(self, w: ResponseWindow):
        try:
            self._windows.remove(w)
        except ValueError:
            pass
        self._last_end_t = time.monotonic()

    @Slot()
    def on_quit(self):
        log.info("Quitting")
        if self.hotkey:
            self.hotkey.stop()
        if self.text_hotkey:
            self.text_hotkey.stop()
        for w in list(self._watchers):
            w.stop()
            w.wait(1000)
        self.qapp.quit()


def run() -> int:
    handlers = []
    try:
        from pathlib import Path
        log_path = Path.home() / ".snipai" / "snipai.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_h = logging.FileHandler(log_path, encoding="utf-8")
        file_h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        handlers.append(file_h)
    except Exception:
        pass

    if sys.stderr is not None and hasattr(sys.stderr, "write"):
        try:
            stream_h = logging.StreamHandler(sys.stderr)
            stream_h.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            ))
            handlers.append(stream_h)
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
    )
    from PySide6.QtWidgets import QSystemTrayIcon

    qapp = QApplication(sys.argv)
    qapp.setApplicationName(config.APP_NAME)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "SnipAI", "System tray not available on this platform.")
        return 1

    app = SnipAIApp(qapp)
    return app.start()
