"""Theme system — generates QSS stylesheets from theme config.

Single source of truth for all UI styling. Every component (response window,
history, prompt bubble) builds its QSS by calling theme.to_stylesheet().

To add a new styleable element: add a key to STYLES dict below, reference it
in to_stylesheet() with {key}, and set the value in ThemeConfig.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
from ..config import ThemeConfig


def _svg_data_uri(svg: str) -> str:
    """Encode an SVG string as a base64 data URI usable in QSS image: url()."""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _toggle_handle(track: str, handle_cx: int) -> str:
    """Build a 40x22 toggle-switch image (rounded track + circular handle)."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='22' "
        "viewBox='0 0 40 22'>"
        f"<rect x='0' y='0' width='40' height='22' rx='11' fill='{track}'/>"
        f"<circle cx='{handle_cx}' cy='11' r='8' fill='#ffffff'/>"
        "</svg>"
    )
    return _svg_data_uri(svg)


def generate_stylesheet(theme: ThemeConfig) -> str:
    """Build the full QSS stylesheet for a given theme."""
    t = theme
    toggle_off = _toggle_handle("#2a2d3a", 11)
    toggle_on = _toggle_handle(t.accent, 29)
    return f"""
        QWidget#root {{
            background: #0f111a;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
        }}

        /* ── Sidebar ─────────────────────────────────────── */
        QWidget#sidebar {{
            background: #090a0f;
            border-right: 1px solid rgba(255, 255, 255, 0.06);
            border-top-left-radius: 16px;
            border-bottom-left-radius: 16px;
        }}
        QLabel#brand_logo {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {t.accent}, stop:1 #8b5bff);
            color: #ffffff; font-size: 13pt; font-weight: 800;
            border-radius: 10px;
        }}
        QLabel#brand_title {{ color: #ffffff; font-size: 12pt; font-weight: 800; }}
        QPushButton#compose_btn {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 9px; color: {t.text_primary};
            font-size: 12pt; padding: 0;
        }}
        QPushButton#compose_btn:hover {{ background: rgba(255,255,255,0.1); }}

        QPushButton#new_chat_btn {{
            background: #23215c;
            color: #ffffff;
            border: 1px solid rgba(139,91,255,0.4);
            border-radius: 11px;
            padding: 11px 14px;
            font-size: 10pt;
            font-weight: 700;
            text-align: left;
        }}
        QPushButton#new_chat_btn:hover {{ background: #2c2a70; }}
        QLabel#keycap {{
            color: {t.text_secondary};
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 5px;
            padding: 1px 6px;
            font-size: 8pt;
            font-weight: 700;
        }}

        QLabel#hist_header {{
            color: rgba(255,255,255,0.35);
            font-size: 8pt;
            font-weight: 800;
            letter-spacing: 1.2px;
            padding: 2px 4px;
        }}
        QPushButton#hist_item {{
            background: transparent;
            border: none;
            border-radius: 8px;
            color: {t.text_primary};
            font-size: 9.5pt;
            font-weight: 500;
            padding: 8px 10px;
            text-align: left;
        }}
        QPushButton#hist_item:hover {{ background: #161924; }}

        QFrame#pro_card {{
            background: #0f111d;
            border: 1px solid rgba(139,91,255,0.25);
            border-radius: 12px;
        }}
        QLabel#pro_title {{ color: #ffffff; font-size: 10pt; font-weight: 800; }}
        QLabel#pro_sub {{ color: {t.text_secondary}; font-size: 8.5pt; }}
        QPushButton#pro_btn {{
            background: transparent;
            border: 1px solid rgba(139,91,255,0.5);
            border-radius: 9px;
            color: #c9b8ff;
            font-size: 9pt; font-weight: 700;
            padding: 7px 10px;
        }}
        QPushButton#pro_btn:hover {{ background: rgba(139,91,255,0.12); }}

        QFrame#profile_row {{
            background: transparent;
            border-top: 1px solid rgba(255,255,255,0.06);
        }}
        QLabel#profile_avatar {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
            color: #ffffff; font-size: 9pt; font-weight: 800;
            border-radius: 17px;
        }}
        QLabel#profile_name {{ color: #ffffff; font-size: 9.5pt; font-weight: 700; }}
        QLabel#profile_role {{ color: {t.text_secondary}; font-size: 8pt; }}
        QPushButton#footer_btn {{
            background: transparent; border: none;
            color: {t.text_secondary}; font-size: 12pt; padding: 4px;
            border-radius: 8px;
        }}
        QPushButton#footer_btn:hover {{
            background: rgba(255,255,255,0.06); color: #ffffff;
        }}

        /* ── Chat area ───────────────────────────────────── */
        QWidget#chat_area {{ background: #0f111a; }}
        QWidget#header {{
            background: transparent;
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
        QTextBrowser#bubble_body .snip-callout {{
            background: rgba(139,91,255,0.08);
            border: 1px solid rgba(139,91,255,0.35);
            border-left: 3px solid #8b5bff;
            border-radius: 10px;
            padding: 10px 12px;
            margin: 8px 0;
        }}
        QTextBrowser#bubble_body .snip-callout-icon {{
            color: #b79bff; font-weight: 800;
        }}
        QTextBrowser#bubble_body .snip-callout-label {{
            color: #c9b8ff; font-weight: 800; letter-spacing: 0.5px;
        }}
        QTextBrowser#bubble_body .snip-callout-text {{ color: {t.text_primary}; }}

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
                stop:0 {t.accent}, stop:1 #6f7dff);
        }}
        QPushButton#primary:pressed {{
            background: {t.accent};
            padding-top: 8px;
        }}
        QFrame#sep {{ background: rgba(255, 255, 255, 0.06); max-height: 1px; }}
        QSizeGrip#size_grip {{ background: transparent; }}

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
            background: transparent;
            color: {t.text_primary};
            border: none;
            padding: 4px 4px;
            font-family: 'Segoe UI', sans-serif;
            font-size: 10.5pt;
            selection-background-color: {t.accent}55;
        }}
        QTextEdit#chat_input:disabled {{ color: {t.text_secondary}; }}

        QFrame#input_container {{
            background: #12141c;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
        }}
        QPushButton#input_tool {{
            background: transparent;
            border: none;
            border-radius: 9px;
            color: {t.text_secondary};
            font-size: 12pt;
            padding: 0;
        }}
        QPushButton#input_tool:hover {{
            background: rgba(255,255,255,0.07); color: #ffffff;
        }}
        QPushButton#send_btn {{
            background: {t.accent};
            border: none;
            border-radius: 9px;
            color: #ffffff;
            font-size: 12pt;
            font-weight: 800;
            padding: 0;
        }}
        QPushButton#send_btn:hover {{ background: #6f7dff; }}
        QPushButton#send_btn:disabled {{ background: rgba(255,255,255,0.08); color: {t.text_secondary}; }}
        QLabel#disclaimer {{ color: rgba(255,255,255,0.3); font-size: 8pt; }}

        /* ── Message rows (side-by-side avatar + content) ── */
        QFrame#user_row, QFrame#assistant_row {{
            background: transparent;
            border: none;
        }}
        QLabel#row_avatar_ai {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {t.accent}, stop:1 #8b5bff);
            color: #ffffff; font-size: 9pt; font-weight: 800;
            border-radius: 16px;
        }}
        QLabel#row_avatar_user {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
            color: #ffffff; font-size: 9pt; font-weight: 800;
            border-radius: 16px;
        }}
        QLabel#row_name {{ color: #ffffff; font-size: 9.5pt; font-weight: 700; }}
        QLabel#row_time {{ color: rgba(255,255,255,0.3); font-size: 8pt; }}

        QWidget#msg_actions {{ background: transparent; }}
        QPushButton#msg_action_btn {{
            background: transparent;
            border: none;
            border-radius: 7px;
            color: {t.text_secondary};
            font-size: 10.5pt;
            padding: 4px 6px;
        }}
        QPushButton#msg_action_btn:hover {{
            background: rgba(255,255,255,0.08); color: #ffffff;
        }}
        QPushButton#export_btn {{
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            color: {t.text_primary};
            font-size: 8.5pt;
            font-weight: 600;
            padding: 4px 10px;
        }}
        QPushButton#export_btn:hover {{ background: rgba(255,255,255,0.09); }}
        QPushButton#export_btn::menu-indicator {{ width: 0; }}
        QMenu {{
            background: {t.bg_secondary};
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            color: {t.text_primary};
            padding: 4px;
        }}
        QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {t.accent}55; }}

        QComboBox#model_select, QComboBox#mode_select {{
            background: rgba(255,255,255,0.04);
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 999px;
            padding: 5px 12px;
            font-size: 9pt;
            font-family: 'Segoe UI', sans-serif;
            min-height: 22px;
        }}
        QComboBox#model_select:hover, QComboBox#mode_select:hover {{
            border: 1px solid {t.accent}80;
            background: rgba(255,255,255,0.07);
        }}
        QComboBox#model_select::drop-down, QComboBox#mode_select::drop-down {{
            border: none; width: 18px;
        }}
        QComboBox#model_select::down-arrow, QComboBox#mode_select::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {t.text_secondary};
            margin-right: 8px;
        }}
        QComboBox#model_select QAbstractItemView, QComboBox#mode_select QAbstractItemView {{
            background: {t.bg_secondary};
            color: {t.text_primary};
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            selection-background-color: {t.accent}55;
            selection-color: #ffffff;
            padding: 4px; outline: 0;
        }}

        /* ── Free-only toggle switch ─────────────────────── */
        QCheckBox#free_only_check {{
            color: {t.text_secondary};
            font-size: 9pt;
            font-weight: 600;
            spacing: 8px;
        }}
        QCheckBox#free_only_check::indicator {{
            width: 40px; height: 22px;
            image: url({toggle_off});
        }}
        QCheckBox#free_only_check::indicator:checked {{
            image: url({toggle_on});
        }}
        QCheckBox#free_only_check:disabled {{
            color: rgba(255,255,255,0.3);
        }}
    """


def get_link_color(theme: ThemeConfig) -> str:
    """Return link color for QPalette."""
    return theme.accent
