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
from .sse import tee_stream
from .storage import SettingsError, Storage

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
    store: Storage | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or OllamaClient(settings.ollama_url, settings.request_timeout_s)
    tokens = tokens if tokens is not None else TokenStore(settings.tokens_file)
    pairing = pairing if pairing is not None else PairingManager(tokens, settings.pairing_file)
    store = store if store is not None else Storage(settings.db_file, settings.language)
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

        user_settings = store.get_settings()
        if not any(m["role"] == "system" for m in messages):
            prompt = SYSTEM_PROMPTS.get(user_settings.language, SYSTEM_PROMPTS["en"])
            messages = [{"role": "system", "content": prompt}, *messages]

        # Historia: istniejąca rozmowa tego telefonu albo nowa, gdy save=true.
        conv_id = body.get("conversation_id")
        if conv_id is not None:
            if not isinstance(conv_id, str) or not store.owns(device.id, conv_id):
                raise HTTPException(404, "Nie znaleziono rozmowy")
        elif body.get("save") is True:
            conv_id = store.create_conversation(device.id, _title(messages))

        model = body.get("model") or AUTO_MODEL
        route_info: dict[str, Any] = {}
        if model == AUTO_MODEL:
            decision = await router.route(messages, prefer_alt=user_settings.chat_model == "bielik")
            model = decision["model"]
            route_info = {"route": decision["route"], "reason": decision.get("reason")}
        elif model not in settings.allowed_models:
            raise HTTPException(400, "Niedozwolony model")

        log.info("chat device=%s model=%s route=%s", device.id, model, route_info.get("route"))
        headers = {**SECURITY_HEADERS, "X-Edge-Model": model}
        if route_info:
            headers["X-Edge-Route"] = str(route_info["route"])
        if conv_id:
            headers["X-Edge-Conversation"] = conv_id
            store.add_message(device.id, conv_id, "user", messages[-1]["content"])

        def save_reply(text: str) -> None:
            if conv_id and text:
                store.add_message(device.id, conv_id, "assistant", text, model=model)

        if body.get("stream") is True:
            return StreamingResponse(
                tee_stream(llm.stream(model, messages, **params), save_reply),
                media_type="text/event-stream",
                headers=headers,
            )

        content = await llm.complete(model, messages, **params)
        save_reply(content)
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
                "edge": {**route_info, "conversation_id": conv_id},
            },
            headers=headers,
        )

    # --- ustawienia (kreator pierwszego uruchomienia) -------------------
    @app.get("/v1/settings")
    async def get_device_settings(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        return store.get_settings().to_dict()

    @app.patch("/v1/settings")
    async def patch_device_settings(
        request: Request, device: DeviceToken = Depends(require_device)
    ) -> dict[str, Any]:
        try:
            changes = json.loads(await request.body())
            if not isinstance(changes, dict):
                raise SettingsError("Nieprawidłowe zapytanie")
            updated = store.update_settings(changes)
        except (SettingsError, ValueError) as exc:
            msg = str(exc) if isinstance(exc, SettingsError) else "Nieprawidłowy JSON"
            raise HTTPException(400, msg) from None
        log.info("settings changed by device=%s keys=%s", device.id, sorted(changes))
        return updated.to_dict()

    # --- historia rozmów ------------------------------------------------
    @app.get("/v1/conversations")
    async def list_conversations(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        return {"data": store.list_conversations(device.id)}

    @app.get("/v1/conversations/{conv_id}")
    async def get_conversation(conv_id: str, device: DeviceToken = Depends(require_device)):
        conv = store.get_conversation(device.id, conv_id)
        if conv is None:
            raise HTTPException(404, "Nie znaleziono rozmowy")
        return conv

    @app.delete("/v1/conversations/{conv_id}")
    async def delete_conversation(conv_id: str, device: DeviceToken = Depends(require_device)):
        if not store.delete_conversation(device.id, conv_id):
            raise HTTPException(404, "Nie znaleziono rozmowy")
        return {"deleted": conv_id}

    @app.delete("/v1/conversations")
    async def delete_all_conversations(device: DeviceToken = Depends(require_device)):
        return {"deleted": store.delete_all(device.id)}

    return app


def _title(messages: list[dict[str, Any]]) -> str:
    content = messages[-1].get("content")
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return str(content or "")[:80]

