"""Theme system — generates QSS stylesheets from theme config.

Single source of truth for all UI styling. Every component (response window,
history, prompt bubble) builds its QSS by calling theme.to_stylesheet().

To add a new styleable element: add a key to STYLES dict below, reference it
in to_stylesheet() with {key}, and set the value in ThemeConfig.
"""
from __future__ import annotations
from dataclasses import dataclass
from ..config import ThemeConfig


def generate_stylesheet(theme: ThemeConfig) -> str:
    """Build the full QSS stylesheet for a given theme."""
    t = theme
    return f"""
        QWidget#root {{
            background: {t.bg_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
        }}
        QWidget#header {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {t.bg_secondary}, stop:1 {t.bg_primary});
            border-top-left-radius: 16px;
            border-top-right-radius: 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }}
        QLabel {{ color: {t.text_primary}; }}
        QLabel#title {{ font-weight: 700; font-size: 12pt; color: #ffffff; }}
        QLabel#subtitle {{
            color: {t.accent}; font-size: 8pt; font-weight: 700; letter-spacing: 1.5px;
        }}
        QLabel#prompt {{ color: {t.text_secondary}; font-size: 9pt; }}
        QLabel#thumb {{
            background: {t.bg_primary};
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 10px;
        }}
        QLabel#status {{ color: {t.text_secondary}; font-size: 8pt; }}
        QLabel#role_name {{ color: {t.text_secondary}; font-size: 9pt; font-weight: 700; }}
        QLabel#avatar_ai {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {t.accent}, stop:1 {t.accent});
            color: white; font-size: 7pt; font-weight: 800;
            border-radius: 10px;
        }}
        QLabel#avatar_user {{
            background: {t.bg_secondary}; color: {t.text_primary};
            font-size: 8pt; font-weight: 800; border-radius: 10px;
        }}

        QScrollArea#feed_scroll {{ background: transparent; border: none; }}
        QWidget#feed {{ background: transparent; }}

        QFrame#user_row {{
            background: {t.bg_secondary};
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }}
        QFrame#assistant_row {{
            background: transparent;
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.04);
        }}
        QTextBrowser#bubble_body {{
            background: transparent;
            color: {t.text_primary};
            border: none;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            selection-background-color: {t.accent}55;
        }}
        QTextBrowser#bubble_body h1, QTextBrowser#bubble_body h2,
        QTextBrowser#bubble_body h3 {{ color: #ffffff; font-weight: 700; }}
        QTextBrowser#bubble_body a {{ color: {t.accent}; }}
        QTextBrowser#bubble_body code {{
            background: rgba(255, 255, 255, 0.07);
            color: {t.accent};
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 10pt;
        }}
        QTextBrowser#bubble_body pre {{
            background: {t.bg_primary};
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 12px 14px;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 10pt;
        }}
        QTextBrowser#bubble_body .snip-link {{
            display: inline-block;
            margin: 3px 4px 3px 0;
            padding: 4px 9px;
            border-radius: 999px;
            color: {t.text_primary};
            background: {t.accent}22;
            border: 1px solid {t.accent}55;
            text-decoration: none;
            font-weight: 600;
        }}
        QTextBrowser#bubble_body .snip-link:hover {{
            background: {t.accent}33;
            color: #ffffff;
        }}
        QTextBrowser#bubble_body .snip-link-icon {{
            color: {t.accent};
            font-weight: 800;
        }}
        QTextBrowser#bubble_body .snip-highlight {{
            color: #ffffff;
            background: {t.accent}22;
            border-radius: 6px;
            padding: 1px 5px;
            font-weight: 700;
        }}
        QTextBrowser#bubble_body .snip-list {{
            margin: 8px 0 10px 18px;
            padding-left: 18px;
        }}
        QTextBrowser#bubble_body .snip-list li {{
            margin-bottom: 7px;
        }}
        QTextBrowser#bubble_body .snip-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
            border-radius: 10px;
            overflow: hidden;
        }}
        QTextBrowser#bubble_body .snip-table th,
        QTextBrowser#bubble_body .snip-table td {{
            border: 1px solid rgba(255,255,255,0.08);
            padding: 8px 10px;
        }}
        QTextBrowser#bubble_body .snip-table th {{
            background: {t.accent}22;
            color: #ffffff;
            font-weight: 700;
        }}
        QTextBrowser#bubble_body .snip-table td {{
            background: {t.bg_secondary};
        }}

        QPushButton {{
            background: rgba(255, 255, 255, 0.05);
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 7px 16px;
            font-size: 9.5pt;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background: rgba(255, 255, 255, 0.1);
        }}
        QPushButton#close_btn {{
            background: transparent; border: none;
            color: {t.text_secondary}; font-size: 14pt; padding: 0;
        }}
        QPushButton#close_btn:hover {{ color: #ff6b6b; }}
        QPushButton#primary {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {t.accent}, stop:1 {t.accent});
            color: white; border: none; font-weight: 700;
        }}
        QPushButton#primary:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {t.accent}, stop:1 {t.accent});
            opacity: 0.9;
        }}
        QFrame#sep {{ background: rgba(255, 255, 255, 0.06); max-height: 1px; }}

        QScrollBar:vertical {{
            background: transparent; width: 8px; margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,0.12); border-radius: 4px; min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.22); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

        QWidget#action_bar {{
            background: transparent;
            min-height: 52px;
        }}
        QPushButton#action_btn {{
            min-height: 38px;
            max-height: 42px;
            padding: 9px 18px;
            border-radius: 18px;
            color: #ffffff;
            font-size: 9.5pt;
            font-weight: 800;
            letter-spacing: 0.3px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(255,255,255,0.18),
                stop:0.45 {t.accent}33,
                stop:1 rgba(255,255,255,0.06));
            border: 1px solid rgba(255,255,255,0.16);
            border-top: 1px solid rgba(255,255,255,0.24);
            border-left: 1px solid rgba(255,255,255,0.20);
            box-shadow: none;
        }}
        QPushButton#action_btn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(255,255,255,0.24),
                stop:0.45 {t.accent}48,
                stop:1 rgba(255,255,255,0.08));
            border-color: rgba(255,255,255,0.28);
            color: #ffffff;
        }}
        QPushButton#action_btn:pressed {{
            background: {t.accent}38;
            border-color: {t.accent}80;
            padding-top: 11px;
            padding-bottom: 7px;
        }}

        QTextEdit#chat_input {{
            background: {t.bg_secondary};
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 10px 14px;
            font-family: 'Segoe UI', sans-serif;
            font-size: 10.5pt;
            selection-background-color: {t.accent}55;
        }}
        QTextEdit#chat_input:focus {{ border: 1px solid {t.accent}80; }}
        QTextEdit#chat_input:disabled {{ background: {t.bg_primary}; color: {t.text_secondary}; }}

        QComboBox#model_select {{
            background: {t.bg_secondary};
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 4px 10px;
            font-size: 9pt;
            font-family: 'Segoe UI', sans-serif;
            min-height: 22px;
        }}
        QComboBox#model_select:hover {{
            border: 1px solid {t.accent}80;
        }}
        QComboBox#model_select::drop-down {{ border: none; width: 18px; }}
        QComboBox#model_select::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {t.accent};
            margin-right: 6px;
        }}
        QComboBox#model_select QAbstractItemView {{
            background: {t.bg_secondary};
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            selection-background-color: {t.accent}55;
            selection-color: #ffffff;
            padding: 4px; outline: 0;
        }}
        QCheckBox#free_only_check {{
            color: {t.text_secondary};
            font-size: 9pt;
            font-weight: 600;
            spacing: 6px;
        }}
        QCheckBox#free_only_check::indicator {{
            width: 14px; height: 14px;
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 3px;
            background: {t.bg_secondary};
        }}
        QCheckBox#free_only_check::indicator:checked {{
            background: {t.accent};
            border: 1px solid {t.accent};
        }}
        QCheckBox#free_only_check:disabled {{
            color: rgba(255,255,255,0.3);
        }}
    """


def get_link_color(theme: ThemeConfig) -> str:
    """Return link color for QPalette."""
    return theme.accent
