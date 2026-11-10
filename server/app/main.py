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
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .agent import sandbox
from .agent.builtin import SPECS, build_registry
from .agent.policy import PolicyConfig, ToolPolicy
from .agent.runner import AgentRunner
from .files import FileError, FileStore
from .config import SYSTEM_PROMPTS, Settings, get_settings
from .llm import LLMClient, OllamaClient
from .router import ModelRouter
from .stt import MAX_AUDIO_BYTES, SttError, Transcriber, WhisperClient
from .security.pairing import PairingError, PairingManager
from .security.ratelimit import FailureLockout, TokenBucket
from .security.tokens import DeviceToken, TokenStore
from .security.validation import ValidationError, clean_messages, clean_params
from .sse import tee_stream
from .status import collect
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
    stt: Transcriber | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or OllamaClient(settings.ollama_url, settings.request_timeout_s)
    tokens = tokens if tokens is not None else TokenStore(settings.tokens_file)
    pairing = pairing if pairing is not None else PairingManager(tokens, settings.pairing_file)
    store = store if store is not None else Storage(settings.db_file, settings.language)
    router = ModelRouter(settings, llm)
    file_store = FileStore(settings.files_dir)
    stt = stt or (WhisperClient(settings.whisper_url) if settings.stt_enabled else None)
    # Agent: narzędzia lokalne; sieć wyłączona. Kod uruchamia się tylko przy EDGE_EXECUTE_ENABLED=1
    # i zainstalowanej piaskownicy (podman + gVisor); bez niej narzędzie w ogóle nie jest rejestrowane.
    run_code = settings.execute_enabled and sandbox.available()
    agent = AgentRunner(
        llm,
        ToolPolicy(SPECS, PolicyConfig(execute_enabled=run_code)),
        build_registry(store, file_store, Path(settings.sandbox_dir) if run_code else None),
        audit=store.add_audit,
    )  # type: ignore[arg-type]
    limiter = TokenBucket(settings.rate_per_min, settings.rate_burst)
    # Za `tailscale serve` adres klienta pochodzi z X-Forwarded-For; bez niego wszyscy mają 127.0.0.1.
    # Dlatego dwie osobne blokady: ostra dla parowania (kod 50-bitowy) i łagodniejsza dla tokenów
    # (256 bitów — odgadnięcie niewykonalne), żeby jeden źle skonfigurowany telefon nie odciął innych.
    lockout = FailureLockout(max_failures=20, window_s=300, lockout_s=900)
    pair_lockout = FailureLockout(max_failures=5, window_s=600, lockout_s=1800)

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
        if pair_lockout.is_blocked(key):
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
            pair_lockout.record_failure(key)
            log.warning("pairing failed from=%s", key)
            raise HTTPException(401, "Nieprawidłowy lub wygasły kod") from None
        pair_lockout.record_success(key)
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

        conv_id = body.get("conversation_id")
        if conv_id is not None and (not isinstance(conv_id, str) or not store.owns(device.id, conv_id)):
            raise HTTPException(404, "Nie znaleziono rozmowy")

        model = body.get("model") or AUTO_MODEL
        route_info: dict[str, Any] = {}
        if model == AUTO_MODEL:
            decision = await router.route(messages, prefer_alt=user_settings.chat_model == "bielik")
            model = decision["model"]
            route_info = {"route": decision["route"], "reason": decision.get("reason")}
        elif model not in settings.allowed_models:
            raise HTTPException(400, "Niedozwolony model")

        # Nową rozmowę zakładamy dopiero po pełnej walidacji (bez pustych wpisów po błędach).
        if conv_id is None and body.get("save") is True:
            conv_id = store.create_conversation(device.id, _title(messages))

        log.info("chat device=%s model=%s route=%s", device.id, model, route_info.get("route"))
        headers = {**SECURITY_HEADERS, "X-Edge-Model": model}
        if route_info:
            headers["X-Edge-Route"] = str(route_info["route"])
        if conv_id:
            headers["X-Edge-Conversation"] = conv_id
            last = messages[-1]
            store.add_message(device.id, conv_id, last["role"], last["content"])

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

    # --- agent z narzędziami --------------------------------------------
    @app.post("/v1/agent")
    async def agent_run(request: Request, device: DeviceToken = Depends(require_device)):
        """Zadanie z narzędziami. Akcje zmieniające dane wracają jako prośba o zgodę."""
        try:
            body = json.loads(await request.body())
            messages = clean_messages(body.get("messages") if isinstance(body, dict) else None)
        except (ValidationError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValidationError) else "Nieprawidłowy JSON"
            raise HTTPException(400, message) from None
        prompt = SYSTEM_PROMPTS.get(store.get_settings().language, SYSTEM_PROMPTS["en"])
        messages = [m for m in messages if m["role"] != "system"]  # zasad nie nadpisuje klient
        result = await agent.run(device.id, settings.main_model, [{"role": "system", "content": prompt}, *messages])
        log.info("agent device=%s steps=%d", device.id, len(result.steps))
        return JSONResponse(result.to_dict(), headers=SECURITY_HEADERS)

    @app.post("/v1/agent/actions/{action_id}")
    async def agent_confirm(action_id: str, request: Request, device: DeviceToken = Depends(require_device)):
        try:
            body = json.loads(await request.body())
            approve = body["approve"]
            if not isinstance(approve, bool):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "Wymagane pole approve: true/false") from None
        try:
            result = await agent.confirm(device.id, action_id, approve)
        except KeyError:
            raise HTTPException(404, "Akcja nie istnieje lub wygasła") from None
        log.info("agent action %s device=%s", "approved" if approve else "rejected", device.id)
        return JSONResponse(result.to_dict(), headers=SECURITY_HEADERS)

    # --- sparowane telefony --------------------------------------------
    @app.get("/v1/devices")
    async def list_devices(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        """Lista sparowanych telefonów (bez skrótów tokenów)."""
        return {
            "data": [
                {
                    "id": d.id,
                    "name": d.name,
                    "created": d.created,
                    "revoked": d.revoked,
                    "current": d.id == device.id,
                }
                for d in tokens.list()
            ]
        }

    @app.delete("/v1/devices/me")
    async def unpair_self(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        """Wylogowanie: telefon unieważnia własny token. Inne telefony unieważnia się
        tylko w konsoli urządzenia — skradziony telefon nie może odciąć właściciela."""
        tokens.revoke(device.id)
        log.info("device unpaired itself device=%s", device.id)
        return {"revoked": device.id}

    # --- stan urządzenia -----------------------------------------------
    @app.get("/v1/status")
    async def device_status(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        loaded: list[str] = []
        getter = getattr(llm, "loaded_models", None)
        if getter is not None:
            try:
                loaded = await getter()
            except Exception:  # Ollama niedostępna — status nadal ma sens
                log.warning("ollama /api/ps unavailable")
        state_dir = str(Path(settings.db_file).parent)
        return {"status": "ok", **collect(state_dir, loaded)}

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

    # --- dziennik audytu narzędzi: tylko odczyt, tylko własne wpisy telefonu ---------
    @app.get("/v1/audit")
    async def list_audit(limit: int = 100, device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        return {"data": store.list_audit(device.id, limit)}

    # --- pamięć agenta (notatki): podgląd i usuwanie przez użytkownika -----
    @app.get("/v1/memory")
    async def list_memory(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        return {"data": store.list_notes(device.id, 100)}

    @app.delete("/v1/memory/{note_id}")
    async def delete_memory(note_id: int, device: DeviceToken = Depends(require_device)):
        if not store.delete_note(device.id, note_id):
            raise HTTPException(404, "Nie znaleziono wpisu")
        return {"deleted": note_id}

    # --- mowa na tekst -------------------------------------------------
    @app.post("/v1/audio/transcriptions")
    async def transcribe(request: Request, device: DeviceToken = Depends(require_device)):
        """Surowe bajty nagrania (wav/m4a/ogg/mp3) -> {"text": ...}. Tekst trafia do czatu po stronie aplikacji."""
        if stt is None:
            raise HTTPException(503, "Rozpoznawanie mowy jest wyłączone na tym urządzeniu")
        audio = await request.body()
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(400, "Nagranie jest puste albo za duże")
        language = store.get_settings().language
        try:
            text = await stt.transcribe(audio, "audio", language)
        except SttError as exc:
            raise HTTPException(502, str(exc)) from None
        log.info("stt device=%s bytes=%d chars=%d", device.id, len(audio), len(text))
        return JSONResponse({"text": text}, headers=SECURITY_HEADERS)

    # --- pliki użytkownika (dla narzędzi agenta) ---------------------------
    @app.get("/v1/files")
    async def list_files(device: DeviceToken = Depends(require_device)) -> dict[str, Any]:
        return {"data": file_store.list(device.id)}

    @app.post("/v1/files")
    async def upload_file(name: str, request: Request, device: DeviceToken = Depends(require_device)):
        try:
            saved = file_store.save(device.id, name, await request.body())
        except FileError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"name": saved}

    @app.delete("/v1/files/{name}")
    async def delete_file(name: str, device: DeviceToken = Depends(require_device)):
        if not file_store.delete(device.id, name):
            raise HTTPException(404, "Nie znaleziono pliku")
        return {"deleted": name}

    return app


def _title(messages: list[dict[str, Any]]) -> str:
    content = messages[-1].get("content")
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return str(content or "")[:80]

