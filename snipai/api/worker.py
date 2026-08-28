"""Streaming worker — calls the hosted backend instead of direct API calls.

Same QThread pattern as the original GeminiWorker, same signals.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import QThread, Signal

from .client import SnipAIBackend, RateLimitError, UpstreamError
from ..ai.models import get_cached_records, pick_free_vision, pick_random_free_vision_across_active, get_active_provider_ids
from ..config import config
import random

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You analyze screenshots. The user has selected a region of their screen "
    "(text, code, image, UI, document, anything) and is asking about it. "
    "Be accurate and concise. If the selection is text or code, treat it as the "
    "primary content. Use Markdown. Keep answers tight. "
    "Format answers for a compact floating chat UI: use short sections, bullets, "
    "bold key takeaways, and tables when comparing items or summarizing structured data. "
    "For links, use descriptive link text and include the URL in parentheses when useful. "
    "For follow-up questions, refer back to the original selection and prior turns. "
    "Never include <think> tags, chain-of-thought, or internal reasoning — only the final answer."
)

PLANNER_SUFFIX = (
    "First, briefly analyze the selection and the question above. "
    "Then decide whether a web search would help answer it with current or external "
    "information (news, official/apply links, prices, dates, facts not visible in the image). "
    "On the VERY LAST line of your reply output EXACTLY one of:\n"
    "SEARCH_QUERY: <a concise, specific web search query>\n"
    "SEARCH_QUERY: NONE"
)


def _last_user_has_image(messages: list[dict]) -> bool:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, list):
                return any(
                    isinstance(p, dict) and p.get("type") == "image_url"
                    for p in content
                )
            return False
    return False


def _strip_images(messages: list[dict]) -> list[dict]:
    """Remove image_url parts from all user messages."""
    out: list[dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            text_parts = [
                p for p in content
                if not (isinstance(p, dict) and p.get("type") == "image_url")
            ]
            if len(text_parts) == 1 and isinstance(text_parts[0], dict) and text_parts[0].get("type") == "text":
                out.append({**m, "content": text_parts[0]["text"]})
            elif text_parts:
                out.append({**m, "content": text_parts})
            else:
                out.append({**m, "content": ""})
        else:
            out.append(m)
    return out


def _parse_search_query(analysis: str) -> tuple[str, str | None]:
    """Split analysis from the trailing SEARCH_QUERY line."""
    query: str | None = None
    lines = analysis.splitlines()
    keep: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.upper().startswith("SEARCH_QUERY:"):
            val = stripped.split(":", 1)[1].strip()
            if val and val.upper() != "NONE":
                query = val
            continue
        keep.append(ln)
    return "\n".join(keep).strip(), query


def build_initial_messages(prompt: str, png: bytes, system: str | None = None) -> list[dict]:
    """First turn: system + user(image + text)."""
    import base64
    b64 = base64.b64encode(png).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": prompt},
            ],
        },
    ]


def build_text_messages(prompt: str, selected_text: str, system: str | None = None) -> list[dict]:
    """Text-selection turn: system + user(prompt + selected text)."""
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f'{prompt}\n\nSelected text:\n"""\n{selected_text}\n"""',
        },
    ]


def build_stack_messages(prompt: str, items: list[dict], system: str | None = None) -> list[dict]:
    """Multi-snip turn: one user message holding several crops/texts."""
    import base64
    content: list[dict] = [{"type": "text", "text": prompt}]
    for i, it in enumerate(items, 1):
        if it.get("png"):
            b64 = base64.b64encode(it["png"]).decode("ascii")
            content.append({"type": "text", "text": f"\n--- Item {i} (image) ---"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        elif it.get("text"):
            content.append({
                "type": "text",
                "text": f'\n--- Item {i} (text) ---\n"""\n{it["text"]}\n"""',
            })
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


class GeminiWorker(QThread):
    """Calls the hosted SnipAI backend. Same interface as original.

    Two-level failover: picks the next free+vision model in the current
    provider, then rotates to the next provider in config.fallback_order.
    Emits `model_switched(model_id)` and `provider_switched(provider_id, model_id)`
    so the UI can sync dropdown + provider badge.
    """

    chunk = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)
    tool_used = Signal(str)
    model_switched = Signal(str)                       # model id
    provider_switched = Signal(str, str)               # provider_id, model_id

    MAX_FALLBACKS = 8

    def __init__(self, prompt: str | None = None, png: bytes | None = None,
                 messages: list[dict] | None = None, model: str | None = None,
                 parent=None):
        super().__init__(parent)
        # Initial provider + model; both are subject to failover.
        self.provider_id = config.PROVIDER
        self.model = model or config.MODEL
        if messages is not None:
            self.messages = messages
        else:
            assert prompt is not None and png is not None
            self.messages = build_initial_messages(prompt, png)

    @classmethod
    def from_messages(cls, messages: list[dict], model: str | None = None,
                      parent=None) -> "GeminiWorker":
        return cls(messages=messages, model=model, parent=parent)

    def _provider_for_backend(self, pid: str) -> tuple[str, str | None, str]:
        """Return (provider_for_backend, base_url, api_key) for the given
        provider id. Resolves custom: ids to their stored config.
        """
        if pid.startswith("custom:"):
            cp = config.custom_provider_for(pid)
            return "custom", (cp.get("base_url") if cp else ""), config.custom_provider_api_key(pid)
        return pid, None, config.provider_key(pid)

    def _next_candidate(self, pid: str, blocked_models: set[str]) -> str | None:
        """Pick the next model id to try for the given provider."""
        # Ensure cache is populated for this provider (best-effort).
        if get_cached_records(pid) is None:
            try:
                from ..ai import models as _models
                _models.fetch_models_sync(pid)
            except Exception as e:
                log.warning("cache populate failed for %s: %s", pid, e)
        rec = pick_free_vision(pid, blocked_models)
        if rec:
            log.info("picked free-vision model %s for %s", rec["id"], pid)
            return rec["id"]
        log.info("no free-vision for %s in cache; falling back to saved model", pid)
        # For custom providers without cached free-vision, use stored default model.
        if pid.startswith("custom:"):
            default = config.custom_provider_default_model(pid)
            if default and default not in blocked_models:
                return default
            return None
        # Preset provider: if no free-vision model is cached (e.g. the models
        # list failed to fetch), fall back to the explicitly chosen model for
        # the active provider, then to the configured default. This prevents a
        # false "no providers configured" failure when a valid API key exists.
        if pid == self.provider_id and self.model and self.model not in blocked_models:
            return self.model
        if pid == self.provider_id and config.MODEL and config.MODEL not in blocked_models:
            return config.MODEL
        return None

    def _candidates_in_order(self, blocked_providers: set[str],
                             blocked_models: set[str]) -> list[tuple[str, str]]:
        """Return ordered list of (provider_id, model_id) to try."""
        out: list[tuple[str, str]] = []
        order = config.FALLBACK_ORDER
        # Make sure the active provider is tried first even if absent from order.
        pids: list[str] = []
        if self.provider_id and self.provider_id not in order:
            pids.append(self.provider_id)
        for p in order:
            if p not in pids:
                pids.append(p)
        for pid in pids:
            if pid in blocked_providers:
                continue
            api_key = config.provider_key(pid)
            if pid.startswith("custom:"):
                api_key = config.custom_provider_api_key(pid)
                if not config.custom_provider_base_url(pid):
                    continue
            else:
                if not api_key:
                    log.info("skipping %s: no API key", pid)
                    continue
            model_id = self._next_candidate(pid, blocked_models)
            if not model_id:
                continue
            out.append((pid, model_id))
        log.info("candidates: %d providers available", len(out))
        return out

    def run(self) -> None:
        log.info("worker.run() entered: provider=%s model=%s", self.provider_id, self.model)
        messages = list(self.messages)
        has_image = _last_user_has_image(messages)

        blocked_providers: set[str] = set()
        blocked_models: set[str] = set()
        last_err: str = ""
        tried_pairs: list[tuple[str, str]] = []

        # Build the initial candidate list (ordered fallback).
        candidates = self._candidates_in_order(blocked_providers, blocked_models)
        if not candidates:
            self.failed.emit(
                "No providers with API keys are configured. Open Settings → Providers."
            )
            return

        # Random free model across ALL active providers (when 2+ active)
        # User wants: fetch free models from all 3 active (Groq/NVIDIA/OpenRouter) and pick random
        chosen: tuple[str, str] | None = None
        try:
            active = get_active_provider_ids()
            if len(active) >= 2:
                rnd = pick_random_free_vision_across_active(blocked_models, blocked_providers)
                if rnd:
                    rnd_pid, rnd_rec = rnd
                    rnd_pair = (rnd_pid, rnd_rec["id"])
                    if rnd_pair not in candidates:
                        candidates.insert(0, rnd_pair)
                    else:
                        candidates.remove(rnd_pair)
                        candidates.insert(0, rnd_pair)
                    log.info("random free pick across %d active: %s/%s", len(active), rnd_pid, rnd_rec["id"])
                    chosen = rnd_pair
                else:
                    raise ValueError("no random free")
            else:
                raise ValueError("single active")
        except Exception as e:
            log.info("random free pick not used (%s), using ordered fallback", e)
            chosen = None
        if chosen is None:
            # Original ordered logic: try explicitly chosen model first
            chosen = (self.provider_id, self.model)
            if chosen in candidates:
                candidates.remove(chosen)
                candidates.insert(0, chosen)
            else:
                api_key = config.provider_key(self.provider_id)
                if self.provider_id.startswith("custom:"):
                    api_key = config.custom_provider_api_key(self.provider_id)
                if api_key and (
                    not self.provider_id.startswith("custom:")
                    or config.custom_provider_base_url(self.provider_id)
                ):
                    candidates.insert(0, chosen)

        for attempt in range(self.MAX_FALLBACKS + 1):
            if self.isInterruptionRequested():
                return
            if not candidates:
                break
            current_provider, current_model = candidates.pop(0)
            blocked_models.add(current_model)
            blocked_providers.add(current_provider)
            tried_pairs.append((current_provider, current_model))

            # Notify UI of any provider/model change.
            if current_provider != self.provider_id:
                self.provider_switched.emit(current_provider, current_model)
                self.provider_id = current_provider
            if current_model != self.model:
                self.model_switched.emit(current_model)
                self.model = current_model

            try:
                self._run_with_provider_model(
                    messages, current_provider, current_model, has_image
                )
                return
            except RateLimitError as e:
                last_err = str(e)
                log.warning("provider=%s model=%s rate-limited: %s",
                            current_provider, current_model, e)
                self.tool_used.emit(
                    f"{current_provider}/{current_model} rate-limited, switching…"
                )
                # Mark the bad model as not-free in this provider's cache so we
                # don't immediately re-pick it.
                recs = get_cached_records(current_provider) or []
                for r in recs:
                    if r["id"] == current_model:
                        r["free"] = False
                        break
                # Refresh candidates (excludes current provider since blocked).
                more = self._candidates_in_order(blocked_providers, blocked_models)
                candidates = more + candidates
            except UpstreamError as e:
                last_err = str(e)
                log.warning("provider=%s model=%s upstream error: %s",
                            current_provider, current_model, e)
                # Mark quota/rate-limit and retired models as not-free so we don't retry them
                lower_msg = e.message.lower() if hasattr(e, "message") else str(e).lower()
                if (
                    e.status_code in (402, 404, 429)
                    or "not_found" in lower_msg
                    or "does not exist" in lower_msg
                    or "rate limit" in lower_msg
                    or "tokens per minute" in lower_msg
                    or "credits" in lower_msg
                    or "quota" in lower_msg
                ):
                    recs = get_cached_records(current_provider) or []
                    for r in recs:
                        if r["id"] == current_model:
                            r["free"] = False
                            break
                more = self._candidates_in_order(blocked_providers, blocked_models)
                candidates = more + candidates
            except Exception as e:
                log.exception("Backend call failed")
                self.failed.emit(f"{type(e).__name__}: {e}")
                return

        summary = ", ".join(f"{p}/{m}" for p, m in tried_pairs[:6])
        self.failed.emit(
            f"All providers exhausted (tried {len(tried_pairs)}). "
            f"Last error: {last_err[:200]}\nTried: {summary}"
        )

    def _run_with_provider_model(self, messages: list[dict], provider_id: str,
                                 model: str, has_image: bool) -> None:
        prov_for_backend, base_url, api_key = self._provider_for_backend(provider_id)
        backend = SnipAIBackend(
            backend_url=config.BACKEND_URL,
            provider=prov_for_backend,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

        # Pass 1: planner — analyze + emit a search query
        # (Best-effort: skip to final if planner fails due to rate limits)
        self.tool_used.emit(f"Analyzing with {provider_id}/{model}…"
                            if has_image else f"Thinking with {provider_id}/{model}…")
        analysis = ""
        query = None
        try:
            planner_messages = list(messages)
            planner_messages.append({"role": "user", "content": PLANNER_SUFFIX})
            planner_chunks = list(backend.stream_chat(planner_messages, max_tokens=1024))
            raw_analysis = "".join(planner_chunks).strip()
            analysis, query = _parse_search_query(raw_analysis)
        except RateLimitError:
            raise
        except UpstreamError:
            raise
        except Exception as e:
            log.warning("planner call failed, skipping search: %s", e)
            analysis = ""
            query = None

        if self.isInterruptionRequested():
            return

        # Step 2: deep web research via backend search endpoint
        web_context = ""
        if query:
            self.tool_used.emit(f"Searching: {query[:60]}")
            # FREE path: TinyFish via Monid locally ($0/1k, no quota) — primary
            # Falls back to backend /v1/search (Jina) if local miss or monid not installed
            try:
                from ..ai.tools import deep_research as local_deep_research
                web_context = local_deep_research(query)
                if not web_context.strip():
                    raise ValueError("empty local search result")
                log.info("local TinyFish deep_research succeeded (%d chars, free)", len(web_context))
            except Exception as e:
                log.warning("local TinyFish search failed/miss, falling back to backend: %s", e)
                try:
                    import httpx
                    resp = httpx.post(
                        f"{config.BACKEND_URL}/v1/search",
                        json={"query": query},
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        web_context = resp.json().get("context", "")
                except Exception as e2:
                    log.warning("backend search also failed, continuing without context: %s", e2)
            if self.isInterruptionRequested():
                return

        # Pass 2: final streaming answer
        final_messages = _strip_images(messages)
        if analysis:
            final_messages.append({"role": "assistant", "content": analysis})

        if web_context:
            final_messages.append({
                "role": "user",
                "content": (
                    "I searched the web and found this context:\n\n"
                    f"{web_context}\n\n"
                    "Now write the complete final answer. Combine what the selection "
                    "shows with the useful facts and links you found above. Include any "
                    "relevant URLs the user asked for. Do not mention that you searched — "
                    "just give a clean, helpful answer in Markdown. "
                    "Use proper Markdown tables with | and |---|---| for comparisons, bullet lists with - or *, "
                    "and bold (**text**) for key takeaways. Never include <think> tags, chain-of-thought, or internal reasoning."
                ),
            })
            self.tool_used.emit("Writing answer...")
        else:
            final_messages.append({
                "role": "user",
                "content": (
                    "Write the complete final answer based on the analysis above. "
                    "Use Markdown. Be concise and helpful. "
                    "Use proper Markdown tables (| + |---|---|) for comparisons, bullet lists, and bold for key points. "
                    "Never include <think> tags, chain-of-thought, or internal reasoning."
                ),
            })

        for chunk in backend.stream_chat(final_messages):
            if self.isInterruptionRequested():
                break
            self.chunk.emit(chunk)

        self.finished_ok.emit()
