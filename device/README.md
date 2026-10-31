# Urządzenie

## Obsługiwane platformy

- **Jetson Orin Nano Super 8 GB** (prototyp) — JetPack 6.2, system na dysku NVMe.
- **Mini PC x86 z Ryzen 7 / Ryzen AI 9, 32 GB** (kandydat docelowy) — Ubuntu 24.04; Ollama z akceleracją Vulkan.

## Instalacja

```bash
git clone <adres-repo> && cd edge-llm
sudo device/install.sh                  # urządzenia 8 GB
sudo device/install.sh --with-code-model # urządzenia 16+ GB (dochodzi model kodu)
```

Skrypt:
1. instaluje Ollamę,
2. pobiera modele z `models.yaml` (router, model główny, Bielik; model kodu opcjonalnie),
3. instaluje serwer API w `/opt/edge-llm` i usługę `edge-llm` (port 8080),
4. generuje token dostępu w `/etc/edge-llm.env`.

## Zdalny dostęp

MVP: Tailscale. Port 8080 nie jest wystawiany do internetu — telefon łączy się przez prywatną sieć Tailscale.

## Do zrobienia

- [ ] Parowanie telefonu kodem QR zamiast ręcznego tokenu
- [ ] Przypięcie wersji i sum kontrolnych modeli w `models.yaml`
- [ ] Monitoring temperatury i pamięci
- [ ] Podpisane aktualizacje
