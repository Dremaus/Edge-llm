from __future__ import annotations

from app.security.redact import MASK, mask_secrets
from app.storage import Storage


def test_mask_known_formats():
    for secret in (
        "sk-ant-api03-abcdefghijklmnopqrstuvwx",
        "ghp_" + "a" * 36,
        "AKIAABCDEFGHIJKLMNOP",
        "hf_" + "b" * 34,
        "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefghijkl",
    ):
        assert secret not in mask_secrets(f"klucz to {secret} ok")


def test_mask_assignment_keeps_field_name():
    assert mask_secrets("hasło: tajne123") == f"hasło: {MASK}"
    assert mask_secrets("password=hunter2!") == f"password={MASK}"
    assert mask_secrets("zwykły tekst o hasłach") == "zwykły tekst o hasłach"


def test_mask_private_key_block():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\nb"
    out = mask_secrets(text)
    assert "MIIB" not in out and out.startswith("a") and out.endswith("b")


def test_notes_masked_and_searchable_per_device():
    db = Storage()
    db.add_note("a", "Kasia lubi zielona herbata, token: abc12345")
    db.add_note("a", "Spotkanie z lekarzem w piątek")
    db.add_note("b", "Zielona herbata u innego użytkownika")
    found = db.search_notes("a", "herbata")
    assert len(found) == 1 and "abc12345" not in found[0]["text"] and MASK in found[0]["text"]
    assert db.search_notes("a", 'lekarz" OR *') == []  # składnia FTS z danych nie działa
    assert db.search_notes("a", "") == []


def test_delete_note_only_own_and_removed_from_index():
    db = Storage()
    nid = db.add_note("a", "unikalnesłowo xyz")
    assert not db.delete_note("b", nid)
    assert db.delete_note("a", nid)
    assert db.search_notes("a", "unikalnesłowo") == []


def test_messages_masked_in_history():
    db = Storage()
    conv = db.create_conversation("a", "t")
    db.add_message("a", conv, "user", "moje hasło: SuperTajne99")
    msgs = db.get_conversation("a", conv)["messages"]
    assert "SuperTajne99" not in msgs[0]["content"]
