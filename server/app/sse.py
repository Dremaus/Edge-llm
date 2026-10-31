"""Przechwytywanie treści ze strumienia SSE (format OpenAI), żeby zapisać odpowiedź w historii."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable


class DeltaCollector:
    """Składa tekst z kolejnych fragmentów `data: {...}` — także przeciętych między paczkami."""

    def __init__(self) -> None:
        self._buffer = b""
        self._parts: list[str] = []

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]" or not data:
                continue
            try:
                event = json.loads(data)
                delta = event["choices"][0].get("delta", {}).get("content")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                continue
            if isinstance(delta, str):
                self._parts.append(delta)

    @property
    def text(self) -> str:
        return "".join(self._parts)


async def tee_stream(
    source: AsyncIterator[bytes], on_complete: Callable[[str], Awaitable[None] | None]
) -> AsyncIterator[bytes]:
    """Przekazuje strumień dalej bez zmian i po zakończeniu wywołuje on_complete(pełny_tekst)."""
    collector = DeltaCollector()
    async for chunk in source:
        collector.feed(chunk)
        yield chunk
    result = on_complete(collector.text)
    if result is not None:
        await result
