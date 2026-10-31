# Bezpieczeństwo — model zagrożeń i zabezpieczenia

Zasada nadrzędna: **obrona warstwowa i domyślna odmowa**. Każda warstwa zakłada,
że poprzednia mogła zawieść. Rozmowy, dokumenty i zdjęcia użytkownika nie opuszczają
urządzenia, a nic nie jest dostępne z internetu bez uwierzytelnionego, szyfrowanego kanału.

## Co chronimy

| Zasób | Dlaczego |
| --- | --- |
| Rozmowy, zdjęcia, pliki użytkownika | Dane osobowe, często wrażliwe (RODO) |
| Tokeny urządzeń i klucze Tailscale | Dają pełny dostęp do asystenta |
| Integralność systemu, modeli i aktualizacji | Podmieniony model lub kod = przejęte urządzenie |
| Dostępność urządzenia | Asystent ma działać 24/7 |

## Zagrożenia i zabezpieczenia

| Zagrożenie | Zabezpieczenie | Stan |
| --- | --- | --- |
| Atak z internetu na port urządzenia | Brak otwartych portów; serwer i Ollama tylko na 127.0.0.1; dostęp wyłącznie przez Tailscale (WireGuard); zapora UFW domyślnie blokuje ruch przychodzący | ✅ |
| Atak z sieci lokalnej (np. przejęty sprzęt w domu) | Serwer i Ollama niewidoczne w LAN; SSH z limitem prób, opcjonalnie tylko klucze | ✅ |
| Kradzież lub odgadnięcie tokenu | Tokeny 256-bitowe per telefon; na dysku tylko SHA-256; porównanie w stałym czasie; unieważnianie bez restartu; blokada adresu po 5 nieudanych próbach; parowanie jednorazowym kodem QR (50 bitów, 10 min, spalany po 10 błędach) | ✅ |
| Podsłuch transmisji | WireGuard (Tailscale) + HTTPS z certyfikatem przez `tailscale serve` | ✅ |
| Przejęty serwer koordynacyjny Tailscale | Tailnet Lock (podpisy węzłów kluczami użytkownika); docelowo własny relay z E2E | ⚠️ konfiguracja ręczna |
| Nadużycie zasobów (DoS) | Limit zapytań na urządzenie, limit rozmiaru zapytania (25 MB), limit treści i obrazów, limity pamięci i procesów w systemd | ✅ |
| SSRF przez obrazy z URL | Obrazy tylko inline (`data:image/...;base64`); serwer nie pobiera adresów podanych przez klienta | ✅ |
| Wymuszenie dowolnego modelu lub parametrów Ollamy | Lista dozwolonych modeli; nieznane parametry odrzucane; wartości przycinane | ✅ |
| Wyciek danych przez przejęty proces serwera | Piaskownica systemd: brak uprawnień, read-only system, `IPAddressDeny=any` (tylko localhost), filtr wywołań systemowych | ✅ |
| Wyciek przez logi | Logi bez treści rozmów i tokenów; tylko id urządzenia, model, ścieżka routera | ✅ |
| Ujawnienie szczegółów błędów | Ogólne komunikaty błędów; wyłączone `/docs` i `/openapi.json` w produkcji | ✅ |
| Podatna zależność | Dependabot, `pip-audit` w CI, CodeQL, bandit; instalacja z `requirements.lock` z sumami kontrolnymi | ✅ / lock do wygenerowania |
| Wyciek sekretu do repozytorium | gitleaks w CI, `.gitignore` dla `.env` i plików tokenów | ✅ |
| Podmieniony model z Hugging Face | Katalog zatwierdzonych modeli; przypięcie wersji i sum SHA-256 | ⏳ przed wydaniem |
| Prompt injection (dokumenty, strony WWW, narzędzia) | Polityka narzędzi (`app/agent/policy.py`): poziomy ryzyka, domyślna odmowa, sieć i uruchamianie kodu wyłączone domyślnie, potwierdzenie przed zapisem i akcjami nieodwracalnymi, budżet wywołań; treść z zewnątrz w losowo oznaczonych blokach UNTRUSTED, których nie da się zamknąć od środka | ✅ polityka / ⏳ podpięcie do agenta |
| Złośliwy kod uruchamiany przez agenta | Podman bez roota + gVisor: bez sieci, system plików tylko do odczytu, bez uprawnień, limity pamięci/CPU/procesów/czasu (`sandbox_command`) | ✅ definicja / ⏳ wdrożenie |
| Kradzież fizyczna urządzenia | Szyfrowanie dysku (LUKS) z kluczem w TPM/fTPM; Secure Boot | ⏳ |
| Podmieniona aktualizacja | Aktualizacje podpisane kluczem producenta, weryfikowane przed instalacją; możliwość wycofania | ⏳ |
| Kradzież telefonu | Token w Keystore/Keychain, blokada biometryczna aplikacji, zdalne unieważnienie tokenu | ⏳ aplikacja |

## Utwardzenie urządzenia (device/install.sh)

- UFW: domyślnie blokada ruchu przychodzącego, otwarty tylko interfejs Tailscale (i SSH z limitem).
- Automatyczne aktualizacje bezpieczeństwa (`unattended-upgrades`), `fail2ban`.
- Ollama wymuszona na `127.0.0.1:11434`, bez dostępu z przeglądarek (`OLLAMA_ORIGINS`).
- Serwer jako osobny użytkownik systemowy bez powłoki; kod należy do roota (tylko odczyt).
- Pliki z tokenami i konfiguracją: uprawnienia 0600/0640, katalog stanu 0700.
- Opcja `--harden-ssh`: tylko klucze, bez roota (wykonywana tylko, gdy istnieje klucz — bez ryzyka odcięcia).

## Lista kontrolna przed sprzedażą

- [ ] Test penetracyjny wykonany przez zewnętrzną firmę
- [ ] Ocena zgodności z RED (EN 18031-1) i przygotowanie do Cyber Resilience Act (SBOM, proces obsługi podatności, zgłaszanie w 24 h)
- [ ] Wygenerowany i podpisany SBOM każdej wersji
- [ ] Szyfrowanie dysku + Secure Boot na urządzeniu docelowym
- [ ] Podpisane aktualizacje z możliwością wycofania
- [ ] Przypięte sumy kontrolne wszystkich modeli
- [ ] Unikalne dane uwierzytelniające na każdym urządzeniu (bez haseł fabrycznych)
- [ ] Polityka prywatności i ocena skutków dla ochrony danych (RODO)
