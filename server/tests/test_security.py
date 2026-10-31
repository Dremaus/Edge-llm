"""Testy modułów bezpieczeństwa (bez zależności od FastAPI)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.security.ratelimit import FailureLockout, TokenBucket
from app.security.tokens import TokenStore
from app.security.validation import (
    MAX_IMAGES,
    MAX_TOKENS_CAP,
    ValidationError,
    clean_messages,
    clean_params,
)


# --- tokeny -------------------------------------------------------------
def test_token_roundtrip_and_hash_only_on_disk(tmp_path):
    path = tmp_path / "tokens.json"
    store = TokenStore(path)
    record, secret = store.create("Telefon")
    assert store.verify(secret).id == record.id
    raw = path.read_text()
    assert secret not in raw  # na dysku tylko skrót
    assert json.loads(raw)["tokens"][0]["sha256"] == record.sha256
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_wrong_and_malformed_tokens_rejected():
    store = TokenStore()
    _, secret = store.create("a")
    assert store.verify(secret[:-1] + ("A" if secret[-1] != "A" else "B")) is None
    assert store.verify("") is None
    assert store.verify("bez-prefiksu") is None
    assert store.verify("edge_" + "x" * 500) is None


def test_revoke_takes_effect_for_running_server(tmp_path):
    path = tmp_path / "tokens.json"
    server_view = TokenStore(path)
    record, secret = server_view.create("Telefon")
    # Unieważnienie z osobnego procesu (CLI) — serwer widzi je bez restartu.
    cli_view = TokenStore(path)
    assert cli_view.revoke(record.id)
    os.utime(path, (1, 1))  # wymuś inną datę modyfikacji niezależnie od rozdzielczości zegara
    assert server_view.verify(secret) is None


def test_refuses_world_readable_tokens_file(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text('{"tokens": []}')
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError):
        TokenStore(path)


def test_tokens_are_unique_and_long():
    store = TokenStore()
    secrets_ = {store.create(str(i))[1] for i in range(50)}
    assert len(secrets_) == 50
    assert all(len(s) >= 40 for s in secrets_)


# --- limity -------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_token_bucket_limits_and_refills():
    clock = Clock()
    bucket = TokenBucket(rate_per_min=60, burst=3, clock=clock)
    assert [bucket.allow("d") for _ in range(4)] == [True, True, True, False]
    clock.t += 1.0  # 1 zapytanie na sekundę
    assert bucket.allow("d")
    assert bucket.allow("inne-urządzenie")


def test_lockout_after_failures_and_expiry():
    clock = Clock()
    lock = FailureLockout(max_failures=3, window_s=60, lockout_s=600, clock=clock)
    for _ in range(3):
        lock.record_failure("1.2.3.4")
    assert lock.is_blocked("1.2.3.4")
    assert not lock.is_blocked("5.6.7.8")
    clock.t += 601
    assert not lock.is_blocked("1.2.3.4")


def test_success_resets_failure_counter():
    lock = FailureLockout(max_failures=3)
    lock.record_failure("k")
    lock.record_failure("k")
    lock.record_success("k")
    lock.record_failure("k")
    assert not lock.is_blocked("k")


# --- walidacja ----------------------------------------------------------
PNG = "data:image/png;base64,iVBORw0KGgo="


def test_valid_text_and_image_message():
    out = clean_messages(
        [
            {"role": "user", "content": "hej", "name": "ignored", "extra": 1},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "co to?"},
                    {"type": "image_url", "image_url": {"url": PNG}},
                ],
            },
        ]
    )
    assert out[0] == {"role": "user", "content": "hej"}  # nieznane pola usunięte
    assert out[1]["content"][1]["image_url"]["url"] == PNG


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",  # SSRF
        "file:///etc/passwd",
        "data:text/html;base64,PHNjcmlwdD4=",
        "data:image/png;base64,abc<script>",
    ],
)
def test_rejects_non_inline_or_malformed_images(url):
    with pytest.raises(ValidationError):
        clean_messages([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}])


def test_rejects_too_many_images():
    parts = [{"type": "image_url", "image_url": {"url": PNG}}] * (MAX_IMAGES + 1)
    with pytest.raises(ValidationError):
        clean_messages([{"role": "user", "content": parts}])


@pytest.mark.parametrize(
    "messages",
    [
        [],
        "tekst",
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": None}],
        [{"role": "user", "content": "x" * 100_001}],
        [{"role": "user", "content": [{"type": "audio", "data": "x"}]}],
    ],
)
def test_rejects_invalid_messages(messages):
    with pytest.raises(ValidationError):
        clean_messages(messages)


def test_params_are_clamped_and_unknown_dropped():
    params = clean_params(
        {"temperature": 9, "max_tokens": 10**9, "top_p": -1, "seed": 1, "options": {"num_gpu": 99}}
    )
    assert params == {"temperature": 2.0, "max_tokens": MAX_TOKENS_CAP, "top_p": 0.0}


@pytest.mark.parametrize("body", [{"temperature": "1"}, {"max_tokens": True}, {"stop": ["x"] * 10}])
def test_params_reject_bad_types(body):
    with pytest.raises(ValidationError):
        clean_params(body)
