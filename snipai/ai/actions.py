"""Action extraction — turn an answer into doable actions (buttons).

Parsed locally from the finished answer markdown (NO extra API calls, so it
can't trigger rate limits). Detects:
  - code blocks     -> "Copy code"
  - URLs            -> "Open <domain>"
  - the whole answer is always copyable via the footer button.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# fenced code blocks ```lang\n...\n```
_CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
# bare URLs and markdown-link URLs
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


@dataclass
class Action:
    kind: str       # "copy_code" | "open_url"
    label: str      # button text
    payload: str    # code to copy / url to open


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    host = m.group(1) if m else url
    return host[4:] if host.startswith("www.") else host


def extract_actions(answer_md: str, max_urls: int = 4) -> list[Action]:
    actions: list[Action] = []

    # Code blocks (first 2 — avoid clutter)
    for code in _CODE_RE.findall(answer_md)[:2]:
        code = code.strip()
        if code:
            actions.append(Action("copy_code", "Copy code", code))

    # URLs (dedup, cap)
    seen: set[str] = set()
    for url in _URL_RE.findall(answer_md):
        url = url.rstrip(".,;")
        if url in seen:
            continue
        seen.add(url)
        actions.append(Action("open_url", f"Open {_domain(url)}", url))
        if len(seen) >= max_urls:
            break

    return actions
