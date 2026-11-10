"""Wykonawca narzędzia run_python: kod modelu trafia do kontenera z `sandbox_command`.

Wyłączony, dopóki użytkownik nie ustawi EDGE_EXECUTE_ENABLED=1, a podman i runsc (gVisor) nie są
zainstalowane. Każde uruchomienie dostaje świeży, pusty katalog (bez plików użytkownika), usuwany po
zakończeniu. Wynik jest obcinany; serwer nie wykonuje kodu sam, tylko przez kontener.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .policy import Risk, ToolSpec
from .tools import ToolError, sandbox_command

RUN_PYTHON = ToolSpec("run_python", "Uruchamia kod Python w izolowanej piaskownicy bez sieci i bez dostępu do plików.", Risk.EXECUTE, 5)
MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 4_000
HARD_TIMEOUT_S = 75  # `timeout 60` w kontenerze + zapas na start

Run = Callable[[list[str]], tuple[int, str]]


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=HARD_TIMEOUT_S, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        return 124, "Przekroczono limit czasu."
    except OSError as exc:
        return 127, f"Nie udało się uruchomić piaskownicy: {exc}"
    return p.returncode, p.stdout + p.stderr


def available() -> bool:
    """Piaskownica jest dostępna tylko z podmanem i gVisorem (bez nich kod nigdy się nie uruchomi)."""
    return shutil.which("podman") is not None and shutil.which("runsc") is not None


def build_run_python(workdir: Path, runner: Run = _run) -> tuple[ToolSpec, dict[str, Any], Callable[[dict[str, Any], str], str]]:
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def execute(args: dict[str, Any], _device: str) -> str:
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ToolError("Brak kodu")
        if len(code) > MAX_CODE_CHARS or "\x00" in code:
            raise ToolError("Kod zbyt długi lub nieprawidłowy")
        with tempfile.TemporaryDirectory(dir=workdir, prefix="run-") as tmp:
            Path(tmp).chmod(0o777)  # kontener działa jako nobody (65534)
            script = Path(tmp) / "main.py"
            script.write_text(code, encoding="utf-8")
            script.chmod(0o644)
            status, out = runner(sandbox_command(tmp, "main.py"))
        out = out.strip()
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + "\n[wynik obcięty]"
        if status == 124:
            return "Przerwano: przekroczono limit czasu.\n" + out
        return f"Kod wyjścia {status}.\n{out}" if status else (out or "(brak wyjścia)")

    schema = {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Kod Python 3 (bez sieci, bez plików, do 60 s)"}},
        "required": ["code"],
    }
    return RUN_PYTHON, schema, execute
