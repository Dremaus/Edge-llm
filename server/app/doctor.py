"""edge-llm doctor: szybki przegląd bezpieczeństwa i stanu urządzenia.

Uruchom: `sudo edge-llm-doctor` (po instalacji) albo `python -m app.doctor`.
Tylko odczyt — niczego nie zmienia. Kod wyjścia: 0 = bez błędów, 1 = są FAIL, 2 = tylko ostrzeżenia.
Sprawdza to, co da się ustalić z systemu; ustawień BIOS (hasło, Secure Boot w firmware) nie widzi.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
SERVICES = ["edge-llm", "ollama"]
OPTIONAL_SERVICES = ["tailscaled", "whisper", "fail2ban"]
# Porty, które mogą słuchać poza localhost (SSH). Reszta tylko na 127.0.0.1 / ::1.
PUBLIC_PORTS_ALLOWED = {22}

Runner = Callable[[list[str]], tuple[int, str]]


@dataclass
class Result:
    status: str
    name: str
    detail: str = ""
    fix: str = ""


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return p.returncode, p.stdout + p.stderr


def check_services(sh: Runner) -> list[Result]:
    out = []
    for name in SERVICES:
        code, text = sh(["systemctl", "is-active", name])
        ok = code == 0 and text.strip() == "active"
        out.append(Result(PASS if ok else FAIL, f"usługa {name}", text.strip() or "brak",
                          "" if ok else f"sudo systemctl status {name}"))
    for name in OPTIONAL_SERVICES:
        code, text = sh(["systemctl", "is-active", name])
        if text.strip() == "active":
            out.append(Result(PASS, f"usługa {name}", "active"))
        elif text.strip() in {"inactive", "failed", "activating"}:
            out.append(Result(WARN, f"usługa {name}", text.strip()))
    return out


def parse_listening(ss_output: str) -> list[tuple[str, int]]:
    """Z wyjścia `ss -ltnH` zwraca (adres, port) każdego gniazda nasłuchującego."""
    found = []
    for line in ss_output.splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        local = cols[3]
        addr, _, port = local.rpartition(":")
        if port.isdigit():
            found.append((addr.strip("[]"), int(port)))
    return found


def check_ports(sh: Runner) -> list[Result]:
    code, text = sh(["ss", "-ltnH"])
    if code != 0:
        return [Result(WARN, "porty nasłuchujące", "nie udało się uruchomić ss")]
    exposed = [
        (a, p) for a, p in parse_listening(text)
        if a not in {"127.0.0.1", "::1", "127.0.0.53", "127.0.0.54"} and p not in PUBLIC_PORTS_ALLOWED
        and not a.startswith("100.")  # adres Tailscale
        and not a.startswith("fd7a:")
    ]
    if exposed:
        return [Result(FAIL, "porty nasłuchujące", ", ".join(f"{a}:{p}" for a, p in exposed),
                       "Ogranicz usługę do 127.0.0.1 albo zablokuj port w ufw")]
    return [Result(PASS, "porty nasłuchujące", "poza SSH i Tailscale tylko localhost")]


def check_firewall(sh: Runner) -> list[Result]:
    code, text = sh(["ufw", "status", "verbose"])
    if code != 0:
        return [Result(WARN, "zapora ufw", "brak informacji (uruchom jako root?)")]
    if "Status: active" not in text:
        return [Result(FAIL, "zapora ufw", "nieaktywna", "sudo ufw enable")]
    if "deny (incoming)" not in text:
        return [Result(FAIL, "zapora ufw", "domyślnie nie blokuje ruchu przychodzącego", "sudo ufw default deny incoming")]
    return [Result(PASS, "zapora ufw", "aktywna, ruch przychodzący domyślnie blokowany")]


def check_ssh(sh: Runner) -> list[Result]:
    code, text = sh(["sshd", "-T"])
    if code != 0:
        return [Result(WARN, "SSH", "nie udało się odczytać konfiguracji (sshd -T)")]
    cfg = {k: v for k, _, v in (line.partition(" ") for line in text.splitlines())}
    out = []
    pw = cfg.get("passwordauthentication", "yes")
    out.append(Result(PASS if pw == "no" else WARN, "SSH: hasła", f"PasswordAuthentication {pw}",
                      "" if pw == "no" else "Uruchom install.sh z --harden-ssh po dodaniu klucza"))
    root = cfg.get("permitrootlogin", "yes")
    out.append(Result(PASS if root in {"no", "prohibit-password"} else FAIL, "SSH: root", f"PermitRootLogin {root}",
                      "" if root in {"no", "prohibit-password"} else "PermitRootLogin no"))
    return out


def mode_of(path: Path) -> int:
    return path.stat().st_mode & 0o777


def check_files(env_file: Path, state_dir: Path) -> list[Result]:
    out = []
    if env_file.exists():
        mode = mode_of(env_file)
        ok = mode & 0o007 == 0
        out.append(Result(PASS if ok else FAIL, f"uprawnienia {env_file}", oct(mode),
                          "" if ok else f"sudo chmod 640 {env_file}"))
    else:
        out.append(Result(WARN, f"uprawnienia {env_file}", "brak pliku"))
    if state_dir.exists():
        mode = mode_of(state_dir)
        ok = mode & 0o077 == 0
        out.append(Result(PASS if ok else FAIL, f"uprawnienia {state_dir}", oct(mode),
                          "" if ok else f"sudo chmod 700 {state_dir}"))
        tokens = state_dir / "tokens.json"
        if tokens.exists() and mode_of(tokens) & 0o077:
            out.append(Result(FAIL, "plik tokenów", oct(mode_of(tokens)), f"sudo chmod 600 {tokens}"))
    return out


def check_ollama_egress(dropin: Path) -> list[Result]:
    if dropin.exists() and "IPAddressDeny=any" in dropin.read_text():
        return [Result(PASS, "Ollama bez internetu", "blokada aktywna")]
    return [Result(WARN, "Ollama bez internetu", "brak blokady ruchu wychodzącego",
                   "Uruchom install.sh ponownie (bez --keep-ollama-online) albo skopiuj device/systemd/ollama-offline.conf")]


def check_disk_encryption(sh: Runner) -> list[Result]:
    code, text = sh(["lsblk", "-no", "TYPE"])
    if code != 0:
        return [Result(WARN, "szyfrowanie dysku", "lsblk niedostępny")]
    if "crypt" in text.split():
        return [Result(PASS, "szyfrowanie dysku", "wykryto LUKS (crypt)")]
    return [Result(WARN, "szyfrowanie dysku", "brak LUKS: skradziony dysk da dostęp do danych",
                   "Włącz szyfrowanie przy instalacji Ubuntu (docs/hardware.md)")]


def check_boot_security(sh: Runner, dev: Path = Path("/dev")) -> list[Result]:
    out = []
    code, text = sh(["mokutil", "--sb-state"])
    if code == 0 and "enabled" in text.lower():
        out.append(Result(PASS, "Secure Boot", "włączony"))
    else:
        detail = "wyłączony" if code == 0 else "nie udało się sprawdzić (brak mokutil?)"
        out.append(Result(WARN, "Secure Boot", detail, "Włącz w BIOS/UEFI; sprawdzenie: sudo apt install mokutil"))
    has_tpm = (dev / "tpmrm0").exists() or (dev / "tpm0").exists()
    out.append(Result(PASS if has_tpm else WARN, "TPM 2.0", "wykryty" if has_tpm else "brak /dev/tpm*",
                      "" if has_tpm else "Włącz fTPM w BIOS"))
    return out


def check_updates(sh: Runner) -> list[Result]:
    code, text = sh(["systemctl", "is-enabled", "unattended-upgrades"])
    ok = code == 0 and text.strip() == "enabled"
    return [Result(PASS if ok else WARN, "automatyczne poprawki", text.strip() or "brak",
                   "" if ok else "sudo apt install unattended-upgrades")]


def check_models(sh: Runner) -> list[Result]:
    if not shutil.which("ollama"):
        return []
    code, text = sh(["ollama", "list"])
    if code != 0:
        return [Result(WARN, "modele Ollama", "nie udało się odczytać listy")]
    names = [ln.split()[0] for ln in text.splitlines()[1:] if ln.split()]
    return [Result(PASS if names else FAIL, "modele Ollama", f"{len(names)} zainstalowanych",
                   "" if names else "sudo device/pull-models.sh")]


def check_extra_tools() -> list[Result]:
    missing = [t for t in ("lynis", "ssh-audit") if not shutil.which(t)]
    if not missing:
        return [Result(PASS, "narzędzia audytu", "lynis i ssh-audit dostępne (uruchom je ręcznie)")]
    return [Result(WARN, "narzędzia audytu", f"brak: {', '.join(missing)}", f"sudo apt install {' '.join(missing)}")]


def collect(sh: Runner = run, env_file: Path = Path("/etc/edge-llm.env"), state_dir: Path = Path("/var/lib/edge-llm"),
            dropin: Path = Path("/etc/systemd/system/ollama.service.d/egress.conf")) -> list[Result]:
    results: list[Result] = []
    for part in (
        check_services(sh), check_ports(sh), check_firewall(sh), check_ssh(sh), check_files(env_file, state_dir),
        check_ollama_egress(dropin), check_disk_encryption(sh), check_boot_security(sh), check_updates(sh),
        check_models(sh), check_extra_tools(),
    ):
        results.extend(part)
    return results


def render(results: list[Result]) -> str:
    colors = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
    use_color = sys.stdout.isatty()
    lines = []
    for r in results:
        tag = f"{colors[r.status]}{r.status}\033[0m" if use_color else r.status
        lines.append(f"[{tag}] {r.name}" + (f" — {r.detail}" if r.detail else ""))
        if r.fix and r.status != PASS:
            lines.append(f"       → {r.fix}")
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, WARN, FAIL)}
    lines.append(f"\nPodsumowanie: {counts[PASS]} OK, {counts[WARN]} ostrzeżeń, {counts[FAIL]} błędów")
    lines.append("Poza zasięgiem tego narzędzia: hasło BIOS, blokada startu z USB, Tailnet Lock i ACL w panelu Tailscale.")
    return "\n".join(lines)


def exit_code(results: list[Result]) -> int:
    if any(r.status == FAIL for r in results):
        return 1
    return 2 if any(r.status == WARN for r in results) else 0


def main() -> int:
    if os.geteuid() != 0:
        print("Uwaga: bez uprawnień roota część testów (zapora, sshd) może się nie udać.", file=sys.stderr)
    results = collect()
    print(render(results))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
