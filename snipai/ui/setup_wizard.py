"""Setup wizard for first-run configuration.

7-step wizard:
  1. Welcome
  2. Provider selection
  3. API key entry
  4. Model selection
  5. Hotkey configuration
  6. Theme customization
  7. Done
"""
from __future__ import annotations
import logging
import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPalette, QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QStackedWidget, QWidget, QProgressBar, QFrame, QColorDialog,
    QSizePolicy, QApplication, QMessageBox,
)
from ..config import AppConfig, ThemeConfig, save_config, get_config

log = logging.getLogger(__name__)

PROVIDER_PRESETS = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-4o",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "key_url": "https://console.anthropic.com/settings/keys",
        "default_model": "claude-3-5-sonnet-20241022",
    },
    "google": {
        "label": "Google (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com",
        "key_url": "https://aistudio.google.com/apikey",
        "default_model": "gemini-2.5-flash",
    },
    "groq": {
        "label": "Groq (fast inference)",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "https://console.groq.com/keys",
        "default_model": "llama-3.2-90b-vision-preview",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_url": "https://build.nvidia.com/explore/discover",
        "default_model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
    },
    "openrouter": {
        "label": "OpenRouter (any model)",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "https://openrouter.ai/keys",
        "default_model": "google/gemini-2.5-flash",
    },
    "opencode_zen": {
        "label": "OpenCode Zen (multi-model gateway)",
        "base_url": "https://opencode.ai/zen/v1",
        "key_url": "https://opencode.ai",
        "default_model": "claude-sonnet-4-6",
    },
    "bluesminds": {
        "label": "Bluesminds",
        "base_url": "https://api.bluesminds.com/v1",
        "key_url": "https://bluesminds.com",
        "default_model": "gpt-4o",
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "base_url": "",
        "key_url": "",
        "default_model": "",
    },
}

THEME_PRESETS = {
    "Midnight": {
        "accent": "#5b6aff",
        "bg_primary": "#0f1117",
        "bg_secondary": "#161d2c",
        "text_primary": "#e2e8f0",
        "text_secondary": "#8b9aff",
    },
    "Light": {
        "accent": "#3b82f6",
        "bg_primary": "#ffffff",
        "bg_secondary": "#f3f4f6",
        "text_primary": "#1f2937",
        "text_secondary": "#6b7280",
    },
    "Forest": {
        "accent": "#10b981",
        "bg_primary": "#0a1f15",
        "bg_secondary": "#133029",
        "text_primary": "#e0f2e9",
        "text_secondary": "#6ee7b7",
    },
    "Sunset": {
        "accent": "#f59e0b",
        "bg_primary": "#1c1410",
        "bg_secondary": "#2d2017",
        "text_primary": "#fef3c7",
        "text_secondary": "#fbbf24",
    },
    "Purple": {
        "accent": "#8b5cf6",
        "bg_primary": "#14101f",
        "bg_secondary": "#1f1733",
        "text_primary": "#ede9fe",
        "text_secondary": "#c4b5fd",
    },
}


class _ModelsFetcher(QThread):
    """Async fetch models from backend."""
    fetched = Signal(list)
    failed = Signal(str)

    def __init__(self, backend_url, provider, api_key, base_url=None):
        super().__init__()
        self.backend_url = backend_url
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        try:
            resp = httpx.post(
                f"{self.backend_url}/v1/models",
                json={
                    "provider": self.provider,
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("models", []) if m.get("id")]
            self.fetched.emit(models)
        except Exception as e:
            self.failed.emit(str(e))


class SetupWizard(QDialog):
    """First-run setup wizard. Returns Accepted if config was saved."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SnipAI Setup")
        self.setMinimumSize(640, 480)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._cfg = AppConfig()
        self._fetcher: _ModelsFetcher | None = None

        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Container
        container = QFrame(self)
        outer.addWidget(container)
        self.container = container
        cv = QVBoxLayout(container)
        cv.setContentsMargins(32, 24, 32, 24)
        cv.setSpacing(16)

        # Title bar with close
        title_bar = QHBoxLayout()
        self.title_label = QLabel("Welcome to SnipAI")
        self.title_label.setStyleSheet("font-size: 20pt; font-weight: 700;")
        title_bar.addWidget(self.title_label)
        title_bar.addStretch(1)
        cv.addLayout(title_bar)

        # Subtitle
        self.subtitle_label = QLabel("Let's get you set up in a few quick steps.")
        self.subtitle_label.setStyleSheet("color: #8b9aff; font-size: 10pt;")
        cv.addWidget(self.subtitle_label)

        # Progress
        self.progress = QProgressBar()
        self.progress.setMaximum(7)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        cv.addWidget(self.progress)

        # Stacked pages
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)

        self._build_page_welcome()
        self._build_page_provider()
        self._build_page_api_key()
        self._build_page_model()
        self._build_page_hotkeys()
        self._build_page_theme()
        self._build_page_done()

        # Nav buttons
        nav = QHBoxLayout()
        self.btn_back = QPushButton("← Back")
        self.btn_back.clicked.connect(self._on_back)
        nav.addWidget(self.btn_back)

        nav.addStretch(1)

        self.btn_next = QPushButton("Next →")
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(self._on_next)
        nav.addWidget(self.btn_next)

        cv.addLayout(nav)

    def _build_page_welcome(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(16)

        v.addStretch(1)

        hero = QLabel("AI-powered screen capture.\nAsk anything, instantly.")
        hero.setStyleSheet("font-size: 16pt; font-weight: 600; line-height: 1.5;")
        hero.setWordWrap(True)
        v.addWidget(hero)

        desc = QLabel(
            "Press a hotkey, select any region of your screen, and SnipAI will analyze it. "
            "Highlight text to summarize, translate, or explain. Works with any AI provider."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b9aff; font-size: 10pt; line-height: 1.6;")
        v.addWidget(desc)

        v.addStretch(2)
        self.stack.addWidget(page)

    def _build_page_provider(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        lbl = QLabel("Choose your AI provider")
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(lbl)

        v.addWidget(QLabel("SnipAI works with any OpenAI-compatible API."))

        self.provider_combo = QComboBox()
        for key, preset in PROVIDER_PRESETS.items():
            self.provider_combo.addItem(preset["label"], key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        v.addWidget(self.provider_combo)

        # Custom base URL
        self.base_url_label = QLabel("Base URL (for Custom):")
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api.example.com/v1")
        v.addWidget(self.base_url_label)
        v.addWidget(self.base_url_input)
        self.base_url_label.hide()
        self.base_url_input.hide()

        self.provider_info = QLabel("")
        self.provider_info.setStyleSheet("color: #8b9aff; font-size: 9pt;")
        self.provider_info.setOpenExternalLinks(True)
        v.addWidget(self.provider_info)

        v.addStretch(1)
        self.stack.addWidget(page)

    def _build_page_api_key(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        lbl = QLabel("Enter your API key")
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(lbl)

        self.key_info = QLabel(
            "Your key is sent with each request and never stored on our servers."
        )
        self.key_info.setStyleSheet("color: #8b9aff; font-size: 9pt;")
        self.key_info.setWordWrap(True)
        v.addWidget(self.key_info)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("sk-... or your provider's key format")
        v.addWidget(self.key_input)

        show_row = QHBoxLayout()
        self.show_key_btn = QPushButton("Show key")
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.toggled.connect(self._toggle_key_visibility)
        show_row.addWidget(self.show_key_btn)
        show_row.addStretch(1)
        v.addLayout(show_row)

        self.key_error = QLabel("")
        self.key_error.setStyleSheet("color: #ff6b6b; font-size: 9pt;")
        v.addWidget(self.key_error)

        v.addStretch(1)
        self.stack.addWidget(page)

    def _build_page_model(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        lbl = QLabel("Select a model")
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(lbl)

        v.addWidget(QLabel("We'll fetch the available models for your provider."))

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        v.addWidget(self.model_combo)

        self.model_status = QLabel("Click 'Fetch models' to load available models.")
        self.model_status.setStyleSheet("color: #8b9aff; font-size: 9pt;")
        v.addWidget(self.model_status)

        self.btn_fetch = QPushButton("Fetch models")
        self.btn_fetch.clicked.connect(self._fetch_models)
        v.addWidget(self.btn_fetch, 0, Qt.AlignmentFlag.AlignLeft)

        v.addStretch(1)
        self.stack.addWidget(page)

    def _build_page_hotkeys(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        lbl = QLabel("Set your hotkeys")
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(lbl)

        v.addWidget(QLabel("Click a field, then press your desired key combination."))

        # Crop hotkey
        v.addWidget(QLabel("Crop hotkey:"))
        self.hotkey_input = QLineEdit("ctrl+shift+space")
        self.hotkey_input.setReadOnly(True)
        self.hotkey_input.mousePressEvent = lambda e: self._start_recording("crop")
        v.addWidget(self.hotkey_input)

        # Text hotkey
        v.addWidget(QLabel("Text hotkey:"))
        self.text_hotkey_input = QLineEdit("ctrl+alt+g")
        self.text_hotkey_input.setReadOnly(True)
        self.text_hotkey_input.mousePressEvent = lambda e: self._start_recording("text")
        v.addWidget(self.text_hotkey_input)

        v.addStretch(1)
        self.stack.addWidget(page)

    def _build_page_theme(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        lbl = QLabel("Pick a theme")
        lbl.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(lbl)

        self.theme_combo = QComboBox()
        for name in THEME_PRESETS:
            self.theme_combo.addItem(name)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        v.addWidget(self.theme_combo)

        v.addWidget(QLabel("Or choose a custom accent color:"))

        color_row = QHBoxLayout()
        self.accent_btn = QPushButton("Pick accent color")
        self.accent_btn.clicked.connect(self._pick_accent)
        color_row.addWidget(self.accent_btn)

        self.accent_preview = QLabel()
        self.accent_preview.setFixedSize(40, 30)
        self.accent_preview.setStyleSheet("background: #5b6aff; border-radius: 6px;")
        color_row.addWidget(self.accent_preview)
        color_row.addStretch(1)
        v.addLayout(color_row)

        v.addStretch(1)
        self.stack.addWidget(page)

    def _build_page_done(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(16)

        v.addStretch(1)

        done_lbl = QLabel("All set! 🎉")
        done_lbl.setStyleSheet("font-size: 18pt; font-weight: 700;")
        done_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(done_lbl)

        desc = QLabel("Click Finish to start using SnipAI.\nYou can change settings anytime from the tray menu.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b9aff; font-size: 10pt;")
        v.addWidget(desc)

        v.addStretch(2)
        self.stack.addWidget(page)

    def _apply_theme(self):
        """Apply current theme to wizard."""
        t = self._cfg.theme
        self.container.setStyleSheet(f"""
            QWidget {{
                background: {t.bg_primary};
                color: {t.text_primary};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLabel {{ color: {t.text_primary}; }}
            QLineEdit {{
                background: {t.bg_secondary};
                color: {t.text_primary};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 10px 12px;
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
            QComboBox:hover {{ border: 1px solid {t.accent}; }}
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {t.text_primary};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.1);
            }}
            QPushButton#primary {{
                background: {t.accent};
                color: white;
                border: none;
                font-weight: 600;
            }}
            QPushButton#primary:hover {{
                background: {t.accent};
                opacity: 0.9;
            }}
            QProgressBar {{
                background: {t.bg_secondary};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {t.accent};
                border-radius: 2px;
            }}
        """)

    def _on_provider_changed(self, idx):
        key = self.provider_combo.currentData()
        preset = PROVIDER_PRESETS.get(key, {})
        is_custom = key == "custom"
        self.base_url_label.setVisible(is_custom)
        self.base_url_input.setVisible(is_custom)

        info_text = ""
        key_url = preset.get("key_url", "")
        if key_url:
            info_text = f'Get your API key: <a href="{key_url}">{key_url}</a>'
        if key == "bluesminds":
            info_text = "Using Bluesminds API (OpenAI-compatible)."
        self.provider_info.setText(info_text)

        self._cfg.provider = key
        self._cfg.base_url = preset.get("base_url", "")

    def _toggle_key_visibility(self, checked):
        self.key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _fetch_models(self):
        api_key = self.key_input.text().strip()
        if not api_key:
            self.model_status.setText("Enter an API key first.")
            return

        self.model_status.setText("Fetching models...")
        self.btn_fetch.setEnabled(False)

        base_url = self.base_url_input.text().strip() if self._cfg.provider == "custom" else self._cfg.base_url
        self._fetcher = _ModelsFetcher(
            backend_url=self._cfg.backend_url,
            provider=self._cfg.provider,
            api_key=api_key,
            base_url=base_url,
        )
        self._fetcher.fetched.connect(self._on_models_fetched)
        self._fetcher.failed.connect(self._on_models_failed)
        self._fetcher.start()

    def _on_models_fetched(self, models):
        self.btn_fetch.setEnabled(True)
        self.model_combo.clear()
        if models:
            # Handle both shapes: list[dict] (new) or list[str] (legacy).
            first = models[0]
            if isinstance(first, dict):
                records = [
                    {
                        "id": m.get("id") or m.get("name") or "",
                        "name": m.get("name") or m.get("id") or "",
                        "free": bool(m.get("free", False)),
                        "vision": bool(m.get("vision", False)),
                    }
                    for m in models if (m.get("id") or m.get("name"))
                ]
                records.sort(key=lambda r: (not r["free"], r["id"]))
                for r in records:
                    label = r["name"] or r["id"]
                    if r["free"]:
                        tag = "★ Free" + (" · vision" if r["vision"] else "")
                        label = f"{label}  ·  {tag}"
                    self.model_combo.addItem(label, r["id"])
                # Auto-pick first free+vision if present.
                pick = next((r for r in records if r["free"] and r["vision"]), None)
                if pick:
                    idx = next((i for i, r in enumerate(records) if r["id"] == pick["id"]), 0)
                    self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.addItems(models)
            self.model_status.setText(f"Found {len(models)} models.")
        else:
            preset = PROVIDER_PRESETS.get(self._cfg.provider, {})
            default = preset.get("default_model", "")
            if default:
                self.model_combo.addItem(default)
            self.model_status.setText("No models returned. Type one manually.")

    def _on_models_failed(self, err):
        self.btn_fetch.setEnabled(True)
        self.model_status.setText(f"Failed: {err}. You can type a model name manually.")
        preset = PROVIDER_PRESETS.get(self._cfg.provider, {})
        default = preset.get("default_model", "")
        if default:
            self.model_combo.addItem(default)

    def _start_recording(self, which):
        if which == "crop":
            self.hotkey_input.setText("Press your hotkey combination...")
            self.hotkey_input.setFocus()
            self._recording = "crop"
        else:
            self.text_hotkey_input.setText("Press your hotkey combination...")
            self.text_hotkey_input.setFocus()
            self._recording = "text"
        self._recording_modifiers = set()

    def keyPressEvent(self, e: QKeyEvent):
        if not hasattr(self, "_recording") or not self._recording:
            super().keyPressEvent(e)
            return

        key = e.key()
        mods = e.modifiers()

        # Escape cancels
        if key == Qt.Key.Key_Escape:
            if self._recording == "crop":
                self.hotkey_input.setText(self._cfg.hotkey)
            else:
                self.text_hotkey_input.setText(self._cfg.text_hotkey)
            self._recording = None
            return

        # Build combo string
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")

        # Map key to name
        key_name = self._key_name(key)
        if key_name and key_name not in ("ctrl", "alt", "shift", "win"):
            parts.append(key_name)
            combo = "+".join(parts)
            if self._recording == "crop":
                self.hotkey_input.setText(combo)
                self._cfg.hotkey = combo
            else:
                self.text_hotkey_input.setText(combo)
                self._cfg.text_hotkey = combo
            self._recording = None

    def _key_name(self, key):
        """Map Qt key to hotkey string."""
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            n = key - Qt.Key.Key_F1 + 1
            return f"f{n}"
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(ord('0') + (key - Qt.Key.Key_0))
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(ord('a') + (key - Qt.Key.Key_A))
        special = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page up",
            Qt.Key.Key_PageDown: "page down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
        }
        return special.get(key)

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

    def _on_back(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self.progress.setValue(idx - 1)
        if idx == 1:
            self.btn_back.setEnabled(False)

    def _on_next(self):
        idx = self.stack.currentIndex()

        # Validate current step before moving on
        if idx == 1:  # provider
            key = self.provider_combo.currentData()
            if key == "custom" and not self.base_url_input.text().strip():
                self.key_error.setText("Enter a base URL for custom provider.")
                return
            self._cfg.base_url = self.base_url_input.text().strip() if key == "custom" else PROVIDER_PRESETS[key]["base_url"]
        elif idx == 2:  # api key
            if not self.key_input.text().strip():
                self.key_error.setText("API key is required.")
                return
            self._cfg.api_key = self.key_input.text().strip()
        elif idx == 3:  # model
            model = self.model_combo.currentText().strip()
            if not model:
                self.model_status.setText("Select or type a model name.")
                return
            self._cfg.model = model

        if idx < self.stack.count() - 1:
            self.stack.setCurrentIndex(idx + 1)
            self.progress.setValue(idx + 1)
            self.btn_back.setEnabled(True)
            if idx + 1 == self.stack.count() - 1:
                self.btn_next.setText("Finish ✓")
        else:
            # Done — save config
            self._cfg.setup_complete = True
            save_config(self._cfg)
            self.accept()

    def closeEvent(self, e):
        if not self._cfg.setup_complete:
            reply = QMessageBox.question(
                self,
                "Cancel setup?",
                "SnipAI isn't configured yet. Exit without saving?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                e.ignore()
                return
        super().closeEvent(e)
