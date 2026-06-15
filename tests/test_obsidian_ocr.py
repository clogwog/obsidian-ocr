"""Tests for obsidian-ocr. The LM Studio client is mocked — no model/network needed."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from obsidian_ocr import walker
from obsidian_ocr.cli import process
from obsidian_ocr.config import Config
from obsidian_ocr.sidecar import build_markdown
from obsidian_ocr.walker import Kind, sidecar_path


# --- helpers -------------------------------------------------------------


class FakeClient:
    """Stand-in for OcrClient that records calls and returns canned text."""

    def __init__(self, text="MOCK OCR TEXT"):
        self.text = text
        self.calls = 0

    def ocr_image(self, image_bytes: bytes) -> str:
        assert isinstance(image_bytes, (bytes, bytearray))
        self.calls += 1
        return self.text


def _make_png(path: Path) -> None:
    """Write a minimal valid 1x1 PNG so PyMuPDF / readers accept it."""
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\xff\xff"  # one white pixel, filter byte 0
    idat = zlib.compress(raw)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.write_bytes(png)


def _make_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def _config(base: Path) -> Config:
    return Config(base_dir=base, lmstudio_host="localhost:1234", lmstudio_model="m")


# --- sidecar path derivation --------------------------------------------


def test_sidecar_path_derivation():
    assert sidecar_path(Path("a/b/c/d/f.pdf")) == Path("a/b/c/d/f.pdf.md")
    assert sidecar_path(Path("x/photo.PNG")) == Path("x/photo.PNG.md")


# --- classification ------------------------------------------------------


@pytest.mark.parametrize(
    "name,kind",
    [
        ("a.png", Kind.IMAGE),
        ("a.JPG", Kind.IMAGE),
        ("doc.pdf", Kind.PDF),
        ("note.md", Kind.IGNORED),
        ("page.html", Kind.IGNORED),
        ("clip.mp4", Kind.UNSUPPORTED),
    ],
)
def test_classify(name, kind):
    assert walker.classify(Path(name)) is kind


def test_walk_skips_dotdirs_and_existing_sidecars(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "hidden.png").write_bytes(b"x")
    _make_png(tmp_path / "real.png")
    (tmp_path / "real.png.md").write_text("existing sidecar")  # must not be re-yielded

    items = list(walker.walk(tmp_path))
    paths = {i.path.name for i in items}
    assert paths == {"real.png"}  # hidden dir + sidecar excluded


# --- skip-if-exists / force ---------------------------------------------


def test_skips_when_sidecar_exists(tmp_path):
    _make_png(tmp_path / "img.png")
    (tmp_path / "img.png.md").write_text("already done")
    client = FakeClient()

    stats = process(_config(tmp_path), client)

    assert client.calls == 0
    assert stats.skipped_exists == 1
    assert stats.ocred == 0
    assert (tmp_path / "img.png.md").read_text() == "already done"


def test_force_regenerates(tmp_path):
    _make_png(tmp_path / "img.png")
    (tmp_path / "img.png.md").write_text("stale")
    client = FakeClient("FRESH")

    stats = process(_config(tmp_path), client, force=True)

    assert client.calls == 1
    assert stats.ocred == 1
    assert "FRESH" in (tmp_path / "img.png.md").read_text()


# --- end to end ----------------------------------------------------------


def test_end_to_end_image_and_pdf(tmp_path):
    _make_png(tmp_path / "scan.png")
    _make_pdf(tmp_path / "doc.pdf")
    (tmp_path / "notes.md").write_text("real note")  # ignored
    (tmp_path / "movie.mp4").write_bytes(b"\x00")     # unsupported
    client = FakeClient("HELLO")

    stats = process(_config(tmp_path), client)

    assert stats.ocred == 2
    assert stats.ignored == 1
    assert stats.unsupported == 1
    assert not stats.failed

    img_md = (tmp_path / "scan.png.md").read_text()
    assert "HELLO" in img_md
    assert "![[scan.png-pages/page-1.png]]" in img_md  # visible, embeddable page image
    assert "(<.scan.png-resources/scan.png>)" in img_md  # link to moved original

    pdf_md = (tmp_path / "doc.pdf.md").read_text()
    assert "HELLO" in pdf_md
    assert "![[doc.pdf-pages/page-1.png]]" in pdf_md
    assert "(<.doc.pdf-resources/doc.pdf>)" in pdf_md

    # Rendered page images land in a VISIBLE (non-dot) folder so Obsidian can embed them.
    assert (tmp_path / "scan.png-pages" / "page-1.png").exists()
    assert (tmp_path / "doc.pdf-pages" / "page-1.png").exists()

    # Each original is moved into its own sibling hidden .<name>-resources folder.
    assert not (tmp_path / "scan.png").exists()
    assert (tmp_path / ".scan.png-resources" / "scan.png").exists()
    assert not (tmp_path / "doc.pdf").exists()
    assert (tmp_path / ".doc.pdf-resources" / "doc.pdf").exists()


def test_dry_run_writes_nothing(tmp_path):
    _make_png(tmp_path / "img.png")

    stats = process(_config(tmp_path), client=None, dry_run=True)

    assert stats.ocred == 1
    assert not (tmp_path / "img.png.md").exists()


# --- markdown shape ------------------------------------------------------


def test_build_markdown_multipage_has_page_headers_and_embeds():
    md = build_markdown(
        Path("x/doc.pdf"),
        [("doc.pdf-pages/page-1.png", "one"), ("doc.pdf-pages/page-2.png", "two")],
    )
    assert "## Page 1" in md and "## Page 2" in md
    assert "![[doc.pdf-pages/page-1.png]]" in md
    assert "![[doc.pdf-pages/page-2.png]]" in md
    assert md.startswith("---")  # frontmatter
    assert "source: .doc.pdf-resources/doc.pdf" in md


def test_build_markdown_empty_ocr_gets_placeholder():
    md = build_markdown(Path("x/scan.png"), [("scan.png-pages/page-1.png", "")])
    assert "_(no text detected)_" in md
    assert "![[scan.png-pages/page-1.png]]" in md  # page still visible
