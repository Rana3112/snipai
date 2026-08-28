"""Pydantic request/response schemas for the SnipAI backend API."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None


class ChatRequest(BaseModel):
    provider: Literal["openai", "anthropic", "google", "bluesminds", "groq", "nvidia", "openrouter", "opencode_zen", "custom"]
    api_key: str
    base_url: str | None = None
    model: str
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float = 0.4
    max_tokens: int = 2048


class ModelInfo(BaseModel):
    id: str
    name: str
    free: bool = False
    vision: bool = False
    modality: str | None = None
    pricing: dict | None = None


class ModelsRequest(BaseModel):
    provider: Literal["openai", "anthropic", "google", "bluesminds", "groq", "nvidia", "openrouter", "opencode_zen", "custom"]
    api_key: str
    base_url: str | None = None


class SearchRequest(BaseModel):
    query: str
    max_results: int = 6
    scrape_pages: int = 3


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
