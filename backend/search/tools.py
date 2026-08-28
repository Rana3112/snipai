"""Web search + deep scraping pipeline — TinyFish (Monid) free tier primary.

Primary: TinyFish via Monid CLI ($0/1k) — killed SerpAPI/Brave/Exa/Tavily.
Fallback: Jina-proxied DuckDuckGo + Jina Reader (also free, no key).

Backend runs on Render where `monid` CLI likely not installed → auto falls back to Jina,
so deploys without extra env. Desktop client with monid installed gets free TinyFish.
"""
from __future__ import annotations
import json
import logging
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote

import requests

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_MONID_TIMEOUT_S = 28

# Candidate JS entry points (Windows + Linux)
_MONID_JS_CANDIDATES = [
    Path(r"C:\Users\utkar\AppData\Roaming\npm\node_modules\@monid-ai\cli\dist\index.js"),
    Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@monid-ai" / "cli" / "dist" / "index.js",
    Path("/usr/local/lib/node_modules/@monid-ai/cli/dist/index.js"),
    Path("/opt/node_modules/@monid-ai/cli/dist/index.js"),
    Path.home() / ".nvm" / "versions" / "node" / "v20.0.0" / "lib" / "node_modules" / "@monid-ai" / "cli" / "dist" / "index.js",
]


def _monid_cmd_base() -> list[str] | None:
    """Return base command to invoke Monid CLI, or None if not installed."""
    # Prefer `monid` binary directly (works cross-platform, respects PATH)
    monid_bin = shutil.which("monid")
    if monid_bin:
        # Use the binary directly — it handles node resolution internally
        # We will call it via `monid` so PATH lookup works, but for subprocess we use full path
        return [monid_bin]
    # Fallback: node + JS entry
    for p in _MONID_JS_CANDIDATES:
        if p.exists():
            node = shutil.which("node")
            if node:
                return [node, str(p)]
            return ["node", str(p)]
    # Try npx as last resort
    npx = shutil.which("npx")
    if npx:
        return [npx, "monid"]
    return None


def _has_monid() -> bool:
    return _monid_cmd_base() is not None


def _search_via_tinyfish(query: str, max_results: int = 6) -> list[dict] | None:
    base = _monid_cmd_base()
    if not base:
        return None
    try:
        payload = json.dumps({"query": query})
        cmd = base + ["run", "-p", "tinyfish", "-e", "/search", "--query", payload, "-w", "-j"]
        env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=_MONID_TIMEOUT_S, env=env)
        if result.returncode != 0:
            log.warning("tinyfish search failed: %s", result.stderr.strip()[:400])
            return None
        data = json.loads(result.stdout)
        if data.get("status") != "COMPLETED":
            if data.get("status") == "BLOCKED":
                log.warning("tinyfish search BLOCKED: %s", json.dumps(data.get("controls", []))[:400])
            return None
        output = data.get("output") or {}
        results = output.get("results") or []
        out: list[dict] = []
        for r in results[:max_results]:
            url = (r.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            out.append({
                "title": (r.get("title") or r.get("site_name") or url).strip(),
                "url": url,
                "snippet": (r.get("snippet") or "").strip()[:400],
            })
        if not out:
            return None
        log.info("tinyfish search '%s' -> %d (free)", query[:60], len(out))
        return out
    except subprocess.TimeoutExpired:
        log.warning("tinyfish search timeout")
        return None
    except Exception as e:
        log.warning("tinyfish search exception: %s", e)
        return None


def _fetch_via_tinyfish(urls: list[str], max_chars: int = 3000) -> list[str] | None:
    if not urls:
        return []
    base = _monid_cmd_base()
    if not base:
        return None
    batch = urls[:10]
    try:
        payload = json.dumps({"urls": batch, "format": "markdown"})
        cmd = base + ["run", "-p", "tinyfish", "-e", "/fetch", "-i", payload, "-w", "-j"]
        env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=_MONID_TIMEOUT_S + 10, env=env)
        if result.returncode != 0:
            log.warning("tinyfish fetch failed: %s", result.stderr.strip()[:400])
            return None
        data = json.loads(result.stdout)
        if data.get("status") != "COMPLETED":
            return None
        output = data.get("output") or {}
        url_to_text: dict[str, str] = {}
        for r in output.get("results") or []:
            url = r.get("url") or r.get("final_url") or ""
            text = r.get("text") or ""
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"
            if url:
                url_to_text[url] = text
                if r.get("final_url") and r.get("final_url") != url:
                    url_to_text[r.get("final_url")] = text
        out: list[str] = []
        for u in batch:
            txt = url_to_text.get(u, "")
            if not txt:
                for k, v in url_to_text.items():
                    if u in k or k in u:
                        txt = v
                        break
            out.append(txt)
        if not any(s.strip() for s in out):
            return None
        return out
    except subprocess.TimeoutExpired:
        log.warning("tinyfish fetch timeout")
        return None
    except Exception as e:
        log.warning("tinyfish fetch exception: %s", e)
        return None


def _search_raw(query: str, max_results: int = 6) -> list[dict]:
    """Fallback: DuckDuckGo via Jina."""
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
    except Exception:
        log.exception("search failed")
        return []


def web_search(query: str, max_results: int = 5) -> str:
    results = _search_via_tinyfish(query, max_results)
    if results is None:
        results = _search_raw(query, max_results)
    if not results:
        return "No results found."
    return "\n\n".join(f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}" for r in results)


def scrape_url(url: str, max_chars: int = 4000) -> str:
    fetched = _fetch_via_tinyfish([url], max_chars)
    if fetched is not None and fetched[0].strip():
        return fetched[0]
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", headers={"User-Agent": _UA}, timeout=20)
        resp.raise_for_status()
        text = resp.text.strip()
        if text:
            return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")
    except Exception as e:
        log.warning("Jina Reader failed for %s: %s", url, e)
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = "\n".join(ln for ln in soup.get_text(separator="\n", strip=True).splitlines() if ln.strip())
        return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")
    except Exception as e:
        log.warning("scrape fallback failed for %s: %s", url, e)
        return ""


def deep_research(query: str, max_results: int = 6, scrape_pages: int = 3,
                  chars_per_page: int = 3000) -> str:
    results = _search_via_tinyfish(query, max_results)
    if results is None:
        results = _search_raw(query, max_results)
    if not results:
        return ""
    top = results[:scrape_pages]
    urls = [r["url"] for r in top]
    scraped = _fetch_via_tinyfish(urls, chars_per_page)
    if scraped is None:
        with ThreadPoolExecutor(max_workers=max(1, len(top))) as ex:
            scraped = list(ex.map(lambda r: scrape_url(r["url"], chars_per_page), top))
    parts: list[str] = []
    for r, content in zip(top, scraped):
        body = (content or "").strip() or r["snippet"]
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{body}")
    for r in results[scrape_pages:]:
        parts.append(f"### {r['title']}\nURL: {r['url']}\n{r['snippet']}")
    return "\n\n---\n\n".join(parts)
