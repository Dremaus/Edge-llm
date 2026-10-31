from __future__ import annotations

import os
import stat

import pytest

from app.security.pairing import CODE_TTL_S, MAX_BAD_ATTEMPTS, PairingError, PairingManager
from app.security.tokens import TokenStore


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def make(tmp_path=None):
    clock = Clock()
    tokens = TokenStore()
    path = tmp_path / "pairing.json" if tmp_path else None
    return PairingManager(tokens, path, clock=clock), tokens, clock


def test_code_exchanged_for_working_token():
    mgr, tokens, _ = make()
    code, _ = mgr.new_code()
    device_id, token = mgr.redeem(code, "Telefon Witka")
    assert tokens.verify(token).id == device_id
    assert tokens.verify(token).name == "Telefon Witka"


def test_code_is_single_use():
    mgr, *_ = make()
    code, _ = mgr.new_code()
    mgr.redeem(code, "a")
    with pytest.raises(PairingError):
        mgr.redeem(code, "b")


def test_code_expires():
    mgr, _, clock = make()
    code, _ = mgr.new_code()
    clock.t += CODE_TTL_S + 1
    with pytest.raises(PairingError):
        mgr.redeem(code, "a")


def test_code_accepts_formatting_variants():
    mgr, *_ = make()
    code, _ = mgr.new_code()
    assert mgr.redeem(code.lower().replace("-", " "), "a")


def test_too_many_bad_attempts_burns_codes():
    mgr, *_ = make()
    code, _ = mgr.new_code()
    for _ in range(MAX_BAD_ATTEMPTS):
        with pytest.raises(PairingError):
            mgr.redeem("AAAA-AAAA-AA", "atak")
    with pytest.raises(PairingError):
        mgr.redeem(code, "spóźniony")


def test_only_hash_on_disk_with_strict_permissions(tmp_path):
    mgr, *_ = make(tmp_path)
    code, _ = mgr.new_code()
    path = tmp_path / "pairing.json"
    assert code.replace("-", "") not in path.read_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_code_created_by_cli_process_is_redeemable_by_server(tmp_path):
    path = tmp_path / "pairing.json"
    tokens_path = tmp_path / "tokens.json"
    cli = PairingManager(TokenStore(tokens_path), path)
    code, _ = cli.new_code()
    server = PairingManager(TokenStore(tokens_path), path)
    _, token = server.redeem(code, "Telefon")
    assert token.startswith("edge_")


@pytest.mark.parametrize("bad", ["", "123", "X" * 50, None])
def test_malformed_codes_rejected(bad):
    mgr, *_ = make()
    mgr.new_code()
    with pytest.raises(PairingError):
        mgr.redeem(bad, "a")
