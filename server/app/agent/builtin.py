"""Rejestr narzędzi faktycznie dostępnych dla agenta (z wykonawcami)."""

from __future__ import annotations

from typing import Any

from ..storage import Storage
from .policy import Risk, ToolSpec
from .runner import Executor
from .tools import calculator, current_time

LIST_NOTES = ToolSpec("list_notes", "Pokazuje ostatnie notatki użytkownika.", Risk.READ)
SAVE_NOTE = ToolSpec("save_note", "Zapisuje notatkę użytkownika na urządzeniu.", Risk.WRITE)
CALCULATOR = ToolSpec("calculator", "Oblicza wyrażenie arytmetyczne, np. '2*(3+4)/5'.", Risk.READ)
CURRENT_TIME = ToolSpec("current_time", "Podaje aktualną datę i godzinę (Europe/Warsaw).", Risk.READ)

SPECS = [CALCULATOR, CURRENT_TIME, LIST_NOTES, SAVE_NOTE]


def build_registry(storage: Storage) -> dict[str, tuple[ToolSpec, dict[str, Any], Executor]]:
    def calc(args: dict[str, Any], _device: str) -> str:
        return str(calculator(str(args.get("expression", ""))))

    def now(_args: dict[str, Any], _device: str) -> str:
        return current_time()

    def save(args: dict[str, Any], device: str) -> str:
        note_id = storage.add_note(device, str(args.get("text", "")))
        return f"Zapisano notatkę nr {note_id}."

    def notes(_args: dict[str, Any], device: str) -> str:
        items = storage.list_notes(device)
        return "\n".join(f"- {n['text']}" for n in items) or "Brak notatek."

    return {
        "calculator": (
            CALCULATOR,
            {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Wyrażenie, np. 12*7"}},
                "required": ["expression"],
            },
            calc,
        ),
        "current_time": (CURRENT_TIME, {"type": "object", "properties": {}}, now),
        "list_notes": (LIST_NOTES, {"type": "object", "properties": {}}, notes),
        "save_note": (
            SAVE_NOTE,
            {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Treść notatki"}},
                "required": ["text"],
            },
            save,
        ),
    }
