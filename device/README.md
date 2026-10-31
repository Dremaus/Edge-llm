# Urządzenie

## Obsługiwane platformy

- **Mini PC z AMD Ryzen AI** (seria 300/400), 16–32 GB DDR5, Ubuntu 24.04 — platforma docelowa.
  Ollama na zintegrowanym Radeonie przez Vulkan. Konfiguracja, BIOS i szyfrowanie dysku: [docs/hardware.md](../docs/hardware.md).
- Jetson Orin Nano (pierwotny prototyp) — porzucony 31.10.2026; instalator może działać, ale nie jest testowany.

## Instalacja

```bash
git clone <adres-repo> && cd edge-llm
sudo device/install.sh                  # model kodu pobierany automatycznie przy 24+ GB RAM
sudo device/install.sh --harden-ssh     # dodatkowo: SSH tylko z kluczem
```

Skrypt:
1. wykrywa grafikę AMD, instaluje sterowniki Vulkan i ustawia profil zasilania na wydajność,
2. instaluje Ollamę,
3. pobiera modele z `models.yaml` (router, model główny, Bielik; model kodu przy 24+ GB RAM),
4. instaluje serwer API w `/opt/edge-llm` i usługę `edge-llm` (port 8080),
5. na końcu pokazuje, jak sparować telefon kodem QR.

## Zdalny dostęp

MVP: Tailscale. Port 8080 nie jest wystawiany do internetu — telefon łączy się przez prywatną sieć Tailscale.

## Do zrobienia

- [x] Parowanie telefonu kodem QR zamiast ręcznego tokenu
- [ ] Przypięcie wersji i sum kontrolnych modeli w `models.yaml`
- [x] Monitoring temperatury, pamięci i grafiki (`/v1/status`)
- [ ] Podpisane aktualizacje
