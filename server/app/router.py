"""Router modeli jako graf LangGraph.

Kolejność decyzji (zgodnie z dokumentem projektowym):
1. Reguły bez modelu: obraz -> model główny; kod -> model kodu.
2. Pozostałe zapytania klasyfikuje mały model (jedna etykieta).
3. Przy błędzie lub niejasnej odpowiedzi -> model główny (bezpieczny wybór).

Decyzje są logowane bez treści zapytań, żeby w fazie 5 porównać router
z NeMo Switchyard na tych samych danych.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import Settings
from .llm import LLMClient

log = logging.getLogger("edge.router")

Route = Literal["simple", "chat", "vision", "code", "multistep"]
LABELS: tuple[str, ...] = ("simple", "chat", "code", "multistep")

_CODE_PATTERN = re.compile(
    r"```|\b(python|javascript|typescript|html|css|sql|bash|regex|json|api|"
    r"kod|kodu|code|funkcj\w*|skrypt\w*|script|debug\w*|bug|błąd w kodzie|"
    r"stron\w* (www|internetow\w*)|website|aplikacj\w* (web|mobiln\w*)|app)\b",
    re.IGNORECASE,
)

CLASSIFY_PROMPT = (
    "Classify the user's request. Reply with exactly one word:\n"
    "simple - short factual answer, classification, extraction, translation of a sentence\n"
    "chat - conversation, explanation, writing, advice\n"
    "code - programming, websites, apps, scripts\n"
    "multistep - a task that needs several steps or tools (plan, research, files)\n"
    "Request:\n"
)


class RouterState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    route: Route
    reason: str
    model: str
    # Użytkownik wybrał Bielika do rozmów (ustawienia). Obrazy i kod zostają na innych modelach,
    # bo Bielik nie rozumie obrazów.
    prefer_alt: bool


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )
    return ""


def _has_image(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list) and any(
            part.get("type") in ("image_url", "input_image") for part in content
        ):
            return True
    return False


def parse_label(text: str) -> str | None:
    words = re.findall(r"[a-z]+", text.lower())
    for word in words:
        if word in LABELS:
            return word
    return None


class ModelRouter:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self._settings = settings
        self._llm = llm
        self._graph = self._build()

    # --- węzły grafu ---------------------------------------------------
    def _rules(self, state: RouterState) -> RouterState:
        messages = state["messages"]
        if _has_image(messages):
            return {"route": "vision", "reason": "rule:image"}
        if _CODE_PATTERN.search(_last_user_text(messages)):
            return {"route": "code", "reason": "rule:code"}
        return {}

    async def _classify(self, state: RouterState) -> RouterState:
        text = _last_user_text(state["messages"])[:2000]
        try:
            answer = await self._llm.complete(
                self._settings.router_model,
                [{"role": "user", "content": CLASSIFY_PROMPT + text}],
                temperature=0,
                max_tokens=5,
            )
        except Exception as exc:  # router nie może zablokować odpowiedzi
            log.warning("classifier failed: %s", type(exc).__name__)
            return {"route": "chat", "reason": "fallback:error"}
        label = parse_label(answer)
        if label is None:
            return {"route": "chat", "reason": "fallback:unparsed"}
        return {"route": label, "reason": "classifier"}  # type: ignore[typeddict-item]

    def _pick_model(self, state: RouterState) -> RouterState:
        s = self._settings
        route = state["route"]
        if route == "simple":
            model = s.router_model
        elif route == "code" and s.code_model_enabled:
            model = s.code_model
        elif route in ("chat", "multistep") and state.get("prefer_alt"):
            model = s.alt_model
        else:
            model = s.main_model
        log.info("route=%s reason=%s model=%s", route, state.get("reason"), model)
        return {"model": model}

    # --- budowa grafu --------------------------------------------------
    def _build(self):
        graph = StateGraph(RouterState)
        graph.add_node("rules", self._rules)
        graph.add_node("classify", self._classify)
        graph.add_node("pick_model", self._pick_model)
        graph.add_edge(START, "rules")
        graph.add_conditional_edges(
            "rules",
            lambda s: "pick_model" if s.get("route") else "classify",
            {"pick_model": "pick_model", "classify": "classify"},
        )
        graph.add_edge("classify", "pick_model")
        graph.add_edge("pick_model", END)
        return graph.compile()

    async def route(self, messages: list[dict[str, Any]], prefer_alt: bool = False) -> RouterState:
        return await self._graph.ainvoke({"messages": messages, "prefer_alt": prefer_alt})
