#!/usr/bin/env bash
# Instalacja asystenta na urządzeniu (Jetson z JetPack 6.x lub mini PC x86 z Ubuntu 24.04).
#
# Użycie: sudo device/install.sh [--with-code-model] [--harden-ssh]
#   --with-code-model  pobiera model kodu (urządzenia 16+ GB)
#   --harden-ssh       wyłącza logowanie hasłem i roota przez SSH (wymaga klucza w authorized_keys)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR=/opt/edge-llm
STATE_DIR=/var/lib/edge-llm
SERVICE_USER=edge
ENV_FILE=/etc/edge-llm.env
WITH_CODE_MODEL=0
HARDEN_SSH=0
for arg in "$@"; do
  case "$arg" in
    --with-code-model) WITH_CODE_MODEL=1 ;;
    --harden-ssh) HARDEN_SSH=1 ;;
    *) echo "Nieznana opcja: $arg" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Uruchom jako root: sudo $0" >&2
  exit 1
fi
umask 027

echo "==> Pamięć RAM: $(free -g | awk '/Mem:/ {print $2}') GB"

echo "==> Aktualizacje bezpieczeństwa"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ufw unattended-upgrades fail2ban python3-venv openssl curl qrencode
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Zapora: domyślnie wszystko zablokowane, ruch tylko przez Tailscale"
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
# SSH z sieci lokalnej zostaje (z limitem prób), żeby instalacja nie odcięła dostępu.
# Gdy Tailscale działa: sudo ufw delete limit 22/tcp  (SSH tylko przez Tailscale).
ufw limit 22/tcp
# Serwer API i Ollama nasłuchują tylko na 127.0.0.1, więc LAN nie ma do nich dostępu.
ufw --force enable

echo "==> Tailscale (szyfrowany dostęp zdalny)"
if ! command -v tailscale >/dev/null; then
  tmp_script="$(mktemp)"
  curl -fsSL https://tailscale.com/install.sh -o "$tmp_script"
  echo "    sha256 skryptu Tailscale: $(sha256sum "$tmp_script" | cut -d' ' -f1)"
  sh "$tmp_script"
  rm -f "$tmp_script"
fi

echo "==> Ollama (tylko localhost)"
if ! command -v ollama >/dev/null; then
  tmp_script="$(mktemp)"
  curl -fsSL https://ollama.com/install.sh -o "$tmp_script"
  echo "    sha256 skryptu Ollamy: $(sha256sum "$tmp_script" | cut -d' ' -f1)"
  sh "$tmp_script"
  rm -f "$tmp_script"
fi
install -d -m 755 /etc/systemd/system/ollama.service.d
install -m 644 "$REPO_DIR/device/systemd/ollama-hardening.conf" /etc/systemd/system/ollama.service.d/hardening.conf
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "==> Pobieranie modeli z device/models.yaml"
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

echo "==> Serwer API"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -m 750 -o root -g "$SERVICE_USER" "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/server"
cp -r "$REPO_DIR/server" "$INSTALL_DIR/"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
if [[ -f "$INSTALL_DIR/server/requirements.lock" ]]; then
  # Wersje przypięte z sumami kontrolnymi (pip-compile --generate-hashes).
  "$INSTALL_DIR/venv/bin/pip" install --quiet --require-hashes -r "$INSTALL_DIR/server/requirements.lock"
  "$INSTALL_DIR/venv/bin/pip" install --quiet --no-deps "$INSTALL_DIR/server"
else
  echo "    UWAGA: brak requirements.lock — instalacja bez przypiętych sum kontrolnych"
  "$INSTALL_DIR/venv/bin/pip" install --quiet "$INSTALL_DIR/server"
fi
# Kod należy do roota — proces usługi może go tylko czytać.
chown -R root:"$SERVICE_USER" "$INSTALL_DIR"
chmod -R g-w,o-rwx "$INSTALL_DIR"

if [[ ! -f $ENV_FILE ]]; then
  cat > "$ENV_FILE" <<EOF
EDGE_LANGUAGE=pl
EDGE_CODE_MODEL_ENABLED=$WITH_CODE_MODEL
EOF
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
fi

install -m 644 "$REPO_DIR/device/systemd/edge-llm.service" /etc/systemd/system/edge-llm.service
systemctl daemon-reload
systemctl enable --now edge-llm

install -d -m 700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR"

if [[ $HARDEN_SSH -eq 1 ]]; then
  echo "==> Utwardzanie SSH"
  if ! compgen -G "/home/*/.ssh/authorized_keys" >/dev/null && [[ ! -s /root/.ssh/authorized_keys ]]; then
    echo "    POMINIĘTO: brak kluczy w authorized_keys — wyłączenie haseł odcięłoby dostęp." >&2
  else
    install -d -m 755 /etc/ssh/sshd_config.d
    cat > /etc/ssh/sshd_config.d/50-edge-llm.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
X11Forwarding no
AllowTcpForwarding no
EOF
    if sshd -t; then
      systemctl reload ssh 2>/dev/null || systemctl reload sshd
    else
      echo "    Błąd konfiguracji SSH — wycofuję zmianę." >&2
      rm -f /etc/ssh/sshd_config.d/50-edge-llm.conf
    fi
  fi
fi

cat <<'EOF'
==> Gotowe.

Kolejne kroki (wymagają interakcji):
  1. sudo tailscale up            # zaloguj urządzenie do swojej sieci Tailscale
  2. sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
                                  # HTTPS z certyfikatem, dostępne tylko w Twojej sieci Tailscale
  3. W panelu Tailscale włącz Tailnet Lock i ustaw ACL: dostęp do urządzenia tylko z Twoich telefonów.
  4. Sparuj telefon (kod QR ważny 10 minut, jednorazowy):
       cd /opt/edge-llm/server && sudo -u edge EDGE_PUBLIC_URL=https://<nazwa>.<tailnet>.ts.net \
         /opt/edge-llm/venv/bin/python -m app.security.pairing new

Zarządzanie tokenami telefonów:
  cd /opt/edge-llm/server && sudo -u edge EDGE_TOKENS_FILE=/var/lib/edge-llm/tokens.json \
    /opt/edge-llm/venv/bin/python -m app.security.tokens list|add <nazwa>|revoke <id>
EOF
