"""Inline settings page — embedded inside ResponseWindow.

Same tabs as SettingsPanel (Hotkeys/Theme/Providers) but as a QWidget
that lives in the chat area's QStackedWidget. No separate window, no shadow.
Emits `closed` when user wants to go back to chat, and `saved` after Save.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import Qt, Signal, QSize, QPoint, QRect, QEvent
from PySide6.QtGui import QColor, QKeyEvent, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFrame, QColorDialog, QTabWidget, QMessageBox,
    QListWidget, QListWidgetItem, QCheckBox, QScrollArea,
)

from ..config import AppConfig, ThemeConfig, save_config, load_config, custom_provider_id
from .setup_wizard import PROVIDER_PRESETS, THEME_PRESETS, _ModelsFetcher
from .theme import generate_stylesheet
from .icons import lucide_icon, lucide_pixmap, set_button_lucide_icon

log = logging.getLogger(__name__)


def _settings_extra_qss(t: ThemeConfig) -> str:
    return f"""
        QFrame#inline_header {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,255,255,0.04), stop:1 transparent);
            border: 1px solid rgba(255,255,255,0.06); border-radius: 12px;
        }}
        QLabel#inline_title {{ color: #ffffff; font-size: 13pt; font-weight: 800; }}
        QLabel#inline_sub {{ color: {t.text_secondary}; font-size: 8.5pt; }}
        QPushButton#inline_back {{
            background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
            border-radius: 999px; color: #ffffff; font-size: 9pt; font-weight: 600;
            padding: 6px 14px;
        }}
        QPushButton#inline_back:hover {{ background: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.12); }}
        QTabWidget::pane {{
            background: transparent; border: none; top: -1px;
        }}
        QTabBar {{ qproperty-drawBase: 0; }}
        QTabBar::tab {{
            background: rgba(255,255,255,0.03); color: {t.text_secondary};
            padding: 8px 18px; margin-right: 6px;
            border: 1px solid rgba(255,255,255,0.06);
            border-bottom: 2px solid transparent;
            border-top-left-radius: 10px; border-top-right-radius: 10px;
            font-size: 9pt; font-weight: 700;
        }}
        QTabBar::tab:hover {{ color: #ffffff; background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.10); }}
        QTabBar::tab:selected {{
            color: #ffffff; background: rgba(255,255,255,0.08);
            border-bottom: 2px solid {t.accent}; border-color: {t.accent}55;
        }}
        QLabel#section_title {{
            color: #ffffff; font-size: 11pt; font-weight: 800; letter-spacing: 0.2px;
            padding: 4px 0;
        }}
        QLabel#field_label {{
            color: {t.text_secondary}; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px;
            padding: 2px 0;
        }}
        QLabel#hint_label {{ color: rgba(255,255,255,0.45); font-size: 8pt; line-height: 1.4; }}
        QLabel#panel_title {{
            color: {t.accent}; font-weight: 800; font-size: 9pt; letter-spacing: 0.5px;
            padding: 2px 0;
        }}
        QFrame#tab_card {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.03), stop:1 rgba(255,255,255,0.01));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
        }}
        QFrame#panel_card {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a1d2e, stop:1 #161a2b);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
        }}
        QLineEdit {{
            background: rgba(255,255,255,0.05); color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
            padding: 9px 12px; font-size: 9.5pt;
            selection-background-color: {t.accent}55;
        }}
        QLineEdit:focus {{ border: 1px solid {t.accent}; background: rgba(255,255,255,0.07); }}
        QLineEdit:hover {{ border: 1px solid rgba(255,255,255,0.14); }}
        QComboBox {{
            background: rgba(255,255,255,0.05); color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
            padding: 8px 12px; font-size: 9.5pt;
        }}
        QComboBox:hover {{ border: 1px solid {t.accent}70; background: rgba(255,255,255,0.07); }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox::down-arrow {{
            image: none; border-left: 4px solid transparent;
            border-right: 4px solid transparent; border-top: 5px solid {t.text_secondary}; margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background: #1e2235; color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
            selection-background-color: {t.accent}55; selection-color: #ffffff; outline: 0; padding: 5px;
        }}
        QListWidget {{
            background: rgba(0,0,0,0.20); border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px; padding: 4px; font-size: 9pt; color: {t.text_primary}; outline: 0;
        }}
        QListWidget::item {{ padding: 7px 10px; border-radius: 8px; margin: 1px 0; }}
        QListWidget::item:hover {{ background: rgba(255,255,255,0.06); }}
        QListWidget::item:selected {{ background: {t.accent}35; color: #ffffff; border: 1px solid {t.accent}50; }}
        QCheckBox {{ color: {t.text_primary}; font-size: 9pt; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border: 1px solid rgba(255,255,255,0.2);
            border-radius: 4px; background: rgba(255,255,255,0.04);
        }}
        QCheckBox::indicator:hover {{ border: 1px solid rgba(255,255,255,0.30); }}
        QCheckBox::indicator:checked {{ background: {t.accent}; border: 1px solid {t.accent}; }}
        QLabel#preview_card {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t.bg_secondary}, stop:1 #1a1d2e);
            color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
            padding: 14px; font-size: 9.5pt;
        }}
        QPushButton#primary {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.accent}, stop:1 #8b5cf6);
            color: #ffffff; border: 1px solid {t.accent}; border-radius: 10px;
            padding: 9px 18px; font-weight: 700; font-size: 9.5pt;
        }}
        QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6f7dff, stop:1 #a78bfa); }}
    """


# Reuse AddProviderDialog from settings_panel — import lazily to avoid circular
from .settings_panel import AddProviderDialog  # noqa: E402


class InlineSettingsWidget(QWidget):
    """Embedded settings — lives inside ResponseWindow's chat stack."""

    closed = Signal()  # back to chat
    saved = Signal()   # config saved

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = load_config()
        self._fetcher: _ModelsFetcher | None = None
        self._recording: str | None = None
        self.setObjectName("inline_settings")
        self._build_ui()
        self._load_values()
        self._apply_theme()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # — Header with back button —
        header = QFrame(objectName="inline_header")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(14, 10, 14, 10)
        hh.setSpacing(8)
        back = QPushButton(" Back to chat", objectName="inline_back")
        set_button_lucide_icon(back, "arrow-left", 14, "#ffffff")
        if back.icon().isNull():
            back.setText("← Back to chat")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.closed.emit)
        hh.addWidget(back, 0)
        hh.addStretch(1)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_col.addWidget(QLabel("Settings", objectName="inline_title"), alignment=Qt.AlignmentFlag.AlignRight)
        title_col.addWidget(QLabel("Providers, hotkeys, appearance", objectName="inline_sub"), alignment=Qt.AlignmentFlag.AlignRight)
        hh.addLayout(title_col)
        close_btn = QPushButton(objectName="close_btn")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_lucide_icon(close_btn, "x", 14, "#9a9a9a")
        if close_btn.icon().isNull():
            close_btn.setText("✕")
        close_btn.clicked.connect(self.closed.emit)
        hh.addWidget(close_btn, 0)
        outer.addWidget(header)

        # — Tabs —
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self._build_tab_hotkeys()
        self._build_tab_theme()
        self._build_tab_providers()
        # Tab icons — Lucide
        try:
            self.tabs.setTabIcon(0, lucide_icon("keyboard", 14, "#9a9a9a"))
            self.tabs.setTabIcon(1, lucide_icon("palette", 14, "#9a9a9a"))
            self.tabs.setTabIcon(2, lucide_icon("plug", 14, "#9a9a9a"))
        except Exception:
            pass

        # — Footer —
        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 12)
        footer.setSpacing(8)
        self.status_label = QLabel("", objectName="hint_label")
        footer.addWidget(self.status_label, 1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.closed.emit)
        footer.addWidget(btn_cancel)
        btn_save = QPushButton("Save Changes", objectName="primary")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save)
        footer.addWidget(btn_save)
        outer.addLayout(footer)

    def _wrap_card(self, inner: QWidget) -> QWidget:
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(4, 8, 4, 4)
        pl.setSpacing(0)
        card = QFrame(objectName="tab_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        cl.addWidget(inner)
        pl.addWidget(card, 1)
        return page

    def _build_tab_hotkeys(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(QLabel("Keyboard Shortcuts", objectName="section_title"))
        v.addWidget(QLabel("CROP HOTKEY", objectName="field_label"))
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setReadOnly(True)
        self.hotkey_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hotkey_input.mousePressEvent = lambda e: self._start_recording("crop")
        v.addWidget(self.hotkey_input)
        v.addWidget(QLabel("TEXT HOTKEY", objectName="field_label"))
        self.text_hotkey_input = QLineEdit()
        self.text_hotkey_input.setReadOnly(True)
        self.text_hotkey_input.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text_hotkey_input.mousePressEvent = lambda e: self._start_recording("text")
        v.addWidget(self.text_hotkey_input)
        hint = QLabel("Click a field, then press the key combination you want. Hotkey changes apply after restarting SnipAI.", objectName="hint_label")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        self.tabs.addTab(self._wrap_card(inner), "Hotkeys")

    def _build_tab_theme(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(QLabel("Appearance", objectName="section_title"))
        v.addWidget(QLabel("THEME PRESET", objectName="field_label"))
        self.theme_combo = QComboBox()
        self.theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for name in THEME_PRESETS:
            self.theme_combo.addItem(name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        v.addWidget(self.theme_combo)
        v.addWidget(QLabel("ACCENT COLOR", objectName="field_label"))
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.accent_preview = QLabel()
        self.accent_preview.setFixedSize(36, 28)
        self.accent_preview.setStyleSheet("background: #5b6aff; border-radius: 6px;")
        color_row.addWidget(self.accent_preview)
        self.accent_btn = QPushButton("Pick color…")
        self.accent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accent_btn.clicked.connect(self._pick_accent)
        color_row.addWidget(self.accent_btn)
        color_row.addStretch(1)
        v.addLayout(color_row)
        v.addWidget(QLabel("PREVIEW", objectName="field_label"))
        self.preview = QLabel("This is how your popup text and accents will look.", objectName="preview_card")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(60)
        v.addWidget(self.preview)
        v.addStretch(1)
        self.tabs.addTab(self._wrap_card(inner), "Theme")

    def _build_tab_providers(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(4, 8, 4, 4)
        outer.setSpacing(10)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Providers & API keys", objectName="section_title"))
        header_row.addStretch(1)
        self.active_count_label = QLabel("")
        self.active_count_label.setObjectName("active_count_label")
        self._style_active_pill()
        header_row.addWidget(self.active_count_label)
        outer.addLayout(header_row)

        self.providers_scroll = QScrollArea(objectName="feed_scroll")
        self.providers_scroll.setWidgetResizable(True)
        self.providers_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.providers_scroll.setMinimumHeight(120)
        self.providers_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.providers_scroll_body = QWidget()
        self.providers_scroll_layout = QVBoxLayout(self.providers_scroll_body)
        self.providers_scroll_layout.setContentsMargins(2, 2, 2, 2)
        self.providers_scroll_layout.setSpacing(6)
        self.providers_scroll_layout.addStretch(1)
        self.providers_scroll.setWidget(self.providers_scroll_body)
        outer.addWidget(self.providers_scroll, 1)
        self._provider_key_edits: dict[str, QLineEdit] = {}

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        custom_box = QFrame(objectName="panel_card")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.setContentsMargins(10, 10, 10, 10)
        custom_layout.setSpacing(6)
        custom_layout.addWidget(QLabel("CUSTOM PROVIDERS", objectName="panel_title"))
        self.custom_list = QListWidget()
        self.custom_list.setMinimumHeight(60)
        self.custom_list.setMaximumHeight(100)
        custom_layout.addWidget(self.custom_list)
        custom_btns = QHBoxLayout()
        custom_btns.setSpacing(5)
        for label, icon, slot in ((" Add…", "plus", self._on_add_custom), (" Edit", "pen-line", self._on_edit_custom), (" Del", "trash", self._on_delete_custom)):
            b = QPushButton(label)
            set_button_lucide_icon(b, icon, 12, "#ececec")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            custom_btns.addWidget(b)
        custom_btns.addStretch(1)
        custom_layout.addLayout(custom_btns)
        bottom_row.addWidget(custom_box, 1)

        order_box = QFrame(objectName="panel_card")
        order_layout = QVBoxLayout(order_box)
        order_layout.setContentsMargins(10, 10, 10, 10)
        order_layout.setSpacing(6)
        order_layout.addWidget(QLabel("FALLBACK ORDER", objectName="panel_title"))
        self.fallback_list = QListWidget()
        self.fallback_list.setMinimumHeight(60)
        self.fallback_list.setMaximumHeight(100)
        order_layout.addWidget(self.fallback_list)
        order_btns = QHBoxLayout()
        order_btns.setSpacing(5)
        for label, icon, slot in ((" Up", "arrow-up", self._on_move_up), (" Down", "arrow-down", self._on_move_down)):
            b = QPushButton(label)
            set_button_lucide_icon(b, icon, 12, "#ececec")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            order_btns.addWidget(b)
        order_btns.addStretch(1)
        order_layout.addLayout(order_btns)
        bottom_row.addWidget(order_box, 1)
        outer.addLayout(bottom_row)

        hint = QLabel("Tip: a row glows green when an API key is set. Add more keys to keep snips working when rate-limited.", objectName="hint_label")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.tabs.addTab(page, "Providers")

    # — Reuse logic from SettingsPanel (copy, keep in sync) —
    def _rebuild_provider_list(self) -> None:
        while self.providers_scroll_layout.count() > 1:
            item = self.providers_scroll_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        total = 0
        active = 0
        for key, preset in PROVIDER_PRESETS.items():
            if key == "custom":
                continue
            total += 1
            stored = self._cfg.provider_keys.get(key, "")
            if not stored and self._cfg.provider == key:
                stored = self._cfg.api_key
            if stored:
                active += 1
            row = self._make_provider_row(pid=key, label=preset["label"], kind="Preset", api_key=stored, base_url=preset.get("base_url", ""), vision=None, t=self._cfg.theme)
            self.providers_scroll_layout.insertWidget(self.providers_scroll_layout.count() - 1, row)
        for cp in self._collect_custom_providers():
            total += 1
            if cp.get("api_key", "") or cp.get("base_url", ""):
                active += 1
            row = self._make_provider_row(pid=custom_provider_id(cp), label=cp.get("name", "?"), kind="Custom", api_key=cp.get("api_key", ""), base_url=cp.get("base_url", ""), vision=bool(cp.get("vision", True)), t=self._cfg.theme)
            self.providers_scroll_layout.insertWidget(self.providers_scroll_layout.count() - 1, row)
        self.active_count_label.setText(f"Active {active} / {total}")

    def _style_active_pill(self) -> None:
        t = self._cfg.theme
        self.active_count_label.setStyleSheet(
            "color: #ffffff; font-size: 8pt; font-weight: 800; padding: 3px 10px; border-radius: 999px; "
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.accent}, stop:1 #8b5cf6);"
        )

    def _make_provider_row(self, pid: str, label: str, kind: str, api_key: str, base_url: str, vision: bool | None, t=None) -> QFrame:
        if t is None:
            t = self._cfg.theme
        is_active = bool(api_key)
        row = QFrame()
        row.setObjectName("provider_row")
        row.setMinimumHeight(56)
        if is_active:
            row.setStyleSheet("QFrame#provider_row { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(74,222,128,0.10), stop:1 rgba(91,106,255,0.05)); border: 1px solid rgba(74,222,128,0.35); border-radius: 10px; }")
        else:
            row.setStyleSheet("QFrame#provider_row { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(8)
        status_col = QVBoxLayout()
        status_col.setSpacing(3)
        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background: {'#4ade80' if is_active else '#6b7280'}; border-radius: 6px; border: 2px solid {'#22c55e' if is_active else '#4b5563'};")
        dot_col = QHBoxLayout()
        dot_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot_col.addWidget(dot)
        status_col.addLayout(dot_col)
        status_lbl = QLabel("ACTIVE" if is_active else "NOT SET")
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setStyleSheet(f"color: {'#4ade80' if is_active else '#6b7280'}; font-size: 7pt; font-weight: 800; letter-spacing: 0.4px;")
        status_lbl.setMinimumWidth(52)
        status_col.addWidget(status_lbl)
        hl.addLayout(status_col)
        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        # Provider name with Lucide icon
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        icon_map = {
            "Anthropic (Claude)": "brain",
            "Google (Gemini)": "sparkles",
            "Groq (fast inference)": "zap",
            "NVIDIA NIM": "cpu",
            "OpenRouter (any model)": "route",
            "OpenCode Zen (multi-model gateway)": "code",
        }
        icon_name = icon_map.get(label, "plug" if kind == "Custom" else "box")
        icon_lab = QLabel()
        icon_lab.setFixedSize(16, 16)
        _pix = lucide_pixmap(icon_name, 14, t.accent if is_active else "#9a9a9a")
        if _pix is not None and not _pix.isNull():
            icon_lab.setPixmap(_pix)
        else:
            # Fallback: small colored dot already shows active, so no text fallback needed
            icon_lab.setText("")
        name_row.addWidget(icon_lab, 0)
        name_lbl = QLabel(label)
        name_lbl.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #e2e8f0;")
        name_row.addWidget(name_lbl, 0)
        name_row.addStretch(1)
        name_col.addLayout(name_row)
        sub_parts = [kind]
        if base_url:
            sub_parts.append(base_url)
        if vision is True:
            sub_parts.append("vision")
        sub_lbl = QLabel("  ·  ".join(sub_parts))
        sub_lbl.setStyleSheet(f"color: {t.accent}; font-size: 7.5pt;")
        sub_lbl.setWordWrap(False)
        name_col.addWidget(sub_lbl)
        hl.addLayout(name_col, 1)
        key_edit = QLineEdit(api_key)
        key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_edit.setPlaceholderText("paste API key…")
        key_edit.setMinimumWidth(150)
        key_edit.setMinimumHeight(30)
        key_edit.setStyleSheet("QLineEdit { background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.10); border-radius: 7px; padding: 5px 9px; color: #e2e8f0; font-size: 9pt; font-family: 'Cascadia Code', 'Consolas', monospace; } QLineEdit:focus { border: 1px solid %s; }" % t.accent)
        row._status_lbl = status_lbl
        row._status_dot = dot
        row._is_active = is_active
        key_edit.textChanged.connect(lambda txt, r=row: self._on_provider_key_edited(r, txt))
        self._provider_key_edits[pid] = key_edit
        hl.addWidget(key_edit, 0)
        show_btn = QPushButton("👁")
        show_btn.setFixedSize(30, 30)
        show_btn.setCheckable(True)
        show_btn.setToolTip("Show/hide key")
        show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        show_btn.setStyleSheet("QPushButton { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; font-size: 10pt; } QPushButton:hover { background: rgba(255,255,255,0.10); } QPushButton:checked { background: %s40; }" % t.accent)
        show_btn.toggled.connect(lambda on, e=key_edit: e.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        hl.addWidget(show_btn, 0)
        test_btn = QPushButton("Test")
        test_btn.setFixedSize(40, 30)
        test_btn.setToolTip("Verify this API key")
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet("QPushButton { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 7px; color: rgba(255,255,255,0.6); font-size: 7.5pt; font-weight: 700; } QPushButton:hover { background: rgba(255,255,255,0.10); color: #ffffff; }")
        test_btn.clicked.connect(lambda _, b=test_btn, e=key_edit, p=pid: self._test_provider_key(p, e, b))
        hl.addWidget(test_btn, 0)
        return row

    def _append_custom_row(self, cp: dict) -> None:
        label = f"{cp.get('name', '?')}  ·  {cp.get('base_url', '')}  ·  {cp.get('model', '?')}"
        if cp.get("vision"):
            label += "  ·  vision"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, dict(cp))
        self.custom_list.addItem(item)

    def _on_add_custom(self):
        dlg = AddProviderDialog(self, existing=None)
        if dlg.exec() == dlg.Accepted:
            cp = dlg.result_provider()
            self._append_custom_row(cp)
            self._rebuild_provider_list()
            self._rebuild_fallback_list()

    def _on_edit_custom(self):
        item = self.custom_list.currentItem()
        if not item:
            QMessageBox.information(self, "Custom Providers", "Pick one to edit first.")
            return
        existing = item.data(Qt.ItemDataRole.UserRole) or {}
        dlg = AddProviderDialog(self, existing=existing)
        if dlg.exec() == dlg.Accepted:
            cp = dlg.result_provider()
            new_name = cp.get("name", "")
            if new_name != existing.get("name") and self._custom_name_exists(new_name):
                QMessageBox.warning(self, "Custom Providers", f"A provider named '{new_name}' already exists.")
                return
            self.custom_list.takeItem(self.custom_list.row(item))
            self._append_custom_row(cp)
            self._rebuild_provider_list()
            self._rebuild_fallback_list()

    def _on_delete_custom(self):
        item = self.custom_list.currentItem()
        if not item:
            return
        self.custom_list.takeItem(self.custom_list.row(item))
        self._rebuild_provider_list()
        self._rebuild_fallback_list()

    def _on_provider_key_edited(self, row: QFrame, new_text: str) -> None:
        is_active = bool(new_text.strip())
        if is_active == row._is_active:
            self._update_active_count()
            return
        row._is_active = is_active
        if is_active:
            row.setStyleSheet("QFrame#provider_row { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(74,222,128,0.10), stop:1 rgba(91,106,255,0.05)); border: 1px solid rgba(74,222,128,0.35); border-radius: 10px; }")
        else:
            row.setStyleSheet("QFrame#provider_row { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }")
        row._status_dot.setStyleSheet(f"background: {'#4ade80' if is_active else '#6b7280'}; border-radius: 6px; border: 2px solid {'#22c55e' if is_active else '#4b5563'};")
        row._status_lbl.setText("ACTIVE" if is_active else "NOT SET")
        row._status_lbl.setStyleSheet(f"color: {'#4ade80' if is_active else '#6b7280'}; font-size: 7.5pt; font-weight: 800; letter-spacing: 0.4px;")
        self._update_active_count()

    def _update_active_count(self) -> None:
        total = 0
        active = 0
        for i in range(self.providers_scroll_layout.count() - 1):
            row = self.providers_scroll_layout.itemAt(i).widget()
            if not isinstance(row, QFrame) or row.objectName() != "provider_row":
                continue
            total += 1
            edit = row.findChild(QLineEdit)
            if edit and edit.text().strip():
                active += 1
        if hasattr(self, "active_count_label"):
            self.active_count_label.setText(f"Active {active} / {total}")

    def _custom_name_exists(self, name: str) -> bool:
        for i in range(self.custom_list.count()):
            cp = self.custom_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
            if cp.get("name") == name:
                return True
        return False

    def _collect_custom_providers(self) -> list[dict]:
        out: list[dict] = []
        for i in range(self.custom_list.count()):
            cp = self.custom_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
            out.append(dict(cp))
        return out

    def _rebuild_fallback_list(self):
        existing = self._collect_fallback_order()
        valid_ids: list[str] = [k for k in PROVIDER_PRESETS if k != "custom"]
        for cp in self._collect_custom_providers():
            valid_ids.append(custom_provider_id(cp))
        seen: set[str] = set()
        new_order: list[str] = []
        for pid in existing:
            if pid in valid_ids and pid not in seen:
                new_order.append(pid)
                seen.add(pid)
        for pid in valid_ids:
            if pid not in seen:
                new_order.append(pid)
                seen.add(pid)
        self.fallback_list.clear()
        for pid in new_order:
            label = PROVIDER_PRESETS[pid]["label"] if pid in PROVIDER_PRESETS else pid.replace("custom:", "Custom · ")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.fallback_list.addItem(item)

    def _collect_fallback_order(self) -> list[str]:
        out: list[str] = []
        for i in range(self.fallback_list.count()):
            item = self.fallback_list.item(i)
            pid = item.data(Qt.ItemDataRole.UserRole)
            if pid:
                out.append(pid)
        return out

    def _on_move_up(self):
        row = self.fallback_list.currentRow()
        if row <= 0:
            return
        item = self.fallback_list.takeItem(row)
        self.fallback_list.insertItem(row - 1, item)
        self.fallback_list.setCurrentRow(row - 1)

    def _on_move_down(self):
        row = self.fallback_list.currentRow()
        if row < 0 or row >= self.fallback_list.count() - 1:
            return
        item = self.fallback_list.takeItem(row)
        self.fallback_list.insertItem(row + 1, item)
        self.fallback_list.setCurrentRow(row + 1)

    def _load_values(self):
        self.hotkey_input.setText(self._cfg.hotkey)
        self.text_hotkey_input.setText(self._cfg.text_hotkey)
        for name, preset in THEME_PRESETS.items():
            if preset["accent"] == self._cfg.theme.accent:
                self.theme_combo.setCurrentText(name)
                break
        self.accent_preview.setStyleSheet(f"background: {self._cfg.theme.accent}; border-radius: 6px;")
        self.custom_list.clear()
        for cp in self._cfg.custom_providers:
            self._append_custom_row(cp)
        self._rebuild_provider_list()
        self._rebuild_fallback_list()

    def _apply_theme(self):
        t = self._cfg.theme
        self.setStyleSheet(generate_stylesheet(t) + _settings_extra_qss(t))
        if hasattr(self, "preview"):
            self.preview.setStyleSheet(f"background: {t.bg_secondary}; color: {t.text_primary}; border: 1px solid {t.accent}55; border-radius: 10px; padding: 12px; font-size: 9.5pt;")

    def _on_theme_changed(self, name):
        if name in THEME_PRESETS:
            preset = THEME_PRESETS[name]
            self._cfg.theme = ThemeConfig(**preset)
            self._apply_theme()
            self._style_active_pill()
            self.accent_preview.setStyleSheet(f"background: {preset['accent']}; border-radius: 6px;")

    def _pick_accent(self):
        color = QColorDialog.getColor(QColor(self._cfg.theme.accent), self, "Pick accent color", QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self._cfg.theme.accent = color.name()
            self._apply_theme()
            self._style_active_pill()
            self.accent_preview.setStyleSheet(f"background: {color.name()}; border-radius: 6px;")

    def _start_recording(self, which):
        if which == "crop":
            self.hotkey_input.setText("Press your hotkey...")
            self.hotkey_input.setFocus()
            self._recording = "crop"
        else:
            self.text_hotkey_input.setText("Press your hotkey...")
            self.text_hotkey_input.setFocus()
            self._recording = "text"

    def keyPressEvent(self, e: QKeyEvent):
        if not hasattr(self, "_recording") or not self._recording:
            super().keyPressEvent(e)
            return
        key = e.key()
        if key == Qt.Key.Key_Escape:
            if self._recording == "crop":
                self.hotkey_input.setText(self._cfg.hotkey)
            else:
                self.text_hotkey_input.setText(self._cfg.text_hotkey)
            self._recording = None
            return
        mods = e.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")
        from .setup_wizard import SetupWizard
        key_name = SetupWizard._key_name(None, key)
        if key_name and key_name not in ("ctrl", "alt", "shift", "win"):
            parts.append(key_name)
            combo = "+".join(parts)
            if self._recording == "crop":
                self.hotkey_input.setText(combo)
            else:
                self.text_hotkey_input.setText(combo)
            self._recording = None

    def _test_provider_key(self, pid: str, key_edit: QLineEdit, btn: QPushButton) -> None:
        api_key = key_edit.text().strip()
        if not api_key:
            self.status_label.setText("Paste a key first.")
            return
        btn.setEnabled(False)
        btn.setText("…")
        self.status_label.setText("Testing…")
        # Determine base_url for custom
        base_url = None
        if pid.startswith("custom:"):
            name = pid[len("custom:"):]
            for i in range(self.custom_list.count()):
                cp = self.custom_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
                if cp.get("name") == name:
                    base_url = cp.get("base_url")
                    break
        else:
            base_url = PROVIDER_PRESETS.get(pid, {}).get("base_url")
        # Use same fetcher as SettingsPanel
        self._fetcher = _ModelsFetcher(backend_url=self._cfg.backend_url, provider=pid if not pid.startswith("custom:") else "custom", api_key=api_key, base_url=base_url)
        # For custom, provider should be "custom" with base_url
        if pid.startswith("custom:"):
            self._fetcher = _ModelsFetcher(backend_url=self._cfg.backend_url, provider="custom", api_key=api_key, base_url=base_url)
        self._fetcher.fetched.connect(lambda models, b=btn: self._on_test_ok(b, models))
        self._fetcher.failed.connect(lambda err, b=btn: self._on_test_fail(b, err))
        self._fetcher.start()

    def _on_test_ok(self, btn: QPushButton, models):
        btn.setEnabled(True)
        btn.setText("Test")
        self.status_label.setText(f"OK — {len(models)} models")

    def _on_test_fail(self, btn: QPushButton, err: str):
        btn.setEnabled(True)
        btn.setText("Test")
        self.status_label.setText(f"Failed: {err[:80]}")

    def _on_save(self):
        # Validate hotkeys
        hotkey = self.hotkey_input.text().strip() or self._cfg.hotkey
        text_hotkey = self.text_hotkey_input.text().strip() or self._cfg.text_hotkey
        self._cfg.hotkey = hotkey
        self._cfg.text_hotkey = text_hotkey
        # Theme already mutated in _cfg.theme via combo/picker
        # Providers: collect keys from edits
        new_keys: dict[str, str] = {}
        for pid, edit in self._provider_key_edits.items():
            if pid.startswith("custom:"):
                continue
            val = edit.text().strip()
            if val:
                new_keys[pid] = val
        self._cfg.provider_keys = new_keys
        # Legacy single key: keep provider/api_key in sync with first active
        if self._cfg.provider in new_keys:
            self._cfg.api_key = new_keys[self._cfg.provider]
        elif new_keys:
            first_pid = next(iter(new_keys))
            self._cfg.provider = first_pid
            self._cfg.api_key = new_keys[first_pid]
        # Custom providers
        self._cfg.custom_providers = self._collect_custom_providers()
        # Fallback order
        self._cfg.fallback_order = self._collect_fallback_order()
        # Also handle preset keys that were edited but not in new_keys? already
        # For custom providers, their api_key lives inside custom_providers list, already captured
        # Also handle base_url for preset provider that is currently active? keep as is
        try:
            save_config(self._cfg)
            self.status_label.setText("Saved — restart SnipAI to apply hotkeys.")
            self.saved.emit()
            # Notify parent to refresh theme
            self._apply_theme()
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    def refresh(self):
        """Reload from disk and refresh UI (call when re-showing)."""
        self._cfg = load_config()
        self._load_values()
        self._apply_theme()
