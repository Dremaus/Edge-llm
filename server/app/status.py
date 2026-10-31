"""Stan urządzenia dla aplikacji: temperatura, pamięć, dysk, czas pracy.

Działa na Jetsonie i na mini PC x86 — czyta standardowe pliki Linuksa.
Zwraca tylko liczby, bez nazw użytkowników, adresów IP ani ścieżek.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Strefy termiczne, które opisują procesor lub GPU (nazwy różnią się między platformami).
_CPU_ZONE_HINTS = ("cpu", "gpu", "soc", "x86_pkg_temp", "k10temp", "tctl", "acpitz")


def read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    """Zwraca total/available w MB."""
    values: dict[str, int] = {}
    try:
        for line in path.read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) // 1024  # kB -> MB
    except (OSError, ValueError, IndexError):
        return {}
    if "MemTotal" not in values:
        return {}
    return {"total_mb": values["MemTotal"], "available_mb": values.get("MemAvailable", 0)}


def read_temperatures(root: Path = Path("/sys/class/thermal")) -> dict[str, float]:
    temps: dict[str, float] = {}
    try:
        zones = sorted(root.glob("thermal_zone*"))
    except OSError:
        return temps
    for zone in zones:
        try:
            name = (zone / "type").read_text().strip().lower()
            milli = int((zone / "temp").read_text().strip())
        except (OSError, ValueError):
            continue
        if any(hint in name for hint in _CPU_ZONE_HINTS) and -40_000 < milli < 150_000:
            temps[name] = round(milli / 1000, 1)
    return temps


def read_uptime(path: Path = Path("/proc/uptime")) -> int | None:
    try:
        return int(float(path.read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def read_disk(path: str) -> dict[str, int]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {}
    return {"total_gb": usage.total // 1024**3, "free_gb": usage.free // 1024**3}


def collect(state_dir: str, loaded_models: list[str] | None) -> dict[str, Any]:
    temps = read_temperatures()
    hottest = max(temps.values()) if temps else None
    return {
        "temperature_c": hottest,
        "temperature_warning": hottest is not None and hottest >= 85.0,
        "memory": read_meminfo(),
        "disk": read_disk(state_dir),
        "uptime_s": read_uptime(),
        "loaded_models": loaded_models or [],
    }
