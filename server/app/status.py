"""Stan urządzenia dla aplikacji: temperatura, pamięć, GPU, dysk, czas pracy.

Platforma docelowa: mini PC z AMD Ryzen AI (zintegrowana grafika Radeon, sterownik amdgpu).
Czyta standardowe pliki Linuksa, więc działa też na innych komputerach.
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


# Czujniki hwmon na AMD: k10temp = procesor (Tctl), amdgpu = zintegrowana grafika.
_HWMON_NAMES = ("k10temp", "amdgpu", "coretemp", "zenpower")


def read_hwmon_temperatures(root: Path = Path("/sys/class/hwmon")) -> dict[str, float]:
    temps: dict[str, float] = {}
    try:
        chips = sorted(root.glob("hwmon*"))
    except OSError:
        return temps
    for chip in chips:
        try:
            name = (chip / "name").read_text().strip().lower()
        except OSError:
            continue
        if name not in _HWMON_NAMES:
            continue
        readings = []
        for sensor in sorted(chip.glob("temp*_input")):
            try:
                milli = int(sensor.read_text().strip())
            except (OSError, ValueError):
                continue
            if -40_000 < milli < 150_000:
                readings.append(milli)
        if readings:
            # Najgorętszy czujnik układu: tego dotyczy ostrzeżenie o przegrzaniu.
            temps[name] = round(max(readings) / 1000, 1)
    return temps


def read_amd_gpu(root: Path = Path("/sys/class/drm")) -> dict[str, int]:
    """Obciążenie i pamięć zintegrowanej grafiki AMD (VRAM + pamięć współdzielona GTT)."""
    try:
        cards = sorted(root.glob("card[0-9]*"))
    except OSError:
        return {}
    for card in cards:
        dev = card / "device"
        try:
            if (dev / "vendor").read_text().strip().lower() != "0x1002":
                continue
            busy = int((dev / "gpu_busy_percent").read_text().strip())
        except (OSError, ValueError):
            continue
        used = total = 0
        for kind in ("vram", "gtt"):
            try:
                used += int((dev / f"mem_info_{kind}_used").read_text().strip())
                total += int((dev / f"mem_info_{kind}_total").read_text().strip())
            except (OSError, ValueError):
                continue
        out = {"busy_percent": max(0, min(busy, 100))}
        if total:
            out["memory_used_mb"] = used // 1024**2
            out["memory_total_mb"] = total // 1024**2
        return out
    return {}


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
    temps = {**read_temperatures(), **read_hwmon_temperatures()}
    hottest = max(temps.values()) if temps else None
    return {
        "temperature_c": hottest,
        "temperature_warning": hottest is not None and hottest >= 85.0,
        "memory": read_meminfo(),
        "gpu": read_amd_gpu(),
        "disk": read_disk(state_dir),
        "uptime_s": read_uptime(),
        "loaded_models": loaded_models or [],
    }
