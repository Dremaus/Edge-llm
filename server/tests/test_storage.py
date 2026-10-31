from __future__ import annotations

import asyncio
import os
import stat

import pytest

from app.sse import DeltaCollector, tee_stream
from app.storage import SettingsError, Storage


def test_default_settings_follow_install_language():
    s = Storage(default_language="en").get_settings()
    assert (s.language, s.chat_model, s.onboarding_done) == ("en", "qwen", False)


def test_onboarding_update_persists(tmp_path):
    path = tmp_path / "edge.db"
    Storage(path).update_settings({"language": "pl", "chat_model": "bielik", "onboarding_done": True})
    again = Storage(path).get_settings()
    assert again.chat_model == "bielik" and again.onboarding_done
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.parametrize(
    "changes",
    [{"language": "de"}, {"chat_model": "gpt"}, {"onboarding_done": "tak"}, {"admin": True}],
)
def test_invalid_settings_rejected(changes):
    with pytest.raises(SettingsError):
        Storage().update_settings(changes)


def test_conversations_are_isolated_per_device():
    db = Storage()
    conv = db.create_conversation("phone-a", "Przepis na pierogi")
    db.add_message("phone-a", conv, "user", "Jak zrobić pierogi?")
    db.add_message("phone-a", conv, "assistant", "Potrzebujesz mąki...", model="qwen3.5:4b")
    assert [c["id"] for c in db.list_conversations("phone-a")] == [conv]
    assert db.list_conversations("phone-b") == []
    assert db.get_conversation("phone-b", conv) is None
    with pytest.raises(KeyError):
        db.add_message("phone-b", conv, "user", "wtargnięcie")
    assert not db.delete_conversation("phone-b", conv)
    full = db.get_conversation("phone-a", conv)
    assert [m["role"] for m in full["messages"]] == ["user", "assistant"]


def test_images_are_not_stored_in_history():
    db = Storage()
    conv = db.create_conversation("d", "Zdjęcie")
    parts = [
        {"type": "text", "text": "Co to?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    db.add_message("d", conv, "user", parts)
    stored = db.get_conversation("d", conv)["messages"][0]["content"]
    assert stored == [{"type": "text", "text": "Co to?"}, {"type": "image_omitted"}]


def test_delete_all_removes_messages_too():
    db = Storage()
    for i in range(3):
        c = db.create_conversation("d", f"r{i}")
        db.add_message("d", c, "user", "x")
    assert db.delete_all("d") == 3
    assert db.list_conversations("d") == []
    assert db._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_title_is_trimmed():
    db = Storage()
    conv = db.create_conversation("d", "  bardzo\n" + "długi " * 40)
    assert len(db.get_conversation("d", conv)["title"]) <= 80


# --- SSE --------------------------------------------------------------
def test_collector_handles_split_chunks():
    c = DeltaCollector()
    c.feed(b'data: {"choices":[{"delta":{"content":"Cze"}}]}\n\ndata: {"choi')
    c.feed(b'ces":[{"delta":{"content":"\xc5\x9b\xc4\x87!"}}]}\n\ndata: [DONE]\n\n')
    assert c.text == "Cześć!"


def test_collector_ignores_garbage():
    c = DeltaCollector()
    c.feed(b": komentarz\n\ndata: nie-json\n\ndata: {\"choices\":[]}\n\n")
    assert c.text == ""


def test_tee_stream_passes_bytes_and_reports_text():
    chunks = [b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n', b"data: [DONE]\n\n"]
    seen: list[str] = []

    async def source():
        for ch in chunks:
            yield ch

    async def run():
        return [c async for c in tee_stream(source(), seen.append)]

    assert asyncio.run(run()) == chunks
    assert seen == ["A"]
