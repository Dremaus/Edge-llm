from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from select_models import parse, select  # noqa: E402

YAML = Path(__file__).parent.parent / "device" / "models.yaml"


def ids(ram, **kw):
    return select(parse(YAML.read_text(encoding="utf-8")), ram, **kw)


def test_16gb_gets_small_stack_without_code_model():
    got = ids(14)
    assert "qwen3.5:0.8b" in got and "qwen3.5:4b" in got
    assert not any("Ornith" in i or "Gemma4-26B" in i for i in got)


def test_32gb_gets_big_stack():
    got = ids(30)
    assert any("Gemma4-26B" in i for i in got) and any("Ornith" in i for i in got)
    assert "qwen3.5:4b" not in got  # model główny zastąpiony przez Gemmę
    assert "qwen3.5:0.8b" in got  # router zostaje


def test_candidates_are_never_selected():
    for ram in (8, 14, 30, 60):
        assert not any("e4b" in i.lower() or "ornith-1.5-9b" in i for i in ids(ram))


def test_flags_override_code_model():
    assert any("Ornith" in i for i in ids(30, with_code=True))
    assert not any("Ornith" in i for i in ids(30, with_code=False))
