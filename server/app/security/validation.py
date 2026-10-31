"""Walidacja i normalizacja zapytań czatu.

Zasada: przepuszczamy do modelu tylko to, co jawnie dozwolone. Nieznane pola są
odrzucane, parametry przycinane do bezpiecznych zakresów, a obrazy przyjmujemy
wyłącznie jako dane inline (data:), żeby serwer nigdy nie pobierał adresów URL
podanych przez klienta (ochrona przed SSRF).
"""

from __future__ import annotations

import re
from typing import Any

ALLOWED_ROLES = {"system", "user", "assistant"}
MAX_MESSAGES = 200
MAX_TEXT_CHARS = 100_000
MAX_IMAGES = 4
MAX_IMAGE_BASE64_CHARS = 8_000_000  # ok. 6 MB obrazu
MAX_TOKENS_CAP = 4096
_DATA_IMAGE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+$")


class ValidationError(ValueError):
    """Komunikat jest bezpieczny do zwrócenia klientowi (bez szczegółów wewnętrznych)."""


def _clean_part(part: Any, image_count: list[int]) -> dict[str, Any]:
    if not isinstance(part, dict):
        raise ValidationError("Nieprawidłowy fragment wiadomości")
    ptype = part.get("type")
    if ptype == "text":
        text = part.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            raise ValidationError("Nieprawidłowy lub zbyt długi tekst")
        return {"type": "text", "text": text}
    if ptype == "image_url":
        image = part.get("image_url")
        url = image.get("url") if isinstance(image, dict) else image
        if not isinstance(url, str) or len(url) > MAX_IMAGE_BASE64_CHARS:
            raise ValidationError("Nieprawidłowy lub zbyt duży obraz")
        if not _DATA_IMAGE.fullmatch(url):
            raise ValidationError("Obrazy przyjmujemy tylko jako dane base64 (data:image/...)")
        image_count[0] += 1
        if image_count[0] > MAX_IMAGES:
            raise ValidationError(f"Maksymalnie {MAX_IMAGES} obrazy w zapytaniu")
        return {"type": "image_url", "image_url": {"url": url}}
    raise ValidationError("Nieobsługiwany typ treści")


def clean_messages(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError("Brak wiadomości")
    if len(raw) > MAX_MESSAGES:
        raise ValidationError(f"Maksymalnie {MAX_MESSAGES} wiadomości")
    images = [0]
    cleaned: list[dict[str, Any]] = []
    for msg in raw:
        if not isinstance(msg, dict) or msg.get("role") not in ALLOWED_ROLES:
            raise ValidationError("Nieprawidłowa rola wiadomości")
        content = msg.get("content")
        if isinstance(content, str):
            if len(content) > MAX_TEXT_CHARS:
                raise ValidationError("Zbyt długa wiadomość")
            cleaned.append({"role": msg["role"], "content": content})
        elif isinstance(content, list) and content:
            cleaned.append(
                {"role": msg["role"], "content": [_clean_part(p, images) for p in content]}
            )
        else:
            raise ValidationError("Nieprawidłowa treść wiadomości")
    return cleaned


def clean_params(body: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if "temperature" in body:
        params["temperature"] = _num(body["temperature"], 0.0, 2.0)
    if "top_p" in body:
        params["top_p"] = _num(body["top_p"], 0.0, 1.0)
    if "max_tokens" in body:
        params["max_tokens"] = int(_num(body["max_tokens"], 1, MAX_TOKENS_CAP))
    if "stop" in body:
        stop = body["stop"]
        if isinstance(stop, str):
            stop = [stop]
        if not isinstance(stop, list) or len(stop) > 4 or not all(
            isinstance(s, str) and len(s) <= 32 for s in stop
        ):
            raise ValidationError("Nieprawidłowy parametr stop")
        params["stop"] = stop
    return params


def _num(value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("Parametr musi być liczbą")
    return max(lo, min(hi, float(value)))
