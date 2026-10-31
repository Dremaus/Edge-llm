from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeLLM:
    def __init__(self) -> None:
        self.seen: list[tuple[str, list[dict[str, Any]]]] = []

    async def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> str:
        self.seen.append((model, messages))
        if "Classify the user's request" in str(messages[-1].get("content")):
            return "chat"
        return "Cześć!"

    async def stream(self, model: str, messages: list[dict[str, Any]], **params: Any):
        self.seen.append((model, messages))
        yield b'data: {"choices":[{"delta":{"content":"Cze"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    async def list_models(self) -> list[str]:
        return ["qwen3.5:4b"]


def make_client(token: str = "secret", language: str = "pl") -> tuple[TestClient, FakeLLM]:
    llm = FakeLLM()
    app = create_app(Settings(api_token=token, language=language, main_model="main"), llm)
    return TestClient(app), llm


AUTH = {"Authorization": "Bearer secret"}


def test_health_is_public():
    client, _ = make_client()
    assert client.get("/health").json()["status"] == "ok"


def test_requires_token():
    client, _ = make_client()
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 401


def test_missing_server_token_is_503():
    client, _ = make_client(token="")
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer "},
        json={"messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 503


def test_auto_routing_and_polish_system_prompt():
    client, llm = make_client()
    r = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "auto", "messages": [{"role": "user", "content": "Opowiedz o Krakowie"}]},
    )
    assert r.status_code == 200
    assert r.headers["X-Edge-Route"] == "chat"
    assert r.json()["choices"][0]["message"]["content"] == "Cześć!"
    model, messages = llm.seen[-1]
    assert model == "main"
    assert messages[0]["role"] == "system"
    assert "po polsku" in messages[0]["content"]


def test_english_system_prompt():
    client, llm = make_client(language="en")
    client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "main", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert "in English" in llm.seen[-1][1][0]["content"]


def test_streaming_passthrough():
    client, _ = make_client()
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "main", "stream": True, "messages": [{"role": "user", "content": "Hej"}]},
    ) as r:
        body = b"".join(r.iter_bytes())
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"[DONE]" in body


def test_models_list_includes_auto():
    client, _ = make_client()
    ids = [m["id"] for m in client.get("/v1/models", headers=AUTH).json()["data"]]
    assert ids[0] == "auto" and "qwen3.5:4b" in ids
