"""Tryb rozumowania: wyłączone / krótkie / pełne.

Modele rozumujące generują setki–tysiące tokenów „myślenia” przed odpowiedzią, co przy kilkunastu tok/s
na mini PC oznacza minuty. Domyślnie rozumowanie jest wyłączone. Ollama nie ma budżetu tokenów myślenia,
więc „krótkie” to niski wysiłek (`reasoning_effort=low`) i górny limit długości odpowiedzi.
Parametr dostają tylko modele z listy (EDGE_THINKING_MODELS): reszta mogłaby odrzucić zapytanie.
"""

from __future__ import annotations

from typing import Any

LEVELS = ("off", "short", "full")
SHORT_MAX_TOKENS = 1500
EFFORT = {"off": "none", "short": "low", "full": "high"}


def supports_thinking(model: str, prefixes: tuple[str, ...]) -> bool:
    name = model.lower()
    return any(name.startswith(p.lower()) for p in prefixes if p)


def apply_thinking(level: str, model: str, prefixes: tuple[str, ...], params: dict[str, Any]) -> dict[str, Any]:
    """Zwraca kopię parametrów z dodanym wysiłkiem rozumowania (jeśli model go obsługuje)."""
    out = dict(params)
    if level not in LEVELS or not supports_thinking(model, prefixes):
        return out
    out["reasoning_effort"] = EFFORT[level]
    if level == "short":
        out["max_tokens"] = min(int(out.get("max_tokens", SHORT_MAX_TOKENS)), SHORT_MAX_TOKENS)
    return out
