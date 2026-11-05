#!/usr/bin/env bash
# Aktualizacja modeli: na czas pobierania zdejmuje blokadę internetu Ollamy, potem ją przywraca.
# Użycie: sudo device/pull-models.sh [identyfikator-modelu ...]   (bez argumentów: wszystkie z models.yaml
# o statusie approved, dopasowane do RAM tak samo jak w install.sh)
set -euo pipefail

DROPIN=/etc/systemd/system/ollama.service.d/egress.conf
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ $EUID -ne 0 ]]; then
  echo "Uruchom jako root: sudo $0" >&2
  exit 1
fi

restore() {
  if [[ -f $DROPIN.off ]]; then
    mv "$DROPIN.off" "$DROPIN"
  fi
  systemctl daemon-reload
  systemctl restart ollama
  echo "==> Blokada internetu Ollamy przywrócona"
}
trap restore EXIT

if [[ -f $DROPIN ]]; then
  mv "$DROPIN" "$DROPIN.off"
  systemctl daemon-reload
  systemctl restart ollama
  echo "==> Blokada internetu Ollamy zdjęta na czas pobierania"
  sleep 3
fi

if (( $# > 0 )); then
  for id in "$@"; do ollama pull "$id"; done
else
  RAM_GB=$(free -g | awk '/Mem:/ {print $2}')
  # Ta sama logika wyboru co w install.sh (wspólna funkcja: tools/select_models.py).
  while IFS= read -r id; do
    echo "    ollama pull $id"
    ollama pull "$id"
  done < <(python3 "$REPO_DIR/tools/select_models.py" "$REPO_DIR/device/models.yaml" --ram-gb "$RAM_GB")
fi
