"""Pętla agenta: model -> wywołania narzędzi -> polityka -> wynik -> model ...

- Narzędzia trafiają do modelu w formacie OpenAI `tools` (Ollama obsługuje function calling).
- Każde wywołanie przechodzi przez ToolPolicy:
    ALLOW   -> wykonujemy, wynik wraca do modelu jako treść niezaufana,
    CONFIRM -> zatrzymujemy pętlę i zwracamy aplikacji prośbę o zgodę (pending action),
    DENY    -> model dostaje informację o odmowie i kontynuuje bez narzędzia.
- Zgody trzymamy w pamięci przez 10 minut, przypisane do konkretnego telefonu.
- Twardy limit kroków chroni przed pętlą.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .policy import AGENT_SYSTEM_RULES, Decision, TaskBudget, ToolPolicy, ToolSpec, wrap_untrusted

MAX_STEPS = 8
PENDING_TTL_S = 600
MAX_ARGS_CHARS = 2000
MAX_RESULT_CHARS = 8000

# Wykonawca dostaje argumenty i id telefonu (np. notatki są osobne dla każdego telefonu).
Executor = Callable[[dict[str, Any], str], Awaitable[str] | str]


class AgentLLM(Protocol):
    async def complete_message(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


@dataclass
class PendingAction:
    id: str
    device_id: str
    tool: str
    arguments: dict[str, Any]
    call_id: str
    messages: list[dict[str, Any]]
    budget: TaskBudget
    model: str
    created: float = field(default_factory=time.time)


@dataclass
class AgentResult:
    content: str | None = None
    pending: PendingAction | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"steps": self.steps}
        if self.pending:
            out["status"] = "needs_confirmation"
            out["action"] = {
                "id": self.pending.id,
                "tool": self.pending.tool,
                "arguments": self.pending.arguments,
            }
        else:
            out["status"] = "done"
            out["content"] = self.content or ""
        return out


def tool_schema(spec: ToolSpec, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": spec.name, "description": spec.description, "parameters": params},
    }


class AgentRunner:
    def __init__(
        self,
        llm: AgentLLM,
        policy: ToolPolicy,
        tools: dict[str, tuple[ToolSpec, dict[str, Any], Executor]],
        audit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._audit = audit
        self._llm = llm
        self._policy = policy
        self._tools = tools
        self._pending: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def _available_schemas(self) -> list[dict[str, Any]]:
        # Modelowi pokazujemy tylko narzędzia, których polityka od razu nie odrzuca.
        schemas = []
        for name, (spec, params, _) in self._tools.items():
            decision, _ = self._policy.decide(name, TaskBudget())
            if decision != Decision.DENY:
                schemas.append(tool_schema(spec, params))
        return schemas

    async def run(self, device_id: str, model: str, messages: list[dict[str, Any]]) -> AgentResult:
        msgs = [{"role": "system", "content": AGENT_SYSTEM_RULES}, *messages]
        return await self._loop(device_id, model, msgs, TaskBudget(), [])

    async def confirm(self, device_id: str, action_id: str, approve: bool) -> AgentResult:
        with self._lock:
            self._expire()
            pending = self._pending.get(action_id)
            # Najpierw sprawdzamy telefon — próba z innego telefonu nie może zużyć cudzej zgody.
            if pending is None or pending.device_id != device_id:
                raise KeyError(action_id)
            del self._pending[action_id]
        msgs = pending.messages
        if approve:
            result = await self._timed(pending.tool, pending.arguments, device_id, "confirmed")
            ToolPolicy.record_call(pending.tool, pending.budget)
            step = {"tool": pending.tool, "decision": "confirmed"}
        else:
            self._log(device_id, pending.tool, "rejected", args=pending.arguments)
            result = "Użytkownik nie zgodził się na tę akcję. Nie ponawiaj jej."
            step = {"tool": pending.tool, "decision": "rejected"}
        msgs.append({"role": "tool", "tool_call_id": pending.call_id, "content": result})
        return await self._loop(device_id, pending.model, msgs, pending.budget, [step])

    def _log(self, device_id: str, tool: str, decision: str, reason: str = "", args: Any = None,
             result: str | None = None, ms: int | None = None) -> None:
        """Dziennik audytu: kto, co, jaka decyzja, czy się udało. Błąd zapisu nie może zatrzymać agenta."""
        if self._audit is None:
            return
        entry = {
            "device_id": device_id, "tool": tool, "decision": decision, "reason": reason,
            "args": args, "ok": None if result is None else not result.startswith("Błąd narzędzia:"), "ms": ms,
        }
        try:
            self._audit(entry)
        except Exception:  # noqa: BLE001
            pass

    async def _timed(self, name: str, args: dict[str, Any], device_id: str, decision: str) -> str:
        start = time.monotonic()
        result = await self._execute(name, args, device_id)
        self._log(device_id, name, decision, args=args, result=result, ms=int((time.monotonic() - start) * 1000))
        return result

    def _expire(self) -> None:
        now = time.time()
        for key in [k for k, p in self._pending.items() if now - p.created > PENDING_TTL_S]:
            del self._pending[key]

    async def _execute(self, name: str, args: dict[str, Any], device_id: str) -> str:
        _, _, executor = self._tools[name]
        try:
            out = executor(args, device_id)
            if not isinstance(out, str):
                out = await out
        except Exception as exc:  # błąd narzędzia nie przerywa rozmowy
            return f"Błąd narzędzia: {type(exc).__name__}: {str(exc)[:200]}"
        return wrap_untrusted(str(out)[:MAX_RESULT_CHARS], f"tool:{name}")

    async def _loop(
        self,
        device_id: str,
        model: str,
        msgs: list[dict[str, Any]],
        budget: TaskBudget,
        steps: list[dict[str, Any]],
    ) -> AgentResult:
        schemas = self._available_schemas()
        for _ in range(MAX_STEPS):
            reply = await self._llm.complete_message(model, msgs, schemas)
            calls = reply.get("tool_calls") or []
            assistant: dict[str, Any] = {"role": "assistant", "content": reply.get("content") or ""}
            if calls:
                assistant["tool_calls"] = calls
            msgs.append(assistant)
            if not calls:
                return AgentResult(content=reply.get("content") or "", steps=steps)
            for index, call in enumerate(calls):
                fn = call.get("function", {})
                name = str(fn.get("name", ""))
                call_id = str(call.get("id") or secrets.token_hex(4))
                args = _parse_args(fn.get("arguments"))
                if args is None:
                    decision, reason = Decision.DENY, "nieprawidłowe argumenty"
                elif name not in self._tools:  # znane polityce, ale bez wykonawcy = nie istnieje
                    decision, reason = Decision.DENY, "nieznane narzędzie"
                else:
                    decision, reason = self._policy.decide(name, budget)
                steps.append({"tool": name, "decision": decision.value})
                if decision == Decision.ALLOW:
                    ToolPolicy.record_call(name, budget)
                    result = await self._timed(name, args or {}, device_id, "allow")
                elif decision == Decision.CONFIRM:
                    pending = PendingAction(
                        id=secrets.token_urlsafe(12),
                        device_id=device_id,
                        tool=name,
                        arguments=args or {},
                        call_id=call_id,
                        messages=msgs,
                        budget=budget,
                        model=model,
                    )
                    # Pozostałe wywołania z tej tury pomijamy — model może je powtórzyć po decyzji.
                    for later in calls[index + 1 :]:
                        msgs.append({
                            "role": "tool",
                            "tool_call_id": str(later.get("id") or ""),
                            "content": "Pominięto: czeka na zgodę użytkownika na wcześniejszą akcję.",
                        })
                    self._log(device_id, name, "confirm_requested", reason, args)
                    with self._lock:
                        self._expire()
                        self._pending[pending.id] = pending
                    return AgentResult(pending=pending, steps=steps)
                else:
                    self._log(device_id, name, "deny", reason, args)
                    result = f"Odmowa: {reason}."
                msgs.append({"role": "tool", "tool_call_id": call_id, "content": result})
        return AgentResult(content="Przerwano: zadanie wymagało zbyt wielu kroków.", steps=steps)


def _parse_args(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        args = raw
    elif isinstance(raw, str):
        if len(raw) > MAX_ARGS_CHARS:
            return None
        try:
            args = json.loads(raw or "{}")
        except ValueError:
            return None
    else:
        return None if raw is not None else {}
    return args if isinstance(args, dict) else None
