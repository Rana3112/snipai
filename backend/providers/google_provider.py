"""Google Gemini provider."""
from __future__ import annotations
import logging
import base64
from typing import Generator

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


def _convert_messages(messages: list[dict]) -> tuple[str, list]:
    """Convert OpenAI-style messages to Gemini format.

    Returns (system_instruction, contents).
    """
    system = ""
    contents = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "system":
            system = content if isinstance(content, str) else ""
            continue
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(types.Part.from_text(text=part.get("text", "")))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            header, b64data = url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            parts.append(types.Part.from_bytes(
                                data=base64.b64decode(b64data),
                                mime_type=media_type,
                            ))
            content = parts if parts else [types.Part.from_text(text="")]
        elif isinstance(content, str):
            content = [types.Part.from_text(text=content)]
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(types.Content(role=gemini_role, parts=content))
    return system, contents


def stream_chat(
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int = 2048,
    **kwargs,
) -> Generator[str, None, None]:
    """Stream chat completion chunks from Google Gemini."""
    client = genai.Client(api_key=api_key)
    system, contents = _convert_messages(messages)

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    if system:
        config.system_instruction = system

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        if chunk.text:
            yield chunk.text


def fetch_models(api_key: str) -> list[dict]:
    """Return known Gemini models (no list endpoint for generative AI)."""
    vision_ids = {"gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"}
    return [
        {
            "id": m,
            "name": m,
            "free": False,
            "vision": m in vision_ids,
            "modality": "text+image->text" if m in vision_ids else "text->text",
            "pricing": None,
        }
        for m in GEMINI_MODELS
    ]
