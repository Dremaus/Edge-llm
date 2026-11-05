#!/usr/bin/env bash
# Instalacja asystenta na urządzeniu.
# Platforma docelowa: mini PC z AMD Ryzen AI (Radeon 860M/880M/890M), Ubuntu 24.04, kernel 6.14+.
#
# Użycie: sudo device/install.sh [--with-code-model|--no-code-model] [--harden-ssh] [--no-performance]
#   --with-code-model  wymusza pobranie modelu kodu (domyślnie: tylko przy 24+ GB RAM)
#   --no-code-model    pomija model kodu niezależnie od pamięci
#   --harden-ssh       wyłącza logowanie hasłem i roota przez SSH (wymaga klucza w authorized_keys)
#   --no-performance   nie przełącza profilu zasilania na wydajność
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR=/opt/edge-llm
STATE_DIR=/var/lib/edge-llm
SERVICE_USER=edge
ENV_FILE=/etc/edge-llm.env
WITH_CODE_MODEL=auto
HARDEN_SSH=0
PERFORMANCE=1
for arg in "$@"; do
  case "$arg" in
    --with-code-model) WITH_CODE_MODEL=1 ;;
    --no-code-model) WITH_CODE_MODEL=0 ;;
    --harden-ssh) HARDEN_SSH=1 ;;
    --no-performance) PERFORMANCE=0 ;;
    *) echo "Nieznana opcja: $arg" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Uruchom jako root: sudo $0" >&2
  exit 1
fi
umask 027

# Grafika zintegrowana dzieli RAM z systemem, więc o modelach decyduje cała pamięć.
# free -g zaokrągla w dół (32 GB pokazuje jako 30), stąd próg 24.
RAM_GB=$(free -g | awk '/Mem:/ {print $2}')
echo "==> Pamięć RAM: ${RAM_GB} GB"
if [[ $WITH_CODE_MODEL == auto ]]; then
  if (( RAM_GB >= 24 )); then WITH_CODE_MODEL=1; else WITH_CODE_MODEL=0; fi
fi

echo "==> Aktualizacje bezpieczeństwa"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ufw unattended-upgrades fail2ban python3-venv openssl curl qrencode pciutils
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Grafika"
AMD_GPU=0
for vendor in /sys/class/drm/card[0-9]*/device/vendor; do
  [[ -r $vendor && $(cat "$vendor") == 0x1002 ]] && AMD_GPU=1
done
if (( AMD_GPU )); then
  # Ollama na zintegrowanym Radeonie: Vulkan (Mesa RADV) — szybsze generowanie niż ROCm
  # i działa na wszystkich Ryzen AI, także tych spoza listy ROCm (np. Ryzen AI 7 350).
  apt-get install -y -q mesa-vulkan-drivers vulkan-tools
  echo "    AMD Radeon wykryty, sterowniki Vulkan zainstalowane"
else
  echo "    UWAGA: nie wykryto grafiki AMD — modele będą działać na procesorze (wolno)."
fi
echo "    Kernel: $(uname -r) (NPU Ryzen AI dla LLM wymaga 7.0+ lub backportu amdxdna — opcjonalne)"

if (( PERFORMANCE )) && command -v powerprofilesctl >/dev/null; then
  # Na profilu wydajności generowanie jest o ok. 1/3 szybsze (pomiar dla Radeon 890M).
  powerprofilesctl set performance && echo "==> Profil zasilania: performance"
fi

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
# Dostęp do GPU (/dev/dri) mają grupy render i video.
if id -u ollama >/dev/null 2>&1; then
  usermod -aG render,video ollama
fi
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "==> Pobieranie modeli z device/models.yaml"
CHOSEN_MAIN="" CHOSEN_CODE=""
pull_model() {
  local id=$1 role=$2 status=$3 min=$4 max=$5
  [[ -z $id ]] && return
  if [[ $status != approved ]]; then
    echo "    pomijam (status: ${status:-brak}): $id"
  elif [[ $role == code && $WITH_CODE_MODEL -eq 0 ]]; then
    echo "    pomijam model kodu: $id (mniej niż 24 GB RAM; wymuś: --with-code-model)"
  elif [[ -n $min ]] && (( RAM_GB < min )) && ! [[ $role == code && $WITH_CODE_MODEL -eq 1 ]]; then
    echo "    pomijam (wymaga ${min}+ GB RAM): $id"
  elif [[ -n $max ]] && (( RAM_GB > max )); then
    echo "    pomijam (przeznaczony dla ${max} GB RAM lub mniej): $id"
  else
    echo "    ollama pull $id"
    ollama pull "$id"
    case $role in
      main) CHOSEN_MAIN=$id ;;
      code) CHOSEN_CODE=$id ;;
    esac
  fi
}
m_id="" m_role="" m_status="" m_min="" m_max=""
while IFS= read -r line; do
  if [[ $line =~ ^[[:space:]]*-[[:space:]]id:[[:space:]]*(.+)$ ]]; then
    pull_model "$m_id" "$m_role" "$m_status" "$m_min" "$m_max"
    m_id="${BASH_REMATCH[1]}" m_role="" m_status="" m_min="" m_max=""
  elif [[ $line =~ ^[[:space:]]+role:[[:space:]]*([a-z]+) ]]; then m_role="${BASH_REMATCH[1]}"
  elif [[ $line =~ ^[[:space:]]+status:[[:space:]]*([a-z]+) ]]; then m_status="${BASH_REMATCH[1]}"
  elif [[ $line =~ ^[[:space:]]+min_ram_gb:[[:space:]]*([0-9]+) ]]; then m_min="${BASH_REMATCH[1]}"
  elif [[ $line =~ ^[[:space:]]+max_ram_gb:[[:space:]]*([0-9]+) ]]; then m_max="${BASH_REMATCH[1]}"
  fi
done < "$REPO_DIR/device/models.yaml"
pull_model "$m_id" "$m_role" "$m_status" "$m_min" "$m_max"

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
  printf 'EDGE_LANGUAGE=pl\n' > "$ENV_FILE"
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
fi
# Modele wybrane według RAM (nadpisywane przy każdej instalacji).
set_env() { grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true; echo "$1=$2" >> "$ENV_FILE.tmp"; cat "$ENV_FILE.tmp" > "$ENV_FILE"; rm -f "$ENV_FILE.tmp"; }
set_env EDGE_CODE_MODEL_ENABLED "$WITH_CODE_MODEL"
[[ -n $CHOSEN_MAIN ]] && set_env EDGE_MAIN_MODEL "$CHOSEN_MAIN"
[[ -n $CHOSEN_CODE && $WITH_CODE_MODEL -eq 1 ]] && set_env EDGE_CODE_MODEL "$CHOSEN_CODE"

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
