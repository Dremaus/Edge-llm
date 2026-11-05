"""Przestrzeń plików użytkownika dla agenta (dokumenty, PDF-y, arkusze).

Każdy telefon ma własny katalog; agent i API widzą tylko jego. Nazwy są płaskie (bez katalogów),
dowiązania symboliczne są odrzucane, a rozmiary ograniczone — plik od użytkownika to niezaufane dane.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 500
QUOTA_BYTES = 300 * 1024 * 1024
_NAME_RE = re.compile(r"^[\w][\w .\-()]{0,99}$", re.UNICODE)


class FileError(ValueError):
    pass


def clean_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name) or ".." in name or name.endswith("."):
        raise FileError("Nieprawidłowa nazwa pliku")
    return name


class FileStore:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)

    def _dir(self, device_id: str) -> Path:
        d = self._root / hashlib.sha256(device_id.encode()).hexdigest()[:24]
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def path(self, device_id: str, name: str, must_exist: bool = True) -> Path:
        p = self._dir(device_id) / clean_name(name)
        if p.is_symlink():
            raise FileError("Nieprawidłowy plik")
        if must_exist and not p.is_file():
            raise FileError(f"Nie ma pliku: {name}")
        return p

    def list(self, device_id: str) -> list[dict]:
        out = []
        for p in sorted(self._dir(device_id).iterdir()):
            if p.is_file() and not p.is_symlink():
                st = p.stat()
                out.append({"name": p.name, "size": st.st_size, "modified": int(st.st_mtime)})
        return out

    def _used(self, device_id: str) -> tuple[int, int]:
        files = self.list(device_id)
        return len(files), sum(f["size"] for f in files)

    def save(self, device_id: str, name: str, data: bytes, overwrite: bool = False) -> str:
        name = clean_name(name)
        if len(data) > MAX_FILE_BYTES:
            raise FileError("Plik jest za duży")
        count, used = self._used(device_id)
        target = self._dir(device_id) / name
        if target.exists() and not overwrite:
            stem, dot, ext = name.rpartition(".")
            for i in range(2, 100):
                cand = f"{stem} ({i}).{ext}" if dot else f"{name} ({i})"
                if not (self._dir(device_id) / cand).exists():
                    name, target = cand, self._dir(device_id) / cand
                    break
            else:
                raise FileError("Nie można nadać unikalnej nazwy")
        replaced = target.stat().st_size if target.exists() else 0
        if count >= MAX_FILES and not replaced:
            raise FileError("Osiągnięto limit plików")
        if used - replaced + len(data) > QUOTA_BYTES:
            raise FileError("Przekroczony limit miejsca")
        tmp = target.with_name(f".{name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
        return name

    def delete(self, device_id: str, name: str) -> bool:
        try:
            p = self.path(device_id, name)
        except FileError:
            return False
        p.unlink()
        return True


def human_age_days(mtime: int) -> int:
    return max(0, int((time.time() - mtime) // 86400))
