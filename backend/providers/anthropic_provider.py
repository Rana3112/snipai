"""Anthropic Claude provider."""
from __future__ import annotations
import logging
from typing import Generator

from anthropic import Anthropic

log = logging.getLogger(__name__)

# Anthropic models with vision support
VISION_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
]


def _convert_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert OpenAI-style messages to Anthropic format.

    Returns (system_prompt, messages_without_system).
    """
    system = ""
    converted = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"] if isinstance(msg["content"], str) else ""
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # Convert OpenAI image_url format to Anthropic format
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append({"type": "text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            # base64 data URI
                            import base64
                            header, b64data = url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64data,
                                },
                            })
                        else:
                            parts.append({
                                "type": "image",
                                "source": {"type": "url", "url": url},
                            })
                elif isinstance(part, str):
                    parts.append({"type": "text", "text": part})
            content = parts if len(parts) > 1 else (parts[0]["text"] if parts and parts[0].get("type") == "text" else parts)
        converted.append({"role": msg["role"], "content": content})
    return system, converted


def stream_chat(
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int = 2048,
    **kwargs,
) -> Generator[str, None, None]:
    """Stream chat completion chunks from Anthropic."""
    client = Anthropic(api_key=api_key)
    system, msgs = _convert_messages(messages)

    params = {
        "model": model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if system:
        params["system"] = system

    with client.messages.stream(**params) as stream:
        for text in stream.text_stream:
            yield text


def fetch_models(api_key: str) -> list[dict]:
    """Return known Anthropic models (no list endpoint)."""
    return [
        {"id": m, "name": m, "free": False, "vision": True,
         "modality": "text+image->text", "pricing": None}
        for m in VISION_MODELS
    ]
