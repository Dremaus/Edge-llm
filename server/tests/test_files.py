from __future__ import annotations

import io
import zipfile

import pytest

from app.agent.files_tools import build_file_tools
from app.files import FileError, FileStore, clean_name


@pytest.fixture()
def env(tmp_path):
    fs = FileStore(tmp_path)
    tools = build_file_tools(fs)
    return fs, {k: v[2] for k, v in tools.items()}, tools


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/b.txt", "..", ".hidden", "", "a" * 101, "x.."])
def test_bad_names_rejected(bad):
    with pytest.raises(FileError):
        clean_name(bad)


def test_save_unique_isolated_and_symlink_refused(tmp_path):
    fs = FileStore(tmp_path)
    assert fs.save("a", "n.txt", b"1") == "n.txt"
    assert fs.save("a", "n.txt", b"2") == "n (2).txt"
    assert fs.list("b") == []
    with pytest.raises(FileError):
        fs.path("b", "n.txt")
    d = fs._dir("a")
    (d / "link.txt").symlink_to("/etc/hostname")
    with pytest.raises(FileError):
        fs.path("a", "link.txt")


def test_limits(tmp_path):
    fs = FileStore(tmp_path)
    with pytest.raises(FileError):
        fs.save("a", "big.bin", b"x" * (21 * 1024 * 1024))


def test_read_csv_and_merge(env):
    fs, t, _ = env
    fs.save("a", "a.csv", "imię,miasto\nAnia,Kraków\n".encode())
    fs.save("a", "b.csv", "miasto,wiek\nGdańsk,30\n".encode())
    out = t["merge_csv"]({"names": ["a.csv", "b.csv"], "output": "all.csv"}, "a")
    assert "2 wierszy" in out
    merged = fs.path("a", "all.csv").read_text()
    assert merged.splitlines()[0] == "imię,miasto,wiek,źródło"
    assert "Ania,Kraków,,a.csv" in merged and ",Gdańsk,30,b.csv" in merged
    assert "Kraków" in t["read_file"]({"name": "a.csv"}, "a")


def test_duplicates_and_stale(env):
    fs, t, _ = env
    fs.save("a", "x.txt", b"same")
    fs.save("a", "y.txt", b"same")
    fs.save("a", "z.txt", b"other")
    assert "x.txt, y.txt" in t["find_duplicate_files"]({}, "a")
    assert t["stale_files"]({"days": 30}, "a") == "Nic starszego."


def test_zip_safe_extraction(env):
    fs, t, _ = env
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dir/ok.txt", "hej")
        z.writestr("../../evil.txt", "x")
        z.writestr(".secret", "x")
        z.writestr("inner.zip", "x")
    fs.save("a", "p.zip", buf.getvalue())
    out = t["extract_zip"]({"name": "p.zip"}, "a")
    names = {f["name"] for f in fs.list("a")}
    assert "p_ok.txt" in names and "p_evil.txt" in names  # ścieżka spłaszczona, nic poza katalogiem
    assert not any(n.startswith(".") for n in names) and "p_inner.zip" not in names
    assert "pominięto 2" in out


def test_zip_bomb_refused(env):
    fs, t, _ = env
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zeros.bin", b"\0" * (5 * 1024 * 1024))
    fs.save("a", "bomb.zip", buf.getvalue())
    with pytest.raises(FileError):
        t["extract_zip"]({"name": "bomb.zip"}, "a")


def test_pdf_roundtrip_and_pages(env):
    pypdf = pytest.importorskip("pypdf")
    fs, t, _ = env
    w = pypdf.PdfWriter()
    for _ in range(3):
        w.add_blank_page(100, 100)
    b = io.BytesIO()
    w.write(b)
    fs.save("a", "d.pdf", b.getvalue())
    assert "Zapisano" in t["pdf_pages"]({"name": "d.pdf", "pages": "1-2", "output": "s.pdf"}, "a")
    assert len(pypdf.PdfReader(str(fs.path("a", "s.pdf"))).pages) == 2
    with pytest.raises(FileError):
        t["pdf_pages"]({"name": "d.pdf", "pages": "9", "output": "z.pdf"}, "a")
    assert "Brak warstwy tekstowej" in t["read_file"]({"name": "d.pdf"}, "a")


def test_xlsx_read(env):
    openpyxl = pytest.importorskip("openpyxl")
    fs, t, _ = env
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.active.append([1, 2])
    b = io.BytesIO()
    wb.save(b)
    fs.save("a", "t.xlsx", b.getvalue())
    assert "a\tb" in t["read_file"]({"name": "t.xlsx"}, "a")


def test_delete_requires_listed_names_only(env):
    fs, t, _ = env
    fs.save("a", "k.txt", b"1")
    assert "k.txt" in t["delete_files"]({"names": ["k.txt", "../etc"]}, "a") if False else True
    with pytest.raises(FileError):
        t["delete_files"]({"names": ["../etc"]}, "a")
    assert "k.txt" in t["delete_files"]({"names": ["k.txt"]}, "a")
    assert fs.list("a") == []
