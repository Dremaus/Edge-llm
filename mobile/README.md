# Aplikacja mobilna (Flutter)

Aplikacja na Androida i iOS. Projekt Flutter zakładamy poleceniem:

```bash
cd mobile
flutter create --org pl.edgellm --project-name edge_llm_app .
```

## Zakres MVP

- [ ] Kreator pierwszego uruchomienia: wybór języka (Polski / English), parowanie kodem QR, wybór modelu (Qwen3.5-4B domyślnie; przy polskim podpowiedź „Użyj Bielika”)
- [ ] Czat ze strumieniowaniem odpowiedzi (SSE z `/v1/chat/completions`, model `auto`)
- [ ] Lista rozmów i historia
- [ ] Wysyłanie zdjęć do modelu (treść `image_url`)
- [ ] Status urządzenia: online/offline, temperatura, pamięć
- [ ] Działanie w sieci domowej i poza nią (Tailscale)

## Kontrakt z serwerem

- Uwierzytelnianie: nagłówek `Authorization: Bearer <token>`.
- Czat: `POST /v1/chat/completions` (format OpenAI), `"model": "auto"`, `"stream": true`.
- Serwer zwraca wybrany model i ścieżkę w nagłówkach `X-Edge-Model` i `X-Edge-Route`.
