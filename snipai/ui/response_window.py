"""Floating chat popup — production chat UI (Claude/ChatGPT style).

Frameless, draggable, always-on-top, rounded.
Per-turn message rows with role labels/avatars, streaming into the active row.
Auto-send on open: cropped image + dynamic default prompt fired immediately.
"""
from __future__ import annotations
import logging
import re
import time
from PySide6.QtCore import (
    Qt, QPoint, QRect, Signal, Slot, QSize, QTimer,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QGuiApplication, QMouseEvent, QPixmap, QImage, QClipboard, QKeyEvent,
    QColor, QPainter, QPalette, QCursor,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QPushButton,
    QApplication, QFrame, QGraphicsDropShadowEffect, QTextEdit,
    QComboBox, QScrollArea, QCheckBox, QMenu, QSizePolicy, QSizeGrip,
    QStackedWidget,
)

from ..api.worker import (
    GeminiWorker, build_initial_messages, build_text_messages,
    build_stack_messages, SYSTEM_PROMPT,
)
from ..ai.models import get_cached_records, ModelsFetcher, get_active_provider_ids, pick_random_free_vision_across_active, collect_free_vision_across_active
from ..ai import modes as prompt_modes
from ..ai.actions import extract_actions, Action
from .. import store
from ..config import config
from .theme import generate_stylesheet, get_link_color
from .markdown import markdown_to_html
from .inline_settings import InlineSettingsWidget
from .icons import lucide_icon, lucide_pixmap, set_button_lucide_icon

log = logging.getLogger(__name__)


AUTO_PROMPT = (
    "Analyze this selection. "
    "If it contains text or code, explain what it says or does and surface anything useful "
    "(definitions, errors, summary, key takeaways). "
    "If it's an image, UI, chart, or diagram, describe what's shown and what it means. "
    "Be concise and use Markdown."
)

LINK_COLOR = get_link_color(config.THEME)


class _ThinkingDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0
        self.setFixedSize(40, 16)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)

    def _tick(self):
        self._phase = (self._phase + 1) % 4
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(3):
            alpha = 255 if (self._phase % 4) == i else 80
            if self._phase == 3:
                alpha = 80
            p.setBrush(QColor(130, 160, 255, alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(i * 14 + 4, 4, 8, 8)
        p.end()


class _ChatInput(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Ask a follow-up...")
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setFixedHeight(48)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(e)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class _MessageRow(QFrame):
    """One conversation turn: avatar column + (name/time, body, actions). Auto-sizes."""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role  # "user" | "assistant"
        self.setObjectName("user_row" if role == "user" else "assistant_row")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(12)

        # ── Avatar column ────────────────────────────────────
        self.avatar = QLabel()
        self.avatar.setFixedSize(32, 32)
        self.avatar.setObjectName("row_avatar_user" if role == "user" else "row_avatar_ai")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _av_pix = lucide_pixmap("user" if role == "user" else "sparkles", 16, "#ffffff")
        if _av_pix is not None and not _av_pix.isNull():
            self.avatar.setPixmap(_av_pix)
        else:
            self.avatar.setText("AD" if role == "user" else "✦")
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        col.addStretch(1)
        lay.addLayout(col, 0)

        # ── Content column ───────────────────────────────────
        content = QVBoxLayout()
        content.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel("You" if role == "user" else "Snip AI")
        name.setObjectName("row_name")
        head.addWidget(name, 0)
        ts = QLabel()
        try:
            ts.setText(time.strftime("%I:%M %p").lstrip("0"))
        except Exception:
            ts.setText("")
        ts.setObjectName("row_time")
        head.addWidget(ts, 0)
        head.addStretch(1)
        content.addLayout(head)

        # ── Markdown body ─────────────────────────────────────
        self.browser = QTextBrowser()
        self.browser.setObjectName("bubble_body")
        self.browser.setOpenExternalLinks(True)
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setSizePolicy(self.browser.sizePolicy().horizontalPolicy(),
                                   self.browser.sizePolicy().Policy.Fixed)
        pal = self.browser.palette()
        pal.setColor(QPalette.ColorRole.Link, QColor(LINK_COLOR))
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        self.browser.setPalette(pal)
        content.addWidget(self.browser)

        # ── Inline actions bar (assistant only) ──────────────
        self.actions = None
        if role == "assistant":
            self.actions = self._build_actions()
            content.addWidget(self.actions)

        lay.addLayout(content, 1)

    def _build_actions(self) -> QWidget:
        bar = QWidget(objectName="msg_actions")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(4)
        for name, tip in (("copy", "Copy"), ("thumbs-up", "Good"), ("thumbs-down", "Bad"), ("volume-2", "Speak"), ("ellipsis", "More")):
            b = QPushButton(objectName="msg_action_btn")
            set_button_lucide_icon(b, name, 15, "#9a9a9a")
            if b.icon().isNull():
                fallback = {"copy": "⧉", "thumbs-up": "👍", "thumbs-down": "👎", "volume-2": "🔊", "ellipsis": "⋯"}[name]
                b.setText(fallback)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setMinimumHeight(28)
            b.setMinimumWidth(32)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            h.addWidget(b, 0)
            if tip == "Copy":
                b.clicked.connect(self._copy_self)
            elif tip == "Good":
                b.clicked.connect(lambda _=False, btn=b: self._on_feedback(btn, True))
            elif tip == "Bad":
                b.clicked.connect(lambda _=False, btn=b: self._on_feedback(btn, False))
            elif tip == "Speak":
                b.clicked.connect(self._speak_self)
            elif tip == "More":
                b.clicked.connect(self._show_more_menu)
        h.addStretch(1)
        export = QPushButton("Export  ▾", objectName="export_btn")
        set_button_lucide_icon(export, "download", 12, "#ececec")
        export.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = QMenu(export)
        for label in ("Copy as Markdown", "Copy as Text", "Save to file"):
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, lbl=label: self._on_export(lbl))
        export.setMenu(menu)
        h.addWidget(export, 0)
        return bar

    def _copy_self(self) -> None:
        QApplication.clipboard().setText(self._raw_md)
        # Visual feedback — briefly highlight
        try:
            from PySide6.QtCore import QTimer
            # Find the copy button and flash it
            for child in self.findChildren(QPushButton):
                if child.toolTip() == "Copy":
                    orig = child.styleSheet()
                    child.setStyleSheet(orig + " background: rgba(91,106,255,0.25); color: #ffffff;")
                    QTimer.singleShot(600, lambda c=child, s=orig: c.setStyleSheet(s))
                    break
        except Exception:
            pass

    def _on_feedback(self, btn: QPushButton, is_good: bool) -> None:
        # Toggle visual state and show toast via parent window status
        try:
            # Reset siblings
            for sibling in self.findChildren(QPushButton):
                if sibling.toolTip() in ("Good", "Bad"):
                    sibling.setStyleSheet("")
            # Highlight selected
            btn.setStyleSheet("background: rgba(91,106,255,0.20); color: #ffffff; border: 1px solid rgba(91,106,255,0.35);")
            # Find parent ResponseWindow and show status
            parent = self
            while parent and not hasattr(parent, "_status_label"):
                parent = parent.parent()
            if parent and hasattr(parent, "_status_label"):
                parent._status_bar.show()
                parent._status_label.setText("Thanks for your feedback!" if is_good else "Thanks — we'll improve.")
                parent._status_label.setStyleSheet("color: #4ade80;" if is_good else "color: #fbbf24;")
        except Exception:
            pass

    def _speak_self(self) -> None:
        # Text-to-speech via QTextToSpeech if available
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            engine = QTextToSpeech()
            # Strip markdown for speaking
            text = re.sub(r"[*_`#\[\]\(\)]", "", self._raw_md)[:4000]
            engine.say(text)
        except Exception:
            try:
                # Fallback: copy to clipboard and notify
                QApplication.clipboard().setText(self._raw_md)
                parent = self
                while parent and not hasattr(parent, "_status_label"):
                    parent = parent.parent()
                if parent:
                    parent._status_bar.show()
                    parent._status_label.setText("Copied for speech — TTS not available")
            except Exception:
                pass

    def _show_more_menu(self) -> None:
        # Show export menu as fallback for More
        try:
            for child in self.findChildren(QPushButton):
                if child.toolTip() == "More":
                    # Find export button in same bar and show its menu
                    bar = child.parent()
                    if bar:
                        for btn in bar.findChildren(QPushButton):
                            if btn.objectName() == "export_btn" and btn.menu():
                                btn.menu().popup(QCursor.pos())
                                return
                    break
            # Fallback: simple menu
            m = QMenu(self)
            for label in ("Copy as Markdown", "Report issue"):
                m.addAction(label)
            m.exec(QCursor.pos())
        except Exception:
            pass

    def _on_export(self, label: str) -> None:
        try:
            if label == "Copy as Markdown":
                QApplication.clipboard().setText(self._raw_md)
            elif label == "Copy as Text":
                import re as _re
                txt = _re.sub(r"[*_`#\[\]]", "", self._raw_md)
                QApplication.clipboard().setText(txt)
            elif label == "Save to file":
                from PySide6.QtWidgets import QFileDialog
                path, _ = QFileDialog.getSaveFileName(self, "Save", "snipai.md", "Markdown (*.md);;Text (*.txt)")
                if path:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(self._raw_md)
        except Exception:
            pass

    def set_markdown(self, md: str) -> None:
        self._raw_md = md
        self.browser.setHtml(markdown_to_html(md))
        self.fit_height()

    _raw_md: str = ""

    def fit_height(self) -> None:
        vw = self.browser.viewport().width()
        if vw <= 0:
            vw = max(self.width() - 80, 200)
        doc = self.browser.document()
        doc.setTextWidth(vw)
        h = int(doc.size().height()) + 6
        self.browser.setFixedHeight(max(h, 24))


class ResponseWindow(QWidget):
    closed = Signal()

    DEFAULT_SIZE = QSize(1020, 850)
    COMPACT_SIZE = QSize(480, 620)
    EXPANDED_SIZE = QSize(1020, 850)
    THUMB_MAX = 64

    def __init__(self, anchor: QRect, png: bytes | None = None,
                 selected_text: str | None = None, mode: str | None = None,
                 stack_items: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._png = png
        self._selected_text = (selected_text or "").strip()
        self._stack_items = stack_items or []
        self._stack_mode = bool(self._stack_items)
        self._text_mode = bool(self._selected_text) and not self._stack_mode
        self._mode_key = mode or prompt_modes.DEFAULT_MODE
        self._messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._first_turn_sent = False
        self._current_buf: str = ""
        self._last_assistant: str = ""
        self._active_row: _MessageRow | None = None
        self._rows: list[_MessageRow] = []
        self._action_bar: QWidget | None = None
        self._drag_offset: QPoint | None = None
        self._worker: GeminiWorker | None = None
        self._models_fetcher: ModelsFetcher | None = None
        self._current_model: str = config.MODEL
        self._model_records: list[dict] = []
        self._free_only: bool = True

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._do_render)
        self._dirty = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(QSize(380, 420))
        # Compact by default: small chat widget; expand button reveals full layout
        self._is_expanded: bool = False
        self._anchor_rect: QRect = QRect(anchor)
        self._compact_size: QSize = QSize(self.COMPACT_SIZE)
        self._expanded_size: QSize = QSize(self.EXPANDED_SIZE)
        self._geom_anim: QPropertyAnimation | None = None
        self.resize(self._compact_size)
        self.setMouseTracking(True)

        # Edge-drag resize state
        self._resize_edge: str = ""
        self._resize_start_geo: QRect | None = None
        self._resize_start_mouse: QPoint | None = None
        self._RESIZE_MARGIN = 8

        self._build_ui(png)
        # Compact: sidebar hidden, ChatGPT-like centered feed
        if hasattr(self, "_sidebar"):
            self._sidebar.setVisible(False)
        self._apply_compact_header(False)
        self._position_compact_near_anchor()
        self._populate_models()
        QTimer.singleShot(0, self._auto_send)

    def _build_ui(self, png: bytes) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))

        self.setStyleSheet(generate_stylesheet(config.THEME))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        root = QWidget(self, objectName="root")
        root.setGraphicsEffect(shadow)
        root.setMouseTracking(True)
        outer.addWidget(root)
        self._root = root

        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        root_lay.addWidget(self._build_sidebar(), 0)
        root_lay.addWidget(self._build_chat_area(png), 1)

    # ── Sidebar ─────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(objectName="sidebar")
        sidebar.setFixedWidth(260)
        self._sidebar = sidebar
        s = QVBoxLayout(sidebar)
        s.setContentsMargins(14, 16, 14, 14)
        s.setSpacing(12)

        # Brand row — Lucide sparkles
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel(objectName="brand_logo")
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _pix = lucide_pixmap("sparkles", 18, "#ffffff")
        if _pix is not None and not _pix.isNull():
            logo.setPixmap(_pix)
        else:
            logo.setText("✦")
        brand.addWidget(logo, 0)
        brand.addWidget(QLabel("Snip AI", objectName="brand_title"), 0)
        brand.addStretch(1)
        compose = QPushButton(objectName="compose_btn")
        compose.setFixedSize(32, 32)
        compose.setCursor(Qt.CursorShape.PointingHandCursor)
        compose.setToolTip("New chat")
        set_button_lucide_icon(compose, "square-pen", 16, "#ececec")
        if compose.icon().isNull():
            compose.setText("✎")
        compose.clicked.connect(self._new_chat)
        brand.addWidget(compose, 0)
        s.addLayout(brand)

        # + New Chat button
        new_chat = QPushButton("  +   New Chat", objectName="new_chat_btn")
        new_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        new_chat.setMinimumHeight(42)
        new_chat.clicked.connect(self._new_chat)
        nc_lay = QHBoxLayout(new_chat)
        nc_lay.setContentsMargins(0, 0, 12, 0)
        nc_lay.addStretch(1)
        keycap = QLabel("Ctrl+K", objectName="keycap")
        nc_lay.addWidget(keycap, 0)
        s.addWidget(new_chat)

        # History (scrollable, grouped)
        hist_scroll = QScrollArea(objectName="feed_scroll")
        hist_scroll.setWidgetResizable(True)
        hist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._hist_container = QWidget()
        self._hist_layout = QVBoxLayout(self._hist_container)
        self._hist_layout.setContentsMargins(0, 0, 0, 0)
        self._hist_layout.setSpacing(4)
        self._build_history()
        hist_scroll.setWidget(self._hist_container)
        s.addWidget(hist_scroll, 1)

        # Footer buttons — Lucide: moon/shield/settings (all responsive)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        for name, tip, slot in (
            ("moon", "Light / Dark mode", self._toggle_theme_mode),
            ("shield", "Documentation", self._open_docs),
            ("settings", "Settings", self._show_inline_settings),
        ):
            b = QPushButton(objectName="footer_btn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.setMinimumSize(36, 32)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            set_button_lucide_icon(b, name, 16, "#9a9a9a")
            if b.icon().isNull():
                fallback = {"moon": "☾", "shield": "⛉", "settings": "⚙"}[name]
                b.setText(fallback)
            if slot:
                b.clicked.connect(slot)
            # Hover feedback via stylesheet already, plus size policy makes it responsive
            footer.addWidget(b, 0)
        footer.addStretch(1)
        s.addLayout(footer)
        return sidebar

    # ── Chat area ───────────────────────────────────────────
    def _build_chat_area(self, png: bytes) -> QWidget:
        area = QWidget(objectName="chat_area")
        v = QVBoxLayout(area)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._chat_stack = QStackedWidget()
        v.addWidget(self._chat_stack, 1)

        chat_page = QWidget(objectName="chat_page")
        pv = QVBoxLayout(chat_page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        # ── Header (dropdown bar) ──────────────────────────
        self.header = QWidget(objectName="header")
        h = QHBoxLayout(self.header)
        h.setContentsMargins(18, 12, 14, 12)
        h.setSpacing(10)

        self.thumb = QLabel(objectName="thumb")
        self.thumb.setFixedSize(40, 40)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._stack_mode:
            self._set_glyph_thumb(f"{len(self._stack_items)}")
        elif self._text_mode:
            self._set_text_thumb()
        else:
            self._set_thumb(png)
        h.addWidget(self.thumb, 0)

        self.header_title = QLabel("Snip AI", objectName="header_title")
        self.header_title.setStyleSheet(
            "color:#ffffff; font-size:11pt; font-weight:700; "
            "font-family:'Inter','Segoe UI',sans-serif; letter-spacing:-0.2px;"
        )
        h.addWidget(self.header_title, 0)

        self.mode_select = QComboBox()
        self.mode_select.setObjectName("mode_select")
        self.mode_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_select.setToolTip("Response mode")
        for key in prompt_modes.ORDER:
            self.mode_select.addItem("✦  " + prompt_modes.get_mode(key).label, key)
        idx = self.mode_select.findData(self._mode_key)
        if idx >= 0:
            self.mode_select.setCurrentIndex(idx)
        self.mode_select.currentIndexChanged.connect(self._on_mode_changed)
        h.addWidget(self.mode_select, 0)

        self.model_select = QComboBox()
        self.model_select.setObjectName("model_select")
        self.model_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_select.setMinimumWidth(170)
        self.model_select.setMaximumWidth(240)
        self.model_select.addItem("∞  " + self._current_model)
        self.model_select.currentTextChanged.connect(self._on_model_changed)
        h.addWidget(self.model_select, 0)

        self.provider_badge = QLabel("")
        self.provider_badge.setObjectName("provider_badge")
        self.provider_badge.setStyleSheet(
            "color: #8b9aff; font-size: 8pt; font-weight: 700; "
            "padding: 2px 8px; border-radius: 999px; "
            "background: rgba(91,106,255,0.15); border: 1px solid rgba(91,106,255,0.3);"
        )
        self.provider_badge.setVisible(False)
        self.provider_badge.setToolTip("Active provider (auto-rotates on failure)")
        h.addWidget(self.provider_badge, 0)

        h.addStretch(1)

        self.free_only_check = QCheckBox("Free only")
        self.free_only_check.setObjectName("free_only_check")
        self.free_only_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.free_only_check.setChecked(self._free_only)
        self.free_only_check.setToolTip("Auto-pick a free, vision-capable model from this provider.")
        self.free_only_check.toggled.connect(self._on_free_only_toggled)
        h.addWidget(self.free_only_check, 0)

        self.btn_switch = QPushButton(objectName="switch_btn")
        self.btn_switch.setFixedSize(32, 32)
        self.btn_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_switch.setToolTip("Switch to another free model — picks random free across all Active providers (Groq/NVIDIA/OpenRouter)")
        set_button_lucide_icon(self.btn_switch, "refresh-cw", 16, "#9a9a9a")
        if self.btn_switch.icon().isNull():
            self.btn_switch.setText("🔄")
        self.btn_switch.clicked.connect(self._switch_to_random_free_model)
        h.addWidget(self.btn_switch, 0)

        self.btn_expand = QPushButton(objectName="expand_btn")
        self.btn_expand.setFixedSize(32, 32)
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setToolTip("Expand to full view")
        set_button_lucide_icon(self.btn_expand, "maximize-2", 16, "#9a9a9a")
        if self.btn_expand.icon().isNull():
            self.btn_expand.setText("⛶")
        self.btn_expand.clicked.connect(self._toggle_expand)
        h.addWidget(self.btn_expand, 0)

        self.btn_close = QPushButton(objectName="close_btn")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_lucide_icon(self.btn_close, "x", 16, "#9a9a9a")
        if self.btn_close.icon().isNull():
            self.btn_close.setText("✕")
        self.btn_close.clicked.connect(self.close)
        h.addWidget(self.btn_close, 0)
        pv.addWidget(self.header)

        # ── Feed (scrollable message rows) ─────────────────
        self.feed_scroll = QScrollArea(objectName="feed_scroll")
        self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feed = QWidget(objectName="feed")
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(0)
        self.feed_layout.addStretch(1)
        self.feed_scroll.setWidget(self.feed)
        pv.addWidget(self.feed_scroll, 1)

        # ── Thinking indicator ─────────────────────────────
        self._thinking_bar = QWidget()
        tb_layout = QHBoxLayout(self._thinking_bar)
        tb_layout.setContentsMargins(20, 4, 20, 4)
        tb_layout.setSpacing(8)
        self._dots = _ThinkingDots()
        tb_layout.addWidget(self._dots)
        self._thinking_label = QLabel("Analyzing...")
        self._thinking_label.setStyleSheet("color: #ececec; font-size: 9pt; font-weight: 600; font-family:'Inter','Segoe UI',sans-serif;")
        tb_layout.addWidget(self._thinking_label)
        tb_layout.addStretch(1)
        pv.addWidget(self._thinking_bar)
        self._thinking_bar.hide()

        # ── Status bar ──────────────────────────────────────
        self._status_bar = QWidget()
        sb_layout = QHBoxLayout(self._status_bar)
        sb_layout.setContentsMargins(20, 4, 20, 4)
        self._status_label = QLabel("", objectName="status")
        sb_layout.addWidget(self._status_label)
        sb_layout.addStretch(1)
        pv.addWidget(self._status_bar)
        self._status_bar.hide()

        # ── Text-mode option cards (shown before first processing) ──
        self._text_options_bar = QWidget(objectName="text_options_bar")
        ob_lay = QHBoxLayout(self._text_options_bar)
        ob_lay.setContentsMargins(20, 8, 20, 8)
        ob_lay.setSpacing(10)
        self._text_option_buttons: list[QPushButton] = []
        options = [
            ("book-open", "Explain the word meaning", "explain_word"),
            ("file-text", "Explain the text in depth", "explain_in_depth"),
            ("search", "Search", "search"),
        ]
        for icon_name, label, key in options:
            btn = QPushButton(f"  {label}", objectName="text_option_card")
            set_button_lucide_icon(btn, icon_name, 16, "#ececec")
            if btn.icon().isNull():
                fallback = {"book-open": "📖", "file-text": "📄", "search": "🌐"}[icon_name]
                btn.setText(f"{fallback}  {label}")
            else:
                btn.setText(f"  {label}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(42)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _=False, k=key: self._on_text_option_selected(k))
            # Card styling — ChatGPT-like pill, matches input_container
            btn.setStyleSheet(
                "QPushButton#text_option_card {"
                " background: #2f2f2f; color: #ececec; border: 1px solid #3a3a3a;"
                " border-radius: 12px; padding: 10px 12px; font-size: 9pt; font-weight: 600;"
                " font-family: 'Inter','Segoe UI',sans-serif; text-align: left;"
                "}"
                "QPushButton#text_option_card:hover { background: #3a3a3a; border-color: #4a4a4a; }"
                "QPushButton#text_option_card:pressed { background: #404040; }"
            )
            ob_lay.addWidget(btn, 1)
            self._text_option_buttons.append(btn)
        pv.addWidget(self._text_options_bar)
        self._text_options_bar.hide()

        # ── Rate limit bar (shown on 429) ─────────────────
        self._rate_limit_bar = QWidget(objectName="rate_limit_bar")
        rl_lay = QHBoxLayout(self._rate_limit_bar)
        rl_lay.setContentsMargins(14, 10, 14, 10)
        rl_lay.setSpacing(10)
        self._rate_limit_label = QLabel("Rate limit reached — try another free model", objectName="rate_limit_label")
        self._rate_limit_label.setWordWrap(True)
        rl_lay.addWidget(self._rate_limit_label, 1)
        self._rate_limit_btn = QPushButton(" Switch model", objectName="rate_limit_btn")
        set_button_lucide_icon(self._rate_limit_btn, "refresh-cw", 14, "#ffffff")
        if self._rate_limit_btn.icon().isNull():
            self._rate_limit_btn.setText("🔄 Switch model")
        else:
            self._rate_limit_btn.setText(" Switch model")
        self._rate_limit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rate_limit_btn.setToolTip("Pick a random free model from all Active providers and retry")
        self._rate_limit_btn.clicked.connect(self._on_rate_limit_retry)
        rl_lay.addWidget(self._rate_limit_btn, 0)
        pv.addWidget(self._rate_limit_bar)
        self._rate_limit_bar.hide()

        # ── Input container ────────────────────────────────
        input_wrap = QWidget()
        iw = QVBoxLayout(input_wrap)
        iw.setContentsMargins(20, 6, 20, 6)
        iw.setSpacing(6)

        container = QFrame(objectName="input_container")
        cv = QVBoxLayout(container)
        cv.setContentsMargins(14, 10, 10, 8)
        cv.setSpacing(4)

        self.chat_input = _ChatInput()
        self.chat_input.setObjectName("chat_input")
        self.chat_input.submitted.connect(self._on_send)
        cv.addWidget(self.chat_input)

        bar = QHBoxLayout()
        bar.setSpacing(4)

        btn_web = QPushButton(objectName="input_tool")
        btn_web.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_web.setToolTip("Web search")
        btn_web.setFixedSize(32, 32)
        set_button_lucide_icon(btn_web, "globe", 16, "#9a9a9a")
        if btn_web.icon().isNull():
            btn_web.setText("🌐")
        bar.addWidget(btn_web, 0)

        btn_attach = QPushButton(objectName="input_tool")
        set_button_lucide_icon(btn_attach, "paperclip", 16, "#9a9a9a")
        if btn_attach.icon().isNull():
            btn_attach.setText("📎")
        btn_attach.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_attach.setToolTip("Attach image")
        btn_attach.setFixedSize(32, 32)
        btn_attach.clicked.connect(self._on_attach)
        bar.addWidget(btn_attach, 0)

        bar.addStretch(1)
        self.btn_send = QPushButton(objectName="send_btn")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setFixedSize(34, 34)
        set_button_lucide_icon(self.btn_send, "send", 16, "#000000")
        if self.btn_send.icon().isNull():
            self.btn_send.setText("➤")
        self.btn_send.clicked.connect(self._on_send)
        bar.addWidget(self.btn_send, 0)
        cv.addLayout(bar)
        iw.addWidget(container)

        disclaimer = QLabel(
            "Snip AI can make mistakes. Verify important information.",
            objectName="disclaimer",
        )
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        iw.addWidget(disclaimer)
        pv.addWidget(input_wrap)

        self._chat_stack.addWidget(chat_page)
        # — Inline settings page (embedded, no separate window) —
        self._inline_settings = InlineSettingsWidget()
        self._inline_settings.closed.connect(self._hide_inline_settings)
        self._inline_settings.saved.connect(self._on_inline_settings_saved)
        self._chat_stack.addWidget(self._inline_settings)
        self._chat_stack.setCurrentIndex(0)
        return area

    # ── Sidebar history ─────────────────────────────────────
    def _build_history(self) -> None:
        from datetime import date
        while self._hist_layout.count():
            item = self._hist_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        recs = store.recent(15)
        if not recs:
            self._hist_layout.addWidget(QLabel("No history yet", objectName="hist_header"))
            self._hist_layout.addStretch(1)
            return

        today = date.today()
        order = ["Today", "Yesterday", "Previous 7 Days", "Older"]
        buckets: dict[str, list] = {name: [] for name in order}
        for rec in recs:
            try:
                delta = (today - date.fromtimestamp(rec.ts)).days
            except Exception:
                delta = 999
            if delta <= 0:
                buckets["Today"].append(rec)
            elif delta == 1:
                buckets["Yesterday"].append(rec)
            elif delta <= 7:
                buckets["Previous 7 Days"].append(rec)
            else:
                buckets["Older"].append(rec)

        for name in order:
            lst = buckets[name]
            if not lst:
                continue
            self._hist_layout.addWidget(QLabel(name.upper(), objectName="hist_header"))
            for rec in lst:
                raw = (rec.question or rec.selected_text or rec.answer or "Untitled")
                label = raw.strip().replace("\n", " ")
                if len(label) > 34:
                    label = label[:34] + "…"
                btn = QPushButton(label, objectName="hist_item")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip(raw.strip()[:200])
                btn.clicked.connect(lambda _=False, r=rec: self._load_history_item(r))
                self._hist_layout.addWidget(btn)
        self._hist_layout.addStretch(1)

    def _reset_feed(self) -> None:
        for row in self._rows:
            self.feed_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        self._clear_actions()
        self._active_row = None
        self._current_buf = ""
        self._thinking_bar.hide()
        self._status_bar.hide()
        self._hide_text_options()
        if hasattr(self, "_rate_limit_bar"):
            self._rate_limit_bar.hide()
        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)

    def _new_chat(self) -> None:
        if self._worker is not None:
            return
        self._reset_feed()
        self._last_assistant = ""
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._first_turn_sent = True  # don't auto-resend the original crop
        self.chat_input.setFocus()

    def _load_history_item(self, rec) -> None:
        if self._worker is not None:
            return
        self._reset_feed()
        q = (rec.question or rec.selected_text or "").strip()
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if q:
            self._add_row("user", q)
            self._messages.append({"role": "user", "content": q})
        if rec.answer:
            self._add_row("assistant", rec.answer)
            self._messages.append({"role": "assistant", "content": rec.answer})
            self._last_assistant = rec.answer
        self._first_turn_sent = True
        self.chat_input.setFocus()

    def _open_settings(self) -> None:
        self._show_inline_settings()

    def _show_inline_settings(self) -> None:
        # Ensure expanded so settings has room; compact widget is too narrow
        if not getattr(self, "_is_expanded", False):
            self._toggle_expand()
            # Give animation a moment, then show settings
            QTimer.singleShot(280, self._do_show_inline_settings)
        else:
            self._do_show_inline_settings()

    def _do_show_inline_settings(self) -> None:
        try:
            self._inline_settings.refresh()
        except Exception:
            pass
        self._chat_stack.setCurrentWidget(self._inline_settings)

    def _hide_inline_settings(self) -> None:
        self._chat_stack.setCurrentIndex(0)
        self.chat_input.setFocus()

    def _on_inline_settings_saved(self) -> None:
        # Re-apply theme after save (accent may have changed)
        try:
            from ..config import load_config
            cfg = load_config()
            self.setStyleSheet(generate_stylesheet(cfg.theme))
            self._inline_settings._apply_theme()
            # Update link color for browsers if needed
        except Exception:
            pass
        self._chat_stack.setCurrentIndex(0)
        self._status_bar.show()
        self._status_label.setText("Settings saved — hotkeys need restart")
        self._status_label.setStyleSheet("")
        self.chat_input.setFocus()

    def _toggle_theme_mode(self) -> None:
        """Footer moon — toggle Dark/Light (Midnight ↔ Light preset)."""
        try:
            from .setup_wizard import THEME_PRESETS
            from ..config import ThemeConfig, save_config, load_config
            cfg = load_config()
            is_light = cfg.theme.bg_primary.lower() == "#ffffff"
            new_preset = THEME_PRESETS["Midnight"] if is_light else THEME_PRESETS["Light"]
            new_theme = ThemeConfig(**new_preset)
            cfg.theme = new_theme
            save_config(cfg)
            self.setStyleSheet(generate_stylesheet(new_theme))
            if hasattr(self, "_inline_settings"):
                try:
                    self._inline_settings._cfg.theme = new_theme
                    self._inline_settings._apply_theme()
                except Exception:
                    pass
            # Update footer moon icon to sun when dark, moon when light for next toggle
            # Find the moon button and swap its icon
            for child in self.findChildren(QPushButton):
                if child.toolTip() == "Light / Dark mode":
                    new_icon = "sun" if not is_light else "moon"
                    # is_light was true → was light, now switching to Midnight (dark) → show moon next? Actually toggle, so after switch to dark, next should be sun
                    icon_name = "sun" if not is_light else "moon"
                    # We are now in dark if we just switched from light, so show sun for next
                    set_button_lucide_icon(child, icon_name, 16, "#9a9a9a")
                    break
            self._status_bar.show()
            self._status_label.setText("Theme: Dark" if not is_light else "Theme: Light")
            self._status_label.setStyleSheet("color: #4ade80;")
        except Exception as e:
            log.warning("Theme toggle failed: %s", e)

    def _open_docs(self) -> None:
        try:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl("https://github.com/Rana3112/snipai"))
            self._status_bar.show()
            self._status_label.setText("Opening docs — github.com/Rana3112/snipai")
        except Exception:
            pass

    def _switch_to_random_free_model(self) -> None:
        """Header 🔄 — pick random free across all Active and switch."""
        if hasattr(self, "_rate_limit_bar"):
            self._rate_limit_bar.hide()
        rnd = pick_random_free_vision_across_active(blocked_models={self._current_model})
        if not rnd:
            rnd = pick_random_free_vision_across_active()
        if not rnd:
            self._status_bar.show()
            self._status_label.setText("No other free models available — add API keys in Settings")
            self._status_label.setStyleSheet("color: #fca5a5;")
            return
        pid, rec = rnd
        new_model = rec["id"]
        found = False
        for i, m in enumerate(self._model_records):
            if m["id"] == new_model:
                self.model_select.blockSignals(True)
                self.model_select.setCurrentIndex(i)
                self.model_select.blockSignals(False)
                found = True
                break
        if not found:
            self.model_select.blockSignals(True)
            self.model_select.addItem(f"{rec.get('name') or new_model}  ·  ★ Free")
            self.model_select.setCurrentIndex(self.model_select.count() - 1)
            self.model_select.blockSignals(False)
            self._model_records.append(rec)
        self._current_model = new_model
        self.model_select.setToolTip(f"Model: {new_model} (switched)")
        self.provider_badge.setText(pid.replace("custom:", "Custom · "))
        self.provider_badge.setVisible(True)
        self._status_bar.show()
        self._status_label.setText(f"Switched to {pid}/{new_model} — free")
        self._status_label.setStyleSheet("color: #4ade80;")
        log.info("manual switch to %s/%s", pid, new_model)

    def _on_rate_limit_retry(self) -> None:
        """Rate-limit bar button — switch and retry last request."""
        if hasattr(self, "_rate_limit_bar"):
            self._rate_limit_bar.hide()
        if self._worker is not None:
            return
        rnd = pick_random_free_vision_across_active(blocked_models={self._current_model})
        if not rnd:
            rnd = pick_random_free_vision_across_active()
        if not rnd:
            self._status_label.setText("No alternative free models — add more API keys in Settings")
            self._status_bar.show()
            return
        pid, rec = rnd
        new_model = rec["id"]
        found = False
        for i, m in enumerate(self._model_records):
            if m["id"] == new_model:
                self.model_select.blockSignals(True)
                self.model_select.setCurrentIndex(i)
                self.model_select.blockSignals(False)
                found = True
                break
        if not found:
            self.model_select.blockSignals(True)
            self.model_select.addItem(f"{rec.get('name') or new_model}  ·  ★ Free")
            self.model_select.setCurrentIndex(self.model_select.count() - 1)
            self.model_select.blockSignals(False)
            self._model_records.append(rec)
        self._current_model = new_model
        self.provider_badge.setText(pid.replace("custom:", "Custom · "))
        self.provider_badge.setVisible(True)
        # Remove the error row if last assistant row is the rate-limit error
        if self._rows and self._rows[-1].role == "assistant":
            last_text = getattr(self._rows[-1], "_raw_md", "")
            if "rate limit" in last_text.lower() or "Rate limit" in last_text:
                row = self._rows.pop()
                self.feed_layout.removeWidget(row)
                row.deleteLater()
                if self._messages and self._messages[-1].get("role") == "assistant":
                    self._messages.pop()
                self._active_row = None
                self._current_buf = ""
        if not self._messages:
            self._status_label.setText("No previous request to retry")
            self._status_bar.show()
            return
        self._first_turn_sent = True
        self.chat_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self._clear_actions()
        self._current_buf = ""
        self._active_row = self._add_row("assistant", "_..._")
        self._thinking_bar.show()
        self._thinking_label.setText(f"Retrying with {pid}/{new_model}...")
        self._status_bar.hide()
        self._start_worker()

    # ── Text-mode option cards ───────────────────────────────────────
    def _show_text_options(self) -> None:
        if hasattr(self, "_text_options_bar"):
            self._text_options_bar.show()

    def _hide_text_options(self) -> None:
        if hasattr(self, "_text_options_bar"):
            self._text_options_bar.hide()

    def _on_text_option_selected(self, key: str) -> None:
        """Handle click on one of the three text-mode cards."""
        if self._worker is not None:
            return
        self._hide_text_options()
        prompts = {
            "explain_word": "Explain the meaning of the selected text. Define the word or phrase, its part of speech, etymology if relevant, usage, and provide 2-3 clear examples. Be concise and use Markdown. Use bullet lists and bold for key points. Never include <think> tags.",
            "explain_in_depth": "Explain the selected text in depth. Provide a comprehensive analysis: break down its meaning, context, significance, key points, and any nuances or implications. Use Markdown with clear sections, bullet lists (- or *), tables (| + |---|---|) for comparisons, and bold (**text**) for key takeaways. Never include <think> tags or internal reasoning.",
            "search": "Search the web for information about the selected text. Find relevant, up-to-date information including definitions, context, related links, and any recent news or references. Provide a concise summary with URLs in Markdown. Use tables for comparisons and bullets for lists. Never include <think> tags.",
        }
        prompt = prompts.get(key, "Analyze this selection. Be concise and use Markdown.")
        extra = self.chat_input.toPlainText().strip()
        if extra:
            prompt = f"{prompt}\n\nAdditional user instruction: {extra}"
            self.chat_input.clear()
        try:
            self._first_turn_sent = True
            self.chat_input.setEnabled(False)
            self.btn_send.setEnabled(False)
            self._clear_actions()
            system = self._system_for_mode()
            self._messages = build_text_messages(prompt, self._selected_text, system=system)
            self._current_buf = ""
            self._active_row = self._add_row("assistant", "_..._")
            self._thinking_bar.show()
            self._thinking_label.setText("Searching..." if key == "search" else "Thinking...")
            self._status_bar.hide()
            self._start_worker()
        except Exception:
            log.exception("text option handling failed")
            self.chat_input.setEnabled(True)
            self.btn_send.setEnabled(True)

    def showEvent(self, e):
        super().showEvent(e)
        self.chat_input.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._scale_content()
        for row in self._rows:
            row.fit_height()

    def _scale_content(self) -> None:
        """Scale sidebar width + base font with the window so content shrinks/grows."""
        w = self.width()
        sb = getattr(self, "_sidebar", None)
        # In compact widget mode we keep sidebar hidden; only expanded may show it
        if getattr(self, "_is_expanded", False):
            if sb is not None:
                if w < 700:
                    # Keep visible but narrower for mid sizes; hide only if very narrow
                    if w < 540:
                        sb.setVisible(False)
                    else:
                        sb.setVisible(True)
                        sb_w = max(200, min(300, int(w * 0.26)))
                        sb.setFixedWidth(sb_w)
                else:
                    sb.setVisible(True)
                    sb_w = max(240, min(300, int(w * 0.26)))
                    sb.setFixedWidth(sb_w)
        else:
            if sb is not None:
                sb.setVisible(False)
        # Base font scales 9pt (narrow) → 11pt (wide) across 640..1100px.
        base = 9.0 if not getattr(self, "_is_expanded", False) else 9.5
        f = max(base, min(11.0, base + (w - 640) / 230.0))
        font = self.font()
        if abs(font.pointSizeF() - f) > 0.1:
            font.setPointSizeF(f)
            self.setFont(font)

    def _apply_compact_header(self, expanded: bool) -> None:
        """Show full header controls only when expanded; compact keeps it minimal."""
        for attr in ("mode_select", "model_select", "free_only_check", "provider_badge"):
            w = getattr(self, attr, None)
            if w is not None:
                if attr == "provider_badge":
                    has_text = bool(getattr(w, "text", lambda: "")())
                    w.setVisible(expanded and has_text)
                else:
                    w.setVisible(expanded)
        if hasattr(self, "header_title"):
            self.header_title.setVisible(not expanded)
        if hasattr(self, "thumb"):
            self.thumb.setVisible(True)
            self.thumb.setFixedSize(36, 36) if not expanded else self.thumb.setFixedSize(40, 40)

    def _set_thumb(self, png: bytes) -> None:
        dpr = float(QGuiApplication.primaryScreen().devicePixelRatio()) or 1.0
        target_px = int(self.THUMB_MAX * dpr)
        img = QImage.fromData(png, "PNG")
        pix = QPixmap.fromImage(img).scaled(
            target_px, target_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pix.setDevicePixelRatio(dpr)
        self.thumb.setPixmap(pix)

    def _set_text_thumb(self) -> None:
        self._set_glyph_thumb("T")

    def _set_glyph_thumb(self, glyph: str) -> None:
        self.thumb.setText(glyph)
        size = "26pt" if len(glyph) <= 1 else "22pt"
        self.thumb.setStyleSheet(
            f"color:#8b9aff; font-size:{size}; font-weight:800;"
            "background:#0b0d12; border:1px solid rgba(255,255,255,0.07);"
            "border-radius:10px;"
        )

    def _position_near(self, anchor: QRect) -> None:
        screen = QGuiApplication.screenAt(anchor.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        size = self.size()
        x = anchor.right() + 14
        y = anchor.y()
        if x + size.width() > sg.right():
            x = anchor.x() - size.width() - 14
        if x < sg.left():
            x = sg.left() + 14
        if y + size.height() > sg.bottom():
            y = sg.bottom() - size.height() - 14
        if y < sg.top():
            y = sg.top() + 14
        self.move(x, y)

    def _position_compact_near_anchor(self) -> None:
        """Place the compact widget near the selection without covering it."""
        geo = self._compute_compact_geo()
        self.setGeometry(geo)

    def _compute_compact_geo(self) -> QRect:
        """Compute where compact widget should sit without moving yet."""
        anchor = getattr(self, "_anchor_rect", None)
        size = self._compact_size
        if anchor is None or anchor.isEmpty():
            screen = QGuiApplication.primaryScreen()
            sg = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
            x = sg.right() - size.width() - 24
            y = sg.bottom() - size.height() - 24
            return QRect(max(sg.left(), x), max(sg.top(), y), size.width(), size.height())
        screen = QGuiApplication.screenAt(anchor.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        x = anchor.right() + 14
        y = anchor.y()
        if x + size.width() > sg.right():
            x = anchor.x() - size.width() - 14
        if x < sg.left():
            x = sg.left() + 14
        if y + size.height() > sg.bottom():
            y = sg.bottom() - size.height() - 14
        if y < sg.top():
            y = sg.top() + 14
        return QRect(x, y, size.width(), size.height())

    def _position_expanded_centered(self) -> QRect:
        screen = QGuiApplication.screenAt(self._anchor_rect.center()) if hasattr(self, "_anchor_rect") else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        target = self._expanded_size
        w = min(target.width(), sg.width() - 32)
        h = min(target.height(), sg.height() - 32)
        x = sg.center().x() - w // 2
        y = sg.center().y() - h // 2
        return QRect(x, y, w, h)

    def _animate_to_geometry(self, target: QRect) -> None:
        try:
            anim = QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self.geometry())
            anim.setEndValue(target)
            anim.start()
            # Keep reference so GC doesn't stop it
            self._geom_anim = anim
            anim.finished.connect(lambda: setattr(self, "_geom_anim", None))
        except Exception:
            self.setGeometry(target)

    def _toggle_expand(self) -> None:
        self._is_expanded = not self._is_expanded
        if self._is_expanded:
            # Expanded → full ChatGPT-like layout
            set_button_lucide_icon(self.btn_expand, "minimize-2", 16, "#9a9a9a")
            if self.btn_expand.icon().isNull():
                self.btn_expand.setText("🗗")
            else:
                self.btn_expand.setText("")
            self.btn_expand.setToolTip("Collapse to compact")
            if hasattr(self, "_sidebar"):
                self._sidebar.setVisible(True)
            self._apply_compact_header(True)
            self.setMinimumSize(QSize(760, 560))
            geo = self._position_expanded_centered()
            self._animate_to_geometry(geo)
        else:
            set_button_lucide_icon(self.btn_expand, "maximize-2", 16, "#9a9a9a")
            if self.btn_expand.icon().isNull():
                self.btn_expand.setText("⛶")
            else:
                self.btn_expand.setText("")
            self.btn_expand.setToolTip("Expand to full view")
            if hasattr(self, "_sidebar"):
                self._sidebar.setVisible(False)
            self._apply_compact_header(False)
            self.setMinimumSize(QSize(380, 420))
            target = self._compute_compact_geo()
            self._animate_to_geometry(target)
        # Reflow messages
        for row in self._rows:
            row.fit_height()

    # ── Feed helpers ────────────────────────────────────────
    def _add_row(self, role: str, text: str = "") -> _MessageRow:
        row = _MessageRow(role)
        self.feed_layout.insertWidget(self.feed_layout.count() - 1, row)
        self._rows.append(row)
        if text:
            row.set_markdown(text)
        QTimer.singleShot(0, row.fit_height)
        self._scroll_bottom()
        return row

    def _scroll_bottom(self) -> None:
        def go():
            sb = self.feed_scroll.verticalScrollBar()
            sb.setValue(sb.maximum())
        QTimer.singleShot(0, go)

    # ── Action buttons (parsed from answer, no extra API call) ───────────────
    def _clear_actions(self) -> None:
        if self._action_bar is not None:
            self.feed_layout.removeWidget(self._action_bar)
            self._action_bar.deleteLater()
            self._action_bar = None

    def _render_actions(self, answer: str) -> None:
        self._clear_actions()
        acts = extract_actions(answer)
        if not acts:
            return
        bar = QWidget(objectName="action_bar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 14)
        lay.setSpacing(10)
        for a in acts:
            btn = self._make_action_button(a)
            lay.addWidget(btn, 0)
        lay.addStretch(1)
        self.feed_layout.insertWidget(self.feed_layout.count() - 1, bar)
        self._action_bar = bar
        self._scroll_bottom()

    def _make_action_button(self, act: Action) -> QPushButton:
        icon = "⧉" if act.kind == "copy_code" else "⬈"
        btn = QPushButton(f"{icon}  {act.label}", objectName="action_btn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(38)
        btn.setFixedWidth(max(128, btn.sizeHint().width() + 12))
        glow = QGraphicsDropShadowEffect(btn)
        glow.setBlurRadius(18)
        glow.setOffset(0, 5)
        glow.setColor(QColor(0, 0, 0, 120))
        btn.setGraphicsEffect(glow)
        self._attach_action_hover(btn)
        btn.clicked.connect(lambda _=False, act=act: self._run_action(act))
        return btn

    def _attach_action_hover(self, btn: QPushButton) -> None:
        original = btn.geometry()
        anim = QPropertyAnimation(btn, b"geometry", self)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)

        def enter() -> None:
            if btn.geometry() != original:
                return
            anim.stop()
            anim.setStartValue(original)
            anim.setEndValue(QRect(original.x() - 4, original.y() - 4, original.width() + 8, original.height() + 8))
            anim.start()

        def leave(e) -> None:
            anim.stop()
            anim.setStartValue(btn.geometry())
            anim.setEndValue(original)
            anim.start()
            QPushButton.leaveEvent(btn, e)

        btn.entered.connect(enter)
        btn.leaveEvent = leave

    def _run_action(self, act: Action) -> None:
        if act.kind == "copy_code":
            QApplication.clipboard().setText(act.payload)
            self._status_bar.show()
            self._status_label.setText("Code copied")
            self._status_label.setStyleSheet("")
        elif act.kind == "open_url":
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(act.payload))

    # ── History ────────────────────────────────────────────
    def _save_history(self, answer: str) -> None:
        try:
            mode = "text" if self._text_mode else "crop"
            question = ""
            for m in self._messages:
                if m.get("role") == "user":
                    c = m.get("content")
                    if isinstance(c, str):
                        question = c
                    elif isinstance(c, list):
                        for p in c:
                            if isinstance(p, dict) and p.get("type") == "text":
                                question = p.get("text", "")
            store.save_snip(
                mode=mode,
                question=question[:500],
                answer=answer,
                selected_text=self._selected_text,
                thumb_png=self._png if not self._text_mode else None,
            )
        except Exception:
            log.exception("save_history failed")

    # ── Models ──────────────────────────────────────────────
    def _populate_models(self) -> None:
        # Free Only + 2+ active → combined random free pool across all providers
        if self._free_only and len(get_active_provider_ids()) >= 2:
            pool = collect_free_vision_across_active()
            if pool:
                combined = [rec for _, rec in pool]
                seen: set[str] = set()
                uniq: list[dict] = []
                for r in combined:
                    if r["id"] not in seen:
                        uniq.append(r)
                        seen.add(r["id"])
                self._apply_model_records(uniq)
                return
            self.model_select.setEnabled(False)
            self.model_select.setToolTip("Loading free models from all active providers...")
            self._fetch_all_active_models()
            return
        cached = get_cached_records()
        if cached:
            self._apply_model_records(cached)
            return
        self.model_select.setEnabled(False)
        self.model_select.setToolTip("Loading models...")
        self._models_fetcher = ModelsFetcher()
        self._models_fetcher.fetched.connect(self._set_models)
        self._models_fetcher.failed.connect(self._on_models_failed)
        self._models_fetcher.finished.connect(self._models_fetcher.deleteLater)
        self._models_fetcher.start()

    def _fetch_all_active_models(self) -> None:
        """Fetch models for every Active provider in parallel, then show combined free pool."""
        from PySide6.QtCore import QThread

        active = get_active_provider_ids()
        if not active:
            self.model_select.setEnabled(True)
            return

        class _AllFetcher(QThread):
            fetched_all = Signal(list)  # list of (pid, records)

            def __init__(self, pids: list[str]):
                super().__init__()
                self.pids = pids

            def run(self) -> None:
                out: list[tuple[str, list[dict]]] = []
                for pid in self.pids:
                    try:
                        from snipai.ai.models import fetch_models_sync
                        recs = fetch_models_sync(pid)
                        out.append((pid, recs))
                    except Exception:
                        out.append((pid, []))
                self.fetched_all.emit(out)

        self._all_fetcher = _AllFetcher(active)
        self._all_fetcher.fetched_all.connect(self._on_all_fetched)
        self._all_fetcher.finished.connect(self._all_fetcher.deleteLater)
        self._all_fetcher.start()

    @Slot(list)
    def _on_all_fetched(self, all_data: list) -> None:
        # all_data: list of (pid, records)
        pool: list[dict] = []
        for _, recs in all_data:
            for r in recs:
                if r.get("free"):
                    pool.append(r)
        if not pool:
            for _, recs in all_data:
                for r in recs:
                    if r.get("vision"):
                        pool.append(r)
                if pool:
                    break
        if not pool:
            for _, recs in all_data:
                pool.extend(recs)
        # Deduplicate
        seen: set[str] = set()
        uniq: list[dict] = []
        for r in pool:
            if r["id"] not in seen:
                uniq.append(r)
                seen.add(r["id"])
        if uniq:
            self._apply_model_records(uniq)
        else:
            self.model_select.setEnabled(True)
            self.model_select.setToolTip("No models found")
        self._all_fetcher = None

    def _apply_model_records(self, records: list[dict]) -> None:
        self._model_records = list(records)
        self.model_select.blockSignals(True)
        self.model_select.clear()
        for m in self._model_records:
            display = m.get("name") or m["id"]
            tags = []
            if m.get("free"):
                tags.append("★ Free")
            if m.get("vision"):
                tags.append("vision")
            if tags:
                display = f"{display}  ·  {', '.join(tags)}"
            self.model_select.addItem(display)
        target = self._current_model
        if self._free_only:
            if len(get_active_provider_ids()) >= 2:
                rnd = pick_random_free_vision_across_active()
                if rnd:
                    target = rnd[1]["id"]
                else:
                    for r in records:
                        if r.get("free"):
                            target = r["id"]
                            break
            else:
                from ..ai.models import pick_free_vision
                free_vision = pick_free_vision()
                if free_vision:
                    target = free_vision["id"]
        idx = next((i for i, m in enumerate(self._model_records) if m["id"] == target), -1)
        if idx >= 0:
            self.model_select.setCurrentIndex(idx)
            self._current_model = self._model_records[idx]["id"]
        elif self._model_records:
            self.model_select.setCurrentIndex(0)
            self._current_model = self._model_records[0]["id"]
        self.model_select.blockSignals(False)
        self.model_select.setEnabled(True)
        if self._free_only and len(get_active_provider_ids()) >= 2:
            self.model_select.setToolTip(f"Model: {self._current_model} (random free across {len(get_active_provider_ids())} providers)")
        else:
            self.model_select.setToolTip(f"Model: {self._current_model}")

        has_free = any(m.get("free") for m in self._model_records)
        if not has_free:
            self.free_only_check.setEnabled(False)
            self.free_only_check.setToolTip("No free models on this provider.")
        else:
            self.free_only_check.setEnabled(True)
            self.free_only_check.setToolTip("Auto-pick a free, vision-capable model.")

    @Slot(list)
    def _set_models(self, records: list[dict]) -> None:
        self._apply_model_records(records)
        self._models_fetcher = None

    @Slot(str)
    def _on_models_failed(self, err: str) -> None:
        log.warning("model list fetch failed: %s", err)
        self.model_select.setEnabled(True)
        self.free_only_check.setEnabled(False)
        self._models_fetcher = None

    @Slot(str)
    def _on_model_changed(self, display_text: str) -> None:
        idx = self.model_select.currentIndex()
        if 0 <= idx < len(self._model_records):
            self._current_model = self._model_records[idx]["id"]

    @Slot(int)
    def _on_mode_changed(self, idx: int) -> None:
        key = self.mode_select.itemData(idx)
        if key:
            self._mode_key = key

    def _system_for_mode(self) -> str:
        return prompt_modes.get_mode(self._mode_key).system

    def _prompt_for_mode(self) -> str:
        return prompt_modes.get_mode(self._mode_key).default_prompt

    @Slot(bool)
    def _on_free_only_toggled(self, on: bool) -> None:
        self._free_only = on
        if not on:
            cached = get_cached_records()
            if cached:
                self._apply_model_records(cached)
            else:
                self._populate_models()
            return
        if len(get_active_provider_ids()) >= 2:
            # Show combined free pool from all active providers, random pick
            self._populate_models()
            return
        if not self._model_records:
            return
        from ..ai.models import pick_free_vision
        free_vision = pick_free_vision()
        if not free_vision:
            return
        idx = next((i for i, m in enumerate(self._model_records) if m["id"] == free_vision["id"]), -1)
        if idx >= 0:
            self.model_select.blockSignals(True)
            self.model_select.setCurrentIndex(idx)
            self.model_select.blockSignals(False)
            self._current_model = free_vision["id"]
            self.model_select.setToolTip(f"Model: {self._current_model}")

    # ── Render (debounced) ──────────────────────────────────
    def _schedule_render(self) -> None:
        if self._dirty:
            return
        self._dirty = True
        self._render_timer.start(80)

    def _do_render(self) -> None:
        self._dirty = False
        if self._active_row is None:
            return
        sb = self.feed_scroll.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 8
        self._active_row.set_markdown(self._current_buf or "_..._")
        if at_bottom:
            self._scroll_bottom()

    # ── Streaming ───────────────────────────────────────────
    @Slot(str)
    def append_chunk(self, text: str) -> None:
        if self._current_buf == "":
            self._thinking_bar.hide()
            self._status_bar.show()
            self._status_label.setText("Streaming response...")
            self._status_label.setStyleSheet("")
        self._current_buf += text
        self._schedule_render()

    @Slot()
    def mark_finished(self) -> None:
        self._thinking_bar.hide()
        self._status_bar.show()
        self._status_label.setText("Response complete")
        self._status_label.setStyleSheet("")
        if hasattr(self, "_rate_limit_bar"):
            self._rate_limit_bar.hide()

        if not self._current_buf:
            self._current_buf = "_(empty response)_"

        if self._active_row is not None:
            self._active_row.set_markdown(self._current_buf)
        # Detect rate-limit / quota that was streamed as normal content (fallback)
        lower_fin = self._current_buf.lower()
        if (
            "rate limit" in lower_fin
            or "tokens per minute" in lower_fin
            or " 429" in self._current_buf
            or " 402" in self._current_buf
            or "credits" in lower_fin
            or "quota" in lower_fin
        ):
            self._status_label.setText("Rate limit / quota exceeded — try another free model")
            self._status_label.setStyleSheet("color: #fca5a5; font-size: 8pt; font-weight: 600;")
            if hasattr(self, "_rate_limit_label"):
                self._rate_limit_label.setText("Limit detected — try another free model")
            if hasattr(self, "_rate_limit_bar"):
                self._rate_limit_bar.show()
        self._messages.append({"role": "assistant", "content": self._current_buf})
        self._last_assistant = self._current_buf
        answer = self._current_buf
        self._current_buf = ""
        self._active_row = None
        self._scroll_bottom()

        self._render_actions(answer)
        self._save_history(answer)
        self._build_history()

        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.chat_input.setFocus()
        self._worker = None

    @Slot(str)
    def mark_failed(self, err: str) -> None:
        self._thinking_bar.hide()
        self._status_bar.show()
        lower = err.lower()
        is_rate = (
            "rate limit" in lower
            or "rate_limit" in lower
            or "tokens per minute" in lower
            or "429" in err
            or "402" in err
            or "credits" in lower
            or "quota" in lower
            or "insufficient" in lower
        )
        if is_rate:
            self._status_label.setText("Rate limit / quota exceeded — try another free model")
            self._status_label.setStyleSheet("color: #fca5a5; font-size: 8pt; font-weight: 600;")
            if hasattr(self, "_rate_limit_label"):
                # Show first line of error
                short = err.splitlines()[0][:140] if err else "Quota exceeded"
                self._rate_limit_label.setText(f"Limit hit — {short}")
            if hasattr(self, "_rate_limit_bar"):
                self._rate_limit_bar.show()
        else:
            self._status_label.setText("Error occurred")
            self._status_label.setStyleSheet("color: #ff6b6b; font-size: 8pt;")
            if hasattr(self, "_rate_limit_bar"):
                self._rate_limit_bar.hide()
        if self._active_row is not None:
            self._active_row.set_markdown(
                (self._current_buf + f"\n\n**Error:** `{err}`").strip()
            )
        self._current_buf = ""
        self._active_row = None
        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self._worker = None

    @Slot(str)
    def _on_tool_used(self, label: str) -> None:
        self._thinking_bar.show()
        self._thinking_label.setText(label)
        self._status_bar.hide()

    # ── Send ───────────────────────────────────────────────
    def _start_worker(self) -> None:
        if hasattr(self, "_rate_limit_bar"):
            self._rate_limit_bar.hide()
        log.info("_start_worker: messages=%d model=%s", len(self._messages), self._current_model)
        self._worker = GeminiWorker.from_messages(list(self._messages), model=self._current_model)
        self._worker.chunk.connect(self.append_chunk)
        self._worker.finished_ok.connect(self.mark_finished)
        self._worker.failed.connect(self.mark_failed)
        self._worker.tool_used.connect(self._on_tool_used)
        self._worker.model_switched.connect(self._on_model_switched)
        self._worker.provider_switched.connect(self._on_provider_switched)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    @Slot()
    def _on_worker_done(self) -> None:
        # Safety net: worker finished but mark_finished/failed not called (interrupted) → re-enable
        # Use singleShot to let queued mark_finished/failed run first
        from PySide6.QtCore import QTimer
        def _ensure_enabled():
            if self._worker is not None:
                log.warning("_on_worker_done: worker still not cleared, forcing enable")
                self._thinking_bar.hide()
                self.chat_input.setEnabled(True)
                self.btn_send.setEnabled(True)
                self.chat_input.setFocus()
                self._worker = None
            self._hide_text_options()
            # Ensure input is enabled if no worker is running
            if self._worker is None and not self.chat_input.isEnabled():
                self.chat_input.setEnabled(True)
                self.btn_send.setEnabled(True)
        QTimer.singleShot(60, _ensure_enabled)
        # Hide text options immediately (they should be gone after first turn)
        self._hide_text_options()

    @Slot(str)
    def _on_model_switched(self, new_model: str) -> None:
        self._current_model = new_model
        for i, m in enumerate(self._model_records):
            if m["id"] == new_model:
                self.model_select.blockSignals(True)
                self.model_select.setCurrentIndex(i)
                self.model_select.blockSignals(False)
                break
        self.model_select.setToolTip(f"Model: {new_model} (auto-rotated)")

    @Slot(str, str)
    def _on_provider_switched(self, provider_id: str, model_id: str) -> None:
        display = provider_id
        if provider_id.startswith("custom:"):
            display = provider_id.replace("custom:", "Custom · ")
        self.provider_badge.setText(display)
        # Only show badge when expanded; compact keeps header minimal
        self.provider_badge.setVisible(bool(getattr(self, "_is_expanded", False)))
        self._current_model = model_id
        for i, m in enumerate(self._model_records):
            if m["id"] == model_id:
                self.model_select.blockSignals(True)
                self.model_select.setCurrentIndex(i)
                self.model_select.blockSignals(False)
                break
        self.model_select.setToolTip(f"Model: {model_id} (auto-rotated)")

    def _auto_send(self) -> None:
        log.info("_auto_send: first_turn=%s worker=%s", self._first_turn_sent, self._worker is not None)
        if self._first_turn_sent or self._worker is not None:
            return
        try:
            self._first_turn_sent = True
            self.chat_input.setEnabled(False)
            self.btn_send.setEnabled(False)
            self._clear_actions()

            system = self._system_for_mode()
            prompt = self._prompt_for_mode()
            if self._stack_mode:
                n = len(self._stack_items)
                self._add_row("user", f"_Analyzing {n} stacked items together._")
                self._messages = build_stack_messages(prompt, self._stack_items, system=system)
            elif self._text_mode:
                # Show the captured selection + option cards, wait for user pick (no auto-send)
                self._add_row("user", self._selected_text)
                self._show_text_options()
                self._first_turn_sent = False
                self.chat_input.setEnabled(True)
                self.btn_send.setEnabled(True)
                self._thinking_bar.hide()
                self._status_bar.hide()
                return
            else:
                self._messages = build_initial_messages(prompt, self._png, system=system)

            self._current_buf = ""
            self._active_row = self._add_row("assistant", "_..._")

            self._thinking_bar.show()
            self._thinking_label.setText("Analyzing...")
            self._status_bar.hide()
        except Exception:
            log.exception("auto_send setup failed")
            self.failed.emit("Popup setup failed — see log")
            return
        log.info("auto_send: calling _start_worker")
        self._start_worker()

    def _on_attach(self) -> None:
        """Open a file picker, load the image, and set it as the next turn's image."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            # Convert to PNG via QImage for consistent encoding
            img = QImage()
            img.loadFromData(data)
            if img.isNull():
                raise ValueError("Could not load image")
            import io
            buf = io.BytesIO()
            ba = img.bits().tobytes()
            # Re-encode as PNG using QPixmap round-trip
            pix = QPixmap.fromImage(img)
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            pix.save(tmp.name, "PNG")
            with open(tmp.name, "rb") as f:
                png = f.read()
            os.unlink(tmp.name)

            self._png = png
            self._text_mode = False
            self._first_turn_sent = False  # allow re-sending with new image
            import os as _os
            fname = _os.path.basename(path)
            self.chat_input.setPlaceholderText(f"Attached: {fname} — ask a question…")
            log.info("Attached image %s (%d bytes)", fname, len(png))
        except Exception as e:
            log.warning("Attach failed: %s", e)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Attach", f"Could not load image:\n{e}")

    def _on_send(self) -> None:
        if self._worker is not None:
            return
        self._hide_text_options()
        text = self.chat_input.toPlainText().strip()
        if not text:
            return
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self._clear_actions()

        system = self._system_for_mode()
        if not self._first_turn_sent:
            if self._text_mode:
                self._messages = build_text_messages(text, self._selected_text, system=system)
            else:
                self._messages = build_initial_messages(text, self._png, system=system)
            self._first_turn_sent = True
        else:
            self._messages.append({"role": "user", "content": text})

        self._add_row("user", text)
        self._current_buf = ""
        self._active_row = self._add_row("assistant", "_..._")

        self._thinking_bar.show()
        self._thinking_label.setText("Thinking...")
        self._status_bar.hide()
        self._start_worker()

    # ── Header drag ────────────────────────────────────────
    # ── Edge-drag resize + header drag ─────────────────────
    def _edge_at(self, pos: QPoint) -> str:
        """Return which edge/corner the point is on, within the resize margin."""
        m = self._RESIZE_MARGIN
        r = self.rect()
        # Account for the 12px translucent outer margin around #root.
        ox = oy = 12
        left = pos.x() <= ox + m
        right = pos.x() >= r.width() - ox - m
        top = pos.y() <= oy + m
        bottom = pos.y() >= r.height() - oy - m
        # Only within the visible root area.
        if pos.x() < ox - m or pos.x() > r.width() - ox + m:
            return ""
        if pos.y() < oy - m or pos.y() > r.height() - oy + m:
            return ""
        v = "top" if top else ("bottom" if bottom else "")
        h = "left" if left else ("right" if right else "")
        return (v + h) if (v or h) else ""

    _CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
        "topleft": Qt.CursorShape.SizeFDiagCursor, "bottomright": Qt.CursorShape.SizeFDiagCursor,
        "topright": Qt.CursorShape.SizeBDiagCursor, "bottomleft": Qt.CursorShape.SizeBDiagCursor,
    }

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_at(e.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_mouse = e.globalPosition().toPoint()
                e.accept()
                return
            top_left = self.header.mapTo(self, QPoint(0, 0))
            header_rect = QRect(top_left, self.header.size())
            if header_rect.contains(e.position().toPoint()):
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        # Active resize drag.
        if self._resize_edge and (e.buttons() & Qt.MouseButton.LeftButton):
            self._do_resize(e.globalPosition().toPoint())
            e.accept()
            return
        # Active window drag.
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        # Hover: update cursor near edges.
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            edge = self._edge_at(e.position().toPoint())
            self.setCursor(self._CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(e)

    def _do_resize(self, gpos: QPoint) -> None:
        geo = QRect(self._resize_start_geo)
        dx = gpos.x() - self._resize_start_mouse.x()
        dy = gpos.y() - self._resize_start_mouse.y()
        minw = self.minimumWidth()
        minh = self.minimumHeight()
        edge = self._resize_edge
        if "left" in edge:
            new_left = geo.left() + dx
            if geo.right() - new_left + 1 < minw:
                new_left = geo.right() - minw + 1
            geo.setLeft(new_left)
        if "right" in edge:
            geo.setWidth(max(minw, geo.width() + dx))
        if "top" in edge:
            new_top = geo.top() + dy
            if geo.bottom() - new_top + 1 < minh:
                new_top = geo.bottom() - minh + 1
            geo.setTop(new_top)
        if "bottom" in edge:
            geo.setHeight(max(minh, geo.height() + dy))
        self.setGeometry(geo)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
        self._resize_edge = ""
        self._resize_start_geo = None
        self._resize_start_mouse = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            if hasattr(self, "_chat_stack") and hasattr(self, "_inline_settings") and self._chat_stack.currentWidget() is self._inline_settings:
                self._hide_inline_settings()
                return
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
