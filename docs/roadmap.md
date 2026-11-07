# Plan prac — pomysły do wdrożenia

Stan na 5.11.2026. Lista zebrana z analiz repozytoriów, artykułów i modeli; uzasadnienia odrzuceń
są w `docs/decisions.md`. Kolejność w sekcjach to proponowany priorytet.

## Wdrożone

- [x] Platforma AMD Ryzen AI: instalator, Vulkan, status GPU, `docs/hardware.md`
- [x] Modele według RAM: Gemma 26B (główny), Ornith 35B (kod), Qwen 4B poniżej 24 GB; wybór zapisywany w konfiguracji
- [x] Pamięć agenta: wyszukiwanie FTS5, narzędzie `search_notes`, `/v1/memory`, ekran „Co pamiętam”
- [x] Maskowanie sekretów w historii i notatkach
- [x] Test złośliwego dokumentu (posłuszny model nie wykona niebezpiecznych akcji)
- [x] Ocena modelem-sędzią w `eval/` (`tools/judge.py`)
- [x] Narzędzia do dokumentów: PDF, XLSX, CSV, ZIP, usuwanie za zgodą (`/v1/files`)

## 1. Bezpieczeństwo (najpierw)

- [x] Zablokować ruch wychodzący Ollamy po pobraniu modeli (badanie Cohere: model próbował wysłać dane do chmury); aktualizacja przez `device/pull-models.sh`
- [x] `edge-llm doctor` (`sudo edge-llm-doctor`): usługi, porty, zapora, SSH, uprawnienia, blokada Ollamy, LUKS, TPM, Secure Boot, poprawki
- [ ] Doctor: uruchamianie Lynis i ssh-audit oraz skan plików konfiguracji pod ukryte polecenia (pomysł z ECC)
- [ ] ZAP i trivy w CI
- [ ] Piaskownica podman/gVisor (lub OpenSandbox) przed włączeniem uruchamiania kodu
- [ ] Dziennik wykonanych narzędzi i zapytań sieciowych

## 2. Funkcje

- [x] Wgrywanie plików z telefonu (ekran „Moje pliki” w aplikacji)
- [ ] Głos: serwer i instalator gotowe (whisper.cpp v1.9.5 z Vulkanem, `/v1/audio/transcriptions`); brakuje przycisku mikrofonu w aplikacji i przypięcia sumy kontrolnej modelu; później Kokoro-82M do odpowiedzi głosowych
- [ ] OCR skanów PDF (PaddleOCR-VL)
- [ ] NER/PII z obsługą polskiego (GLiNER wielojęzyczny, polskie modele NER) obok maskowania sekretów; modele z innych źródeł bez polskiego odpadają
- [ ] Lokalny RAG na własnych dokumentach: osadzenia EmbeddingGemma lub nomic-embed-text, router 0,8B filtruje fragmenty
- [ ] Klasyfikator routera, ewentualnie dostrojony LoRA (uczenie na osobnym komputerze, np. LlamaFactory, Apache 2.0)
- [ ] Kompresja wyników narzędzi i historii przed wysłaniem do modelu: sprawdzić `headroom` (Apache 2.0, działa lokalnie) albo prostą własną deduplikację logów i JSON — krótszy prompt to szybszy start odpowiedzi
- [ ] Generowanie aplikacji krok po kroku z testem po każdym kroku
- [ ] Kontrola wygenerowanych stron w przeglądarce bez okna: kontrast, fokus, układ na telefonie (pomysł z `hallmark`)
- [ ] Styl odpowiedzi w ustawieniach: normalny / krótki / prosty (pomysły z `i-have-adhd` i `caveman`). Krótki styl skraca też czas generowania na wolnym sprzęcie; sprawdzić utratę jakości oceną sędziego
- [ ] Wyszukiwanie w historii rozmów (FTS5), jak w `hermes-agent`
- [ ] Zadania cykliczne w języku naturalnym (np. dzienny raport) z zatwierdzeniem harmonogramu przez użytkownika; powiadomienia na telefon (pomysł z `hermes-agent`)
- [ ] Strojenie promptów routera i reguł agenta na zbiorze `eval/` z bramką walidacji; wynik jako PR do przeglądu, nigdy samoistna zmiana (pomysł z Microsoft SkillOpt i Google Harness²: propozycje zmian testowane na tym samym zadaniu; wymaga silnego modelu-edytora, więc tylko poza urządzeniem)

## 3. Sprzęt i testy (po stronie właściciela)

- [ ] Kupić mini PC (UM870 Slim 32+1TB, 839 €, albo Pro-470 32+1TB, 1249 €); BIOS, LUKS i TPM wg `docs/hardware.md`
- [ ] Tydzień testów: tok/s, polski w Gemmie, obrazy przez mmproj, Qwen3.5 vs Bielik, oceny sędziego i ludzi
- [ ] Test Gemmy E4B z dźwiękiem, Parakeet i EmbeddingGemma
- [ ] Test grafu wiedzy graphify
- [ ] Prawdziwe zrzuty i testy interfejsu aplikacji na emulatorze (`google/artemis`, Apache 2.0) — sprawdzić, czy działa z lokalnym modelem

## 4. Dojrzałość projektu

- [ ] Przypięcie wersji i sum kontrolnych modeli, codzienna synchronizacja przez PR
- [ ] Tryb dewelopera: sprawdzić Aidera, Continue, Cline i OpenCode na adresie zgodnym z OpenAI
- [ ] Przegląd kodu lokalnym modelem (`alibaba/open-code-review`, Apache 2.0) — sprawdzić, czy przyjmie adres zgodny z OpenAI
- [ ] Role agentów z ograniczonymi uprawnieniami i zasada „gotowe tylko z dowodem"

## Zadania w GitHubie (ręcznie)

- [ ] Usunąć gałąź `deps/requirements-lock` (odtwarza się przy zmianie `pyproject.toml`)
- [ ] Włączyć „Private vulnerability reporting"

## Odrzucone

Frameworki LangChain, AutoGPT, CrewAI i Dify, vLLM, ComfyUI, kontenery Docker z Portainerem i n8n,
modele z licencją badawczą (Arch-Router, Nemotron-Orchestrator), redakcja PDF przez pymupdf (AGPL),
modele „Claude/Fable distill", repozytoria z samoaktualizacją i zdalnymi ogłoszeniami (`dsh-our-free-model`),
agregatory darmowych API chmurowych (`freellmapi`), agent z dostępem do prawdziwego, zalogowanego Chrome (`browser-harness`), n8n, Firecrawl, Open WebUI, Dify i WebUI Stable Diffusion (licencje), Deep-Live-Cam (podmiana twarzy), narzędzia AGPL (VoiceStudio, OpenMontage, worldmonitor), Gemini CLI (tylko Google Cloud),
zestaw ofensywny `reverse-skill`, wycieki promptów komercyjnych narzędzi (`system-prompts-and-models-of-ai-tools`, GPL), agenci z autonomicznym tworzeniem własnych umiejętności (`hermes-agent`), asystent z kanałami komunikatorów i instalatorem `curl | bash` (`openclaw`), Supabase, narzędzia do usuwania znaczników pochodzenia AI, `gpu-unlock` (NVIDIA).
