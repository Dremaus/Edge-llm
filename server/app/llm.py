"""Klient Ollamy przez API zgodne z OpenAI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx


class LLMClient(Protocol):
    async def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> str: ...

    def stream(
        self, model: str, messages: list[dict[str, Any]], **params: Any
    ) -> AsyncIterator[bytes]: ...

    async def list_models(self) -> list[str]: ...


class OllamaClient:
    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_s, connect=10.0)

    async def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> str:
        payload = {"model": model, "messages": messages, "stream": False, **params}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    async def stream(
        self, model: str, messages: list[dict[str, Any]], **params: Any
    ) -> AsyncIterator[bytes]:
        """Przekazuje surowe zdarzenia SSE z Ollamy bez zmian."""
        payload = {"model": model, "messages": messages, "stream": True, **params}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/models")
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]
