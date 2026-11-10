from __future__ import annotations

from app.agent.builtin import SPECS, build_registry
from app.agent.policy import PolicyConfig, ToolPolicy
from app.agent.runner import AgentRunner
from app.storage import AUDIT_KEEP_PER_DEVICE, Storage
from test_runner import ScriptedLLM, call, run, user


def setup(replies):
    storage = Storage()
    r = AgentRunner(ScriptedLLM(replies), ToolPolicy(SPECS, PolicyConfig()), build_registry(storage), audit=storage.add_audit)
    return r, storage


def test_allow_deny_confirm_reject_and_confirmed_are_logged():
    r, storage = setup([call("calculator", {"expression": "2+2"}), call("run_python", {"code": "1"}, "c2"),
                        call("save_note", {"text": "abc"}, "c3"), {"content": "ok"}])
    first = run(r.run("p1", "m", user("x")))
    assert first.pending is not None
    run(r.confirm("p1", first.pending.id, True))
    log = list(reversed(storage.list_audit("p1")))
    assert [(e["tool"], e["decision"]) for e in log] == [
        ("calculator", "allow"), ("run_python", "deny"), ("save_note", "confirm_requested"), ("save_note", "confirmed")]
    assert log[0]["ok"] is True and log[0]["ms"] is not None
    assert log[1]["reason"] and log[1]["ok"] is None


def test_rejected_is_logged():
    r, storage = setup([call("save_note", {"text": "abc"}), {"content": "ok"}])
    first = run(r.run("p1", "m", user("x")))
    run(r.confirm("p1", first.pending.id, False))
    assert storage.list_audit("p1")[0]["decision"] == "rejected"


def test_args_are_masked_truncated_and_isolated_per_device():
    storage = Storage()
    storage.add_audit({"device_id": "a", "tool": "save_note", "decision": "allow",
                       "args": {"text": "klucz sk-" + "A" * 40 + " " + "x" * 500}})
    entry = storage.list_audit("a")[0]
    assert "AAAA" not in entry["args"] and len(entry["args"]) <= 200
    assert storage.list_audit("b") == []


def test_retention_cap():
    storage = Storage()
    for i in range(AUDIT_KEEP_PER_DEVICE + 5):
        storage.add_audit({"device_id": "a", "tool": "t", "decision": "allow"})
    assert len(storage.list_audit("a", 500)) == 500
    assert storage._db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == AUDIT_KEEP_PER_DEVICE


def test_audit_failure_does_not_stop_agent():
    def boom(_e):
        raise RuntimeError("dysk pełny")
    storage = Storage()
    r = AgentRunner(ScriptedLLM([call("calculator", {"expression": "1+1"}), {"content": "2"}]),
                    ToolPolicy(SPECS, PolicyConfig()), build_registry(storage), audit=boom)
    assert run(r.run("p", "m", user("x"))).content == "2"
