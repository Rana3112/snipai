"""Web search + deep scraping pipeline — TinyFish (Monid) free tier primary.

Deterministic: search and page-fetch run in pure Python (no model roundtrips),
so the AI backend is only hit for the final answer. Avoids rate-limit (429)
from agentic tool-call loops.

Primary path (FREE, $0/1k):
  TinyFish via Monid CLI — 100% free search & fetch (killed SerpAPI/Brave/Exa/Tavily
  per https://monid.ai/SKILL.md). Uses `monid run -p tinyfish -e /search|/fetch`.
  No subscriptions, no quotas, no credit card. $0 per 1,000 searches vs $7 elsewhere.

Fallback (also free, no key):
  DuckDuckGo HTML proxied through Jina Reader + Jina Reader scrape + BeautifulSoup.
  Jina IP never hits DDG directly → no 202/ratelimit block.

Switching is automatic: try TinyFish, fall back to Jina on any failure or if
`monid` CLI / API key is missing. Keeps SnipAI working offline and in CI.
"""
from __future__ import annotations
import json
import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Monid CLI location — installed via `npm install -g @monid-ai/cli`
_MONID_JS_CANDIDATES = [
    Path(r"C:\Users\utkar\AppData\Roaming\npm\node_modules\@monid-ai\cli\dist\index.js"),
    Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@monid-ai" / "cli" / "dist" / "index.js",
]
# Also check generic npm global via `which monid` -> resolve node path
_MONID_TIMEOUT_S = 28  # search/fetch typically 2-4s p50, 18s p95


def _monid_js_path() -> Path | None:
    """Return Monid CLI entry JS if present, else None."""
    for p in _MONID_JS_CANDIDATES:
        if p.exists():
            return p
    # Try resolving `monid` binary and derive JS path
    which = shutil.which("monid")
    if which:
        # monid.ps1 lives next to node_modules
        base = Path(which).resolve().parent
        cand = base / "node_modules" / "@monid-ai" / "cli" / "dist" / "index.js"
        if cand.exists():
            return cand
        # Also try `which node` base
        node = shutil.which("node")
        if node:
            cand2 = Path(node).parent.parent / "lib" / "node_modules" / "@monid-ai" / "cli" / "dist" / "index.js"
            if cand2.exists():
                return cand2
    return None


def _has_monid() -> bool:
    """True if Monid CLI is installed. Key validity is checked at run-time."""
    return _monid_js_path() is not None


def _search_via_tinyfish(query: str, max_results: int = 6) -> list[dict] | None:
    """Search via TinyFish (Monid) — FREE $0 per 1k. Returns list of {title,url,snippet} or None on failure."""
    js = _monid_js_path()
    if not js:
        return None
    try:
        payload = json.dumps({"query": query})
        # TinyFish /search is GET with queryParams. We request web corpus, default.
        cmd = ["node", str(js), "run", "-p", "tinyfish", "-e", "/search", "--query", payload, "-w", "-j"]
        env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=_MONID_TIMEOUT_S, env=env)
        if result.returncode != 0:
            log.warning("tinyfish search failed (rc=%s): %s", result.returncode, result.stderr.strip()[:400])
            return None
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            log.warning("tinyfish search JSON parse failed: %s | stdout=%.500s", e, result.stdout)
            return None
        if data.get("status") != "COMPLETED":
            # Check for BLOCKED (budget cap) — surface to user via log, fall back
            if data.get("status") == "BLOCKED":
                log.warning("tinyfish search BLOCKED by workspace control: %s", json.dumps(data.get("controls", []))[:400])
            else:
                log.warning("tinyfish search not COMPLETED: %s", data.get("status"))
            return None
        output = data.get("output") or {}
        results = output.get("results") or []
        out: list[dict] = []
        for r in results[:max_results]:
            url = (r.get("url") or "").strip()
            if not url or not url.startswith("http"):
                continue
            title = (r.get("title") or r.get("site_name") or url).strip()
            snippet = (r.get("snippet") or "").strip()[:400]
            out.append({"title": title, "url": url, "snippet": snippet})
        # If TinyFish returned 0 results but query was valid, let caller fall back to Jina
        if not out:
            log.info("tinyfish search returned 0 results for '%s', falling back", query[:60])
            return None
        log.info("tinyfish search '%s' -> %d results (free)", query[:60], len(out))
        return out
    except subprocess.TimeoutExpired:
        log.warning("tinyfish search timeout for '%s'", query[:60])
        return None
    except Exception as e:
        log.warning("tinyfish search exception: %s", e)
        return None


def _fetch_via_tinyfish(urls: list[str], max_chars: int = 3000) -> list[str] | None:
    """Fetch 1-10 URLs via TinyFish /fetch — FREE. Returns list[str] aligned with urls, or None on hard failure."""
    if not urls:
        return []
    js = _monid_js_path()
    if not js:
        return None
    # TinyFish caps at 10 URLs per call — SnipAI never exceeds 3, so single batch
    batch = urls[:10]
    try:
        payload = json.dumps({"urls": batch, "format": "markdown"})
        cmd = ["node", str(js), "run", "-p", "tinyfish", "-e", "/fetch", "-i", payload, "-w", "-j"]
        env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=_MONID_TIMEOUT_S + 10, env=env)
        if result.returncode != 0:
            log.warning("tinyfish fetch failed (rc=%s): %s", result.returncode, result.stderr.strip()[:400])
            return None
        try:
            data = json.loads(result.stdout)
        except Exception as e:
            log.warning("tinyfish fetch JSON parse failed: %s", e)
            return None
        if data.get("status") != "COMPLETED":
            if data.get("status") == "BLOCKED":
                log.warning("tinyfish fetch BLOCKED: %s", json.dumps(data.get("controls", []))[:400])
            else:
                log.warning("tinyfish fetch not COMPLETED: %s", data.get("status"))
            return None
        output = data.get("output") or {}
        # Results contain per-URL text; errors contain per-URL failures
        results = output.get("results") or []
        errors = output.get("errors") or []
        # Map url -> text
        url_to_text: dict[str, str] = {}
        for r in results:
            url = r.get("url") or r.get("final_url") or ""
            text = r.get("text") or ""
            if text and len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"
            if url:
                url_to_text[url] = text
                # Also map final_url if different
                final = r.get("final_url")
                if final and final != url:
                    url_to_text[final] = text
        # Log per-URL errors but don't fail batch
        if errors:
            log.info("tinyfish fetch partial errors: %s", json.dumps(errors)[:500])
        out: list[str] = []
        for u in batch:
            txt = url_to_text.get(u, "")
            if not txt:
                # Try matching by final_url key or substring
                for k, v in url_to_text.items():
                    if u in k or k in u:
                        txt = v
                        break
            out.append(txt)
        # If all empty, signal fallback
        if not any(s.strip() for s in out):
            log.info("tinyfish fetch returned all empty for %d urls, falling back", len(batch))
            return None
        log.info("tinyfish fetch %d urls -> %d with content (free)", len(batch), sum(1 for s in out if s.strip()))
        return out
    except subprocess.TimeoutExpired:
        log.warning("tinyfish fetch timeout for %d urls", len(batch))
        return None
    except Exception as e:
        log.warning("tinyfish fetch exception: %s", e)
        return None


# ── Legacy Jina/DuckDuckGo path (fallback, also free) ─────────────────────

def _search_raw(query: str, max_results: int = 6) -> list[dict]:
    """Fallback: Search via DuckDuckGo HTML proxied through Jina Reader."""
    import re
    import requests
    from urllib.parse import quote, unquote

    try:
        proxied = "https://r.jina.ai/https://duckduckgo.com/html/?q=" + quote(query)
        resp = requests.get(proxied, headers={"User-Agent": _UA}, timeout=25)
        resp.raise_for_status()
        md = resp.text

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
    """Formatted search results (titles/urls/snippets) as a single string. Prefers TinyFish free."""
    # Try free TinyFish first
    results = _search_via_tinyfish(query, max_results)
    if results is None:
        results = _search_raw(query, max_results)
    if not results:
        return "No results found."
    return "\n\n".join(
        f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}"
        for r in results
    )


def scrape_url(url: str, max_chars: int = 4000) -> str:
    """Fetch page text. Prefers TinyFish free fetch, falls back to Jina Reader + BeautifulSoup."""
    # Try TinyFish for single URL
    fetched = _fetch_via_tinyfish([url], max_chars)
    if fetched is not None and fetched[0].strip():
        return fetched[0]
    # Fallback: Jina Reader
    import requests

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
    """Full pipeline: search → fetch top N pages → build context block.

    Primary: TinyFish free ($0). Fallback: Jina/DuckDuckGo.
    Returns "" if search finds nothing (caller answers without web context).
    """
    # 1. Search — prefer free TinyFish
    results = _search_via_tinyfish(query, max_results)
    if results is None:
        log.info("deep_research: tinyfish search miss, using Jina fallback for '%s'", query[:60])
        results = _search_raw(query, max_results)
    if not results:
        return ""

    top = results[:scrape_pages]
    urls = [r["url"] for r in top]

    # 2. Fetch — prefer free TinyFish batch fetch (1 call for up to 10 URLs)
    scraped: list[str] | None = _fetch_via_tinyfish(urls, chars_per_page)
    if scraped is None:
        log.info("deep_research: tinyfish fetch miss, using Jina concurrent fallback")
        # Fallback: concurrent Jina fetches — pure HTTP, no model calls.
        with ThreadPoolExecutor(max_workers=max(1, len(top))) as ex:
            scraped = list(ex.map(lambda r: scrape_url(r["url"], chars_per_page), top))
    # scraped is now aligned with top

    parts: list[str] = []
    for r, content in zip(top, scraped):
        body = (content or "").strip() or r["snippet"]
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{body}")
    # Remaining results: snippet-only (gives the model more links to cite).
    for r in results[scrape_pages:]:
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{r['snippet']}")

    return "\n\n---\n\n".join(parts)
