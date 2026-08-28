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
        # Use inline styles for QTextBrowser compatibility, plus class for QSS
        cells = "".join(f"<{tag}>{_format_inline(cell)}</{tag}>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    # QTextBrowser needs explicit border/cellpadding for reliable rendering; CSS in theme.py refines it
    return "<table class='snip-table' border=\"1\" cellpadding=\"8\" cellspacing=\"0\">" + "".join(body) + "</table>"


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

    # Bullet list — handles -, *, •, ·
    if re.match(r"^([-*•·]|\u2022)\s+", text):
        items = []
        for line in text.splitlines():
            m = re.match(r"^([-*•·]|\u2022)\s+(.+)$", line.strip())
            if m:
                items.append(f"<li>{_format_inline(m.group(2) if m.lastindex == 2 else m.group(1))}</li>")
            else:
                # Handle lines like "• **Title**: description" without extra dash
                m2 = re.match(r"^[•·]\s*(.+)$", line.strip())
                if m2:
                    items.append(f"<li>{_format_inline(m2.group(1))}</li>")
        if items:
            return "<ul class='snip-list'>" + "".join(items) + "</ul>"
    # Also handle block where every line starts with bullet char
    lines = text.splitlines()
    if len(lines) >= 2 and all(re.match(r"^\s*([-*•·]|\u2022)\s+", ln) or not ln.strip() for ln in lines):
        items = []
        for line in lines:
            if not line.strip():
                continue
            m = re.match(r"^\s*([-*•·]|\u2022)\s+(.+)$", line.strip())
            if m:
                items.append(f"<li>{_format_inline(m.group(2))}</li>")
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

    # Simple table block — robust: any block where 2+ lines contain | with same column count, even without separator
    if "|" in text and len(text.splitlines()) >= 2:
        rows = _split_table_block(text.splitlines())
        # Require at least header + 1 data row, and consistent column count
        if len(rows) >= 2:
            # Check that at least 2 rows have same number of columns (tolerate 1 col diff)
            col_counts = [len(r) for r in rows]
            # Most common count
            most_common = max(set(col_counts), key=col_counts.count)
            # Filter rows to those with most_common columns (allow header/data mismatch of 1)
            filtered = [r for r in rows if abs(len(r) - most_common) <= 1]
            # Pad short rows
            for r in filtered:
                while len(r) < most_common:
                    r.append("")
                if len(r) > most_common:
                    del r[most_common:]
            if len(filtered) >= 2:
                return _format_table(filtered)
        elif rows:
            return _format_table(rows)

    return f"<p>{_format_inline(text)}</p>"


def _strip_thinking(md: str) -> str:
    """Remove <think>...</think> and similar reasoning blocks that leak into the answer.

    Handles:
      - <think>...</think> (with any case, DOTALL)
      - Unclosed <think> at start (e.g., "<think> The user wants..." with no closing tag) — strip up to first real heading or paragraph
      - [THINK]...[/THINK] variant
    """
    if not md:
        return md
    # Remove complete <think>...</think> blocks (case-insensitive, DOTALL)
    md = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(r"\[\s*think\s*\].*?\[\s*/\s*think\s*\]", "", md, flags=re.IGNORECASE | re.DOTALL)
    # Handle unclosed <think> at the very start (common when model streams thinking without closing)
    # If md starts with <think> and no closing, strip from <think> to the first "---" or heading or double newline that looks like answer start
    m = re.match(r"^\s*<\s*think\s*>(.*)", md, flags=re.IGNORECASE | re.DOTALL)
    if m:
        rest = m.group(1)
        # Try to find where thinking ends: look for a heading like "#", "##", or a clear answer start like "Based on" or "The text is"
        # Fallback: if rest contains "</think>" we already removed, so this is unclosed — strip up to the last occurrence of a reasoning marker
        # Heuristic: find the last "I need to:" or "The user wants" block and remove it, keep the rest after a double newline following it
        # Simpler: if rest still contains a lot of "Rainbow Six" reasoning, try to find the first real answer heading like "##" or "###"
        # For now, if we detected unclosed think at start, remove the think tag and the following reasoning up to the first markdown heading or "---"
        # Look for a markdown heading or horizontal rule that likely starts the real answer
        # If not found, just remove the <think> tag itself and keep the rest (the reasoning will be shown but without the tag)
        # Better to strip the think tag only, not the content, if unclosed — but the image shows the entire reasoning was shown, which we want to hide
        # So we strip from <think> to the first occurrence of a clear answer marker like "\n\n" followed by a capital letter and not "I need"
        # Use a simple heuristic: split rest by double newline and drop leading paragraphs that look like internal reasoning
        parts = re.split(r"\n\s*\n", rest)
        # Drop leading parts that contain internal reasoning signals
        reasoning_signals = ["i need to:", "the user wants", "let's verify", "actually,", "wait, no", "or maybe it's about"]
        filtered = []
        dropping = True
        for p in parts:
            low = p.strip().lower()
            if dropping and any(sig in low for sig in reasoning_signals):
                continue
            if dropping and len(p.strip()) > 0 and not re.match(r"^(#{1,6}\s+|[-*•]\s+|\d+\.)", p.strip()) and len(filtered) == 0:
                # Still in reasoning, skip until we find a heading, list, or table
                # Check if next part looks like a real answer (contains a table or a clear section)
                continue
            dropping = False
            filtered.append(p)
        if filtered:
            md = "\n\n".join(filtered)
        else:
            # Fallback: just remove the tag
            md = re.sub(r"^\s*<\s*think\s*>", "", md, flags=re.IGNORECASE)
    # Also strip any remaining stray <think> or </think> tags
    md = re.sub(r"<\s*/?\s*think\s*>", "", md, flags=re.IGNORECASE)
    md = re.sub(r"\[\s*/?\s*think\s*\]", "", md, flags=re.IGNORECASE)
    return md.strip()


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

    # Strip leaked chain-of-thought before any rendering
    md = _strip_thinking(md)

    # Split into blocks on blank lines.
    blocks = re.split(r"\n\s*\n", md)
    out = []
    for block in blocks:
        formatted = _format_block(block)
        if formatted:
            out.append(formatted)

    return "\n".join(out)
