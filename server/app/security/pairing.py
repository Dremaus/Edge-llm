"""Parowanie telefonu jednorazowym kodem (wyświetlanym jako kod QR).

Przebieg:
1. Na urządzeniu (konsola/SSH) uruchamiamy `python -m app.security.pairing new`.
   Powstaje kod ważny 10 minut, wyświetlany jako QR z adresem urządzenia.
2. Aplikacja skanuje QR i wysyła kod na `POST /v1/pair`.
3. Serwer wymienia kod na token urządzenia (pokazywany tylko raz) i spala kod.

Zabezpieczenia:
- kod ma 50 bitów losowości, żyje 10 minut i działa tylko raz,
- na dysku tylko skrót SHA-256 kodu (plik 0600),
- po 10 błędnych próbach wszystkie aktywne kody są unieważniane
  (dodatkowo działa blokada adresu IP po 5 nieudanych próbach w API),
- kod da się wygenerować tylko lokalnie na urządzeniu — nie ma do tego endpointu.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .tokens import TokenStore

CODE_TTL_S = 600
MAX_BAD_ATTEMPTS = 10
DEFAULT_PATH = "/var/lib/edge-llm/pairing.json"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _normalize(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


class PairingError(Exception):
    pass


class PairingManager:
    def __init__(
        self,
        tokens: TokenStore,
        path: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tokens = tokens
        self._path = Path(path) if path else None
        self._clock = clock
        self._lock = threading.Lock()
        self._mem: dict = {"codes": [], "bad_attempts": 0}

    # --- trwałość (kod tworzy CLI, wymienia serwer — osobne procesy) -----
    def _read(self) -> dict:
        if not self._path:
            return self._mem
        if not self._path.exists():
            return {"codes": [], "bad_attempts": 0}
        if self._path.stat().st_mode & 0o077:
            raise PermissionError(f"{self._path} musi mieć uprawnienia 0600")
        return json.loads(self._path.read_text("utf-8"))

    def _write(self, data: dict) -> None:
        if not self._path:
            self._mem = data
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".pairing-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _prune(self, data: dict) -> dict:
        now = self._clock()
        data["codes"] = [c for c in data["codes"] if c["expires"] > now]
        return data

    # --- API ------------------------------------------------------------
    def new_code(self) -> tuple[str, float]:
        """Zwraca kod (np. 'K7Q2-M9XA-3F') i czas wygaśnięcia."""
        raw = base64.b32encode(secrets.token_bytes(7)).decode()[:10]  # 50 bitów
        expires = self._clock() + CODE_TTL_S
        with self._lock:
            data = self._prune(self._read())
            data["codes"].append({"sha256": _hash(raw), "expires": expires})
            data["bad_attempts"] = 0
            self._write(data)
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}", expires

    def redeem(self, code: str, device_name: str) -> tuple[str, str]:
        """Wymienia kod na (device_id, token). Rzuca PairingError przy błędzie."""
        normalized = _normalize(code or "")
        if len(normalized) != 10:
            raise PairingError("Nieprawidłowy kod")
        digest = _hash(normalized)
        with self._lock:
            data = self._prune(self._read())
            match = None
            for entry in data["codes"]:
                if hmac.compare_digest(entry["sha256"], digest):
                    match = entry
            if match is None:
                data["bad_attempts"] = data.get("bad_attempts", 0) + 1
                if data["bad_attempts"] >= MAX_BAD_ATTEMPTS:
                    data["codes"] = []  # zbyt wiele prób — spalamy wszystkie kody
                    data["bad_attempts"] = 0
                self._write(data)
                raise PairingError("Nieprawidłowy lub wygasły kod")
            data["codes"].remove(match)  # kod jednorazowy
            self._write(data)
        record, token = self._tokens.create(device_name or "Telefon")
        return record.id, token


def _print_qr(payload: str) -> None:
    if shutil.which("qrencode"):
        subprocess.run(["qrencode", "-t", "ANSIUTF8", payload], check=False)  # noqa: S603,S607
    else:
        print("(zainstaluj 'qrencode', aby zobaczyć kod QR)")


def _cli(argv: list[str]) -> int:
    if argv[:1] != ["new"]:
        print(__doc__)
        return 2
    tokens = TokenStore(os.environ.get("EDGE_TOKENS_FILE", "/var/lib/edge-llm/tokens.json"))
    manager = PairingManager(tokens, os.environ.get("EDGE_PAIRING_FILE", DEFAULT_PATH))
    code, expires = manager.new_code()
    url = os.environ.get("EDGE_PUBLIC_URL", "")
    payload = json.dumps({"v": 1, "url": url, "code": code}, separators=(",", ":"))
    _print_qr(payload)
    print(f"Kod parowania: {code}")
    print(f"Ważny do: {time.strftime('%H:%M:%S', time.localtime(expires))} (jednorazowy)")
    if not url:
        print("Wskazówka: ustaw EDGE_PUBLIC_URL (np. https://urzadzenie.tailnet.ts.net), żeby QR zawierał adres.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
