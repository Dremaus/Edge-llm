from __future__ import annotations

import pytest

from app.agent import sandbox
from app.agent.builtin import SPECS, build_registry
from app.agent.policy import Decision, PolicyConfig, TaskBudget, ToolPolicy
from app.agent.tools import ToolError
from app.storage import Storage


def make(tmp_path, runner):
    store = Storage(str(tmp_path / "e.db"), "pl")
    reg = build_registry(store, None, tmp_path / "sb", runner)
    return reg["run_python"][2]


def test_run_python_builds_locked_command_and_cleans_up(tmp_path):
    seen = {}

    def runner(cmd):
        seen["cmd"] = cmd
        work = next(a for a in cmd if a.startswith("--volume=")).split("=", 1)[1].split(":")[0]
        from pathlib import Path
        seen["code"] = (Path(work) / "main.py").read_text()
        seen["dir"] = work
        return 0, "42\n"

    fn = make(tmp_path, runner)
    assert fn({"code": "print(42)"}, "dev") == "42"
    assert "--network=none" in seen["cmd"] and "--runtime=runsc" in seen["cmd"]
    assert seen["code"] == "print(42)"
    from pathlib import Path
    assert not Path(seen["dir"]).exists()  # katalog usunięty po uruchomieniu


def test_run_python_output_and_errors(tmp_path):
    assert "Kod wyjścia 1" in make(tmp_path, lambda c: (1, "Traceback"))({"code": "1/0"}, "d")
    assert "limit czasu" in make(tmp_path, lambda c: (124, ""))({"code": "while 1: pass"}, "d")
    long = make(tmp_path, lambda c: (0, "x" * 10_000))({"code": "print(1)"}, "d")
    assert long.endswith("[wynik obcięty]") and len(long) < 4100


@pytest.mark.parametrize("code", [None, "", "   ", "a\x00b", "x" * 20_001, 5])
def test_run_python_rejects_bad_code(tmp_path, code):
    with pytest.raises(ToolError):
        make(tmp_path, lambda c: (0, ""))({"code": code}, "d")


def test_not_registered_without_sandbox(tmp_path):
    store = Storage(str(tmp_path / "e.db"), "pl")
    assert "run_python" not in build_registry(store)


def test_policy_denies_execute_by_default_and_confirms_when_enabled():
    assert ToolPolicy(SPECS, PolicyConfig()).decide("run_python", TaskBudget())[0] == Decision.DENY
    assert ToolPolicy(SPECS, PolicyConfig(execute_enabled=True)).decide("run_python", TaskBudget())[0] == Decision.CONFIRM


def test_available_needs_both_tools(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda n: "/x" if n == "podman" else None)
    assert sandbox.available() is False
    monkeypatch.setattr(sandbox.shutil, "which", lambda n: "/x")
    assert sandbox.available() is True
