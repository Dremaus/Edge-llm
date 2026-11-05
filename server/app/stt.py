"""Rozpoznawanie mowy: klient lokalnej usługi whisper.cpp (whisper-server na localhost)."""

from __future__ import annotations

from typing import Protocol

import httpx

MAX_AUDIO_BYTES = 25 * 1024 * 1024


class SttError(RuntimeError):
    pass


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str: ...


class WhisperClient:
    def __init__(self, base_url: str, timeout_s: float = 120) -> None:
        self._url = base_url.rstrip("/") + "/inference"
        self._timeout = timeout_s

    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        data = {"response_format": "json", "temperature": "0.0", "language": language}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.post(self._url, files={"file": (filename, audio)}, data=data)
        except httpx.HTTPError as exc:
            raise SttError("Usługa rozpoznawania mowy jest niedostępna") from exc
        if res.status_code != 200:
            raise SttError("Nie udało się rozpoznać mowy")
        try:
            return str(res.json().get("text", "")).strip()
        except ValueError as exc:
            raise SttError("Nieprawidłowa odpowiedź usługi mowy") from exc
