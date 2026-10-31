# edge-llm

Prywatny asystent AI działający w całości na małym urządzeniu w domu lub firmie, z dostępem z aplikacji na smartfonie — także spoza sieci lokalnej. Dane nie opuszczają urządzenia.

Pełny plan projektu (cele, sprzęt, modele, architektura, koszty, roadmapa) jest w dokumencie projektowym: https://claude.ai/artifact/WgErVzXtiF86DtRptPqoMX

## Struktura repozytorium

| Katalog | Zawartość |
| --- | --- |
| `server/` | Serwer API (FastAPI) z orkiestratorem LangGraph: router modeli, API zgodne z OpenAI, strumieniowanie SSE, uwierzytelnianie |
| `device/` | Instalacja urządzenia: skrypt instalacyjny, katalog modeli z Hugging Face, usługa systemd |
| `mobile/` | Aplikacja na Androida i iOS (Flutter) — do założenia |
| `docs/` | Dokumentacja techniczna i decyzje architektoniczne |

## Założenia (stan na 31.10.2026)

- **Modele:** gotowe, otwarte wagi z Hugging Face w formacie GGUF, uruchamiane przez Ollamę.
  - Model główny: Qwen3.5-4B (polski i angielski, obrazy).
  - Router i proste czynności: Qwen3.5-0.8B.
  - Model kodu: Granite 4.2 8B (faza 5).
  - Bielik-4.5B-v3.0-Instruct: preinstalowany, do włączenia w ustawieniach.
- **Orkiestracja:** LangGraph; router w MVP to reguły + klasyfikacja małym modelem.
- **Zdalny dostęp:** Tailscale na start, później własny serwer przekaźnikowy.
- **Sprzęt:** prototyp na Jetson Orin Nano Super 8 GB; równolegle testujemy mini PC z Ryzen 7 i 32 GB jako tańszą platformę docelową.

## Szybki start (serwer, tryb deweloperski)

Wymagania: Python 3.11+, działająca Ollama (`http://localhost:11434`).

```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export EDGE_TOKENS_FILE="$PWD/.tokens.json"
python -m app.security.tokens add "Mój laptop"   # token pokazywany tylko raz
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Test:

```bash
curl -N http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","stream":true,"messages":[{"role":"user","content":"Cześć! Kim jesteś?"}]}'
```

Model `auto` włącza router: serwer sam wybiera model do zadania. Można też podać nazwę konkretnego modelu z katalogu.

Testy: `cd server && pytest`.

## Instalacja na urządzeniu

```bash
sudo device/install.sh
```

Skrypt instaluje Ollamę, pobiera modele z `device/models.yaml` i uruchamia serwer jako usługę systemd. Szczegóły w `device/README.md`.

## Bezpieczeństwo

Urządzenie nie ma żadnych portów dostępnych z internetu ani z sieci lokalnej: serwer i Ollama nasłuchują tylko na `127.0.0.1`, a telefon łączy się przez szyfrowany tunel Tailscale. Każdy telefon ma własny, unieważnialny token. Model zagrożeń i pełna lista zabezpieczeń: [docs/security.md](docs/security.md). Zgłaszanie podatności: [SECURITY.md](SECURITY.md).

## Licencja

[Apache License 2.0](LICENSE).
