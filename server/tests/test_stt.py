from __future__ import annotations

import asyncio

import httpx
import pytest

from app.stt import SttError, WhisperClient


def client_with(handler):
    c = WhisperClient("http://127.0.0.1:8081")
    real = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)  # type: ignore[assignment]
    return c, lambda: setattr(httpx, "AsyncClient", real)


def test_posts_multipart_and_parses_text():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["body"] = str(req.url), req.content
        return httpx.Response(200, json={"text": " Dzień dobry "})

    c, restore = client_with(handler)
    try:
        assert asyncio.run(c.transcribe(b"AUDIO", "a.wav", "pl")) == "Dzień dobry"
    finally:
        restore()
    assert seen["url"] == "http://127.0.0.1:8081/inference"
    assert b'name="language"' in seen["body"] and b"pl" in seen["body"] and b"AUDIO" in seen["body"]


@pytest.mark.parametrize("handler", [lambda r: httpx.Response(500), lambda r: httpx.Response(200, content=b"nie json")])
def test_errors_become_stt_error(handler):
    c, restore = client_with(handler)
    try:
        with pytest.raises(SttError):
            asyncio.run(c.transcribe(b"x", "a.wav", "pl"))
    finally:
        restore()
