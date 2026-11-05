"""Maskowanie sekretów w tekście zapisywanym na urządzeniu (historia, notatki, logi).

Wzorce obejmują typowe formaty kluczy i tokenów. To zabezpieczenie dodatkowe: chroni przed
tym, że hasło wklejone do rozmowy zostanie zapisane i potem znalezione w kopii zapasowej.
"""

from __future__ import annotations

import re

MASK = "[SEKRET]"

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI / Anthropic
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),  # Hugging Face
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*"),
    re.compile(r"\btskey-[A-Za-z0-9\-]{20,}"),  # Tailscale
]
# hasło=..., password: ..., api_key = ... — maskujemy wartość, zostawiamy nazwę pola
_ASSIGNMENT = re.compile(
    r"(?i)\b(pass(?:word|wd)?|has[łl]o|secret|token|api[_-]?key|klucz)\b(\s*[:=]\s*)(?:\"[^\"\n]{3,}\"|'[^'\n]{3,}'|[^\s\"',;]{4,})"
)


def mask_secrets(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)


def mask_content(content):
    """Maskuje tekst w treści wiadomości (napis albo lista części)."""
    if isinstance(content, str):
        return mask_secrets(content)
    if isinstance(content, list):
        return [
            {**p, "text": mask_secrets(p["text"])} if isinstance(p, dict) and isinstance(p.get("text"), str) else p
            for p in content
        ]
    return content
