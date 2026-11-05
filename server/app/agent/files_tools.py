"""Narzędzia agenta do dokumentów: odczyt, porządki, scalanie, rozpakowanie, usuwanie.

Zasady: wszystko dzieje się w katalogu urządzenia (FileStore). Odczyt jest bez zgody,
tworzenie plików wymaga zgody (WRITE), usuwanie — zawsze zgody (IRREVERSIBLE).
Treść plików wraca do modelu w ograniczniku UNTRUSTED (robi to runner).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from typing import Any

from ..files import FileError, FileStore, clean_name, human_age_days
from .policy import Risk, ToolSpec

try:  # opcjonalne: bez bibliotek narzędzia PDF/XLSX po prostu nie są rejestrowane
    import pypdf
except ImportError:  # pragma: no cover
    pypdf = None
try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None

MAX_READ_CHARS = 6000
MAX_PDF_PAGES = 30
MAX_XLSX_ROWS = 50
MAX_ZIP_ENTRIES = 200
MAX_ZIP_TOTAL = 50 * 1024 * 1024
MAX_ZIP_RATIO = 100

LIST_FILES = ToolSpec("list_files", "Pokazuje pliki użytkownika (nazwa, rozmiar, wiek w dniach).", Risk.READ)
READ_FILE = ToolSpec("read_file", "Czyta plik tekstowy, CSV, PDF lub XLSX (początek).", Risk.READ)
FIND_DUPLICATES = ToolSpec("find_duplicate_files", "Znajduje pliki o identycznej treści.", Risk.READ)
STALE_FILES = ToolSpec("stale_files", "Raport plików nieruszanych od N dni (niczego nie usuwa).", Risk.READ)
MERGE_CSV = ToolSpec("merge_csv", "Scala pliki CSV po nazwach kolumn do nowego pliku.", Risk.WRITE)
EXTRACT_ZIP = ToolSpec("extract_zip", "Rozpakowuje archiwum ZIP (bezpiecznie, 1 poziom).", Risk.WRITE)
PDF_PAGES = ToolSpec("pdf_pages", "Tworzy nowy PDF z wybranych stron (np. 1-3,5) albo scala PDF-y.", Risk.WRITE)
DELETE_FILES = ToolSpec("delete_files", "Usuwa wskazane pliki użytkownika. Nieodwracalne.", Risk.IRREVERSIBLE, 3)


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_STR = {"type": "string"}
_NAMES = {"type": "array", "items": _STR}


def _names(args: dict[str, Any], key: str = "names", limit: int = 50) -> list[str]:
    raw = args.get(key)
    if not isinstance(raw, list) or not raw or len(raw) > limit:
        raise FileError(f"Pole {key} musi być listą 1–{limit} nazw")
    return [clean_name(str(n)) for n in raw]


def build_file_tools(files: FileStore) -> dict[str, tuple[ToolSpec, dict[str, Any], Any]]:
    def list_files(_a, dev):
        rows = files.list(dev)
        return "\n".join(f"- {f['name']} ({f['size']} B, {human_age_days(f['modified'])} dni)" for f in rows) or "Brak plików."

    def read_pdf(path, start: int) -> str:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            return "PDF jest zaszyfrowany — nie czytam."
        total = len(reader.pages)
        parts = []
        has_text = False
        for i in range(start, min(total, start + MAX_PDF_PAGES)):
            page_text = reader.pages[i].extract_text() or ""
            has_text = has_text or bool(page_text.strip())
            parts.append(f"[strona {i + 1}/{total}]\n{page_text}")
        return "\n".join(parts) if has_text else "Brak warstwy tekstowej (skan?) — wymagany OCR."

    def read_xlsx(path) -> str:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:5]:
            out.append(f"[arkusz {ws.title}]")
            for n, row in enumerate(ws.iter_rows(values_only=True)):
                if n >= MAX_XLSX_ROWS:
                    out.append("…")
                    break
                out.append("\t".join("" if c is None else str(c) for c in row))
        wb.close()
        return "\n".join(out)

    def read_file(args, dev):
        path = files.path(dev, str(args.get("name", "")))
        ext = path.suffix.lower()
        if ext == ".pdf":
            if pypdf is None:
                return "Obsługa PDF niedostępna na tym urządzeniu."
            return read_pdf(path, max(0, int(args.get("start_page", 1)) - 1))[:MAX_READ_CHARS * 3]
        if ext == ".xlsx":
            if openpyxl is None:
                return "Obsługa XLSX niedostępna na tym urządzeniu."
            return read_xlsx(path)[:MAX_READ_CHARS]
        if ext in {".txt", ".md", ".csv", ".json", ".log", ".tsv"}:
            return path.read_bytes()[: MAX_READ_CHARS * 4].decode("utf-8", errors="replace")[:MAX_READ_CHARS]
        return "Nieobsługiwany typ pliku (czytam: txt, md, csv, json, pdf, xlsx)."

    def sha(path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def duplicates(_a, dev):
        groups: dict[str, list[str]] = defaultdict(list)
        for f in files.list(dev):
            groups[sha(files.path(dev, f["name"]))].append(f["name"])
        dup = [g for g in groups.values() if len(g) > 1]
        return "\n".join("- " + ", ".join(g) for g in dup) or "Brak duplikatów."

    def stale(args, dev):
        days = max(1, min(int(args.get("days", 90)), 3650))
        old = [f for f in files.list(dev) if human_age_days(f["modified"]) >= days]
        return "\n".join(f"- {f['name']} ({human_age_days(f['modified'])} dni)" for f in old) or "Nic starszego."

    def merge_csv(args, dev):
        names = _names(args, limit=20)
        out_name = clean_name(str(args.get("output", "scalone.csv")))
        rows: list[dict[str, str]] = []
        columns: list[str] = []
        for n in names:
            text = files.path(dev, n).read_bytes().decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for c in reader.fieldnames or []:
                if c not in columns:
                    columns.append(c)
            for r in reader:
                rows.append({**{k: v for k, v in r.items() if k is not None}, "źródło": n})
                if len(rows) > 100_000:
                    raise FileError("Za dużo wierszy")
        if not rows:
            raise FileError("Brak danych do scalenia")
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[*columns, "źródło"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        saved = files.save(dev, out_name, buf.getvalue().encode())
        return f"Zapisano {saved}: {len(rows)} wierszy z {len(names)} plików."

    def extract_zip(args, dev):
        name = clean_name(str(args.get("name", "")))
        path = files.path(dev, name)
        stem = re.sub(r"\.zip$", "", name, flags=re.I)
        done = skipped = total = 0
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise FileError("Za dużo plików w archiwum")
            for info in infos:
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_ZIP_TOTAL or (info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO):
                    raise FileError("Archiwum wygląda na bombę rozpakowującą")
                flat = re.sub(r"[^\w.\- ()]", "_", info.filename.replace("\\", "/").split("/")[-1])
                if not flat or flat.startswith(".") or flat.lower().endswith(".zip") or (info.external_attr >> 28) == 0xA:
                    skipped += 1  # puste nazwy, ukryte, zagnieżdżone ZIP-y i dowiązania pomijamy
                    continue
                files.save(dev, f"{stem}_{flat}"[:100], zf.read(info))
                done += 1
        return f"Rozpakowano {done} plików, pominięto {skipped}."

    def pdf_pages(args, dev):
        out_name = clean_name(str(args.get("output", "wynik.pdf")))
        writer = pypdf.PdfWriter()
        if args.get("merge"):
            for n in _names(args, "merge", 20):
                r = pypdf.PdfReader(str(files.path(dev, n)))
                if r.is_encrypted:
                    raise FileError("Zaszyfrowany PDF")
                for page in r.pages:
                    writer.add_page(page)
        else:
            r = pypdf.PdfReader(str(files.path(dev, str(args.get("name", "")))))
            if r.is_encrypted:
                raise FileError("Zaszyfrowany PDF")
            wanted: list[int] = []
            for part in str(args.get("pages", "")).split(","):
                m = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
                if not m:
                    raise FileError("Strony podaj jako np. 1-3,5")
                a, b = int(m.group(1)), int(m.group(2) or m.group(1))
                wanted += list(range(a, b + 1))
            if not wanted or len(wanted) > 500 or any(p < 1 or p > len(r.pages) for p in wanted):
                raise FileError("Strony poza zakresem")
            for p in wanted:
                writer.add_page(r.pages[p - 1])
        buf = io.BytesIO()
        writer.write(buf)
        saved = files.save(dev, out_name, buf.getvalue())
        return f"Zapisano {saved} ({len(writer.pages)} stron)."

    def delete_files(args, dev):
        names = _names(args, limit=20)
        gone = [n for n in names if files.delete(dev, n)]
        return f"Usunięto: {', '.join(gone) or 'nic'}."

    reg: dict[str, tuple[ToolSpec, dict[str, Any], Any]] = {
        "list_files": (LIST_FILES, _obj({}), list_files),
        "read_file": (READ_FILE, _obj({"name": _STR, "start_page": {"type": "integer"}}, ["name"]), read_file),
        "find_duplicate_files": (FIND_DUPLICATES, _obj({}), duplicates),
        "stale_files": (STALE_FILES, _obj({"days": {"type": "integer"}}), stale),
        "merge_csv": (MERGE_CSV, _obj({"names": _NAMES, "output": _STR}, ["names"]), merge_csv),
        "extract_zip": (EXTRACT_ZIP, _obj({"name": _STR}, ["name"]), extract_zip),
        "delete_files": (DELETE_FILES, _obj({"names": _NAMES}, ["names"]), delete_files),
    }
    if pypdf is not None:
        reg["pdf_pages"] = (
            PDF_PAGES,
            _obj({"name": _STR, "pages": _STR, "merge": _NAMES, "output": _STR}),
            pdf_pages,
        )
    return reg
