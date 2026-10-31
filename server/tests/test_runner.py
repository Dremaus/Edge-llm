from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.agent.builtin import SPECS, build_registry
from app.agent.policy import PolicyConfig, ToolPolicy
from app.agent.runner import MAX_STEPS, AgentRunner
from app.storage import Storage


class ScriptedLLM:
    """Zwraca kolejne odpowiedzi ze scenariusza; zapisuje, co dostał."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[str]] = []

    async def complete_message(self, model, messages, tools):
        self.calls.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in tools])
        return self.replies.pop(0) if self.replies else {"content": "koniec"}


def call(name: str, args: dict[str, Any] | str, cid: str = "c1") -> dict[str, Any]:
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {"tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": arguments}}]}


def runner(replies, **cfg):
    storage = Storage()
    llm = ScriptedLLM(replies)
    r = AgentRunner(llm, ToolPolicy(SPECS, PolicyConfig(**cfg)), build_registry(storage))
    return r, llm, storage


def run(coro):
    return asyncio.run(coro)


def user(text):
    return [{"role": "user", "content": text}]


def test_read_tool_runs_and_result_is_marked_untrusted():
    r, llm, _ = runner([call("calculator", {"expression": "12*7"}), {"content": "Wynik to 84."}])
    out = run(r.run("phone", "m", user("ile to 12*7?")))
    assert out.to_dict() == {"steps": [{"tool": "calculator", "decision": "allow"}], "status": "done", "content": "Wynik to 84."}
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and "84" in tool_msg["content"] and "UNTRUSTED" in tool_msg["content"]
    assert llm.calls[0][0]["role"] == "system"  # zasady agenta zawsze na początku


def test_write_tool_waits_for_confirmation_then_runs():
    r, _, storage = runner([call("save_note", {"text": "kupić mleko"}), {"content": "Zapisane."}])
    first = run(r.run("phone", "m", user("zanotuj: kupić mleko")))
    data = first.to_dict()
    assert data["status"] == "needs_confirmation"
    assert data["action"]["tool"] == "save_note"
    assert storage.list_notes("phone") == []  # nic się nie stało przed zgodą
    done = run(r.confirm("phone", data["action"]["id"], approve=True))
    assert done.content == "Zapisane."
    assert [n["text"] for n in storage.list_notes("phone")] == ["kupić mleko"]


def test_rejected_action_is_not_executed():
    r, llm, storage = runner([call("save_note", {"text": "x"}), {"content": "Rozumiem, nie zapisuję."}])
    pending = run(r.run("phone", "m", user("zanotuj x"))).pending
    out = run(r.confirm("phone", pending.id, approve=False))
    assert storage.list_notes("phone") == []
    assert "nie zgodził" in llm.calls[-1][-1]["content"]
    assert out.steps[-1]["decision"] == "rejected"


def test_confirmation_cannot_be_used_by_another_phone_or_twice():
    r, _, _ = runner([call("save_note", {"text": "x"})])
    pending = run(r.run("phone-a", "m", user("zanotuj"))).pending
    with pytest.raises(KeyError):
        run(r.confirm("phone-b", pending.id, approve=True))
    # Próba z cudzego telefonu nie zużyła zgody — właściciel nadal może zdecydować, ale tylko raz.
    run(r.confirm("phone-a", pending.id, approve=False))
    with pytest.raises(KeyError):
        run(r.confirm("phone-a", pending.id, approve=True))


def test_unknown_tool_and_bad_arguments_are_denied():
    r, llm, _ = runner([call("delete_everything", {}), call("calculator", "{zły json", "c2"), {"content": "ok"}])
    out = run(r.run("phone", "m", user("rób")))
    assert [s["decision"] for s in out.steps] == ["deny", "deny"]
    assert "Odmowa" in llm.calls[1][-1]["content"]


def test_tools_hidden_from_model_when_policy_denies():
    r, llm, _ = runner([{"content": "hej"}])
    run(r.run("phone", "m", user("hej")))
    assert set(llm.tools_seen[0]) == {"calculator", "current_time", "list_notes", "save_note"}


def test_step_limit_stops_loops():
    replies = [call("current_time", {}, f"c{i}") for i in range(MAX_STEPS + 2)]
    r, _, _ = runner(replies, max_tool_calls_per_task=100)
    out = run(r.run("phone", "m", user("pętla")))
    assert out.content.startswith("Przerwano")


def test_tool_errors_do_not_crash_the_run():
    r, llm, _ = runner([call("calculator", {"expression": "1/0"}), {"content": "Nie da się dzielić przez zero."}])
    out = run(r.run("phone", "m", user("1/0")))
    assert out.content.startswith("Nie da się")
    assert "Błąd narzędzia" in llm.calls[1][-1]["content"]


def test_notes_are_isolated_per_phone():
    r, _, storage = runner([call("list_notes", {}), {"content": "brak"}])
    storage.add_note("phone-a", "tajne a")
    run(r.run("phone-b", "m", user("pokaż notatki")))
    assert storage.list_notes("phone-b") == []
