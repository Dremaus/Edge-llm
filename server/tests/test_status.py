from __future__ import annotations

from app.status import (
    collect,
    read_amd_gpu,
    read_hwmon_temperatures,
    read_meminfo,
    read_temperatures,
    read_uptime,
)


def test_meminfo_parsed_to_mb(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:       16384000 kB\nMemFree: 1 kB\nMemAvailable:    8192000 kB\n")
    assert read_meminfo(f) == {"total_mb": 16000, "available_mb": 8000}


def test_meminfo_missing_file_is_empty(tmp_path):
    assert read_meminfo(tmp_path / "nope") == {}


def test_temperatures_filter_relevant_zones(tmp_path):
    for i, (kind, temp) in enumerate(
        [("CPU-therm", "52500"), ("GPU-therm", "61000"), ("battery", "30000"), ("cpu-bad", "999999")]
    ):
        zone = tmp_path / f"thermal_zone{i}"
        zone.mkdir()
        (zone / "type").write_text(kind)
        (zone / "temp").write_text(temp)
    assert read_temperatures(tmp_path) == {"cpu-therm": 52.5, "gpu-therm": 61.0}


def test_uptime(tmp_path):
    f = tmp_path / "uptime"
    f.write_text("12345.67 999.0\n")
    assert read_uptime(f) == 12345


def test_collect_has_no_identifying_data(tmp_path):
    status = collect(str(tmp_path), ["qwen3.5:4b"])
    assert set(status) == {
        "temperature_c",
        "temperature_warning",
        "memory",
        "gpu",
        "disk",
        "uptime_s",
        "loaded_models",
    }
    assert status["loaded_models"] == ["qwen3.5:4b"]
    assert status["disk"]["total_gb"] >= 0


def test_hwmon_reads_amd_cpu_and_gpu_sensors(tmp_path):
    for i, (name, temps) in enumerate(
        [("k10temp", ["71300", "65000"]), ("amdgpu", ["58000"]), ("nvme", ["40000"]), ("amdgpu", ["bad"])]
    ):
        chip = tmp_path / f"hwmon{i}"
        chip.mkdir()
        (chip / "name").write_text(name + "\n")
        for j, t in enumerate(temps, start=1):
            (chip / f"temp{j}_input").write_text(t)
    # nvme pomijamy; dla procesora bierzemy najgorętszy czujnik
    assert read_hwmon_temperatures(tmp_path) == {"k10temp": 71.3, "amdgpu": 58.0}


def test_amd_gpu_busy_and_shared_memory(tmp_path):
    other = tmp_path / "card0" / "device"
    other.mkdir(parents=True)
    (other / "vendor").write_text("0x8086\n")
    dev = tmp_path / "card1" / "device"
    dev.mkdir(parents=True)
    files = {
        "vendor": "0x1002",
        "gpu_busy_percent": "37",
        "mem_info_vram_used": str(256 * 1024**2),
        "mem_info_vram_total": str(512 * 1024**2),
        "mem_info_gtt_used": str(3 * 1024**3),
        "mem_info_gtt_total": str(16 * 1024**3),
    }
    for k, v in files.items():
        (dev / k).write_text(v)
    assert read_amd_gpu(tmp_path) == {"busy_percent": 37, "memory_used_mb": 3328, "memory_total_mb": 16896}


def test_no_amd_gpu_gives_empty_dict(tmp_path):
    assert read_amd_gpu(tmp_path) == {}
