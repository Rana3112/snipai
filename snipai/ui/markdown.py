"""Small Markdown → HTML formatter for SnipAI chat bubbles.

Keeps the UI readable without depending on a heavy Markdown renderer.
"""
from __future__ import annotations
import html
import re

from PySide6.QtCore import QUrl


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s<)]+")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*]+)\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _format_inline(text: str) -> str:
    text = _escape(text.strip())
    links: list[str] = []

    def link_placeholder(m: re.Match[str]) -> str:
        links.append(_link_html(m.group(1), m.group(2)))
        return f"__SNIP_LINK_{len(links) - 1}__"

    text = _LINK_RE.sub(link_placeholder, text)
    text = _BARE_URL_RE.sub(lambda m: _link_html(m.group(0), m.group(0)), text)
    for i, link in enumerate(links):
        text = text.replace(f"__SNIP_LINK_{i}__", link)
    text = _BOLD_RE.sub(r"<strong class='snip-highlight'>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    return text


def _link_html(label: str, url: str) -> str:
    href = url.strip()
    label_text = label.strip() or href
    return (
        f"<a class='snip-link' href='{_escape(href)}'>"
        f"<span class='snip-link-icon'>LINK</span> {_escape(label_text)}</a>"
    )


def _format_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    body = []
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{_format_inline(cell)}</{tag}>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return "<table class='snip-table'>" + "".join(body) + "</table>"


def _split_table_block(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # Skip separator rows like ---|---|---
        if all(set(cell.replace("-", "")) <= {" ", ":", "-"} for cell in cells):
            continue
        rows.append(cells)
    return rows


_RELEVANCE_RE = re.compile(r"^\*{0,2}Relevance:?\*{0,2}\s*", re.IGNORECASE)


def _format_block(text: str) -> str:
    text = text.strip()
    if not text:
        return ""

    # Relevance callout — paragraphs starting with "Relevance:" or "**Relevance:**"
    rel_match = _RELEVANCE_RE.match(text)
    if rel_match:
        body = text[rel_match.end():].strip()
        return (
            "<div class='snip-callout'>"
            "<span class='snip-callout-icon'>&#10022;</span>"
            "<span class='snip-callout-label'>Relevance</span> "
            f"<span class='snip-callout-text'>{_format_inline(body)}</span>"
            "</div>"
        )

    # Code fence
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        code = "\n".join(lines[1:-1])
        return f"<pre class='snip-code'><code>{_escape(code)}</code></pre>"

    # Heading
    heading_match = re.match(r"^(#{1,6})\s+(.+)$", text)
    if heading_match:
        level = len(heading_match.group(1))
        cls = f"snip-heading-{level}"
        return f"<h{level} class='{cls}'>{_format_inline(heading_match.group(2))}</h{level}>"

    # Bullet list
    if re.match(r"^[-*]\s+", text):
        items = []
        for line in text.splitlines():
            m = re.match(r"^[*-]\s+(.+)$", line.strip())
            if m:
                items.append(f"<li>{_format_inline(m.group(1))}</li>")
        if items:
            return "<ul class='snip-list'>" + "".join(items) + "</ul>"

    # Ordered list
    if re.match(r"^\d+[.)]\s+", text):
        items = []
        for line in text.splitlines():
            m = re.match(r"^\d+[.)]\s+(.+)$", line.strip())
            if m:
                items.append(f"<li>{_format_inline(m.group(1))}</li>")
        if items:
            return "<ol class='snip-list'>" + "".join(items) + "</ol>"

    # Simple table block
    if "|" in text and len(text.splitlines()) >= 2:
        rows = _split_table_block(text.splitlines())
        if rows:
            return _format_table(rows)

    return f"<p>{_format_inline(text)}</p>"


def markdown_to_html(md: str) -> str:
    """Convert a compact Markdown string to HTML for QTextBrowser.

    Handles:
      - headings
      - bullets
      - ordered lists
      - simple tables
      - fenced code blocks
      - bold / italic / inline code
      - Markdown links and bare URLs
    """
    if not md:
        return ""

    # Split into blocks on blank lines.
    blocks = re.split(r"\n\s*\n", md)
    out = []
    for block in blocks:
        formatted = _format_block(block)
        if formatted:
            out.append(formatted)

    return "\n".join(out)
