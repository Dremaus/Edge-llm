# API serwera urządzenia

Adres: `https://<urządzenie>.<tailnet>.ts.net` (przez `tailscale serve`). Serwer nasłuchuje tylko na `127.0.0.1:8080`.
Wszystkie endpointy poza `/health` i `/v1/pair` wymagają nagłówka `Authorization: Bearer <token>`.

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| GET | `/health` | Czy serwer działa (bez uwierzytelnienia) |
| POST | `/v1/pair` | Wymiana jednorazowego kodu z QR na token telefonu |
| GET | `/v1/models` | Dozwolone modele (`auto` + katalog) |
| POST | `/v1/chat/completions` | Czat w formacie OpenAI, z routerem i strumieniowaniem |
| GET / PATCH | `/v1/settings` | Język, model rozmów, stan kreatora |
| GET | `/v1/devices` | Sparowane telefony (bez tokenów); `current` = ten telefon |
| DELETE | `/v1/devices/me` | Wylogowanie: telefon unieważnia własny token |
| GET | `/v1/status` | Temperatura, pamięć, dysk, załadowane modele |
| GET | `/v1/conversations` | Lista rozmów tego telefonu |
| GET / DELETE | `/v1/conversations/{id}` | Jedna rozmowa / usunięcie |
| DELETE | `/v1/conversations` | Usunięcie wszystkich rozmów tego telefonu |

## Parowanie

```http
POST /v1/pair
{"code": "K7Q2-M9XA-3F", "device_name": "Pixel Witka"}

200 {"device_id": "a1b2c3d4", "token": "edge_..."}
401 kod nieprawidłowy lub wygasły · 429 zbyt wiele prób (blokada 30 min)
```

Kod generuje się na urządzeniu: `python -m app.security.pairing new` (QR zawiera `{"v":1,"url":"https://...","code":"..."}`).

## Czat

```http
POST /v1/chat/completions
{
  "model": "auto",
  "stream": true,
  "save": true,
  "messages": [{"role": "user", "content": "Cześć!"}]
}
```

- `model`: `auto` (router wybiera model) albo nazwa z `/v1/models`.
- `save: true` zakłada nową rozmowę; `conversation_id` dopisuje do istniejącej.
- Obrazy: `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}` — tylko inline, maks. 4.
- Parametry: `temperature` (0–2), `top_p` (0–1), `max_tokens` (≤ 4096), `stop` (≤ 4). Inne pola są ignorowane.

Nagłówki odpowiedzi: `X-Edge-Model` (użyty model), `X-Edge-Route` (`simple`/`chat`/`vision`/`code`/`multistep`), `X-Edge-Conversation` (id rozmowy).

## Ustawienia

```http
PATCH /v1/settings
{"language": "pl", "chat_model": "bielik", "onboarding_done": true}
```

`language`: `pl` | `en`. `chat_model`: `qwen` | `bielik` (Bielik obsługuje rozmowy; zdjęcia zawsze trafiają do Qwen).

## Kody błędów

| Kod | Znaczenie | Co robi aplikacja |
| --- | --- | --- |
| 400 | Nieprawidłowe zapytanie | Pokazuje komunikat |
| 401 | Token nieważny lub unieważniony | Wraca do parowania |
| 404 | Rozmowa nie istnieje lub należy do innego telefonu | Odświeża listę |
| 411 / 413 | Brak `Content-Length` / zapytanie > 25 MB | Zmniejsza zdjęcie |
| 429 | Limit zapytań lub blokada po nieudanych próbach | Ponawia później |
