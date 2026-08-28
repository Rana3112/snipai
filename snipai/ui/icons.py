"""Lucide icon helper for SnipAI — modern, crisp SVG icons.

Uses Lucide (https://lucide.dev) SVGs rendered via QSvgRenderer.
Icons are stroke-based, 24×24 viewBox, currentColor → replaced with requested color.
Falls back to text glyph if SVG missing or QtSvg not available.

Setup: `pnpm add lucide` for web, but for PySide6 we bundle SVGs in `snipai/ui/lucide_icons/`
or fetch on demand from unpkg CDN and cache in `~/.snipai/lucide_cache/`.

Usage:
    from .icons import lucide_icon, lucide_pixmap
    btn.setIcon(lucide_icon("search", 18, "#ececec"))
    label.setPixmap(lucide_pixmap("sparkles", 24, "#5b6aff"))
"""
from __future__ import annotations
import logging
from pathlib import Path
import re

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import QByteArray, QSize, Qt

log = logging.getLogger(__name__)

# Try to import QSvgRenderer (QtSvg)
try:
    from PySide6.QtSvg import QSvgRenderer
    HAS_SVG = True
except ImportError:
    try:
        from PySide6.QtSvgWidgets import QSvgRenderer  # type: ignore
        HAS_SVG = True
    except ImportError:
        HAS_SVG = False
        log.warning("QtSvg not available — Lucide icons will fallback to text")

# Cache dir for downloaded SVGs
_CACHE_DIR = Path.home() / ".snipai" / "lucide_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Bundled icons dir (inside package)
_BUNDLED_DIR = Path(__file__).parent / "lucide_icons"

# CDN for on-demand fetch (fallback)
_CDN_TEMPLATES = [
    "https://unpkg.com/lucide-static@latest/icons/{name}.svg",
    "https://cdn.jsdelivr.net/npm/lucide-static@latest/icons/{name}.svg",
]

# Simple in-memory cache of QIcon/QPixmap
_ICON_CACHE: dict[tuple[str, int, str], QIcon] = {}
_PIXMAP_CACHE: dict[tuple[str, int, str], QPixmap] = {}


def _load_svg_content(name: str) -> str | None:
    """Load SVG string for icon `name`. Checks bundled, then cache, then CDN."""
    # 1. Bundled
    bundled = _BUNDLED_DIR / f"{name}.svg"
    if bundled.exists():
        try:
            return bundled.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("Failed to read bundled %s: %s", name, e)
    # 2. Disk cache
    cached = _CACHE_DIR / f"{name}.svg"
    if cached.exists():
        try:
            return cached.read_text(encoding="utf-8")
        except Exception:
            pass
    # 3. CDN fetch (best-effort, short timeout)
    try:
        import requests
        for tmpl in _CDN_TEMPLATES:
            url = tmpl.format(name=name)
            try:
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200 and "<svg" in resp.text:
                    svg = resp.text
                    try:
                        cached.write_text(svg, encoding="utf-8")
                    except Exception:
                        pass
                    return svg
            except Exception:
                continue
    except Exception as e:
        log.debug("CDN fetch failed for %s: %s", name, e)
    return None


def _colorize_svg(svg: str, color: str) -> str:
    """Replace currentColor/stroke with `color`, ensure stroke width consistent."""
    # Lucide uses stroke="currentColor" and fill="none" by default
    # Replace all stroke="currentColor" and stroke="black"/etc. with requested color
    # Keep fill="none" as is, but ensure stroke is set
    svg = re.sub(r'stroke="[^"]*"', f'stroke="{color}"', svg)
    # If no stroke attribute on path, Lucide SVGs already have it; but ensure root has stroke
    if 'stroke=' not in svg:
        svg = svg.replace("<svg", f'<svg stroke="{color}"', 1)
    # Ensure color is applied to style if present
    return svg


def _render_svg_to_pixmap(svg: str, size: int, color: str) -> QPixmap | None:
    """Render SVG string to QPixmap of `size`×`size` with `color` stroke."""
    if not HAS_SVG:
        return None
    try:
        colored = _colorize_svg(svg, color)
        data = QByteArray(colored.encode("utf-8"))
        renderer = QSvgRenderer(data)
        if not renderer.isValid():
            log.warning("Invalid SVG for rendering")
            return None
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        return pix
    except Exception as e:
        log.warning("SVG render failed: %s", e)
        return None


def lucide_pixmap(name: str, size: int = 24, color: str = "#ececec") -> QPixmap | None:
    """Return QPixmap for Lucide icon `name` or None if unavailable."""
    key = (name, size, color)
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
    svg = _load_svg_content(name)
    if not svg:
        log.debug("Lucide icon not found: %s", name)
        return None
    pix = _render_svg_to_pixmap(svg, size, color)
    if pix is not None:
        _PIXMAP_CACHE[key] = pix
    return pix


def lucide_icon(name: str, size: int = 24, color: str = "#ececec") -> QIcon:
    """Return QIcon for Lucide icon `name`. Falls back to empty icon if missing."""
    key = (name, size, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    pix = lucide_pixmap(name, size, color)
    if pix is not None and not pix.isNull():
        icon = QIcon(pix)
        _ICON_CACHE[key] = icon
        return icon
    # Fallback: empty icon (caller should handle text fallback)
    icon = QIcon()
    _ICON_CACHE[key] = icon
    return icon


def set_button_lucide_icon(button, name: str, size: int = 18, color: str = "#ececec", fallback_text: str | None = None):
    """Helper: set QPushButton icon to Lucide, with optional text fallback."""
    icon = lucide_icon(name, size, color)
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QSize(size, size))
        # Keep text if provided, but icon will be shown; for icon-only buttons, clear text
        if fallback_text is not None:
            # For buttons that were text-only, we replace text with empty and rely on icon
            # But keep tooltip as fallback_text
            if not button.text() or button.text() in ["✕", "⛶", "🗗", "🔄", "✦", "📖", "📄", "🌐", "⧉", "👍", "👎", "🔊", "⋯", "➤", "📎", "☾", "⛉", "⚙", "✎"]:
                button.setText("")
        else:
            # If button already has text like "Explain...", keep it and add icon
            pass
    else:
        # No icon available — keep fallback text
        if fallback_text and not button.text():
            button.setText(fallback_text)


# Convenience: common icons mapping for SnipAI
ICON_MAP = {
    # Brand / general
    "sparkles": "sparkles",
    "bot": "bot",
    "plus": "plus",
    "pen": "square-pen",
    "history": "history",
    "clock": "clock",
    # Footer
    "moon": "moon",
    "shield": "shield",
    "settings": "settings",
    # Header
    "maximize": "maximize-2",
    "minimize": "minimize-2",
    "close": "x",
    "refresh": "refresh-cw",
    "shuffle": "shuffle",
    # Text options
    "book_open": "book-open",
    "file_text": "file-text",
    "globe": "globe",
    # Input
    "paperclip": "paperclip",
    "send": "send",
    "send_horizontal": "send-horizontal",
    # Message actions
    "copy": "copy",
    "thumbs_up": "thumbs-up",
    "thumbs_down": "thumbs-down",
    "volume": "volume-2",
    "ellipsis": "ellipsis",
    "download": "download",
    # Misc
    "user": "user",
    "search": "search",
    "chevron_down": "chevron-down",
    "sliders": "sliders-horizontal",
    "palette": "palette",
}
