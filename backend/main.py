"""SnipAI Backend — FastAPI server.

Stateless: never stores user API keys. User sends their key with each request.
Routes to the correct AI provider and streams the response.
"""
from __future__ import annotations
import logging
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from models import ChatRequest, ModelsRequest, SearchRequest, HealthResponse
from providers.router import stream_chat, fetch_models
from search.tools import deep_research

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("SnipAI backend starting")
    yield
    log.info("SnipAI backend shutting down")


app = FastAPI(
    title="SnipAI Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    """Stream chat completion from the selected provider.

    Request includes the user's API key — we never store it.
    """
    log.info("Chat request: provider=%s model=%s messages=%d stream=%s",
             req.provider, req.model, len(req.messages), req.stream)

    messages = [m.model_dump() for m in req.messages]

    def event_stream():
        try:
            for chunk in stream_chat(
                provider=req.provider,
                api_key=req.api_key,
                base_url=req.base_url,
                model=req.model,
                messages=messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                data = json.dumps({
                    "choices": [{"delta": {"content": chunk}}]
                })
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.exception("Chat completion failed")
            # Surface the failure as an error envelope (NOT as chat content) so
            # the client raises RateLimitError/UpstreamError and fails over to
            # the next provider/model instead of showing the raw exception.
            status = getattr(e, "status_code", None)
            yield f"data: {json.dumps({'error': str(e), 'status': status})}\n\n"
            yield "data: [DONE]\n\n"

    if req.stream:
        return StreamingResponse(event_stream(), media_type="text/event-stream")
    else:
        # Non-streaming: collect all chunks and return as one response
        full_response = ""
        for chunk in stream_chat(
            provider=req.provider,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ):
            full_response += chunk
        return {
            "choices": [{"message": {"role": "assistant", "content": full_response}}]
        }


@app.post("/v1/models")
async def list_models(req: ModelsRequest):
    """List available models for a provider."""
    log.info("Models request: provider=%s", req.provider)
    try:
        models = fetch_models(
            provider=req.provider,
            api_key=req.api_key,
            base_url=req.base_url,
        )
        return {"models": models}
    except Exception as e:
        log.exception("Models fetch failed")
        return {"models": [], "error": str(e)}


@app.post("/v1/search")
async def search(req: SearchRequest):
    """Deep web search — returns scraped context for the caller to inject into AI."""
    log.info("Search request: query=%s", req.query)
    context = deep_research(
        query=req.query,
        max_results=req.max_results,
        scrape_pages=req.scrape_pages,
    )
    return {"context": context}
