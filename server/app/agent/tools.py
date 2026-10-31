"""Wbudowane narzędzia agenta (zestaw podstawowy) i piaskownica do uruchamiania kodu."""

from __future__ import annotations

import ast
import datetime as dt
import operator
from zoneinfo import ZoneInfo

from .policy import Risk, ToolSpec

TOOLS = [
    ToolSpec("calculator", "Oblicza wyrażenie arytmetyczne, np. '2*(3+4)/5'.", Risk.READ),
    ToolSpec("current_time", "Podaje aktualną datę i godzinę (strefa Europe/Warsaw).", Risk.READ),
    ToolSpec("web_search", "Wyszukuje w internecie (wymaga zgody w ustawieniach).", Risk.NETWORK),
    ToolSpec("save_note", "Zapisuje notatkę użytkownika na urządzeniu.", Risk.WRITE),
    ToolSpec("run_python", "Uruchamia kod Python w izolowanej piaskownicy bez sieci.", Risk.EXECUTE, 5),
    ToolSpec("delete_files", "Usuwa pliki z katalogu projektu.", Risk.IRREVERSIBLE, 3),
]

# --- kalkulator bez eval() -------------------------------------------
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
MAX_EXPR_LEN = 200
MAX_POW_EXPONENT = 100


class ToolError(ValueError):
    pass


def calculator(expression: str) -> float | int:
    if len(expression) > MAX_EXPR_LEN:
        raise ToolError("Wyrażenie zbyt długie")
    try:
        tree = ast.parse(expression.replace(",", ".").replace("^", "**"), mode="eval")
    except SyntaxError:
        raise ToolError("Nieprawidłowe wyrażenie") from None
    return _eval(tree.body)


def _eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POW_EXPONENT:
            raise ToolError("Zbyt duży wykładnik")
        try:
            return _OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ToolError("Dzielenie przez zero") from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ToolError("Dozwolone są tylko liczby i działania + - * / // % **")


def current_time(tz: str = "Europe/Warsaw") -> str:
    return dt.datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M (%A)")


# --- piaskownica kodu -------------------------------------------------
def sandbox_command(project_dir: str, script: str, image: str = "docker.io/library/python:3.12-slim") -> list[str]:
    """Polecenie uruchomienia kodu w izolowanym kontenerze (podman bez roota + gVisor).

    Kontener: bez sieci, system plików tylko do odczytu (poza /work i /tmp), bez uprawnień,
    z limitem pamięci, CPU, procesów i czasu. Katalog projektu montowany jako /work.
    """
    if "\x00" in project_dir or not project_dir.startswith("/"):
        raise ToolError("Nieprawidłowy katalog projektu")
    if not script or "\x00" in script or script.startswith("-") or "/" in script or ".." in script:
        raise ToolError("Nieprawidłowa nazwa skryptu")
    return [
        "podman", "run", "--rm",
        "--runtime=runsc",            # gVisor: osobne jądro w przestrzeni użytkownika
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:rw,size=64m,noexec",
        f"--volume={project_dir}:/work:rw,Z",
        "--workdir=/work",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=128",
        "--ulimit=nofile=256:256",
        "--stop-timeout=5",
        image,
        "timeout", "60", "python", "-I", script,
    ]
