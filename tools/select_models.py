#!/usr/bin/env python3
"""Wypisuje identyfikatory modeli do pobrania dla danej ilości RAM (te same zasady co install.sh).

Zasady: tylko status `approved`; min_ram_gb/max_ram_gb ograniczają zakres pamięci (wartość z `free -g`).
Model kodu (role: code) jest pomijany poniżej 24 GB, chyba że podano --with-code-model.
Parser jest prosty (plik ma płaski format), dzięki czemu działa bez bibliotek zewnętrznych.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CODE_MIN_RAM_GB = 24


def parse(text: str) -> list[dict[str, str]]:
    models: list[dict[str, str]] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*-\s+id:\s*(\S.*?)\s*$", line)
        if m:
            models.append({"id": m.group(1)})
            continue
        m = re.match(r"^\s+(role|status|min_ram_gb|max_ram_gb):\s*([\w.-]+)", line)
        if m and models:
            models[-1][m.group(1)] = m.group(2)
    return models


def select_full(models: list[dict[str, str]], ram_gb: int, with_code: bool | None = None) -> list[dict[str, str]]:
    if with_code is None:
        with_code = ram_gb >= CODE_MIN_RAM_GB
    out = []
    for m in models:
        if m.get("status") != "approved":
            continue
        if m.get("role") == "code" and not with_code:
            continue
        if "min_ram_gb" in m and ram_gb < int(m["min_ram_gb"]) and not (m.get("role") == "code" and with_code):
            continue
        if "max_ram_gb" in m and ram_gb > int(m["max_ram_gb"]):
            continue
        out.append(m)
    return out


def select(models: list[dict[str, str]], ram_gb: int, with_code: bool | None = None) -> list[str]:
    return [m["id"] for m in select_full(models, ram_gb, with_code)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("models_yaml")
    ap.add_argument("--ram-gb", type=int, required=True)
    ap.add_argument("--with-code-model", action="store_true")
    ap.add_argument("--no-code-model", action="store_true")
    ap.add_argument("--with-roles", action="store_true", help="wypisz: rola<TAB>identyfikator")
    args = ap.parse_args(argv)
    with_code = True if args.with_code_model else False if args.no_code_model else None
    for m in select_full(parse(Path(args.models_yaml).read_text(encoding="utf-8")), args.ram_gb, with_code):
        print(f"{m.get('role', '')}\t{m['id']}" if args.with_roles else m["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
