"""Serwer API asystenta: API zgodne z OpenAI, router modeli, strumieniowanie SSE.

Warstwy ochrony (szczegóły: docs/security.md):
- serwer nasłuchuje tylko na 127.0.0.1; z zewnątrz dostępny wyłącznie przez
  szyfrowany tunel Tailscale (HTTPS, uwierzytelnione urządzenia),
- tokeny per urządzenie (skróty SHA-256, unieważnianie bez restartu),
- blokada po serii nieudanych prób i limit zapytań na urządzenie,
- limit rozmiaru zapytania, ścisła walidacja treści, lista dozwolonych modeli,
- obrazy tylko inline (bez pobierania URL-i), brak /docs w produkcji,
- logi bez treści rozmów i bez tokenów.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import SYSTEM_PROMPTS, Settings, get_settings
from .llm import LLMClient, OllamaClient
from .router import ModelRouter
from .security.pairing import PairingError, PairingManager
from .security.ratelimit import FailureLockout, TokenBucket
from .security.tokens import DeviceToken, TokenStore
from .security.validation import ValidationError, clean_messages, clean_params

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("edge.api")

AUTO_MODEL = "auto"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000",
}


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    tokens: TokenStore | None = None,
    pairing: PairingManager | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or OllamaClient(settings.ollama_url, settings.request_timeout_s)
    tokens = tokens if tokens is not None else TokenStore(settings.tokens_file)
    pairing = pairing if pairing is not None else PairingManager(tokens, settings.pairing_file)
    router = ModelRouter(settings, llm)
    limiter = TokenBucket(settings.rate_per_min, settings.rate_burst)
    lockout = FailureLockout()

    app = FastAPI(
        title="edge-llm",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Odrzucamy zbyt duże zapytania, zanim cokolwiek zostanie wczytane.
        length = request.headers.get("content-length")
        if length is not None:
            try:
                too_big = int(length) > settings.max_body_bytes
            except ValueError:
                too_big = True
            if too_big:
                return JSONResponse({"error": "Zapytanie zbyt duże"}, 413, headers=SECURITY_HEADERS)
        elif request.method in ("POST", "PUT", "PATCH"):
            return JSONResponse({"error": "Wymagany nagłówek Content-Length"}, 411, headers=SECURITY_HEADERS)
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def require_device(request: Request, authorization: str = Header(default="")) -> DeviceToken:
        key = client_key(request)
        if lockout.is_blocked(key):
            raise HTTPException(429, "Zbyt wiele nieudanych prób. Spróbuj później.")
        scheme, _, presented = authorization.partition(" ")
        device = tokens.verify(presented) if scheme.lower() == "bearer" else None
        if device is None:
            lockout.record_failure(key)
            log.warning("auth failed from=%s", key)
            raise HTTPException(401, "Brak dostępu")
        lockout.record_success(key)
        if not limiter.allow(device.id):
            raise HTTPException(429, "Zbyt wiele zapytań. Zwolnij.")
        return device

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Bez szczegółów wewnętrznych w odpowiedzi.
        log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
        return JSONResponse({"error": "Błąd serwera"}, 500, headers=SECURITY_HEADERS)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.post("/v1/pair")
    async def pair(request: Request) -> dict[str, Any]:
        """Wymiana jednorazowego kodu z QR na token telefonu (bez uwierzytelnienia)."""
        key = client_key(request)
        if lockout.is_blocked(key):
            raise HTTPException(429, "Zbyt wiele nieudanych prób. Spróbuj później.")
        raw = await request.body()
        if len(raw) > 1024:
            raise HTTPException(413, "Zapytanie zbyt duże")
        try:
            body = json.loads(raw)
            code = str(body["code"])
            name = str(body.get("device_name", "Telefon"))[:64]
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "Nieprawidłowe zapytanie") from None
        try:
            device_id, token = pairing.redeem(code, name)
        except PairingError:
            lockout.record_failure(key)
            log.warning("pairing failed from=%s", key)
            raise HTTPException(401, "Nieprawidłowy lub wygasły kod") from None
        lockout.record_success(key)
        log.info("paired device=%s", device_id)
        return {"device_id": device_id, "token": token}

    @app.get("/v1/models")
    async def models(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        ids = [AUTO_MODEL, *sorted(settings.allowed_models)]
        return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, device: DeviceToken = Depends(require_device)):
        try:
            body = json.loads(await request.body())
            if not isinstance(body, dict):
                raise ValidationError("Nieprawidłowe zapytanie")
            messages = clean_messages(body.get("messages"))
            params = clean_params(body)
        except (ValidationError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValidationError) else "Nieprawidłowy JSON"
            raise HTTPException(400, message) from None

        if not any(m["role"] == "system" for m in messages):
            prompt = SYSTEM_PROMPTS.get(settings.language, SYSTEM_PROMPTS["en"])
            messages = [{"role": "system", "content": prompt}, *messages]

        model = body.get("model") or AUTO_MODEL
        route_info: dict[str, Any] = {}
        if model == AUTO_MODEL:
            decision = await router.route(messages)
            model = decision["model"]
            route_info = {"route": decision["route"], "reason": decision.get("reason")}
        elif model not in settings.allowed_models:
            raise HTTPException(400, "Niedozwolony model")

        log.info("chat device=%s model=%s route=%s", device.id, model, route_info.get("route"))
        headers = {**SECURITY_HEADERS, "X-Edge-Model": model}
        if route_info:
            headers["X-Edge-Route"] = str(route_info["route"])

        if body.get("stream") is True:
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
