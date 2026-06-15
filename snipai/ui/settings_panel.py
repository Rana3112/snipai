"""Settings panel — opened from tray to change config after initial setup.

Reuses wizard widgets but shows all on one page, no progression.
"""
from __future__ import annotations
import logging
import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QWidget, QFrame, QColorDialog, QTabWidget, QMessageBox,
    QListWidget, QListWidgetItem, QCheckBox, QScrollArea,
)

from ..config import AppConfig, ThemeConfig, save_config, load_config, custom_provider_id
from .setup_wizard import PROVIDER_PRESETS, THEME_PRESETS, _ModelsFetcher

log = logging.getLogger(__name__)


class AddProviderDialog(QDialog):
    """Modal dialog for adding or editing a custom OpenAI-compatible provider."""

    def __init__(self, parent=None, existing: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Provider" if not existing else "Edit Provider")
        self.setMinimumSize(420, 360)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._edit_name = existing.get("name") if existing else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame(self)
        outer.addWidget(self.container)
        cv = QVBoxLayout(self.container)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Add Provider" if not existing else "Edit Provider")
        title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        btn_close = QPushButton("✕")
        btn_close.setObjectName("close_btn")
        btn_close.setFixedSize(28, 28)
        btn_close.clicked.connect(self.reject)
        header.addWidget(btn_close)
        cv.addLayout(header)

        cv.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit(existing.get("name", "") if existing else "")
        self.name_input.setPlaceholderText("Local Ollama")
        cv.addWidget(self.name_input)

        cv.addWidget(QLabel("Base URL:"))
        self.base_url_input = QLineEdit(existing.get("base_url", "") if existing else "")
        self.base_url_input.setPlaceholderText("http://localhost:11434/v1")
        cv.addWidget(self.base_url_input)

        cv.addWidget(QLabel("API Key (optional):"))
        self.api_key_input = QLineEdit(existing.get("api_key", "") if existing else "")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        cv.addWidget(self.api_key_input)

        cv.addWidget(QLabel("Default model:"))
        self.model_input = QLineEdit(existing.get("model", "") if existing else "")
        self.model_input.setPlaceholderText("llava")
        cv.addWidget(self.model_input)

        detect_row = QHBoxLayout()
        self.vision_check = QCheckBox("Vision-capable")
        self.vision_check.setChecked(bool(existing.get("vision", True)) if existing else True)
        detect_row.addWidget(self.vision_check)
        detect_row.addStretch(1)
        self.btn_detect = QPushButton("Detect models…")
        self.btn_detect.clicked.connect(self._detect_models)
        detect_row.addWidget(self.btn_detect)
        cv.addLayout(detect_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8b9aff; font-size: 9pt;")
        cv.addWidget(self.status_label)

        self.models_combo = QComboBox()
        self.models_combo.setEditable(True)
        self.models_combo.setVisible(False)
        cv.addWidget(self.models_combo)

        cv.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        btn_save = QPushButton("Save")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._on_save)
        footer.addWidget(btn_save)
        cv.addLayout(footer)

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
        self.result = {
            "name": name,
            "base_url": base_url,
            "api_key": self.api_key_input.text().strip(),
            "model": model,
            "vision": self.vision_check.isChecked(),
        }
        self.accept()

    def result_provider(self) -> dict:
        return getattr(self, "result", {})


class SettingsPanel(QDialog):
    """All-in-one settings panel — tabs for Provider, Hotkeys, Theme, Providers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SnipAI Settings")
        self.setMinimumSize(620, 540)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._cfg = load_config()
        self._fetcher: _ModelsFetcher | None = None

        self._build_ui()
        self._load_values()
        self._apply_theme()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame(self)
        outer.addWidget(container)
        self.container = container
        cv = QVBoxLayout(container)
        cv.setContentsMargins(24, 20, 24, 20)
        cv.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 16pt; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        btn_close = QPushButton("✕")
        btn_close.setObjectName("close_btn")
        btn_close.setFixedSize(32, 32)
        btn_close.clicked.connect(self.close)
        header.addWidget(btn_close)
        cv.addLayout(header)

        # Tabs
        self.tabs = QTabWidget()
        cv.addWidget(self.tabs, 1)

        self._build_tab_hotkeys()
        self._build_tab_theme()
        self._build_tab_providers()

        # Footer
        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8b9aff; font-size: 9pt;")
        footer.addWidget(self.status_label)
        footer.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.close)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("Save")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._on_save)
        footer.addWidget(btn_save)
        cv.addLayout(footer)

    def _build_tab_hotkeys(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        v.addWidget(QLabel("Crop hotkey:"))
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setReadOnly(True)
        self.hotkey_input.mousePressEvent = lambda e: self._start_recording("crop")
        v.addWidget(self.hotkey_input)

        v.addWidget(QLabel("Text hotkey:"))
        self.text_hotkey_input = QLineEdit()
        self.text_hotkey_input.setReadOnly(True)
        self.text_hotkey_input.mousePressEvent = lambda e: self._start_recording("text")
        v.addWidget(self.text_hotkey_input)

        v.addStretch(1)
        self.tabs.addTab(page, "Hotkeys")

    def _build_tab_theme(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        v.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        for name in THEME_PRESETS:
            self.theme_combo.addItem(name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        v.addWidget(self.theme_combo)

        v.addWidget(QLabel("Accent color:"))
        color_row = QHBoxLayout()
        self.accent_btn = QPushButton("Pick...")
        self.accent_btn.clicked.connect(self._pick_accent)
        color_row.addWidget(self.accent_btn)
        self.accent_preview = QLabel()
        self.accent_preview.setFixedSize(40, 30)
        self.accent_preview.setStyleSheet("background: #5b6aff; border-radius: 6px;")
        color_row.addWidget(self.accent_preview)
        color_row.addStretch(1)
        v.addLayout(color_row)

        # Preview
        v.addWidget(QLabel("Preview:"))
        self.preview = QLabel("This is how your popup will look.")
        self.preview.setMinimumHeight(60)
        v.addWidget(self.preview)

        v.addStretch(1)
        self.tabs.addTab(page, "Theme")

    def _build_tab_providers(self):
        """Multi-provider config: provider status list, custom providers, fallback order."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # ── Status header with count ──
        header_row = QHBoxLayout()
        header_lbl = QLabel("Providers & API keys")
        header_lbl.setStyleSheet("font-size: 12pt; font-weight: 800; letter-spacing: 0.3px;")
        header_row.addWidget(header_lbl)
        header_row.addStretch(1)
        self.active_count_label = QLabel("")
        self.active_count_label.setObjectName("active_count_label")
        self.active_count_label.setStyleSheet(
            "color: #ffffff; font-size: 9pt; font-weight: 800; "
            "padding: 4px 12px; border-radius: 999px; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #5b6aff, stop:1 #8b5cf6);"
        )
        header_row.addWidget(self.active_count_label)
        outer.addLayout(header_row)

        # ── Scrollable provider list (takes most of the space) ──
        self.providers_scroll = QScrollArea()
        self.providers_scroll.setWidgetResizable(True)
        self.providers_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.providers_scroll.setMinimumHeight(260)
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
        bottom_row.setSpacing(10)

        # Custom providers (left).
        custom_box = QFrame()
        custom_box.setObjectName("panel_card")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.setContentsMargins(10, 10, 10, 10)
        custom_layout.setSpacing(8)
        clbl = QLabel("Custom providers")
        clbl.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #8b9aff;")
        custom_layout.addWidget(clbl)
        self.custom_list = QListWidget()
        self.custom_list.setMinimumHeight(80)
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
            b.clicked.connect(slot)
            custom_btns.addWidget(b)
        custom_btns.addStretch(1)
        custom_layout.addLayout(custom_btns)
        bottom_row.addWidget(custom_box, 1)

        # Fallback order (right).
        order_box = QFrame()
        order_box.setObjectName("panel_card")
        order_layout = QVBoxLayout(order_box)
        order_layout.setContentsMargins(10, 10, 10, 10)
        order_layout.setSpacing(8)
        olbl = QLabel("Fallback order")
        olbl.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #8b9aff;")
        order_layout.addWidget(olbl)
        self.fallback_list = QListWidget()
        self.fallback_list.setMinimumHeight(80)
        self.fallback_list.setMaximumHeight(120)
        order_layout.addWidget(self.fallback_list)
        order_btns = QHBoxLayout()
        order_btns.setSpacing(6)
        for label, slot in (
            ("Up", self._on_move_up),
            ("Down", self._on_move_down),
        ):
            b = QPushButton(label)
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
        hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # Seed the list now that the layout is fully set up.
        self._rebuild_fallback_list()
        self._rebuild_provider_list()

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
            )
            self.providers_scroll_layout.insertWidget(
                self.providers_scroll_layout.count() - 1, row
            )

        self.active_count_label.setText(f"Active {active} / {total}")

    def _make_provider_row(self, pid: str, label: str, kind: str,
                           api_key: str, base_url: str,
                           vision: bool | None) -> QFrame:
        """Build a single row widget for the provider list."""
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
        status_lbl.setMinimumWidth(60)
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
        sub_lbl.setStyleSheet("color: #8b9aff; font-size: 8pt;")
        sub_lbl.setWordWrap(False)
        sub_lbl.setTextFormat(Qt.TextFormat.PlainText)
        name_col.addWidget(sub_lbl)
        hl.addLayout(name_col, 1)

        # API key field.
        key_edit = QLineEdit(api_key)
        key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_edit.setPlaceholderText("paste API key…")
        key_edit.setMinimumWidth(220)
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
            "QLineEdit:focus { border: 1px solid #5b6aff; }"
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
            "QPushButton:checked { background: rgba(91,106,255,0.25); }"
        )
        show_btn.toggled.connect(
            lambda on, e=key_edit: e.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        hl.addWidget(show_btn, 0)

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
        # All valid ids: presets + custom providers.
        valid_ids: list[str] = list(PROVIDER_PRESETS.keys())
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
        # Try to detect which preset matches
        for name, preset in THEME_PRESETS.items():
            if preset["accent"] == self._cfg.theme.accent:
                self.theme_combo.setCurrentText(name)
                break
        self.accent_preview.setStyleSheet(f"background: {self._cfg.theme.accent}; border-radius: 6px;")

    def _apply_theme(self):
        t = self._cfg.theme
        self.container.setStyleSheet(f"""
            QWidget {{
                background: {t.bg_primary};
                color: {t.text_primary};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLabel {{ color: {t.text_primary}; }}
            QTabWidget::pane {{
                background: {t.bg_primary};
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {t.text_secondary};
                padding: 8px 16px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                color: {t.accent};
                border-bottom: 2px solid {t.accent};
            }}
            QLineEdit {{
                background: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 10pt;
            }}
            QLineEdit:focus {{ border: 1px solid {t.accent}; }}
            QComboBox {{
                background: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 10pt;
            }}
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {t.text_primary};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 10pt;
            }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 0.1); }}
            QPushButton#primary {{
                background: {t.accent};
                color: white;
                border: none;
                font-weight: 600;
            }}
            QPushButton#close_btn {{
                background: transparent;
                border: none;
                color: {t.text_secondary};
                font-size: 14pt;
            }}
            QPushButton#close_btn:hover {{ color: #ff6b6b; }}
        """)
        # Update preview
        if hasattr(self, 'preview'):
            self.preview.setStyleSheet(
                f"background: {t.bg_secondary}; color: {t.text_primary}; "
                f"border-radius: 8px; padding: 16px; font-size: 10pt;"
            )

    def _on_theme_changed(self, name):
        if name in THEME_PRESETS:
            preset = THEME_PRESETS[name]
            self._cfg.theme = ThemeConfig(**preset)
            self._apply_theme()
            self.accent_preview.setStyleSheet(f"background: {preset['accent']}; border-radius: 6px;")

    def _pick_accent(self):
        color = QColorDialog.getColor(
            QColor(self._cfg.theme.accent), self, "Pick accent color"
        )
        if color.isValid():
            self._cfg.theme.accent = color.name()
            self._apply_theme()
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
        self.status_label.setText("Settings saved. Restart SnipAI to apply hotkeys.")
        QMessageBox.information(
            self, "Settings", "Settings saved. Hotkey changes will apply on next app restart."
        )
        self.accept()
