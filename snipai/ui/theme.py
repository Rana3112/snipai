"""Theme system — generates QSS stylesheets from theme config.

ChatGPT-inspired premium dark redesign (2024-2025): #212121 base, #171717 sidebar,
#303030 input & user bubble, ultra-pill inputs, minimal borders #2f2f2f,
Inter/Segoe UI typography, subtle shadows. Keeps accent injection for links/highlights.
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
    """Build the full ChatGPT-style QSS stylesheet."""
    t = theme
    toggle_off = _toggle_handle("#2a2d3a", 11)
    toggle_on = _toggle_handle(t.accent, 29)
    # ChatGPT dark palette — fixed base, accent stays dynamic
    bg_root = "#212121"
    bg_sidebar = "#171717"
    bg_chat = "#212121"
    bg_input = "#303030"
    bg_user = "#303030"
    bg_code = "#2f2f2f"
    border_soft = "#2f2f2f"
    border_hover = "#3f3f3f"
    text_main = "#ececec"
    text_muted = "#9a9a9a"
    text_dim = "#6b7280"
    return f"""
        /* ── Root container ──────────────────────────────── */
        QWidget#root {{
            background: {bg_root};
            border: 1px solid {border_soft};
            border-radius: 16px;
        }}

        /* ── Sidebar (ChatGPT left nav) ────────────────── */
        QWidget#sidebar {{
            background: {bg_sidebar};
            border-right: 1px solid {border_soft};
            border-top-left-radius: 16px;
            border-bottom-left-radius: 16px;
        }}
        QLabel#brand_logo {{
            background: {t.accent};
            color: #ffffff; font-size: 13pt; font-weight: 800;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.08);
        }}
        QLabel#brand_title {{
            color: #ffffff; font-size: 11.5pt; font-weight: 700;
            font-family: 'Inter','Segoe UI',sans-serif; letter-spacing: -0.2px;
        }}
        QPushButton#compose_btn {{
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px; color: {text_main};
            font-size: 11pt; padding: 0;
        }}
        QPushButton#compose_btn:hover {{ background: rgba(255,255,255,0.10); }}

        QPushButton#new_chat_btn {{
            background: transparent;
            color: #ffffff;
            border: 1px solid {border_soft};
            border-radius: 10px;
            padding: 10px 14px;
            font-size: 9.5pt;
            font-weight: 600;
            text-align: left;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#new_chat_btn:hover {{
            background: {bg_input};
            border-color: {border_hover};
        }}
        QLabel#keycap {{
            color: {text_muted};
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 6px;
            padding: 2px 7px;
            font-size: 7.5pt;
            font-weight: 700;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}

        QLabel#hist_header {{
            color: {text_dim};
            font-size: 7.5pt;
            font-weight: 700;
            letter-spacing: 0.8px;
            padding: 8px 4px 4px 4px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#hist_item {{
            background: transparent;
            border: none;
            border-radius: 8px;
            color: #d1d5db;
            font-size: 9pt;
            font-weight: 400;
            padding: 7px 10px;
            text-align: left;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#hist_item:hover {{ background: rgba(255,255,255,0.06); color: #ffffff; }}

        QPushButton#footer_btn {{
            background: transparent; border: none;
            color: {text_muted}; font-size: 11pt; padding: 5px;
            border-radius: 8px;
        }}
        QPushButton#footer_btn:hover {{
            background: rgba(255,255,255,0.07); color: #ffffff;
        }}

        /* ── Chat area ─────────────────────────────────── */
        QWidget#chat_area {{ background: {bg_chat}; border-top-right-radius: 16px; border-bottom-right-radius: 16px; }}
        QWidget#header {{
            background: {bg_chat};
            border-top-right-radius: 16px;
            border-bottom: 1px solid {border_soft};
        }}
        QLabel {{ color: {text_main}; font-family: 'Inter','Segoe UI',sans-serif; }}
        QLabel#title {{ font-weight: 700; font-size: 11pt; color: #ffffff; }}
        QLabel#subtitle {{
            color: {t.accent}; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px;
        }}
        QLabel#prompt {{ color: {text_muted}; font-size: 9pt; }}
        QLabel#thumb {{
            background: {bg_input};
            border: 1px solid {border_soft};
            border-radius: 10px;
        }}
        QLabel#status {{ color: {text_muted}; font-size: 8pt; font-family: 'Inter','Segoe UI',sans-serif; }}
        QLabel#role_name {{ color: {text_muted}; font-size: 9pt; font-weight: 600; }}

        /* avatars — ChatGPT style: AI dark with accent ring, user neutral */
        QLabel#avatar_ai {{
            background: {t.accent};
            color: #ffffff; font-size: 8.5pt; font-weight: 800;
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.10);
        }}
        QLabel#avatar_user {{
            background: #52525b; color: #ffffff;
            font-size: 8pt; font-weight: 700; border-radius: 16px;
        }}

        QScrollArea#feed_scroll {{
            background: transparent; border: none;
        }}
        QWidget#feed {{ background: transparent; }}

        /* ChatGPT: user bubble = filled pill, assistant = transparent */
        QFrame#user_row {{
            background: {bg_user};
            border: 1px solid {border_soft};
            border-radius: 18px;
            margin: 6px 16px;
        }}
        QFrame#assistant_row {{
            background: transparent;
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            margin: 2px 0;
        }}
        QTextBrowser#bubble_body {{
            background: transparent;
            color: {text_main};
            border: none;
            font-family: 'Inter','Segoe UI',sans-serif;
            font-size: 10.5pt;
            line-height: 1.65;
            selection-background-color: {t.accent}55;
            selection-color: #ffffff;
        }}
        QTextBrowser#bubble_body h1, QTextBrowser#bubble_body h2,
        QTextBrowser#bubble_body h3 {{
            color: #ffffff; font-weight: 700; letter-spacing: -0.3px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QTextBrowser#bubble_body a {{
            color: #60a5fa; text-decoration: none; font-weight: 500;
        }}
        QTextBrowser#bubble_body a:hover {{ color: #93c5fd; text-decoration: underline; }}
        QTextBrowser#bubble_body code {{
            background: rgba(255, 255, 255, 0.08);
            color: #e5e7eb;
            padding: 2px 6px;
            border-radius: 6px;
            font-family: 'Cascadia Code','Consolas',monospace;
            font-size: 9.5pt;
            border: 1px solid rgba(255,255,255,0.06);
        }}
        QTextBrowser#bubble_body pre {{
            background: {bg_code};
            border: 1px solid {border_soft};
            border-radius: 12px;
            padding: 14px 16px;
            font-family: 'Cascadia Code','Consolas',monospace;
            font-size: 9.5pt;
            margin: 10px 0;
        }}
        QTextBrowser#bubble_body .snip-link {{
            display: inline-block;
            margin: 4px 6px 4px 0;
            padding: 5px 12px;
            border-radius: 999px;
            color: #ffffff;
            background: {t.accent}18;
            border: 1px solid {t.accent}40;
            text-decoration: none;
            font-weight: 600;
            font-size: 9pt;
        }}
        QTextBrowser#bubble_body .snip-link:hover {{
            background: {t.accent}28;
            border-color: {t.accent}60;
        }}
        QTextBrowser#bubble_body .snip-link-icon {{
            color: {t.accent};
            font-weight: 800;
        }}
        QTextBrowser#bubble_body .snip-highlight {{
            color: #ffffff;
            background: {t.accent}1a;
            border-radius: 6px;
            padding: 1px 5px;
            font-weight: 600;
        }}
        QTextBrowser#bubble_body .snip-list {{
            margin: 10px 0 12px 20px;
            padding-left: 20px;
            list-style-type: disc;
        }}
        QTextBrowser#bubble_body .snip-list li {{
            margin-bottom: 8px; color: {text_main}; line-height: 1.6;
            padding-left: 4px;
        }}
        QTextBrowser#bubble_body .snip-table {{
            width: 100%;
            margin: 14px 0;
            border: 1px solid {border_soft};
            background-color: #1e1e1e;
        }}
        QTextBrowser#bubble_body .snip-table th,
        QTextBrowser#bubble_body .snip-table td {{
            border: 1px solid {border_soft};
            padding: 10px 12px;
            text-align: left;
            vertical-align: top;
        }}
        QTextBrowser#bubble_body .snip-table th {{
            background-color: #2f2f2f;
            color: #ffffff;
            font-weight: 700;
            font-size: 9.5pt;
            border-bottom: 2px solid {t.accent};
        }}
        QTextBrowser#bubble_body .snip-table td {{
            background-color: #252525; color: {text_main};
        }}
        QTextBrowser#bubble_body .snip-table tr:nth-child(even) td {{
            background-color: #2a2a2a;
        }}
        QTextBrowser#bubble_body .snip-callout {{
            background: rgba(255,255,255,0.04);
            border: 1px solid {border_soft};
            border-left: 3px solid {t.accent};
            border-radius: 10px;
            padding: 12px 14px;
            margin: 10px 0;
        }}
        QTextBrowser#bubble_body .snip-callout-icon {{ color: {t.accent}; font-weight: 800; }}
        QTextBrowser#bubble_body .snip-callout-label {{ color: #ffffff; font-weight: 700; letter-spacing: 0.3px; }}
        QTextBrowser#bubble_body .snip-callout-text {{ color: {text_main}; }}

        /* ── Buttons ───────────────────────────────────── */
        QPushButton {{
            background: rgba(255, 255, 255, 0.06);
            color: {text_main};
            border: 1px solid {border_soft};
            border-radius: 10px;
            padding: 8px 16px;
            font-size: 9.5pt;
            font-weight: 500;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton:hover {{
            background: rgba(255, 255, 255, 0.10);
            border-color: {border_hover};
        }}
        QPushButton#close_btn {{
            background: transparent; border: none;
            color: {text_muted}; font-size: 12pt; padding: 0;
            border-radius: 8px;
        }}
        QPushButton#close_btn:hover {{ background: rgba(255,255,255,0.08); color: #ffffff; }}
        QPushButton#expand_btn {{
            background: transparent; border: 1px solid transparent;
            color: {text_muted}; font-size: 11pt; padding: 0;
            border-radius: 8px;
        }}
        QPushButton#expand_btn:hover {{
            background: rgba(255,255,255,0.08); color: #ffffff; border-color: {border_soft};
        }}
        QPushButton#switch_btn {{
            background: transparent; border: 1px solid transparent;
            color: {text_muted}; font-size: 11pt; padding: 0;
            border-radius: 8px;
        }}
        QPushButton#switch_btn:hover {{
            background: rgba(255,255,255,0.08); color: #ffffff; border-color: {border_soft};
        }}
        QWidget#rate_limit_bar {{
            background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25);
            border-radius: 12px; margin: 8px 16px;
        }}
        QLabel#rate_limit_label {{
            color: #fca5a5; font-size: 9pt; font-weight: 600; font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#rate_limit_btn {{
            background: #ef4444; color: #ffffff; border: none; font-weight: 700;
            border-radius: 999px; padding: 7px 16px; font-size: 9pt; font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#rate_limit_btn:hover {{ background: #dc2626; }}
        QPushButton#primary {{
            background: #ffffff;
            color: #000000; border: none; font-weight: 650;
            border-radius: 10px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#primary:hover {{ background: #ececec; }}
        QPushButton#primary:pressed {{ background: #d4d4d4; }}
        QFrame#sep {{ background: {border_soft}; max-height: 1px; }}
        QSizeGrip#size_grip {{ background: transparent; }}

        QScrollBar:vertical {{
            background: transparent; width: 6px; margin: 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,0.14); border-radius: 3px; min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.22); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

        /* ── Action bar / pills ────────────────────────── */
        QWidget#action_bar {{ background: transparent; min-height: 48px; }}
        QPushButton#action_btn {{
            min-height: 34px;
            max-height: 38px;
            padding: 7px 14px;
            border-radius: 999px;
            color: #ffffff;
            font-size: 9pt;
            font-weight: 600;
            letter-spacing: 0.2px;
            background: rgba(255,255,255,0.08);
            border: 1px solid {border_soft};
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#action_btn:hover {{
            background: rgba(255,255,255,0.12);
            border-color: {border_hover};
        }}
        QPushButton#action_btn:pressed {{
            background: rgba(255,255,255,0.16);
        }}

        /* ── Chat input — ChatGPT pill ─────────────────── */
        QTextEdit#chat_input {{
            background: transparent;
            color: #ffffff;
            border: none;
            padding: 6px 2px;
            font-family: 'Inter','Segoe UI',sans-serif;
            font-size: 10.5pt;
            selection-background-color: {t.accent}55;
        }}
        QTextEdit#chat_input:disabled {{ color: {text_muted}; }}

        QFrame#input_container {{
            background: {bg_input};
            border: 1px solid {border_soft};
            border-radius: 24px;
        }}
        QFrame#input_container:focus-within {{
            border: 1px solid {border_hover};
        }}
        QPushButton#input_tool {{
            background: transparent;
            border: none;
            border-radius: 999px;
            color: {text_muted};
            font-size: 11pt;
            padding: 0;
        }}
        QPushButton#input_tool:hover {{
            background: rgba(255,255,255,0.08); color: #ffffff;
        }}
        QPushButton#send_btn {{
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.06);
            border-radius: 10px;
            color: #000000;
            font-size: 11pt;
            font-weight: 800;
            padding: 0;
        }}
        QPushButton#send_btn:hover {{ background: #ececec; border-color: rgba(0,0,0,0.08); }}
        QPushButton#send_btn:pressed {{ background: #d4d4d4; }}
        QPushButton#send_btn:disabled {{
            background: rgba(255,255,255,0.12); color: {text_dim}; border: 1px solid transparent;
        }}
        QLabel#disclaimer {{
            color: {text_dim}; font-size: 7.5pt; font-family: 'Inter','Segoe UI',sans-serif;
        }}

        /* ── Message rows ──────────────────────────────── */
        QFrame#user_row, QFrame#assistant_row {{
            border: none;
        }}
        QLabel#row_avatar_ai {{
            background: #ffffff;
            color: #000000; font-size: 8pt; font-weight: 800;
            border-radius: 16px;
            border: 1px solid rgba(0,0,0,0.06);
        }}
        QLabel#row_avatar_user {{
            background: #52525b; color: #ffffff;
            font-size: 8pt; font-weight: 700; border-radius: 16px;
        }}
        QLabel#row_name {{ color: #ffffff; font-size: 9pt; font-weight: 600; font-family: 'Inter','Segoe UI',sans-serif; }}
        QLabel#row_time {{ color: {text_dim}; font-size: 7.5pt; font-family: 'Inter','Segoe UI',sans-serif; }}

        QWidget#msg_actions {{ background: transparent; }}
        QPushButton#msg_action_btn {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            color: {text_muted};
            font-size: 10pt;
            padding: 4px 6px;
        }}
        QPushButton#msg_action_btn:hover {{
            background: rgba(255,255,255,0.06); color: #ffffff; border-color: {border_soft};
        }}
        QPushButton#export_btn {{
            background: rgba(255,255,255,0.06);
            border: 1px solid {border_soft};
            border-radius: 999px;
            color: {text_main};
            font-size: 8pt;
            font-weight: 600;
            padding: 5px 12px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QPushButton#export_btn:hover {{ background: rgba(255,255,255,0.10); border-color: {border_hover}; }}
        QPushButton#export_btn::menu-indicator {{ width: 0; }}
        QMenu {{
            background: #2a2a2a;
            border: 1px solid {border_soft};
            border-radius: 12px;
            color: {text_main};
            padding: 6px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QMenu::item {{ padding: 8px 16px; border-radius: 8px; font-size: 9.5pt; }}
        QMenu::item:selected {{ background: {bg_input}; color: #ffffff; }}

        QComboBox#model_select, QComboBox#mode_select {{
            background: {bg_input};
            color: {text_main};
            border: 1px solid {border_soft};
            border-radius: 999px;
            padding: 6px 14px;
            font-size: 8.5pt;
            font-family: 'Inter','Segoe UI',sans-serif;
            min-height: 22px;
        }}
        QComboBox#model_select:hover, QComboBox#mode_select:hover {{
            border: 1px solid {border_hover};
            background: #3a3a3a;
        }}
        QComboBox#model_select::drop-down, QComboBox#mode_select::drop-down {{
            border: none; width: 16px;
        }}
        QComboBox#model_select::down-arrow, QComboBox#mode_select::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {text_muted};
            margin-right: 8px;
        }}
        QComboBox#model_select QAbstractItemView, QComboBox#mode_select QAbstractItemView {{
            background: #2a2a2a;
            color: {text_main};
            border: 1px solid {border_soft};
            border-radius: 12px;
            selection-background-color: {t.accent}55;
            selection-color: #ffffff;
            padding: 6px; outline: 0;
        }}

        /* ── Free-only toggle ──────────────────────────── */
        QCheckBox#free_only_check {{
            color: {text_muted};
            font-size: 8.5pt;
            font-weight: 500;
            spacing: 8px;
            font-family: 'Inter','Segoe UI',sans-serif;
        }}
        QCheckBox#free_only_check::indicator {{
            width: 40px; height: 22px;
            image: url({toggle_off});
        }}
        QCheckBox#free_only_check::indicator:checked {{
            image: url({toggle_on});
        }}
        QCheckBox#free_only_check:disabled {{ color: {text_dim}; }}
    """


def get_link_color(theme: ThemeConfig) -> str:
    """Return link color for QPalette."""
    return theme.accent
