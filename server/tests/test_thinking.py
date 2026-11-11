from __future__ import annotations

import pytest

from app.storage import SettingsError, Storage
from app.thinking import SHORT_MAX_TOKENS, apply_thinking

PREFIX = ("qwen3",)


def test_off_short_full_for_supported_model():
    assert apply_thinking("off", "qwen3.5:4b", PREFIX, {})["reasoning_effort"] == "none"
    short = apply_thinking("short", "qwen3.5:4b", PREFIX, {})
    assert short["reasoning_effort"] == "low" and short["max_tokens"] == SHORT_MAX_TOKENS
    full = apply_thinking("full", "qwen3.5:4b", PREFIX, {"max_tokens": 3000})
    assert full["reasoning_effort"] == "high" and full["max_tokens"] == 3000


def test_short_respects_smaller_client_limit_and_does_not_mutate():
    original = {"max_tokens": 200, "temperature": 0.2}
    out = apply_thinking("short", "qwen3.5:4b", PREFIX, original)
    assert out["max_tokens"] == 200 and out["temperature"] == 0.2 and "reasoning_effort" not in original


@pytest.mark.parametrize("model", ["hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0", "gemma4"])
def test_unsupported_models_untouched(model):
    assert apply_thinking("full", model, PREFIX, {"max_tokens": 10}) == {"max_tokens": 10}


def test_unknown_level_ignored():
    assert apply_thinking("???", "qwen3.5:4b", PREFIX, {}) == {}


def test_setting_stored_and_validated():
    s = Storage()
    assert s.get_settings().thinking == "off"
    assert s.update_settings({"thinking": "short"}).thinking == "short"
    with pytest.raises(SettingsError):
        s.update_settings({"thinking": "max"})
