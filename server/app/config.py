"""Konfiguracja serwera z zmiennych środowiskowych."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    # Token dostępu dla sparowanych telefonów (MVP: jeden wspólny token).
    api_token: str = field(default_factory=lambda: os.environ.get("EDGE_API_TOKEN", ""))
    # Adres API Ollamy zgodnego z OpenAI.
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("EDGE_OLLAMA_URL", "http://localhost:11434/v1")
    )
    # Język wybrany przy pierwszym uruchomieniu: "pl" lub "en".
    language: str = field(default_factory=lambda: os.environ.get("EDGE_LANGUAGE", "pl"))
    # Modele według roli (zgodne z device/models.yaml).
    router_model: str = field(
        default_factory=lambda: os.environ.get("EDGE_ROUTER_MODEL", "qwen3.5:0.8b")
    )
    main_model: str = field(default_factory=lambda: os.environ.get("EDGE_MAIN_MODEL", "qwen3.5:4b"))
    code_model: str = field(
        default_factory=lambda: os.environ.get("EDGE_CODE_MODEL", "granite4.2:8b")
    )
    # Gdy brak modelu kodu (urządzenie 8 GB), kod obsługuje model główny.
    code_model_enabled: bool = field(
        default_factory=lambda: os.environ.get("EDGE_CODE_MODEL_ENABLED", "0") == "1"
    )
    request_timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("EDGE_TIMEOUT_S", "300"))
    )


SYSTEM_PROMPTS = {
    "pl": "Jesteś prywatnym asystentem działającym lokalnie na urządzeniu użytkownika. "
    "Odpowiadaj po polsku, chyba że użytkownik pisze w innym języku.",
    "en": "You are a private assistant running locally on the user's device. "
    "Answer in English unless the user writes in another language.",
}


def get_settings() -> Settings:
    return Settings()
