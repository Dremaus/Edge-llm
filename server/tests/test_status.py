from __future__ import annotations

from app.status import collect, read_meminfo, read_temperatures, read_uptime


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
        "disk",
        "uptime_s",
        "loaded_models",
    }
    assert status["loaded_models"] == ["qwen3.5:4b"]
    assert status["disk"]["total_gb"] >= 0
