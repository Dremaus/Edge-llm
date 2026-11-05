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

- [ ] Zablokować ruch wychodzący Ollamy po pobraniu modeli (badanie Cohere: model próbował wysłać dane do chmury)
- [ ] `edge-llm doctor`: Lynis, ssh-audit, kontrola portów, skan plików konfiguracji pod ukryte polecenia (pomysł z ECC)
- [ ] ZAP i trivy w CI
- [ ] Piaskownica podman/gVisor (lub OpenSandbox) przed włączeniem uruchamiania kodu
- [ ] Dziennik wykonanych narzędzi i zapytań sieciowych

## 2. Funkcje

- [ ] Wgrywanie plików z telefonu (wybór pliku w aplikacji)
- [ ] Głos: whisper.cpp z Vulkanem, endpoint transkrypcji, przycisk mikrofonu; później Kokoro-82M do odpowiedzi głosowych
- [ ] OCR skanów PDF (PaddleOCR-VL)
- [ ] Lokalny RAG na własnych dokumentach: osadzenia EmbeddingGemma lub nomic-embed-text, router 0,8B filtruje fragmenty
- [ ] Klasyfikator routera, ewentualnie dostrojony LoRA
- [ ] Generowanie aplikacji krok po kroku z testem po każdym kroku

## 3. Sprzęt i testy (po stronie właściciela)

- [ ] Kupić mini PC (UM870 Slim 32+1TB, 839 €, albo Pro-470 32+1TB, 1249 €); BIOS, LUKS i TPM wg `docs/hardware.md`
- [ ] Tydzień testów: tok/s, polski w Gemmie, obrazy przez mmproj, Qwen3.5 vs Bielik, oceny sędziego i ludzi
- [ ] Test Gemmy E4B z dźwiękiem, Parakeet i EmbeddingGemma
- [ ] Test grafu wiedzy graphify

## 4. Dojrzałość projektu

- [ ] Przypięcie wersji i sum kontrolnych modeli, codzienna synchronizacja przez PR
- [ ] Tryb dewelopera: sprawdzić Aidera, Continue, Cline i OpenCode na adresie zgodnym z OpenAI
- [ ] Role agentów z ograniczonymi uprawnieniami i zasada „gotowe tylko z dowodem"

## Zadania w GitHubie (ręcznie)

- [ ] Usunąć gałąź `deps/requirements-lock` (odtwarza się przy zmianie `pyproject.toml`)
- [ ] Włączyć „Private vulnerability reporting"

## Odrzucone

Frameworki LangChain, AutoGPT, CrewAI i Dify, vLLM, ComfyUI, kontenery Docker z Portainerem i n8n,
modele z licencją badawczą (Arch-Router, Nemotron-Orchestrator), redakcja PDF przez pymupdf (AGPL),
modele „Claude/Fable distill".
