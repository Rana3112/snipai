"""System tray icon + menu."""
from __future__ import annotations
import ctypes
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QBrush, QFont
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication


def _build_icon() -> QIcon:
    """Lucide sparkles on brand gradient — crisp, modern."""
    try:
        from .ui.icons import lucide_pixmap
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Brand gradient background
        p.setBrush(QBrush(QColor(91, 106, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 12, 12)
        # Lucide sparkles white, centered
        icon_pix = lucide_pixmap("sparkles", 36, "#ffffff")
        if icon_pix is not None and not icon_pix.isNull():
            x = (64 - icon_pix.width()) // 2
            y = (64 - icon_pix.height()) // 2
            p.drawPixmap(x, y, icon_pix)
        else:
            p.setPen(QColor(255, 255, 255))
            f = QFont("Segoe UI", 26, QFont.Weight.Bold)
            p.setFont(f)
            p.drawText(pix.rect(), 0x84, "AI")
        p.end()
        return QIcon(pix)
    except Exception:
        # Fallback procedural
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(50, 130, 246)))
        p.setPen(QColor(255, 255, 255))
        p.drawRoundedRect(4, 4, 56, 56, 12, 12)
        p.setPen(QColor(255, 255, 255))
        f = QFont("Segoe UI", 26, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(pix.rect(), 0x84, "AI")
        p.end()
        return QIcon(pix)


class Tray(QObject):
    snip_requested = Signal()
    text_requested = Signal()
    stack_add_requested = Signal()
    stack_analyze_requested = Signal()
    watch_requested = Signal()
    history_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, app: QApplication, parent=None):
        super().__init__(parent)
        self.app = app
        self.icon = QSystemTrayIcon(_build_icon(), parent=self)
        self.icon.setToolTip("SnipAI")

        menu = QMenu()

        act_snip = QAction("Snip now (crop)", menu)
        act_snip.triggered.connect(self.snip_requested.emit)
        menu.addAction(act_snip)

        act_text = QAction("Grab selected text", menu)
        act_text.triggered.connect(self.text_requested.emit)
        menu.addAction(act_text)

        menu.addSeparator()

        act_stack_add = QAction("Add snip to stack", menu)
        act_stack_add.triggered.connect(self.stack_add_requested.emit)
        menu.addAction(act_stack_add)

        self.act_stack_analyze = QAction("Analyze stack (0)", menu)
        self.act_stack_analyze.triggered.connect(self.stack_analyze_requested.emit)
        self.act_stack_analyze.setEnabled(False)
        menu.addAction(self.act_stack_analyze)

        menu.addSeparator()

        act_watch = QAction("Watch a region…", menu)
        act_watch.triggered.connect(self.watch_requested.emit)
        menu.addAction(act_watch)

        act_history = QAction("History…", menu)
        act_history.triggered.connect(self.history_requested.emit)
        menu.addAction(act_history)

        menu.addSeparator()

        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(act_settings)

        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self._prev_hwnd: int = 0

        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activate)

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            # Capture before context menu steals foreground
            self._prev_hwnd = ctypes.windll.user32.GetForegroundWindow()
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.snip_requested.emit()

    def set_stack_count(self, n: int) -> None:
        self.act_stack_analyze.setText(f"Analyze stack ({n})")
        self.act_stack_analyze.setEnabled(n > 0)

    def show(self) -> None:
        self.icon.show()

    def notify(self, title: str, msg: str) -> None:
        self.icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)
