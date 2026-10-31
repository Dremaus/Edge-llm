#!/usr/bin/env bash
# Instalacja asystenta na urządzeniu (Jetson z JetPack 6.x lub mini PC x86 z Ubuntu 24.04).
# Użycie: sudo device/install.sh [--with-code-model]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR=/opt/edge-llm
SERVICE_USER=edge
ENV_FILE=/etc/edge-llm.env
WITH_CODE_MODEL=0
[[ "${1:-}" == "--with-code-model" ]] && WITH_CODE_MODEL=1

if [[ $EUID -ne 0 ]]; then
  echo "Uruchom jako root: sudo $0" >&2
  exit 1
fi

echo "==> Pamięć RAM: $(free -g | awk '/Mem:/ {print $2}') GB"

echo "==> Instalacja Ollamy"
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama

echo "==> Pobieranie modeli z device/models.yaml"
# Prosty parser: bierze 'id' z każdego wpisu; model kodu tylko z flagą.
current_id=""
while IFS= read -r line; do
  if [[ $line =~ ^[[:space:]]*-[[:space:]]id:[[:space:]]*(.+)$ ]]; then
    current_id="${BASH_REMATCH[1]}"
  elif [[ $line =~ ^[[:space:]]*role:[[:space:]]*(.+)$ && -n $current_id ]]; then
    role="${BASH_REMATCH[1]}"
    if [[ $role == "code" && $WITH_CODE_MODEL -eq 0 ]]; then
      echo "    pomijam model kodu: $current_id (użyj --with-code-model)"
    else
      echo "    ollama pull $current_id"
      ollama pull "$current_id"
    fi
    current_id=""
  fi
done < "$REPO_DIR/device/models.yaml"

echo "==> Instalacja serwera API"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$INSTALL_DIR"
cp -r "$REPO_DIR/server" "$INSTALL_DIR/"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet "$INSTALL_DIR/server"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

if [[ ! -f $ENV_FILE ]]; then
  echo "==> Tworzenie $ENV_FILE z nowym tokenem"
  umask 077
  cat > "$ENV_FILE" <<EOF
EDGE_API_TOKEN=$(openssl rand -hex 32)
EDGE_LANGUAGE=pl
EDGE_CODE_MODEL_ENABLED=$WITH_CODE_MODEL
EOF
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
fi

install -m 644 "$REPO_DIR/device/systemd/edge-llm.service" /etc/systemd/system/edge-llm.service
systemctl daemon-reload
systemctl enable --now edge-llm

echo "==> Gotowe. Status: systemctl status edge-llm"
echo "    Token dla aplikacji jest w $ENV_FILE (EDGE_API_TOKEN)."
echo "    Zdalny dostęp: zainstaluj Tailscale (https://tailscale.com/download) i zaloguj urządzenie."
