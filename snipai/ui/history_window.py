"""History browser — searchable list of past snips. Frameless dark window.

Click a row to view its full answer. Reuses the app's dark aesthetic.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QFrame, QGraphicsDropShadowEffect,
)

from .. import store
from ..config import config
from .theme import get_link_color

log = logging.getLogger(__name__)

LINK_COLOR = get_link_color(config.THEME)


def _ago(ts: float) -> str:
    d = max(0, int(time.time() - ts))
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


class HistoryWindow(QWidget):
    closed = Signal()

    DEFAULT_SIZE = QSize(720, 560)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[store.SnipRecord] = []

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(self.DEFAULT_SIZE)

        self._build_ui()
        self._center()
        self._reload()

    def _build_ui(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))

        self.setStyleSheet(f"""
            QWidget#root {{
                background: #0f1117;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
            }}
            QWidget#header {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #161b27, stop:1 #131722);
                border-top-left-radius: 16px; border-top-right-radius: 16px;
                border-bottom: 1px solid rgba(255,255,255,0.06);
            }}
            QLabel {{ color: #e2e8f0; }}
            QLabel#title {{ font-weight: 700; font-size: 12pt; color: #fff; }}
            QLabel#subtitle {{ color:#8b9aff; font-size:8pt; font-weight:700; letter-spacing:1.5px; }}
            QLineEdit#search {{
                background:#161d2c; color:#e8eaf0;
                border:1px solid rgba(255,255,255,0.08); border-radius:10px;
                padding:8px 14px; font-size:10.5pt; font-family:'Segoe UI',sans-serif;
            }}
            QLineEdit#search:focus {{ border:1px solid rgba(100,130,255,0.5); }}
            QListWidget {{
                background:#0b0d12; color:#e2e8f0;
                border:1px solid rgba(255,255,255,0.06); border-radius:10px;
                padding:4px; font-family:'Segoe UI',sans-serif; font-size:10pt;
                outline:0;
            }}
            QListWidget::item {{ padding:9px 10px; border-radius:8px; }}
            QListWidget::item:selected {{ background:rgba(91,106,255,0.25); color:#fff; }}
            QListWidget::item:hover {{ background:rgba(255,255,255,0.05); }}
            QTextBrowser {{
                background:#0b0d12; color:#e2e8f0;
                border:1px solid rgba(255,255,255,0.06); border-radius:10px;
                padding:14px 16px; font-family:'Segoe UI',sans-serif; font-size:10.5pt;
            }}
            QPushButton {{
                background:rgba(255,255,255,0.05); color:#b0b6c6;
                border:1px solid rgba(255,255,255,0.08); border-radius:10px;
                padding:7px 14px; font-size:9.5pt; font-weight:500;
            }}
            QPushButton:hover {{ background:rgba(255,255,255,0.1); color:#e2e8f0; }}
            QPushButton#close_btn {{ background:transparent; border:none; color:#5a6070; font-size:14pt; }}
            QPushButton#close_btn:hover {{ color:#ff6b6b; }}
            QPushButton#danger:hover {{ color:#ff6b6b; border-color:rgba(255,107,107,0.4); }}
            QFrame#sep {{ background:rgba(255,255,255,0.06); max-height:1px; }}
            QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
            QScrollBar::handle:vertical {{ background:rgba(255,255,255,0.12); border-radius:4px; min-height:30px; }}
            QScrollBar::handle:vertical:hover {{ background:rgba(255,255,255,0.22); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)

        from PySide6.QtWidgets import QVBoxLayout as _V
        outer = _V(self)
        outer.setContentsMargins(12, 12, 12, 12)
        root = QWidget(self, objectName="root")
        root.setGraphicsEffect(shadow)
        outer.addWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        header = QWidget(objectName="header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 14, 14, 14)
        meta = QVBoxLayout()
        meta.setSpacing(2)
        meta.addWidget(QLabel("SNIP AI", objectName="subtitle"))
        meta.addWidget(QLabel("History", objectName="title"))
        h.addLayout(meta, 1)
        self.btn_close = QPushButton("✕", objectName="close_btn")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        h.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)
        v.addWidget(header)

        # Search row
        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 14)
        body.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit(objectName="search")
        self.search.setPlaceholderText("Search your snips...")
        self.search.textChanged.connect(self._on_search)
        search_row.addWidget(self.search, 1)
        self.btn_clear = QPushButton("Clear all", objectName="danger")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_all)
        search_row.addWidget(self.btn_clear)
        body.addLayout(search_row)

        # Split: list | detail
        split = QHBoxLayout()
        split.setSpacing(10)
        self.list = QListWidget()
        self.list.setMinimumWidth(280)
        self.list.currentRowChanged.connect(self._on_row)
        split.addWidget(self.list, 0)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        pal = self.detail.palette()
        pal.setColor(QPalette.ColorRole.Link, QColor(LINK_COLOR))
        self.detail.setPalette(pal)
        self.detail.setMarkdown("_Select a snip to view._")
        split.addWidget(self.detail, 1)
        body.addLayout(split, 1)

        v.addLayout(body)

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        x = sg.center().x() - self.width() // 2
        y = sg.center().y() - self.height() // 2
        self.move(x, y)

    def _reload(self, query: str = "") -> None:
        self._records = store.search(query) if query.strip() else store.recent()
        self.list.clear()
        for rec in self._records:
            label = (rec.question or rec.selected_text or rec.answer or "(empty)").strip()
            label = " ".join(label.split())[:60]
            item = QListWidgetItem(f"[{rec.mode}] {label}\n{_ago(rec.ts)}")
            self.list.addItem(item)
        if self._records:
            self.list.setCurrentRow(0)
        else:
            self.detail.setMarkdown("_No snips yet._" if not query else "_No matches._")

    def _on_search(self, text: str) -> None:
        self._reload(text)

    def _on_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._records):
            return
        rec = self._records[idx]
        parts = []
        if rec.selected_text:
            parts.append(f"**Selection:**\n\n> {rec.selected_text[:500]}\n")
        if rec.question:
            parts.append(f"**Question:** {rec.question}\n")
        parts.append("---\n")
        parts.append(rec.answer or "_(no answer)_")
        self.detail.setMarkdown("\n".join(parts))

    def _clear_all(self) -> None:
        store.clear_all()
        self._reload()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
