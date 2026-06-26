"""Settings panel — opened from the popup to change config after initial setup.

Premium dark UI matching the Snip chat window: frameless rounded container with
drop shadow, draggable header, resize grip, themed via generate_stylesheet().
Tabs for Hotkeys, Theme, and Providers.
"""
from __future__ import annotations
import logging
import httpx
from PySide6.QtCore import Qt, QThread, Signal, QSize, QPoint, QRect, QEvent
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QGuiApplication, QCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QWidget, QFrame, QColorDialog, QTabWidget, QMessageBox,
    QListWidget, QListWidgetItem, QCheckBox, QScrollArea,
    QGraphicsDropShadowEffect,
)

from ..config import AppConfig, ThemeConfig, save_config, load_config, custom_provider_id
from .setup_wizard import PROVIDER_PRESETS, THEME_PRESETS, _ModelsFetcher
from .theme import generate_stylesheet

log = logging.getLogger(__name__)


def _settings_extra_qss(t: ThemeConfig) -> str:
    """Settings-specific QSS appended to the shared chat stylesheet."""
    return f"""
        QFrame#settings_header {{ background: transparent; }}
        QLabel#settings_title {{ color: #ffffff; font-size: 16pt; font-weight: 800; }}
        QLabel#settings_sub {{ color: {t.text_secondary}; font-size: 9pt; }}

        QTabWidget::pane {{ background: transparent; border: none; top: -1px; }}
        QTabBar {{ qproperty-drawBase: 0; }}
        QTabBar::tab {{
            background: rgba(255,255,255,0.04);
            color: {t.text_secondary};
            padding: 9px 20px;
            margin-right: 6px;
            border: 1px solid rgba(255,255,255,0.08);
            border-bottom: 2px solid transparent;
            border-top-left-radius: 9px;
            border-top-right-radius: 9px;
            font-size: 10pt;
            font-weight: 700;
        }}
        QTabBar::tab:hover {{ color: #ffffff; background: rgba(255,255,255,0.08); }}
        QTabBar::tab:selected {{
            color: #ffffff;
            background: rgba(255,255,255,0.07);
            border-bottom: 2px solid {t.accent};
            border-color: {t.accent}66;
        }}

        QLabel#section_title {{
            color: #ffffff; font-size: 12pt; font-weight: 800; letter-spacing: 0.3px;
        }}
        QLabel#field_label {{
            color: {t.text_secondary}; font-size: 9pt; font-weight: 700; letter-spacing: 0.4px;
        }}
        QLabel#hint_label {{ color: rgba(255,255,255,0.34); font-size: 8.5pt; }}
        QLabel#panel_title {{
            color: {t.accent}; font-weight: 800; font-size: 9.5pt; letter-spacing: 0.4px;
        }}

        QFrame#tab_card {{
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 14px;
        }}
        QFrame#panel_card {{
            background: #0f111d;
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 14px;
        }}

        QLineEdit {{
            background: rgba(255,255,255,0.04);
            color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 9px 12px;
            font-size: 10pt;
            selection-background-color: {t.accent}55;
        }}
        QLineEdit:focus {{ border: 1px solid {t.accent}; background: rgba(255,255,255,0.06); }}

        QComboBox {{
            background: rgba(255,255,255,0.04);
            color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 10pt;
        }}
        QComboBox:hover {{ border: 1px solid {t.accent}80; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {t.text_secondary};
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background: {t.bg_secondary}; color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;
            selection-background-color: {t.accent}55; selection-color: #ffffff;
            outline: 0; padding: 4px;
        }}

        QListWidget {{
            background: rgba(0,0,0,0.22);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 4px;
            font-size: 9.5pt;
            color: {t.text_primary};
            outline: 0;
        }}
        QListWidget::item {{ padding: 7px 9px; border-radius: 7px; }}
        QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}
        QListWidget::item:selected {{ background: {t.accent}40; color: #ffffff; }}

        QCheckBox {{ color: {t.text_primary}; font-size: 9.5pt; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 5px;
            background: rgba(255,255,255,0.04);
        }}
        QCheckBox::indicator:checked {{ background: {t.accent}; border: 1px solid {t.accent}; }}

        QSizeGrip#size_grip {{ background: transparent; }}
        QLabel#preview_card {{
            background: {t.bg_secondary};
            color: {t.text_primary};
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 16px;
            font-size: 10.5pt;
        }}
    """


class AddProviderDialog(QDialog):
    """Modal dialog for adding or editing a custom OpenAI-compatible provider."""

    def __init__(self, parent=None, existing: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Provider" if not existing else "Edit Provider")
        self.setMinimumSize(440, 420)
        self.resize(QSize(460, 460))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._edit_name = existing.get("name") if existing else None
        self._drag_offset: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        self.container = QFrame(self, objectName="root")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.container.setGraphicsEffect(shadow)
        outer.addWidget(self.container)
        cv = QVBoxLayout(self.container)
        cv.setContentsMargins(22, 18, 22, 18)
        cv.setSpacing(12)

        self.header = QFrame(objectName="settings_header")
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Add Provider" if not existing else "Edit Provider",
                       objectName="settings_title")
        header.addWidget(title)
        header.addStretch(1)
        btn_close = QPushButton("✕", objectName="close_btn")
        btn_close.setFixedSize(30, 30)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        header.addWidget(btn_close)
        cv.addWidget(self.header)

        cv.addWidget(QLabel("NAME", objectName="field_label"))
        self.name_input = QLineEdit(existing.get("name", "") if existing else "")
        self.name_input.setPlaceholderText("Local Ollama")
        cv.addWidget(self.name_input)

        cv.addWidget(QLabel("BASE URL", objectName="field_label"))
        self.base_url_input = QLineEdit(existing.get("base_url", "") if existing else "")
        self.base_url_input.setPlaceholderText("http://localhost:11434/v1")
        cv.addWidget(self.base_url_input)

        cv.addWidget(QLabel("API KEY (OPTIONAL)", objectName="field_label"))
        self.api_key_input = QLineEdit(existing.get("api_key", "") if existing else "")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        cv.addWidget(self.api_key_input)

        cv.addWidget(QLabel("DEFAULT MODEL", objectName="field_label"))
        self.model_input = QLineEdit(existing.get("model", "") if existing else "")
        self.model_input.setPlaceholderText("llava")
        cv.addWidget(self.model_input)

        detect_row = QHBoxLayout()
        self.vision_check = QCheckBox("Vision-capable")
        self.vision_check.setChecked(bool(existing.get("vision", True)) if existing else True)
        detect_row.addWidget(self.vision_check)
        detect_row.addStretch(1)
        self.btn_detect = QPushButton("Detect models…")
        self.btn_detect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detect.clicked.connect(self._detect_models)
        detect_row.addWidget(self.btn_detect)
        cv.addLayout(detect_row)

        self.status_label = QLabel("", objectName="hint_label")
        cv.addWidget(self.status_label)

        self.models_combo = QComboBox()
        self.models_combo.setEditable(True)
        self.models_combo.setVisible(False)
        cv.addWidget(self.models_combo)

        cv.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        btn_save = QPushButton("Save", objectName="primary")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save)
        footer.addWidget(btn_save)
        cv.addLayout(footer)

        cfg = load_config()
        self.setStyleSheet(generate_stylesheet(cfg.theme) + _settings_extra_qss(cfg.theme))

    def showEvent(self, e):
        super().showEvent(e)
        self._center_on_parent()
        # Both parent and this dialog are always-on-top; ensure we land in front.
        self.raise_()
        self.activateWindow()

    def _center_on_parent(self):
        par = self.parent()
        if par is not None and par.isVisible():
            geo = par.frameGeometry()
            self.move(geo.center() - self.rect().center())
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        self.move(sg.center() - self.rect().center())

    # ── Header drag ────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            top_left = self.header.mapTo(self, QPoint(0, 0))
            if QRect(top_left, self.header.size()).contains(e.position().toPoint()):
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

    def _detect_models(self):
        base_url = self.base_url_input.text().strip()
        if not base_url:
            self.status_label.setText("Enter a base URL first.")
            return
        self.status_label.setText("Fetching…")
        self.btn_detect.setEnabled(False)
        # Resolve backend URL: prefer parent settings' config, else global.
        backend_url = load_config().backend_url
        parent = self.parent()
        if isinstance(parent, SettingsPanel):
            backend_url = parent._cfg.backend_url
        self._fetcher = _ModelsFetcher(
            backend_url=backend_url,
            provider="custom",
            api_key=self.api_key_input.text().strip(),
            base_url=base_url,
        )
        self._fetcher.fetched.connect(self._on_detected)
        self._fetcher.failed.connect(self._on_detect_failed)
        self._fetcher.start()

    def _on_detected(self, models):
        self.btn_detect.setEnabled(True)
        self.models_combo.clear()
        if not models:
            self.status_label.setText("No models returned. Type one manually.")
            return
        if isinstance(models[0], dict):
            ids = [m.get("id") or m.get("name") for m in models if (m.get("id") or m.get("name"))]
            vision = any(m.get("vision") for m in models if isinstance(m, dict))
            self.vision_check.setChecked(vision)
        else:
            ids = [str(m) for m in models]
            self.vision_check.setChecked(any(
                ("vision" in mid.lower() or "vl" in mid.lower() or "scout" in mid.lower()
                 or "llava" in mid.lower() or "qvq" in mid.lower())
                for mid in ids
            ))
        self.models_combo.setVisible(True)
        self.models_combo.addItems(ids)
        if ids:
            self.models_combo.setCurrentIndex(0)
        self.status_label.setText(f"Found {len(ids)} models.")

    def _on_detect_failed(self, err):
        self.btn_detect.setEnabled(True)
        self.status_label.setText(f"Failed: {err}")

    def _on_save(self):
        name = self.name_input.text().strip()
        base_url = self.base_url_input.text().strip()
        if not name or not base_url:
            QMessageBox.warning(self, "Add Provider", "Name and base URL are required.")
            return
        if not name.replace("_", "").replace("-", "").isalnum() and " " in name:
            QMessageBox.warning(self, "Add Provider", "Name cannot contain spaces.")
            return
        # Pick a model from the combo if user picked one, else from the text field.
        model = self.model_input.text().strip()
        if not model and self.models_combo.count() > 0:
            model = self.models_combo.currentText().strip()
        self._result = {
            "name": name,
            "base_url": base_url,
            "api_key": self.api_key_input.text().strip(),
            "model": model,
            "vision": self.vision_check.isChecked(),
        }
        self.accept()

    def result_provider(self) -> dict:
        return getattr(self, "_result", {})


class SettingsPanel(QDialog):
    """All-in-one settings panel — tabs for Hotkeys, Theme, Providers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SnipAI Settings")
        self.setMinimumSize(QSize(620, 520))
        self.resize(QSize(880, 700))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._cfg = load_config()
        self._fetcher: _ModelsFetcher | None = None
        self._drag_offset: QPoint | None = None
        # Edge-drag resize state
        self._resize_edge: str = ""
        self._resize_start_geo: QRect | None = None
        self._resize_start_mouse: QPoint | None = None
        self._RESIZE_MARGIN = 8

        self._build_ui()
        self._load_values()
        self._apply_theme()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        container = QFrame(self, objectName="root")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 190))
        container.setGraphicsEffect(shadow)
        container.setMouseTracking(True)
        outer.addWidget(container)
        self.container = container
        self._root = container
        cv = QVBoxLayout(container)
        cv.setContentsMargins(26, 22, 26, 20)
        cv.setSpacing(14)

        # Top bar: draggable title area + close button.
        # The title area is transparent for mouse events so clicks pass through
        # to the dialog and trigger the dialog-level drag handler. The close
        # button stays separate and clickable.
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)

        self.header = QFrame(objectName="settings_header")
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.header.setMouseTracking(True)
        hh = QHBoxLayout(self.header)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(2)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(QLabel("Settings", objectName="settings_title"))
        title_col.addWidget(QLabel("Configure providers, hotkeys, and appearance",
                                   objectName="settings_sub"))
        hh.addLayout(title_col)
        hh.addStretch(1)
        top_bar.addWidget(self.header, 1)

        # Install event filter for header dragging
        self.header.installEventFilter(self)
        for child in self.header.findChildren(QWidget):
            child.installEventFilter(self)

        btn_close = QPushButton("✕", objectName="close_btn")
        btn_close.setFixedSize(32, 32)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        top_bar.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignTop)
        cv.addLayout(top_bar)

        # Tabs
        self.tabs = QTabWidget()
        cv.addWidget(self.tabs, 1)

        self._build_tab_hotkeys()
        self._build_tab_theme()
        self._build_tab_providers()

        # Footer
        footer = QHBoxLayout()
        self.status_label = QLabel("", objectName="hint_label")
        footer.addWidget(self.status_label)
        footer.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.close)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("Save Changes", objectName="primary")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save)
        footer.addWidget(btn_save)
        cv.addLayout(footer)

    def _wrap_card(self, inner: QWidget) -> QWidget:
        """Wrap a tab's content in a rounded card with comfortable padding."""
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(2, 12, 2, 2)
        pl.setSpacing(0)
        card = QFrame(objectName="tab_card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(12)
        cl.addWidget(inner)
        pl.addWidget(card, 1)
        return page

    def _build_tab_hotkeys(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

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

        hint = QLabel("Click a field, then press the key combination you want. "
                      "Hotkey changes apply after restarting SnipAI.",
                      objectName="hint_label")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addStretch(1)
        self.tabs.addTab(self._wrap_card(inner), "Hotkeys")

    def _build_tab_theme(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

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
        color_row.setSpacing(10)
        self.accent_preview = QLabel()
        self.accent_preview.setFixedSize(44, 32)
        self.accent_preview.setStyleSheet("background: #5b6aff; border-radius: 8px;")
        color_row.addWidget(self.accent_preview)
        self.accent_btn = QPushButton("Pick color…")
        self.accent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accent_btn.clicked.connect(self._pick_accent)
        color_row.addWidget(self.accent_btn)
        color_row.addStretch(1)
        v.addLayout(color_row)

        v.addWidget(QLabel("PREVIEW", objectName="field_label"))
        self.preview = QLabel("This is how your popup text and accents will look.",
                              objectName="preview_card")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(72)
        v.addWidget(self.preview)

        v.addStretch(1)
        self.tabs.addTab(self._wrap_card(inner), "Theme")

    def _build_tab_providers(self):
        """Multi-provider config: provider status list, custom providers, fallback order."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(2, 12, 2, 2)
        outer.setSpacing(12)

        # ── Status header with count ──
        header_row = QHBoxLayout()
        header_lbl = QLabel("Providers & API keys", objectName="section_title")
        header_row.addWidget(header_lbl)
        header_row.addStretch(1)
        self.active_count_label = QLabel("")
        self.active_count_label.setObjectName("active_count_label")
        self._style_active_pill()
        header_row.addWidget(self.active_count_label)
        outer.addLayout(header_row)

        # ── Scrollable provider list (takes most of the space) ──
        self.providers_scroll = QScrollArea(objectName="feed_scroll")
        self.providers_scroll.setWidgetResizable(True)
        self.providers_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.providers_scroll.setMinimumHeight(150)
        self.providers_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.providers_scroll_body = QWidget()
        self.providers_scroll_layout = QVBoxLayout(self.providers_scroll_body)
        self.providers_scroll_layout.setContentsMargins(2, 2, 2, 2)
        self.providers_scroll_layout.setSpacing(8)
        self.providers_scroll_layout.addStretch(1)
        self.providers_scroll.setWidget(self.providers_scroll_body)
        outer.addWidget(self.providers_scroll, 1)

        self._provider_key_edits: dict[str, QLineEdit] = {}

        # ── Custom providers + Fallback order side-by-side ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        # Custom providers (left).
        custom_box = QFrame(objectName="panel_card")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.setContentsMargins(12, 12, 12, 12)
        custom_layout.setSpacing(8)
        custom_layout.addWidget(QLabel("CUSTOM PROVIDERS", objectName="panel_title"))
        self.custom_list = QListWidget()
        self.custom_list.setMinimumHeight(70)
        self.custom_list.setMaximumHeight(120)
        custom_layout.addWidget(self.custom_list)
        custom_btns = QHBoxLayout()
        custom_btns.setSpacing(6)
        for label, slot in (
            ("Add…", self._on_add_custom),
            ("Edit", self._on_edit_custom),
            ("Del", self._on_delete_custom),
        ):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            custom_btns.addWidget(b)
        custom_btns.addStretch(1)
        custom_layout.addLayout(custom_btns)
        bottom_row.addWidget(custom_box, 1)

        # Fallback order (right).
        order_box = QFrame(objectName="panel_card")
        order_layout = QVBoxLayout(order_box)
        order_layout.setContentsMargins(12, 12, 12, 12)
        order_layout.setSpacing(8)
        order_layout.addWidget(QLabel("FALLBACK ORDER", objectName="panel_title"))
        self.fallback_list = QListWidget()
        self.fallback_list.setMinimumHeight(70)
        self.fallback_list.setMaximumHeight(120)
        order_layout.addWidget(self.fallback_list)
        order_btns = QHBoxLayout()
        order_btns.setSpacing(6)
        for label, slot in (
            ("↑ Up", self._on_move_up),
            ("↓ Down", self._on_move_down),
        ):
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            order_btns.addWidget(b)
        order_btns.addStretch(1)
        order_layout.addLayout(order_btns)
        bottom_row.addWidget(order_box, 1)

        outer.addLayout(bottom_row)

        # Footer hint.
        hint = QLabel(
            "Tip: a row glows green when an API key is set. Add more keys to keep "
            "snips working when one provider rate-limits you."
        )
        hint.setObjectName("hint_label")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.tabs.addTab(page, "Providers")

    def _rebuild_provider_list(self) -> None:
        """Re-render the provider status list (presets + custom)."""
        # Remove all existing rows (keep stretch at the end).
        while self.providers_scroll_layout.count() > 1:
            item = self.providers_scroll_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        total = 0
        active = 0

        # Preset providers.
        for key, preset in PROVIDER_PRESETS.items():
            if key == "custom":
                continue
            total += 1
            stored = self._cfg.provider_keys.get(key, "")
            if not stored and self._cfg.provider == key:
                stored = self._cfg.api_key
            if stored:
                active += 1
            row = self._make_provider_row(
                pid=key,
                label=preset["label"],
                kind="Preset",
                api_key=stored,
                base_url=preset.get("base_url", ""),
                vision=None,
                t=self._cfg.theme,
            )
            self.providers_scroll_layout.insertWidget(
                self.providers_scroll_layout.count() - 1, row
            )

        # Custom providers.
        for cp in self._collect_custom_providers():
            total += 1
            if cp.get("api_key", "") or cp.get("base_url", ""):
                active += 1
            row = self._make_provider_row(
                pid=custom_provider_id(cp),
                label=cp.get("name", "?"),
                kind="Custom",
                api_key=cp.get("api_key", ""),
                base_url=cp.get("base_url", ""),
                vision=bool(cp.get("vision", True)),
                t=self._cfg.theme,
            )
            self.providers_scroll_layout.insertWidget(
                self.providers_scroll_layout.count() - 1, row
            )

        self.active_count_label.setText(f"Active {active} / {total}")

    def _style_active_pill(self) -> None:
        """Style the Active N/M pill, anchored on the theme accent."""
        t = self._cfg.theme
        self.active_count_label.setStyleSheet(
            "color: #ffffff; font-size: 9pt; font-weight: 800; "
            "padding: 4px 12px; border-radius: 999px; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {t.accent}, stop:1 #8b5cf6);"
        )

    def _make_provider_row(self, pid: str, label: str, kind: str,
                           api_key: str, base_url: str,
                           vision: bool | None,
                           t: ThemeConfig | None = None) -> QFrame:
        """Build a single row widget for the provider list."""
        if t is None:
            t = self._cfg.theme
        is_active = bool(api_key)
        row = QFrame()
        row.setObjectName("provider_row")
        row.setMinimumHeight(64)
        if is_active:
            row.setStyleSheet(
                "QFrame#provider_row {"
                "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                "    stop:0 rgba(74,222,128,0.10), stop:1 rgba(91,106,255,0.05));"
                "  border: 1px solid rgba(74,222,128,0.35);"
                "  border-radius: 12px;"
                "}"
            )
        else:
            row.setStyleSheet(
                "QFrame#provider_row {"
                "  background: rgba(255,255,255,0.03);"
                "  border: 1px solid rgba(255,255,255,0.08);"
                "  border-radius: 12px;"
                "}"
            )

        hl = QHBoxLayout(row)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(12)

        # Status indicator: colored dot + status pill.
        status_col = QVBoxLayout()
        status_col.setSpacing(4)
        dot = QLabel()
        dot.setFixedSize(14, 14)
        dot.setStyleSheet(
            f"background: {'#4ade80' if is_active else '#6b7280'}; "
            f"border-radius: 7px; "
            f"border: 2px solid {'#22c55e' if is_active else '#4b5563'};"
        )
        dot_col = QHBoxLayout()
        dot_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot_col.addWidget(dot)
        status_col.addLayout(dot_col)
        status_lbl = QLabel("ACTIVE" if is_active else "NOT SET")
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setStyleSheet(
            f"color: {'#4ade80' if is_active else '#6b7280'}; "
            f"font-size: 7.5pt; font-weight: 800; letter-spacing: 0.5px;"
        )
        status_lbl.setMinimumWidth(58)
        status_col.addWidget(status_lbl)
        hl.addLayout(status_col)

        # Name + meta column.
        name_col = QVBoxLayout()
        name_col.setSpacing(3)
        name_lbl = QLabel(label)
        name_lbl.setStyleSheet("font-weight: 700; font-size: 10.5pt; color: #e2e8f0;")
        name_col.addWidget(name_lbl)
        sub_parts = [kind]
        if base_url:
            sub_parts.append(base_url)
        if vision is True:
            sub_parts.append("vision")
        sub_lbl = QLabel("  ·  ".join(sub_parts))
        sub_lbl.setStyleSheet(f"color: {t.accent}; font-size: 8pt;")
        sub_lbl.setWordWrap(False)
        sub_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_col.addWidget(sub_lbl)
        hl.addLayout(name_col, 1)

        # API key field.
        key_edit = QLineEdit(api_key)
        key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_edit.setPlaceholderText("paste API key…")
        key_edit.setMinimumWidth(180)
        key_edit.setMinimumHeight(34)
        key_edit.setStyleSheet(
            "QLineEdit {"
            "  background: rgba(0,0,0,0.25);"
            "  border: 1px solid rgba(255,255,255,0.10);"
            "  border-radius: 8px;"
            "  padding: 6px 10px;"
            "  color: #e2e8f0;"
            "  font-size: 9.5pt;"
            "  font-family: 'Cascadia Code', 'Consolas', monospace;"
            "}"
            f"QLineEdit:focus {{ border: 1px solid {t.accent}; }}"
        )
        # Track which visual elements belong to this row for live updates.
        row._status_lbl = status_lbl
        row._status_dot = dot
        row._is_active = is_active

        key_edit.textChanged.connect(
            lambda txt, r=row: self._on_provider_key_edited(r, txt)
        )
        self._provider_key_edits[pid] = key_edit
        hl.addWidget(key_edit, 0)

        # Show/hide toggle.
        show_btn = QPushButton("👁")
        show_btn.setFixedSize(34, 34)
        show_btn.setCheckable(True)
        show_btn.setToolTip("Show/hide key")
        show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        show_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.05); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; "
            "font-size: 11pt; }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); }"
            f"QPushButton:checked {{ background: {t.accent}40; }}"
        )
        show_btn.toggled.connect(
            lambda on, e=key_edit: e.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        hl.addWidget(show_btn, 0)

        # Test key button.
        test_btn = QPushButton("Test")
        test_btn.setFixedSize(46, 34)
        test_btn.setToolTip("Verify this API key works")
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; "
            "color: rgba(255,255,255,0.6); font-size: 8pt; font-weight: 700; }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); color: #ffffff; }"
        )
        test_btn.clicked.connect(
            lambda _, b=test_btn, e=key_edit, p=pid: self._test_provider_key(p, e, b)
        )
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
        if dlg.exec() == QDialog.DialogCode.Accepted:
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
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cp = dlg.result_provider()
            new_name = cp.get("name", "")
            if new_name != existing.get("name") and self._custom_name_exists(new_name):
                QMessageBox.warning(self, "Custom Providers", f"A provider named '{new_name}' already exists.")
                return
            # Replace in list.
            self.custom_list.takeItem(self.custom_list.row(item))
            self._append_custom_row(cp)
            # If name changed, update fallback order entries too.
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
        """Live update of the row's visual + active count when a key changes."""
        is_active = bool(new_text.strip())
        if is_active == row._is_active:
            # Recompute the global count anyway because other rows may have changed
            # in ways we don't track here (rare path: programmatic set).
            self._update_active_count()
            return
        row._is_active = is_active
        # Restyle the row.
        if is_active:
            row.setStyleSheet(
                "QFrame#provider_row {"
                "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                "    stop:0 rgba(74,222,128,0.10), stop:1 rgba(91,106,255,0.05));"
                "  border: 1px solid rgba(74,222,128,0.35);"
                "  border-radius: 12px;"
                "}"
            )
        else:
            row.setStyleSheet(
                "QFrame#provider_row {"
                "  background: rgba(255,255,255,0.03);"
                "  border: 1px solid rgba(255,255,255,0.08);"
                "  border-radius: 12px;"
                "}"
            )
        row._status_dot.setStyleSheet(
            f"background: {'#4ade80' if is_active else '#6b7280'}; "
            f"border-radius: 7px; "
            f"border: 2px solid {'#22c55e' if is_active else '#4b5563'};"
        )
        row._status_lbl.setText("ACTIVE" if is_active else "NOT SET")
        row._status_lbl.setStyleSheet(
            f"color: {'#4ade80' if is_active else '#6b7280'}; "
            f"font-size: 7.5pt; font-weight: 800; letter-spacing: 0.5px;"
        )
        self._update_active_count()

    def _update_active_count(self) -> None:
        """Recompute the active/total pill from current row states."""
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
        # Preserve existing order; remove providers that no longer exist; add new ones.
        existing = self._collect_fallback_order()
        # All valid ids: presets (minus the 'custom' template) + custom providers.
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
        """Populate UI from current config."""
        # Hotkeys tab
        self.hotkey_input.setText(self._cfg.hotkey)
        self.text_hotkey_input.setText(self._cfg.text_hotkey)

        # Theme tab
        for name, preset in THEME_PRESETS.items():
            if preset["accent"] == self._cfg.theme.accent:
                self.theme_combo.setCurrentText(name)
                break
        self.accent_preview.setStyleSheet(f"background: {self._cfg.theme.accent}; border-radius: 8px;")

        # Providers tab — populate custom providers from saved config
        self.custom_list.clear()
        for cp in self._cfg.custom_providers:
            self._append_custom_row(cp)
        # Rebuild lists now that custom_list is populated
        self._rebuild_provider_list()
        self._rebuild_fallback_list()

    def _apply_theme(self):
        t = self._cfg.theme
        self.setStyleSheet(generate_stylesheet(t) + _settings_extra_qss(t))
        # Update preview accent tint
        if hasattr(self, "preview"):
            self.preview.setStyleSheet(
                f"background: {t.bg_secondary}; color: {t.text_primary}; "
                f"border: 1px solid {t.accent}55; border-radius: 12px; "
                f"padding: 16px; font-size: 10.5pt;"
            )

    def showEvent(self, e):
        super().showEvent(e)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._center_on_screen)
        self.raise_()
        self.activateWindow()

    def _center_on_screen(self):
        par = self.parent()
        if par is not None and par.isVisible():
            screen = QGuiApplication.screenAt(par.frameGeometry().center())
        else:
            screen = QGuiApplication.screenAt(QCursor.pos())
        screen = screen or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()
        # Shrink to fit the screen if the dialog is taller/wider than it.
        w = min(self.width(), sg.width())
        h = min(self.height(), sg.height())
        if w != self.width() or h != self.height():
            self.resize(w, h)
        # Center, then clamp so no edge (esp. the top) goes off-screen.
        pt = sg.center() - self.rect().center()
        x = max(sg.left(), min(pt.x(), sg.right() - self.width()))
        y = max(sg.top(), min(pt.y(), sg.bottom() - self.height()))
        self.move(x, y)

    def resizeEvent(self, e):
        super().resizeEvent(e)

    # ── Edge-drag resize + header drag ─────────────────────
    def eventFilter(self, obj, e):
        """Forward header-area mouse events to the dialog so dragging works
        even when the press lands on a child label (not the bare dialog)."""
        if obj is self.header or (self.header is not None and self.header.isAncestorOf(obj)):
            etype = e.type()
            if etype == QEvent.Type.MouseButtonPress:
                self.mousePressEvent(e)
                return True
            if etype == QEvent.Type.MouseMove:
                self.mouseMoveEvent(e)
                return True
            if etype == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(e)
                return True
        return super().eventFilter(obj, e)

    def _edge_at(self, pos: QPoint) -> str:
        m = self._RESIZE_MARGIN
        r = self.rect()
        ox = oy = 14  # translucent outer margin around #root
        if pos.x() < ox - m or pos.x() > r.width() - ox + m:
            return ""
        if pos.y() < oy - m or pos.y() > r.height() - oy + m:
            return ""
        left = pos.x() <= ox + m
        right = pos.x() >= r.width() - ox - m
        top = pos.y() <= oy + m
        bottom = pos.y() >= r.height() - oy - m
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
            edge = self._edge_at(self.mapFromGlobal(e.globalPosition().toPoint()))
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_mouse = e.globalPosition().toPoint()
                e.accept()
                return
            # Header drag — use global coordinates so this works whether the
            # event came from the dialog or a forwarded child (label) event.
            hdr_top_left = self.header.mapToGlobal(QPoint(0, 0))
            hdr_rect = QRect(hdr_top_left, self.header.size())
            if hdr_rect.contains(e.globalPosition().toPoint()):
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._resize_edge and (e.buttons() & Qt.MouseButton.LeftButton):
            self._do_resize(e.globalPosition().toPoint())
            e.accept()
            return
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            edge = self._edge_at(self.mapFromGlobal(e.globalPosition().toPoint()))
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

    def _on_theme_changed(self, name):
        if name in THEME_PRESETS:
            preset = THEME_PRESETS[name]
            self._cfg.theme = ThemeConfig(**preset)
            self._apply_theme()
            self._style_active_pill()
            self.accent_preview.setStyleSheet(f"background: {preset['accent']}; border-radius: 8px;")

    def _pick_accent(self):
        # Use Qt's own picker (not the native Win32 dialog) so it respects the
        # parent's always-on-top stacking instead of hiding behind the panel.
        color = QColorDialog.getColor(
            QColor(self._cfg.theme.accent), self, "Pick accent color",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if color.isValid():
            self._cfg.theme.accent = color.name()
            self._apply_theme()
            self._style_active_pill()
            self.accent_preview.setStyleSheet(f"background: {color.name()}; border-radius: 8px;")

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

        # Use same key mapping as wizard
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
        """Fire a quick models-list call to verify the API key is valid."""
        api_key = key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Test Key", "Paste an API key first.")
            return
        btn.setText("…")
        btn.setEnabled(False)

        # Resolve base_url for custom providers.
        base_url = None
        if pid.startswith("custom:"):
            for cp in self._collect_custom_providers():
                from ..config import custom_provider_id
                if custom_provider_id(cp) == pid:
                    base_url = cp.get("base_url", "")
                    break
            provider_for_backend = "custom"
        else:
            provider_for_backend = pid

        backend_url = self._cfg.backend_url
        self._test_fetcher = _ModelsFetcher(
            backend_url=backend_url,
            provider=provider_for_backend,
            api_key=api_key,
            base_url=base_url or "",
        )

        def on_ok(models):
            btn.setText("✓")
            btn.setStyleSheet(
                btn.styleSheet() +
                "QPushButton { color: #4ade80 !important; border-color: #4ade80 !important; }"
            )
            btn.setEnabled(True)
            count = len(models) if isinstance(models, list) else "?"
            self.status_label.setText(f"✓ {pid}: key valid — {count} models available")

        def on_fail(err):
            btn.setText("✗")
            btn.setStyleSheet(
                btn.styleSheet() +
                "QPushButton { color: #f87171 !important; border-color: #f87171 !important; }"
            )
            btn.setEnabled(True)
            self.status_label.setText(f"✗ {pid}: {err[:120]}")

        self._test_fetcher.fetched.connect(on_ok)
        self._test_fetcher.failed.connect(on_fail)
        self._test_fetcher.start()

    def _on_save(self):
        """Validate and save config."""
        # ── Persist per-provider keys ──
        for key, edit in self._provider_key_edits.items():
            val = edit.text().strip()
            if val:
                self._cfg.provider_keys[key] = val
            else:
                # Don't keep empty entries.
                self._cfg.provider_keys.pop(key, None)

        # ── Persist custom providers (from list) ──
        self._cfg.custom_providers = self._collect_custom_providers()

        # ── Persist fallback order (from list) ──
        self._cfg.fallback_order = self._collect_fallback_order()

        # ── Active provider + model ──
        # If user toggled "Free only", the popup already auto-picked; mirror
        # that into cfg for use by the worker at startup.
        # Here we simply keep the existing provider unless the config has none.
        if not self._cfg.provider:
            self._cfg.provider = "groq"
        # Pick the first provider with a key as the active one if current is dead.
        if not self._cfg.provider_keys.get(self._cfg.provider, "") and not self._cfg.api_key:
            for pid in self._cfg.fallback_order:
                if self._cfg.provider_keys.get(pid, ""):
                    self._cfg.provider = pid
                    break

        self._cfg.hotkey = self.hotkey_input.text().strip() or "ctrl+shift+space"
        self._cfg.text_hotkey = self.text_hotkey_input.text().strip() or "ctrl+alt+g"
        # theme already updated via _on_theme_changed / _pick_accent

        # Require at least one configured key.
        if not self._cfg.provider_keys and not self._cfg.api_key:
            QMessageBox.warning(
                self, "Settings",
                "Add at least one API key in the Providers tab first."
            )
            return

        self._cfg.setup_complete = True
        save_config(self._cfg)
        self.status_label.setText("Saved. Restart SnipAI to apply hotkeys.")
        QMessageBox.information(
            self, "Settings", "Settings saved. Hotkey changes will apply on next app restart."
        )
        self.accept()
