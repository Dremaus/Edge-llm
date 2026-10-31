from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.tokens import TokenStore


class FakeLLM:
    def __init__(self) -> None:
        self.seen: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []

    async def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> str:
        self.seen.append((model, messages, params))
        if "Classify the user's request" in str(messages[-1].get("content")):
            return "chat"
        return "Cześć!"

    async def stream(self, model: str, messages: list[dict[str, Any]], **params: Any):
        self.seen.append((model, messages, params))
        yield b'data: {"choices":[{"delta":{"content":"Cze"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    async def list_models(self) -> list[str]:
        return []


def make_client(language: str = "pl", **overrides: Any):
    llm = FakeLLM()
    store = TokenStore()
    _, token = store.create("test")
    settings = Settings(language=language, main_model="main", router_model="small", **overrides)
    app = create_app(settings, llm, store)
    return TestClient(app), llm, {"Authorization": f"Bearer {token}"}, store


def chat(client, headers, **body):
    body.setdefault("messages", [{"role": "user", "content": "Opowiedz o Krakowie"}])
    return client.post("/v1/chat/completions", headers=headers, json=body)


def test_health_is_public_and_has_security_headers():
    client, *_ = make_client()
    r = client.get("/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"


def test_docs_disabled_in_production():
    client, *_ = make_client()
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_requires_valid_token():
    client, *_ = make_client()
    assert chat(client, {}).status_code == 401
    assert chat(client, {"Authorization": "Bearer edge_wrong"}).status_code == 401
    assert chat(client, {"Authorization": "Basic abc"}).status_code == 401


def test_lockout_after_repeated_failures():
    client, _, good, _ = make_client()
    for _ in range(5):
        chat(client, {"Authorization": "Bearer edge_wrong"})
    # Nawet poprawny token jest blokowany z tego adresu do końca blokady.
    assert chat(client, good).status_code == 429


def test_revoked_token_rejected():
    client, _, headers, store = make_client()
    device = store.list()[0]
    store.revoke(device.id)
    assert chat(client, headers).status_code == 401


def test_rate_limit_per_device():
    client, _, headers, _ = make_client(rate_per_min=1, rate_burst=2)
    codes = [chat(client, headers).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_body_size_limit():
    client, _, headers, _ = make_client(max_body_bytes=1000)
    r = chat(client, headers, messages=[{"role": "user", "content": "x" * 2000}])
    assert r.status_code == 413


def test_disallowed_model_rejected():
    client, _, headers, _ = make_client()
    assert chat(client, headers, model="llama-evil:70b").status_code == 400


def test_invalid_payloads_rejected():
    client, _, headers, _ = make_client()
    assert chat(client, headers, messages=[{"role": "tool", "content": "x"}]).status_code == 400
    r = client.post(
        "/v1/chat/completions",
        headers={**headers, "Content-Type": "application/json"},
        content=b"{not json",
    )
    assert r.status_code == 400


def test_remote_image_url_rejected():
    client, _, headers, _ = make_client()
    msg = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "http://10.0.0.1/x.png"}}]}]
    assert chat(client, headers, messages=msg).status_code == 400


def test_auto_routing_polish_prompt_and_param_filtering():
    client, llm, headers, _ = make_client()
    r = chat(client, headers, model="auto", temperature=5, options={"num_gpu": 1})
    assert r.status_code == 200
    assert r.headers["X-Edge-Route"] == "chat"
    model, messages, params = llm.seen[-1]
    assert model == "main"
    assert "po polsku" in messages[0]["content"]
    assert params == {"temperature": 2.0}


def test_english_system_prompt():
    client, llm, headers, _ = make_client(language="en")
    chat(client, headers, model="main")
    assert "in English" in llm.seen[-1][1][0]["content"]


def test_streaming_passthrough():
    client, _, headers, _ = make_client()
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=headers,
        json={"model": "main", "stream": True, "messages": [{"role": "user", "content": "Hej"}]},
    ) as r:
        body = b"".join(r.iter_bytes())
    assert r.headers["content-type"].startswith("text/event-stream")
    assert b"[DONE]" in body


def test_pairing_flow_and_lockout():
    from app.security.pairing import PairingManager

    llm = FakeLLM()
    store = TokenStore()
    pairing = PairingManager(store)
    client = TestClient(create_app(Settings(main_model="main"), llm, store, pairing))
    code, _ = pairing.new_code()
    r = client.post("/v1/pair", json={"code": code, "device_name": "Pixel"})
    assert r.status_code == 200
    token = r.json()["token"]
    ok = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    # Ten sam kod drugi raz nie działa, a seria błędów blokuje adres.
    assert client.post("/v1/pair", json={"code": code}).status_code == 401
    for _ in range(4):
        client.post("/v1/pair", json={"code": "AAAA-AAAA-AA"})
    assert client.post("/v1/pair", json={"code": "AAAA-AAAA-AA"}).status_code == 429


def test_models_lists_only_allowed():
    client, _, headers, _ = make_client()
    ids = [m["id"] for m in client.get("/v1/models", headers=headers).json()["data"]]
    assert ids[0] == "auto"
    assert "main" in ids and "granite4.2:8b" not in ids  # model kodu wyłączony
