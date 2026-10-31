"""Tokeny dostępu per urządzenie (telefon).

- Token ma 256 bitów entropii i jest pokazywany tylko raz, przy tworzeniu.
- Na dysku trzymamy wyłącznie skrót SHA-256 (przy 256 bitach losowości wolny
  hash typu Argon2 nie jest potrzebny — nie da się go odgadnąć słownikowo).
- Porównanie w stałym czasie; plik zapisywany atomowo z uprawnieniami 0600.
- Każde urządzenie można osobno unieważnić.

Użycie (na urządzeniu):
    python -m app.security.tokens add "Telefon Witka"
    python -m app.security.tokens list
    python -m app.security.tokens revoke <id>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

TOKEN_PREFIX = "edge_"
DEFAULT_PATH = "/var/lib/edge-llm/tokens.json"


@dataclass
class DeviceToken:
    id: str
    name: str
    sha256: str
    created: int
    revoked: bool = False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._tokens: dict[str, DeviceToken] = {}
        self._mtime: float | None = None
        self._load()

    # --- trwałość -------------------------------------------------------
    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        mode = self._path.stat().st_mode & 0o777
        if mode & 0o077:
            raise PermissionError(
                f"{self._path} ma zbyt szerokie uprawnienia ({oct(mode)}); wymagane 0600"
            )
        data = json.loads(self._path.read_text("utf-8"))
        self._tokens = {t["id"]: DeviceToken(**t) for t in data.get("tokens", [])}
        self._mtime = self._path.stat().st_mtime

    def _reload_if_changed(self) -> None:
        # Pozwala unieważnić token z CLI bez restartu serwera.
        if self._path and self._path.exists() and self._path.stat().st_mtime != self._mtime:
            self._load()

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"tokens": [asdict(t) for t in self._tokens.values()]}, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tokens-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._mtime = self._path.stat().st_mtime

    # --- API ------------------------------------------------------------
    def create(self, name: str) -> tuple[DeviceToken, str]:
        """Zwraca rekord i jawny token (do pokazania użytkownikowi tylko raz)."""
        name = name.strip()[:64] or "urządzenie"
        secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = DeviceToken(
            id=secrets.token_hex(4), name=name, sha256=_hash(secret), created=int(time.time())
        )
        with self._lock:
            self._tokens[record.id] = record
            self._save()
        return record, secret

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            record = self._tokens.get(token_id)
            if not record:
                return False
            record.revoked = True
            self._save()
            return True

    def list(self) -> list[DeviceToken]:
        with self._lock:
            self._reload_if_changed()
            return list(self._tokens.values())

    def verify(self, presented: str) -> DeviceToken | None:
        """Zwraca urządzenie dla poprawnego tokenu albo None."""
        if not presented or not presented.startswith(TOKEN_PREFIX) or len(presented) > 128:
            return None
        digest = _hash(presented)
        with self._lock:
            self._reload_if_changed()
            match: DeviceToken | None = None
            # Przechodzimy po wszystkich rekordach, żeby czas nie zależał od pozycji.
            for record in self._tokens.values():
                if hmac.compare_digest(record.sha256, digest) and not record.revoked:
                    match = record
            return match


def _cli(argv: list[str]) -> int:
    path = os.environ.get("EDGE_TOKENS_FILE", DEFAULT_PATH)
    store = TokenStore(path)
    if len(argv) >= 2 and argv[0] == "add":
        record, secret = store.create(" ".join(argv[1:]))
        print(f"id: {record.id}\nnazwa: {record.name}\ntoken (pokazywany tylko raz): {secret}")
        return 0
    if argv[:1] == ["list"]:
        for t in store.list():
            state = "UNIEWAŻNIONY" if t.revoked else "aktywny"
            print(f"{t.id}  {state:12}  {time.strftime('%Y-%m-%d', time.localtime(t.created))}  {t.name}")
        return 0
    if len(argv) == 2 and argv[0] == "revoke":
        ok = store.revoke(argv[1])
        print("unieważniono" if ok else "nie znaleziono")
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
