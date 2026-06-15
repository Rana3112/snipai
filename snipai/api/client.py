"""HTTP client for the hosted SnipAI backend.

Stateless: sends user's API key with every request. Never stores it server-side.
"""
from __future__ import annotations
import json
import logging
from typing import Generator

import httpx

log = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the upstream provider returns 429."""
    def __init__(self, model: str, message: str):
        super().__init__(message)
        self.model = model
        self.message = message


class UpstreamError(Exception):
    """Raised on any other upstream / HTTP error during streaming."""
    def __init__(self, model: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.model = model
        self.message = message
        self.status_code = status_code


class SnipAIBackend:
    """Client for the hosted SnipAI FastAPI backend."""

    def __init__(self, backend_url: str, provider: str, api_key: str,
                 model: str, base_url: str | None = None):
        self.backend_url = backend_url.rstrip("/")
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def stream_chat(self, messages: list[dict],
                    temperature: float = 0.4,
                    max_tokens: int = 2048) -> Generator[str, None, None]:
        """Stream SSE chunks from the backend.

        Raises:
            RateLimitError — if upstream returned 429 (per-model quota).
            UpstreamError  — on any other HTTP / protocol failure.
        """
        payload = {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.backend_url}/v1/chat/completions"
        try:
            with httpx.Client(timeout=120) as client:
                with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code == 429:
                        # Read the body and surface the upstream message.
                        body = resp.read().decode(errors="ignore")[:500]
                        raise RateLimitError(self.model, body)
                    if resp.status_code >= 400:
                        body = resp.read().decode(errors="ignore")[:500]
                        raise UpstreamError(self.model, body, resp.status_code)
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        # Backend error envelope.
                        if isinstance(data, dict) and "error" in data:
                            err_str = str(data["error"])
                            if "rate" in err_str.lower() or "429" in err_str:
                                raise RateLimitError(self.model, err_str)
                            raise UpstreamError(self.model, err_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
        except httpx.HTTPStatusError as e:
            raise UpstreamError(self.model, str(e), e.response.status_code) from e
        except httpx.RequestError as e:
            raise UpstreamError(self.model, str(e)) from e

    def fetch_models(self) -> list[dict]:
        """Fetch available models for the current provider."""
        payload = {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        url = f"{self.backend_url}/v1/models"
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("models", [])

    def health_check(self) -> bool:
        """Check if backend is reachable."""
        try:
            resp = httpx.get(f"{self.backend_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

