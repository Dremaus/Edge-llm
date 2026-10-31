# Sprzęt — platforma AMD Ryzen AI

Decyzja z 31.10.2026: urządzenie docelowe to mini PC z procesorem **AMD Ryzen AI** (seria 300/400)
zamiast Jetsona. Powód: niższy koszt przy dwa–cztery razy większej pamięci, standardowy x86 z Ubuntu,
a do tego TPM i Secure Boot do szyfrowania dysku.

## Zalecana konfiguracja

| Element | Minimum | Zalecane | Uwagi |
| --- | --- | --- | --- |
| Procesor | Ryzen 7 H 255 (Radeon 780M, bez NPU) / Ryzen AI 7 350 | Ryzen AI 9 HX 370 / HX 470 | Prędkość generowania zależy głównie od pamięci, nie od rdzeni grafiki |
| RAM | 16 GB DDR5-5600, dwa moduły | 32 GB DDR5-5600, dwa moduły | **Musi być dwukanałowo** (2 kości) — jedna kość = połowa prędkości |
| Dysk | 512 GB NVMe | 1 TB NVMe | Modele zajmują ok. 15 GB; reszta na dane i kopie |
| System | Ubuntu 24.04 LTS | jw., kernel HWE 6.14+ | Kernel 7.0+ potrzebny tylko do NPU |

Z 32 GB mieszczą się jednocześnie router, model główny, Bielik i model kodu. Przy 16 GB model kodu
nie jest pobierany (instalator decyduje automatycznie).

Wersje z pamięcią LPDDR5X-7500 (lutowaną) są o ok. 1/3 szybsze w generowaniu, ale nie da się ich
rozbudować. Unikamy modułów 24 Gbit w ASUS PN54 — według użytkowników nie działają.

### Oferty Minisforum (minisforumpc.eu, 31.10.2026)

minisforumpc.eu to oficjalny sklep UE: store.minisforum.de (wymieniony na minisforum.com) przekierowuje
na tę domenę (sprawdzone 31.10.2026). Mimo to płacić z ochroną kupującego (PayPal, karta).

| Model | Procesor | Konfiguracja | Cena |
| --- | --- | --- | --- |
| AI X1 Mini PC | Ryzen 7 H 255 (8 rdzeni, Radeon 780M, bez NPU) | 32 GB + 512 GB | 859 € |
| AI X1 Mini PC | Ryzen 7 H 255 | 32 GB + 1 TB | 939 € |
| AI X1 Mini PC | Ryzen AI 9 HX 370 | barebone | 619 € |
| AI X1 Mini PC | Ryzen AI 9 HX 370 | 32 GB + 1 TB | 1199 € |
| AI X1 Mini PC | Ryzen AI 9 HX 470 | 32 GB + 1 TB | 1359 € (drożej niż Pro-470) |
| UM773 Lite | Ryzen 7 7735HS (Radeon 680M, DDR5-4800, bez NPU) | 32 GB + 1 TB | 729 € |
| UM870 Slim | Ryzen 7 8745H (Radeon 780M, DDR5-5600, bez NPU) | barebone | 329 € |
| UM870 Slim | Ryzen 7 8745H | 32 GB + 1 TB | 839 € (wysyłka z Hongkongu) |
| UM890 Pro | Ryzen 9 8945HS (Radeon 780M, NPU XDNA1 — bez wsparcia LLM pod Linuksem) | 64 GB + 1 TB | 1429 € |

Najlepszy stosunek ceny do wydajności na test: **UM870 Slim 32 GB + 1 TB (839 €)** — ta sama klasa co
Ryzen 7 H 255 (Radeon 780M, DDR5-5600), taniej niż X1 Mini. UM773 Lite jest najtańszy, ale wolniejsza
pamięć (DDR5-4800) to ok. 15% wolniejsze generowanie.
| AI X1 Pro-470 | Ryzen AI 9 HX 470 (12 rdzeni, NPU) | barebone | 729 € |
| AI X1 Pro-470 | Ryzen AI 9 HX 470 | 32 GB + 1 TB | 1249 € |
| AI X1 Pro-470 | Ryzen AI 9 HX 470 | 64 GB + 1 TB | 1679 € |

Wariant „Lite” = H 255 (ta sama pamięć DDR5-5600, więc podobna prędkość generowania; wolniejsze
przetwarzanie długich promptów i zdjęć, brak NPU). Wariant „Pro” = HX 470.

## Jak liczymy modele

- **Grafika:** Ollama z backendem **Vulkan** (Mesa RADV). W pomiarach na Radeon 890M Vulkan generował
  tekst ok. 2× szybciej niż ROCm, a działa też na układach spoza listy ROCm (np. Radeon 860M w Ryzen AI 7 350).
- **Szacunek wydajności:** Qwen3-8B Q4 osiąga ok. 13 tok/s na Radeon 890M z DDR5-5600 (profil
  wydajności). Nasz Qwen3.5-4B jest o połowę mniejszy, więc spodziewamy się ok. 20–25 tok/s —
  do potwierdzenia w tygodniu testów (`tools/bench.py`).
- **Profil zasilania:** instalator ustawia `performance`; na profilu oszczędnym generowanie jest
  o ok. 1/3 wolniejsze.
- **NPU (opcjonalnie, później):** od 2026 r. Lemonade (AMD) + FastFlowLM uruchamiają LLM i Whisper na NPU
  pod Linuksem (kernel 7.0+ lub backport sterownika `amdxdna`). Kandydaci do przeniesienia na NPU:
  router 0.8B i rozpoznawanie mowy, żeby nie zajmowały grafiki. Licencje obu projektów do sprawdzenia
  przed użyciem.
- **Do zbadania:** dekodowanie spekulacyjne (Qwen3.5-0.8B jako model szkicowy dla 4B) dawało w pomiarach
  +40–80% prędkości, ale Ollama go nie obsługuje — wymagałoby `llama-server`.

## Bezpieczeństwo sprzętowe

Przed pierwszym uruchomieniem w BIOS/UEFI:

1. Ustaw hasło administratora BIOS.
2. Włącz **Secure Boot** i **fTPM / Pluton** (TPM 2.0).
3. Wyłącz uruchamianie z USB i sieci (PXE) albo ustaw dysk jako jedyne źródło.

Podczas instalacji Ubuntu wybierz **szyfrowanie dysku (LUKS)**. Potem powiąż klucz z TPM,
żeby urządzenie startowało bez wpisywania hasła, ale tylko z niezmienionym systemem:

```bash
sudo systemd-cryptenroll --recovery-key /dev/nvme0n1p3   # zapisz klucz awaryjny poza urządzeniem
sudo systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/nvme0n1p3
# w /etc/crypttab dopisz do opcji: tpm2-device=auto
```

PCR 7 wiąże klucz ze stanem Secure Boot: wyjęty dysk albo zmieniony bootloader nie odblokuje danych.
Ograniczenie: skradzione **całe** urządzenie uruchomi się samo — wtedy chronią nas hasło BIOS,
zablokowany start z USB, brak lokalnego logowania (tylko SSH z kluczem) i tokeny, które można unieważnić.
Wyższy poziom: `--tpm2-with-pin=yes` (PIN przy każdym starcie), kosztem pracy bez monitora.

## Źródła

- Ollama — obsługa GPU (ROCm, Vulkan): https://docs.ollama.com/gpu
- Pomiary Radeon 890M (Vulkan vs ROCm, spekulacja): https://msf.github.io/blogpost/local-llm-performance-framework13.html
- NPU Ryzen AI pod Linuksem (Lemonade, FastFlowLM): https://phoronix.com/news/AMD-Ryzen-AI-NPUs-Linux-LLMs
- Mini PC z NPU, ceny 10.2026: https://computingforgeeks.com/best-mini-pc-with-npu/
