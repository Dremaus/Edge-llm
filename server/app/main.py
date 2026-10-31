"""Serwer API asystenta: API zgodne z OpenAI, router modeli, strumieniowanie SSE."""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import SYSTEM_PROMPTS, Settings, get_settings
from .llm import LLMClient, OllamaClient
from .router import ModelRouter

logging.basicConfig(level=logging.INFO)

AUTO_MODEL = "auto"


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or OllamaClient(settings.ollama_url, settings.request_timeout_s)
    router = ModelRouter(settings, llm)
    app = FastAPI(title="edge-llm", version="0.1.0")

    def require_token(authorization: str = Header(default="")) -> None:
        if not settings.api_token:
            raise HTTPException(503, "Serwer nie ma ustawionego EDGE_API_TOKEN")
        expected = f"Bearer {settings.api_token}"
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Nieprawidłowy token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "language": settings.language}

    @app.get("/v1/models", dependencies=[Depends(require_token)])
    async def models() -> dict[str, Any]:
        ids = [AUTO_MODEL]
        try:
            ids += await llm.list_models()
        except Exception:
            pass
        return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}

    @app.post("/v1/chat/completions", dependencies=[Depends(require_token)])
    async def chat_completions(request: Request):
        body: dict[str, Any] = await request.json()
        messages: list[dict[str, Any]] = body.get("messages") or []
        if not messages:
            raise HTTPException(400, "Brak wiadomości")

        if not any(m.get("role") == "system" for m in messages):
            prompt = SYSTEM_PROMPTS.get(settings.language, SYSTEM_PROMPTS["en"])
            messages = [{"role": "system", "content": prompt}, *messages]

        model = body.get("model") or AUTO_MODEL
        route_info: dict[str, Any] = {}
        if model == AUTO_MODEL:
            decision = await router.route(messages)
            model = decision["model"]
            route_info = {"route": decision["route"], "reason": decision.get("reason")}

        params = {
            k: body[k] for k in ("temperature", "top_p", "max_tokens", "stop") if k in body
        }
        headers = {"X-Edge-Model": model}
        if route_info:
            headers["X-Edge-Route"] = str(route_info["route"])

        if body.get("stream"):
            return StreamingResponse(
                llm.stream(model, messages, **params),
                media_type="text/event-stream",
                headers=headers,
            )

        content = await llm.complete(model, messages, **params)
        return JSONResponse(
            {
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "edge": route_info,
            },
            headers=headers,
        )

    return app


app = create_app()
