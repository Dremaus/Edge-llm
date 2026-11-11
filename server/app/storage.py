"""Trwałe dane urządzenia: ustawienia i historia rozmów (SQLite).

- Każdy telefon widzi tylko własne rozmowy (izolacja po device_id).
- Plik bazy ma uprawnienia 0600; `secure_delete` nadpisuje usuwane dane zerami.
- Szyfrowanie całego dysku (LUKS) zapewnia system — patrz docs/security.md.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .security.redact import mask_content, mask_secrets

LANGUAGES = ("pl", "en")
CHAT_MODELS = ("qwen", "bielik")
MAX_TITLE = 80

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS conv_device ON conversations(device_id, updated DESC);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS msg_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_device ON notes(device_id, id DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, content='notes', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    ts REAL NOT NULL,
    tool TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    args TEXT NOT NULL DEFAULT '',
    ok INTEGER,
    ms INTEGER
);
CREATE INDEX IF NOT EXISTS audit_device ON audit_log(device_id, id DESC);
"""

AUDIT_KEEP_PER_DEVICE = 2000
AUDIT_ARGS_CHARS = 200


@dataclass
class DeviceSettings:
    language: str = "pl"
    chat_model: str = "qwen"
    onboarding_done: bool = False
    thinking: str = "off"

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "chat_model": self.chat_model,
            "onboarding_done": self.onboarding_done,
            "thinking": self.thinking,
        }


class SettingsError(ValueError):
    pass


class Storage:
    def __init__(self, path: str | os.PathLike[str] = ":memory:", default_language: str = "pl") -> None:
        self._lock = threading.Lock()
        self._default_language = default_language if default_language in LANGUAGES else "pl"
        if str(path) != ":memory:":
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.touch(mode=0o600)
            os.chmod(p, 0o600)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA secure_delete = ON")
        if str(path) != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    # --- ustawienia (wspólne dla urządzenia) -----------------------------
    def get_settings(self) -> DeviceSettings:
        with self._lock:
            rows = dict(self._db.execute("SELECT key, value FROM settings").fetchall())
        return DeviceSettings(
            language=rows.get("language", self._default_language),
            chat_model=rows.get("chat_model", "qwen"),
            onboarding_done=rows.get("onboarding_done") == "1",
            thinking=rows.get("thinking", "off") if rows.get("thinking") in ("off", "short", "full") else "off",
        )

    def update_settings(self, changes: dict[str, Any]) -> DeviceSettings:
        allowed = {"language", "chat_model", "onboarding_done", "thinking"}
        unknown = set(changes) - allowed
        if unknown:
            raise SettingsError("Nieznane ustawienie")
        values: dict[str, str] = {}
        if "language" in changes:
            if changes["language"] not in LANGUAGES:
                raise SettingsError("Język musi być 'pl' lub 'en'")
            values["language"] = changes["language"]
        if "chat_model" in changes:
            if changes["chat_model"] not in CHAT_MODELS:
                raise SettingsError("Model musi być 'qwen' lub 'bielik'")
            values["chat_model"] = changes["chat_model"]
        if "thinking" in changes:
            if changes["thinking"] not in ("off", "short", "full"):
                raise SettingsError("Rozumowanie musi być 'off', 'short' lub 'full'")
            values["thinking"] = changes["thinking"]
        if "onboarding_done" in changes:
            if not isinstance(changes["onboarding_done"], bool):
                raise SettingsError("onboarding_done musi być wartością logiczną")
            values["onboarding_done"] = "1" if changes["onboarding_done"] else "0"
        with self._lock:
            self._db.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(values.items()),
            )
            self._db.commit()
        return self.get_settings()

    # --- rozmowy ---------------------------------------------------------
    def create_conversation(self, device_id: str, title: str) -> str:
        conv_id = secrets.token_hex(8)
        now = int(time.time())
        title = " ".join(title.split())[:MAX_TITLE] or "Nowa rozmowa"
        with self._lock:
            self._db.execute(
                "INSERT INTO conversations(id, device_id, title, created, updated) VALUES(?,?,?,?,?)",
                (conv_id, device_id, title, now, now),
            )
            self._db.commit()
        return conv_id

    def owns(self, device_id: str, conv_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND device_id = ?", (conv_id, device_id)
            ).fetchone()
        return row is not None

    def add_message(
        self, device_id: str, conv_id: str, role: str, content: Any, model: str | None = None
    ) -> None:
        if not self.owns(device_id, conv_id):
            raise KeyError(conv_id)
        stored = mask_content(content) if isinstance(content, str) else json.dumps(mask_content(_strip_images(content)))
        now = int(time.time())
        with self._lock:
            self._db.execute(
                "INSERT INTO messages(conversation_id, role, content, model, created) VALUES(?,?,?,?,?)",
                (conv_id, role, stored, model, now),
            )
            self._db.execute("UPDATE conversations SET updated = ? WHERE id = ?", (now, conv_id))
            self._db.commit()

    def list_conversations(self, device_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, title, created, updated FROM conversations "
                "WHERE device_id = ? ORDER BY updated DESC LIMIT ?",
                (device_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, device_id: str, conv_id: str) -> dict[str, Any] | None:
        with self._lock:
            conv = self._db.execute(
                "SELECT id, title, created, updated FROM conversations WHERE id = ? AND device_id = ?",
                (conv_id, device_id),
            ).fetchone()
            if conv is None:
                return None
            msgs = self._db.execute(
                "SELECT role, content, model, created FROM messages WHERE conversation_id = ? ORDER BY id",
                (conv_id,),
            ).fetchall()
        return {**dict(conv), "messages": [_decode(dict(m)) for m in msgs]}

    def delete_conversation(self, device_id: str, conv_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM conversations WHERE id = ? AND device_id = ?", (conv_id, device_id)
            )
            self._db.commit()
        return cur.rowcount > 0

    def delete_all(self, device_id: str) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM conversations WHERE device_id = ?", (device_id,))
            self._db.commit()
        return cur.rowcount

    # --- dziennik audytu narzędzi (bez treści plików i wyników; argumenty maskowane i skrócone) -------
    def add_audit(self, entry: dict[str, Any]) -> None:
        args = entry.get("args")
        text = ""
        if args:
            text = mask_secrets(json.dumps(args, ensure_ascii=False, default=str))[:AUDIT_ARGS_CHARS]
        ok = entry.get("ok")
        with self._lock:
            self._db.execute(
                "INSERT INTO audit_log(device_id, ts, tool, decision, reason, args, ok, ms) VALUES (?,?,?,?,?,?,?,?)",
                (entry["device_id"], time.time(), str(entry["tool"])[:64], str(entry["decision"]),
                 str(entry.get("reason") or "")[:200], text, None if ok is None else int(bool(ok)), entry.get("ms")),
            )
            self._db.execute(
                "DELETE FROM audit_log WHERE device_id = ? AND id NOT IN "
                "(SELECT id FROM audit_log WHERE device_id = ? ORDER BY id DESC LIMIT ?)",
                (entry["device_id"], entry["device_id"], AUDIT_KEEP_PER_DEVICE),
            )
            self._db.commit()

    def list_audit(self, device_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, tool, decision, reason, args, ok, ms FROM audit_log WHERE device_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (device_id, max(1, min(limit, 500))),
            ).fetchall()
        return [{**dict(r), "ok": None if r["ok"] is None else bool(r["ok"])} for r in rows]

    # --- notatki (narzędzie agenta) ---------------------------------------
    def add_note(self, device_id: str, text: str) -> int:
        text = mask_secrets(text.strip()[:MAX_NOTE])
        if not text:
            raise ValueError("Pusta notatka")
        with self._lock:
            count = self._db.execute(
                "SELECT COUNT(*) FROM notes WHERE device_id = ?", (device_id,)
            ).fetchone()[0]
            if count >= MAX_NOTES_PER_DEVICE:
                raise ValueError("Osiągnięto limit notatek")
            cur = self._db.execute(
                "INSERT INTO notes(device_id, text, created) VALUES(?,?,?)",
                (device_id, text, int(time.time())),
            )
            self._db.commit()
        return int(cur.lastrowid)

    def list_notes(self, device_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, text, created FROM notes WHERE device_id = ? ORDER BY id DESC LIMIT ?",
                (device_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_notes(self, device_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Wyszukiwanie pełnotekstowe (FTS5) wśród notatek tego urządzenia."""
        words = re.findall(r"\w{2,}", query.lower())[:8]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)  # cytowanie: bez składni FTS z danych użytkownika
        with self._lock:
            rows = self._db.execute(
                "SELECT n.id, n.text, n.created FROM notes_fts f JOIN notes n ON n.id = f.rowid "
                "WHERE notes_fts MATCH ? AND n.device_id = ? ORDER BY rank LIMIT ?",
                (match, device_id, max(1, min(limit, 20))),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_note(self, device_id: str, note_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM notes WHERE id = ? AND device_id = ?", (note_id, device_id))
            self._db.commit()
        return cur.rowcount > 0


MAX_NOTE = 2000
MAX_NOTES_PER_DEVICE = 1000


def _strip_images(parts: Any) -> Any:
    """Nie przechowujemy obrazów w historii — tylko informację, że były."""
    if not isinstance(parts, list):
        return parts
    out = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "image_url":
            out.append({"type": "image_omitted"})
        else:
            out.append(part)
    return out


def _decode(msg: dict[str, Any]) -> dict[str, Any]:
    content = msg["content"]
    if content.startswith("["):
        try:
            msg["content"] = json.loads(content)
        except ValueError:
            pass
    return msg
