from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.router import ModelRouter, parse_label


class FakeLLM:
    def __init__(self, answer: str = "chat", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.calls: list[str] = []

    async def complete(self, model: str, messages: list[dict[str, Any]], **params: Any) -> str:
        self.calls.append(model)
        if self.fail:
            raise RuntimeError("ollama down")
        return self.answer

    async def stream(self, model, messages, **params):  # pragma: no cover
        yield b""

    async def list_models(self) -> list[str]:
        return []


def settings(**overrides: Any) -> Settings:
    base = dict(
        api_token="t",
        router_model="small",
        main_model="main",
        code_model="coder",
        code_model_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


def user(text: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": text}]


async def test_image_goes_to_main_model_without_classifier():
    llm = FakeLLM()
    r = ModelRouter(settings(), llm)
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Co jest na zdjęciu?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            ],
        }
    ]
    out = await r.route(msgs)
    assert out["route"] == "vision"
    assert out["model"] == "main"
    assert llm.calls == []


@pytest.mark.parametrize(
    "text",
    [
        "Napisz skrypt w Pythonie, który zmienia nazwy plików",
        "Zrób mi stronę www dla piekarni",
        "Fix this bug:\n```js\nconsole.log(x)\n```",
    ],
)
async def test_code_rule(text):
    llm = FakeLLM()
    out = await ModelRouter(settings(), llm).route(user(text))
    assert out["route"] == "code"
    assert out["model"] == "coder"
    assert llm.calls == []


async def test_code_falls_back_to_main_when_code_model_disabled():
    out = await ModelRouter(settings(code_model_enabled=False), FakeLLM()).route(
        user("napisz funkcję w python")
    )
    assert out["model"] == "main"


async def test_classifier_simple_uses_small_model():
    llm = FakeLLM(answer="simple")
    out = await ModelRouter(settings(), llm).route(user("Jaka jest stolica Francji?"))
    assert out["route"] == "simple"
    assert out["model"] == "small"
    assert llm.calls == ["small"]


async def test_classifier_error_falls_back_to_main():
    out = await ModelRouter(settings(), FakeLLM(fail=True)).route(user("Opowiedz mi o Krakowie"))
    assert out["route"] == "chat"
    assert out["model"] == "main"
    assert out["reason"] == "fallback:error"


async def test_unparsed_answer_falls_back_to_chat():
    out = await ModelRouter(settings(), FakeLLM(answer="???")).route(user("hej"))
    assert out["reason"] == "fallback:unparsed"
    assert out["model"] == "main"


def test_parse_label():
    assert parse_label("  Multistep.") == "multistep"
    assert parse_label("The answer: code") == "code"
    assert parse_label("nie wiem") is None
