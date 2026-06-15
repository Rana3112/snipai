"""Floating chat popup — production chat UI (Claude/ChatGPT style).

Frameless, draggable, always-on-top, rounded.
Per-turn message rows with role labels/avatars, streaming into the active row.
Auto-send on open: cropped image + dynamic default prompt fired immediately.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import (
    Qt, QPoint, QRect, Signal, Slot, QSize, QTimer,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QGuiApplication, QMouseEvent, QPixmap, QImage, QClipboard, QKeyEvent,
    QColor, QPainter, QPalette,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser, QPushButton,
    QApplication, QFrame, QGraphicsDropShadowEffect, QTextEdit,
    QComboBox, QScrollArea, QCheckBox,
)

from ..api.worker import (
    GeminiWorker, build_initial_messages, build_text_messages,
    build_stack_messages, SYSTEM_PROMPT,
)
from ..ai.models import get_cached_records, ModelsFetcher
from ..ai import modes as prompt_modes
from ..ai.actions import extract_actions, Action
from .. import store
from ..config import config
from .theme import generate_stylesheet, get_link_color
from .markdown import markdown_to_html

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
    """One conversation turn: role label + markdown content. Auto-sizes height."""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role  # "user" | "assistant"
        self.setObjectName("user_row" if role == "user" else "assistant_row")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(7)

        # ── Role header (avatar dot + name) ──────────────────
        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(20, 20)
        dot.setObjectName("avatar_user" if role == "user" else "avatar_ai")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setText("U" if role == "user" else "AI")
        head.addWidget(dot, 0)
        name = QLabel("You" if role == "user" else "Snip AI")
        name.setObjectName("role_name")
        head.addWidget(name, 0)
        head.addStretch(1)
        lay.addLayout(head)

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
        lay.addWidget(self.browser)

    def set_markdown(self, md: str) -> None:
        self.browser.setHtml(markdown_to_html(md))
        self.fit_height()

    def fit_height(self) -> None:
        vw = self.browser.viewport().width()
        if vw <= 0:
            vw = max(self.width() - 40, 200)
        doc = self.browser.document()
        doc.setTextWidth(vw)
        h = int(doc.size().height()) + 6
        self.browser.setFixedHeight(max(h, 24))


class ResponseWindow(QWidget):
    closed = Signal()

    DEFAULT_SIZE = QSize(600, 680)
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
        self.resize(self.DEFAULT_SIZE)

        self._build_ui(png)
        self._position_near(anchor)
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
        outer.addWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Header ─────────────────────────────────────────
        self.header = QWidget(objectName="header")
        h = QHBoxLayout(self.header)
        h.setContentsMargins(16, 12, 14, 12)
        h.setSpacing(12)

        self.thumb = QLabel(objectName="thumb")
        self.thumb.setFixedSize(self.THUMB_MAX, self.THUMB_MAX)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._stack_mode:
            self._set_glyph_thumb(f"{len(self._stack_items)}")
        elif self._text_mode:
            self._set_text_thumb()
        else:
            self._set_thumb(png)
        h.addWidget(self.thumb, 0)

        meta = QVBoxLayout()
        meta.setSpacing(3)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        subtitle = QLabel("SNIP AI", objectName="subtitle")
        brand_row.addWidget(subtitle, 0)
        brand_row.addStretch(1)

        self.mode_select = QComboBox()
        self.mode_select.setObjectName("model_select")
        self.mode_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_select.setMinimumWidth(96)
        self.mode_select.setToolTip("Response mode")
        for key in prompt_modes.ORDER:
            self.mode_select.addItem(prompt_modes.get_mode(key).label, key)
        idx = self.mode_select.findData(self._mode_key)
        if idx >= 0:
            self.mode_select.setCurrentIndex(idx)
        self.mode_select.currentIndexChanged.connect(self._on_mode_changed)
        brand_row.addWidget(self.mode_select, 0)

        self.model_select = QComboBox()
        self.model_select.setObjectName("model_select")
        self.model_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_select.setMinimumWidth(160)
        self.model_select.setMaximumWidth(220)
        self.model_select.addItem(self._current_model)
        self.model_select.currentTextChanged.connect(self._on_model_changed)
        brand_row.addWidget(self.model_select, 0)

        self.provider_badge = QLabel("")
        self.provider_badge.setObjectName("provider_badge")
        self.provider_badge.setStyleSheet(
            "color: #8b9aff; font-size: 8pt; font-weight: 700; "
            "padding: 2px 8px; border-radius: 999px; "
            "background: rgba(91,106,255,0.15); border: 1px solid rgba(91,106,255,0.3);"
        )
        self.provider_badge.setVisible(False)
        self.provider_badge.setToolTip("Active provider (auto-rotates on failure)")
        brand_row.addWidget(self.provider_badge, 0)

        self.free_only_check = QCheckBox("Free only")
        self.free_only_check.setObjectName("free_only_check")
        self.free_only_check.setChecked(self._free_only)
        self.free_only_check.setToolTip("Auto-pick a free, vision-capable model from this provider.")
        self.free_only_check.toggled.connect(self._on_free_only_toggled)
        brand_row.addWidget(self.free_only_check, 0)
        meta.addLayout(brand_row)

        title = QLabel("Snip Chat", objectName="title")
        meta.addWidget(title)
        prompt_label = QLabel(
            "Reading selected text" if self._text_mode else "Analyzing your selection",
            objectName="prompt",
        )
        prompt_label.setWordWrap(True)
        meta.addWidget(prompt_label)
        meta.addStretch(1)
        h.addLayout(meta, 1)

        self.btn_close = QPushButton("✕", objectName="close_btn")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        h.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)

        v.addWidget(self.header)
        sep = QFrame(objectName="sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        v.addWidget(sep)

        # ── Feed (scrollable message rows) ────────────────────
        self.feed_scroll = QScrollArea(objectName="feed_scroll")
        self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feed = QWidget(objectName="feed")
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(0)
        self.feed_layout.addStretch(1)
        self.feed_scroll.setWidget(self.feed)
        v.addWidget(self.feed_scroll, 1)

        # ── Thinking indicator ────────────────────────────────
        self._thinking_bar = QWidget()
        tb_layout = QHBoxLayout(self._thinking_bar)
        tb_layout.setContentsMargins(18, 4, 18, 4)
        tb_layout.setSpacing(8)
        self._dots = _ThinkingDots()
        tb_layout.addWidget(self._dots)
        self._thinking_label = QLabel("Analyzing...")
        self._thinking_label.setStyleSheet("color: #8b9aff; font-size: 9pt; font-weight: 600;")
        tb_layout.addWidget(self._thinking_label)
        tb_layout.addStretch(1)
        v.addWidget(self._thinking_bar)
        self._thinking_bar.hide()

        # ── Status bar ────────────────────────────────────────
        self._status_bar = QWidget()
        sb_layout = QHBoxLayout(self._status_bar)
        sb_layout.setContentsMargins(18, 4, 18, 4)
        self._status_label = QLabel("", objectName="status")
        sb_layout.addWidget(self._status_label)
        sb_layout.addStretch(1)
        v.addWidget(self._status_bar)
        self._status_bar.hide()

        # ── Chat input ────────────────────────────────────────
        sep_chat = QFrame(objectName="sep")
        sep_chat.setFrameShape(QFrame.Shape.HLine)
        v.addWidget(sep_chat)

        chat_row = QWidget()
        chat_layout = QHBoxLayout(chat_row)
        chat_layout.setContentsMargins(14, 12, 14, 12)
        chat_layout.setSpacing(8)
        self.chat_input = _ChatInput()
        self.chat_input.setObjectName("chat_input")
        self.chat_input.submitted.connect(self._on_send)
        chat_layout.addWidget(self.chat_input, 1)

        self.btn_send = QPushButton("Send  →", objectName="primary")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setFixedHeight(48)
        self.btn_send.clicked.connect(self._on_send)
        chat_layout.addWidget(self.btn_send)
        v.addWidget(chat_row)

        # ── Footer ────────────────────────────────────────────
        sep2 = QFrame(objectName="sep")
        sep2.setFrameShape(QFrame.Shape.HLine)
        v.addWidget(sep2)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 14)
        footer.setSpacing(8)
        footer.addStretch(1)
        self.btn_copy = QPushButton("  Copy")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy)
        footer.addWidget(self.btn_copy)
        self.btn_done = QPushButton("Done", objectName="primary")
        self.btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_done.clicked.connect(self.close)
        footer.addWidget(self.btn_done)
        v.addLayout(footer)

    def showEvent(self, e):
        super().showEvent(e)
        self.chat_input.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for row in self._rows:
            row.fit_height()

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
        if not on or not self._model_records:
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

        if not self._current_buf:
            self._current_buf = "_(empty response)_"

        if self._active_row is not None:
            self._active_row.set_markdown(self._current_buf)
        self._messages.append({"role": "assistant", "content": self._current_buf})
        self._last_assistant = self._current_buf
        answer = self._current_buf
        self._current_buf = ""
        self._active_row = None
        self._scroll_bottom()

        self._render_actions(answer)
        self._save_history(answer)

        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.chat_input.setFocus()
        self._worker = None

    @Slot(str)
    def mark_failed(self, err: str) -> None:
        self._thinking_bar.hide()
        self._status_bar.show()
        self._status_label.setText("Error occurred")
        self._status_label.setStyleSheet("color: #ff6b6b; font-size: 8pt;")
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
        log.info("_start_worker: messages=%d model=%s", len(self._messages), self._current_model)
        self._worker = GeminiWorker.from_messages(list(self._messages), model=self._current_model)
        self._worker.chunk.connect(self.append_chunk)
        self._worker.finished_ok.connect(self.mark_finished)
        self._worker.failed.connect(self.mark_failed)
        self._worker.tool_used.connect(self._on_tool_used)
        self._worker.model_switched.connect(self._on_model_switched)
        self._worker.provider_switched.connect(self._on_provider_switched)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

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
        self.provider_badge.setVisible(True)
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
                # Show the captured selection as the first user row.
                self._add_row("user", self._selected_text)
                self._messages = build_text_messages(prompt, self._selected_text, system=system)
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

    def _on_send(self) -> None:
        if self._worker is not None:
            return
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
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if self.header.geometry().contains(e.position().toPoint()):
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)

    # ── Actions ────────────────────────────────────────────
    def _copy(self) -> None:
        cb: QClipboard = QApplication.clipboard()
        cb.setText(self._last_assistant or "")
        self.btn_copy.setText("  Copied!")
        QTimer.singleShot(2000, lambda: self.btn_copy.setText("  Copy"))
