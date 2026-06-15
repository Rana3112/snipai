"""Bluesminds (OpenAI-compatible) streaming worker. Runs in QThread; emits chunks via Qt signals.

Deep-research pipeline (deterministic, rate-limit safe):
  1. Planner call (non-streaming): analyze selection + decide a web search query.
  2. Python: run deep_research (search + concurrent scrape) — NO model calls.
  3. Final call (streaming): write answer merging analysis + web context.

Only 2 model calls per turn → avoids 429 from agentic tool-call loops.
"""
from __future__ import annotations
import base64
import logging
from PySide6.QtCore import QThread, Signal

from ..config import config
from .tools import deep_research

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You analyze screenshots. The user has selected a region of their screen "
    "(text, code, image, UI, document, anything) and is asking about it. "
    "Be accurate and concise. If the selection is text or code, treat it as the "
    "primary content. Use Markdown. Keep answers tight. "
    "For follow-up questions, refer back to the original selection and prior turns."
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
    """Remove image_url parts from all user messages. Keeps text intact."""
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
    """Split analysis from the trailing SEARCH_QUERY line.

    Returns (clean_analysis, query_or_None).
    """
    query: str | None = None
    lines = analysis.splitlines()
    keep: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.upper().startswith("SEARCH_QUERY:"):
            val = stripped.split(":", 1)[1].strip()
            if val and val.upper() != "NONE":
                query = val
            # drop this line from analysis text
            continue
        keep.append(ln)
    return "\n".join(keep).strip(), query


def build_initial_messages(prompt: str, png: bytes, system: str | None = None) -> list[dict]:
    """First turn: system + user(image + text)."""
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
    """Text-selection turn: system + user(prompt + selected text). No image."""
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f'{prompt}\n\nSelected text:\n"""\n{selected_text}\n"""',
        },
    ]


def build_stack_messages(prompt: str, items: list[dict], system: str | None = None) -> list[dict]:
    """Multi-snip turn: one user message holding several crops/texts together.

    items: list of {"png": bytes} and/or {"text": str}. Order preserved.
    """
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
    """Class name kept for back-compat; backend is Bluesminds (OpenAI-compatible)."""

    chunk = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)
    tool_used = Signal(str)   # UI status hint, e.g. "Searching: ..."

    def __init__(self, prompt: str | None = None, png: bytes | None = None,
                 messages: list[dict] | None = None, model: str | None = None,
                 parent=None):
        super().__init__(parent)
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

    def run(self) -> None:
        try:
            from openai import OpenAI

            # Resolve base_url for the current provider
            _provider_urls = {
                "bluesminds": "https://api.bluesminds.com/v1",
                "groq": "https://api.groq.com/openai/v1",
                "nvidia": "https://integrate.api.nvidia.com/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "openai": "https://api.openai.com/v1",
                "opencode_zen": "https://opencode.ai/zen/v1",
            }
            base_url = config.BASE_URL or _provider_urls.get(config.PROVIDER, "")

            client = OpenAI(
                api_key=config.API_KEY,
                base_url=base_url,
            )

            messages = list(self.messages)
            has_image = _last_user_has_image(messages)

            # ── Pass 1: planner — analyze + emit a search query ──
            self.tool_used.emit("Analyzing..." if has_image else "Thinking...")
            planner_messages = list(messages)
            planner_messages.append({"role": "user", "content": PLANNER_SUFFIX})

            plan = client.chat.completions.create(
                model=self.model,
                messages=planner_messages,
                temperature=0.4,
                max_tokens=1024,
                stream=False,
            )
            if self.isInterruptionRequested():
                return
            raw_analysis = (plan.choices[0].message.content or "").strip()
            analysis, query = _parse_search_query(raw_analysis)

            # ── Step 2: deep web research (pure Python, no model calls) ──
            web_context = ""
            if query:
                self.tool_used.emit(f"Searching: {query[:60]}")
                web_context = deep_research(query)
                if self.isInterruptionRequested():
                    return

            # ── Pass 2: final streaming answer ──
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
                        "just give a clean, helpful answer in Markdown."
                    ),
                })
                self.tool_used.emit("Writing answer...")
            else:
                final_messages.append({
                    "role": "user",
                    "content": (
                        "Write the complete final answer based on the analysis above. "
                        "Use Markdown. Be concise and helpful."
                    ),
                })

            stream = client.chat.completions.create(
                model=self.model,
                messages=final_messages,
                temperature=0.4,
                max_tokens=2048,
                stream=True,
            )
            for ev in stream:
                if self.isInterruptionRequested():
                    break
                if not ev.choices:
                    continue
                delta = ev.choices[0].delta
                txt = getattr(delta, "content", None)
                if txt:
                    self.chunk.emit(txt)

            self.finished_ok.emit()

        except Exception as e:
            log.exception("Bluesminds call failed")
            self.failed.emit(f"{type(e).__name__}: {e}")
