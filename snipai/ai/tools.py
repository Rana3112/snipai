"""Web search + deep scraping pipeline.

Deterministic: search and page-fetch run in pure Python (no model roundtrips),
so the AI backend is only hit for the final answer. Avoids rate-limit (429)
from agentic tool-call loops.
"""
from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _search_raw(query: str, max_results: int = 6) -> list[dict]:
    """Search via DuckDuckGo HTML proxied through Jina Reader.

    Routing the search page through r.jina.ai uses Jina's IP, so our IP never
    hits DDG directly → no 202/ratelimit block. Returns list of {title, url, snippet}.
    """
    import re
    import requests
    from urllib.parse import quote, unquote

    try:
        proxied = "https://r.jina.ai/https://duckduckgo.com/html/?q=" + quote(query)
        resp = requests.get(proxied, headers={"User-Agent": _UA}, timeout=25)
        resp.raise_for_status()
        md = resp.text

        # Each result is a markdown heading: ## [Title](ddg-redirect-url)
        # followed by snippet text until the next heading.
        blocks = re.split(r"^##\s+", md, flags=re.M)
        out: list[dict] = []
        link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        for block in blocks[1:]:
            m = link_re.search(block)
            if not m:
                continue
            title, href = m.group(1).strip(), m.group(2).strip()
            if "uddg=" in href:
                href = unquote(href.split("uddg=")[1].split("&")[0])
            if not href.startswith("http") or "duckduckgo.com" in href:
                continue
            # Snippet: text after the link line, cleaned of markdown noise.
            rest = block[m.end():]
            snippet = " ".join(
                ln.strip() for ln in rest.splitlines()
                if ln.strip() and not ln.strip().startswith(("[", "!", "#", "URL"))
            )[:300]
            out.append({"title": title, "url": href, "snippet": snippet})
            if len(out) >= max_results:
                break
        return out
    except Exception as e:
        log.exception("search failed")
        return []


def web_search(query: str, max_results: int = 5) -> str:
    """Formatted search results (titles/urls/snippets) as a single string."""
    results = _search_raw(query, max_results)
    if not results:
        return "No results found."
    return "\n\n".join(
        f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}"
        for r in results
    )


def scrape_url(url: str, max_chars: int = 4000) -> str:
    """Fetch page text via Jina Reader (handles JS/paywalls/403). Falls back to direct scrape."""
    import requests

    # Primary: Jina Reader — prefix url, returns clean markdown. No API key.
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if text:
            return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")
    except Exception as e:
        log.warning("Jina Reader failed for %s: %s — falling back", url, e)

    # Fallback: direct fetch + BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = "\n".join(
            ln for ln in soup.get_text(separator="\n", strip=True).splitlines() if ln.strip()
        )
        return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")
    except Exception as e:
        log.warning("scrape fallback failed for %s: %s", url, e)
        return ""


def deep_research(query: str, max_results: int = 6, scrape_pages: int = 3,
                  chars_per_page: int = 3000) -> str:
    """Full pipeline: search → concurrently scrape top N pages → build context block.

    Returns "" if search finds nothing (caller answers without web context).
    """
    results = _search_raw(query, max_results)
    if not results:
        return ""

    top = results[:scrape_pages]
    # Concurrent page fetch — pure HTTP, no model calls.
    with ThreadPoolExecutor(max_workers=max(1, len(top))) as ex:
        scraped = list(ex.map(lambda r: scrape_url(r["url"], chars_per_page), top))

    parts: list[str] = []
    for r, content in zip(top, scraped):
        body = content.strip() or r["snippet"]
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{body}")
    # Remaining results: snippet-only (gives the model more links to cite).
    for r in results[scrape_pages:]:
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{r['snippet']}")

    return "\n\n---\n\n".join(parts)
