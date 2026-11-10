#!/usr/bin/env bash
# Opcjonalna piaskownica dla narzędzia run_python (agent uruchamia kod modelu).
# Wymaga: podman i runsc (gVisor). Uruchom: sudo device/sandbox-setup.sh
# Skrypt NIE instaluje gVisora z nieznanego źródła: zainstaluj runsc według
# https://gvisor.dev/docs/user_guide/install/ (z weryfikacją podpisu), potem uruchom ten skrypt ponownie.
set -euo pipefail

IMAGE="docker.io/library/python:3.12-slim"
ENV_FILE=/etc/edge-llm.env

[ "$(id -u)" -eq 0 ] || { echo "Uruchom jako root (sudo)." >&2; exit 1; }

if ! command -v podman >/dev/null; then
  apt-get update && apt-get install -y --no-install-recommends podman
fi
if ! command -v runsc >/dev/null; then
  echo "Brak runsc (gVisor). Zainstaluj go według https://gvisor.dev/docs/user_guide/install/ i uruchom skrypt ponownie." >&2
  echo "Bez gVisora kod NIE jest uruchamiany (zwykły kontener to za słaba izolacja dla kodu pisanego przez model)." >&2
  exit 1
fi

# Obraz pobierany raz (to jedyne wyjście do sieci); potem kontenery działają z --network=none.
podman image exists "$IMAGE" || podman pull "$IMAGE"

echo "Test szczelności piaskownicy..."
out=$(podman run --rm --runtime=runsc --network=none --read-only --user=65534:65534 --cap-drop=ALL \
  --security-opt=no-new-privileges --memory=256m "$IMAGE" python -I -c '
import socket, sys
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3); print("SIEC-OTWARTA"); sys.exit(1)
except OSError:
    pass
try:
    open("/etc/edge-llm-test", "w"); print("ZAPIS-MOZLIWY"); sys.exit(1)
except OSError:
    pass
print("OK")
')
[ "$out" = "OK" ] || { echo "Test piaskownicy nie przeszedł: $out" >&2; exit 1; }

grep -v '^EDGE_EXECUTE_ENABLED=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
echo "EDGE_EXECUTE_ENABLED=1" >> "$ENV_FILE.tmp"
cat "$ENV_FILE.tmp" > "$ENV_FILE"; rm -f "$ENV_FILE.tmp"
echo "Gotowe. Uruchom ponownie: sudo systemctl restart edge-llm. Każde uruchomienie kodu nadal wymaga zgody w aplikacji."
