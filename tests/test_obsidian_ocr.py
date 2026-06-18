"""Tests for obsidian-ocr. The LM Studio client is mocked — no model/network needed."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from obsidian_ocr import walker
from obsidian_ocr.cli import process
from obsidian_ocr.config import Config
from obsidian_ocr.sidecar import build_image_markdown, build_pdf_markdown
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


def test_walk_skips_leftover_pages_folders(tmp_path):
    # Leftover render folders from an earlier version must not be re-OCR'd.
    _make_png(tmp_path / "scan.png")
    pages = tmp_path / "doc.pdf-pages"
    pages.mkdir()
    _make_png(pages / "page-1.png")

    paths = {i.path.name for i in walker.walk(tmp_path)}
    assert paths == {"scan.png"}  # page-1.png inside the -pages folder is skipped


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


def test_skips_pdf_when_sidecar_exists(tmp_path):
    _make_pdf(tmp_path / "doc.pdf")
    (tmp_path / "doc.pdf.md").write_text("already done")
    client = FakeClient()

    stats = process(_config(tmp_path), client)

    assert client.calls == 0          # PDF not re-rendered or re-OCR'd
    assert stats.skipped_exists == 1
    assert stats.ocred == 0
    assert (tmp_path / "doc.pdf.md").read_text() == "already done"


def test_force_regenerates(tmp_path):
    _make_png(tmp_path / "img.png")
    (tmp_path / "img.png.md").write_text("stale")
    client = FakeClient("FRESH")

    stats = process(_config(tmp_path), client, force=True)

    assert client.calls == 1
    assert stats.ocred == 1
    assert "FRESH" in (tmp_path / "img.png.md").read_text()


# --- migration from the old "move original" layout ----------------------


def test_migrates_old_layout_then_reprocesses(tmp_path):
    # Recreate the old layout for a/doc.pdf: original moved away, -pages folder, old sidecar.
    res = tmp_path / ".doc.pdf-resources"
    res.mkdir()
    _make_pdf(res / "doc.pdf")
    pages = tmp_path / "doc.pdf-pages"
    pages.mkdir()
    _make_png(pages / "page-1.png")
    (tmp_path / "doc.pdf.md").write_text("OLD SIDECAR referencing .doc.pdf-resources")
    client = FakeClient("FRESH")

    stats = process(_config(tmp_path), client)

    # Original restored in place; leftovers gone.
    assert (tmp_path / "doc.pdf").exists()
    assert not res.exists()
    assert not pages.exists()
    # Sidecar regenerated in the new format (link to in-place original, fresh OCR).
    md = (tmp_path / "doc.pdf.md").read_text()
    assert "FRESH" in md
    assert "[doc.pdf](<doc.pdf>)" in md
    assert "OLD SIDECAR" not in md
    assert stats.ocred == 1


def test_migration_skips_when_original_already_in_place(tmp_path):
    # Defensive: never clobber a file that already exists where the original would land.
    _make_pdf(tmp_path / "doc.pdf")
    res = tmp_path / ".doc.pdf-resources"
    res.mkdir()
    _make_pdf(res / "doc.pdf")
    (tmp_path / "doc.pdf.md").write_text("existing")
    client = FakeClient("X")

    process(_config(tmp_path), client)

    assert res.exists()  # left alone rather than overwriting the in-place doc.pdf


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

    # Image: sidecar embeds the image IN PLACE and holds the OCR text.
    img_md = (tmp_path / "scan.png.md").read_text()
    assert "HELLO" in img_md
    assert "![[scan.png]]" in img_md

    # PDF: sidecar links to the original PDF and holds the per-page OCR text.
    pdf_md = (tmp_path / "doc.pdf.md").read_text()
    assert "HELLO" in pdf_md
    assert "[doc.pdf](<doc.pdf>)" in pdf_md

    # Originals are left exactly where they are — nothing is moved.
    assert (tmp_path / "scan.png").exists()
    assert (tmp_path / "doc.pdf").exists()
    # No extra page/resource folders are created.
    assert not any(p.is_dir() for p in tmp_path.iterdir())


def test_image_with_no_text_leaves_marker_and_skips_on_rerun(tmp_path):
    _make_png(tmp_path / "blank.png")
    client = FakeClient("ab")  # <= 4 chars -> treated as text-less

    stats = process(_config(tmp_path), client)

    assert stats.no_text == 1
    assert stats.ocred == 0
    assert not (tmp_path / "blank.png.md").exists()      # no sidecar written
    assert (tmp_path / "blank.png").exists()             # original untouched
    assert (tmp_path / ".blank.png.notext").exists()     # hidden marker dropped

    # Re-run: the marker makes us skip without calling the model again.
    again = process(_config(tmp_path), client)
    assert client.calls == 1                             # not re-OCR'd
    assert again.skipped_exists == 1
    assert again.no_text == 0


def test_short_text_under_threshold_is_treated_as_no_text(tmp_path):
    _make_png(tmp_path / "tiny.png")
    client = FakeClient("1234")  # exactly 4 chars -> not "longer than 4"

    stats = process(_config(tmp_path), client)

    assert stats.no_text == 1
    assert not (tmp_path / "tiny.png.md").exists()
    assert (tmp_path / ".tiny.png.notext").exists()


def test_mixed_directory_some_with_text_some_without(tmp_path):
    # walk() yields in sorted-path order, so name files to fix the response order.
    for name in ("a_with.png", "b_blank.png", "c_with.png"):
        _make_png(tmp_path / name)

    class SequenceClient:
        def __init__(self, texts):
            self.texts = list(texts)
            self.calls = 0

        def ocr_image(self, image_bytes):
            text = self.texts[self.calls]
            self.calls += 1
            return text

    client = SequenceClient(["hello world", "", "more text here"])

    stats = process(_config(tmp_path), client)

    assert client.calls == 3
    assert stats.ocred == 2
    assert stats.no_text == 1
    # Each file gets its own independent outcome.
    assert (tmp_path / "a_with.png.md").exists()
    assert not (tmp_path / ".a_with.png.notext").exists()
    assert (tmp_path / ".b_blank.png.notext").exists()
    assert not (tmp_path / "b_blank.png.md").exists()
    assert (tmp_path / "c_with.png.md").exists()
    assert "hello world" in (tmp_path / "a_with.png.md").read_text()
    assert "more text here" in (tmp_path / "c_with.png.md").read_text()


def test_text_over_threshold_writes_sidecar_not_marker(tmp_path):
    _make_png(tmp_path / "doc.png")
    client = FakeClient("12345")  # 5 chars -> real text

    stats = process(_config(tmp_path), client)

    assert stats.ocred == 1
    assert (tmp_path / "doc.png.md").exists()
    assert not (tmp_path / ".doc.png.notext").exists()


def test_no_marker_written_when_ocr_errors(tmp_path):
    _make_png(tmp_path / "boom.png")

    class FailingClient:
        calls = 0

        def ocr_image(self, image_bytes):
            raise RuntimeError("model exploded")

    stats = process(_config(tmp_path), FailingClient())

    assert stats.failed == ["boom.png"]
    assert not (tmp_path / ".boom.png.notext").exists()  # only mark on clean OCR
    assert stats.no_text == 0


def test_dry_run_writes_nothing(tmp_path):
    _make_png(tmp_path / "img.png")

    stats = process(_config(tmp_path), client=None, dry_run=True)

    assert stats.ocred == 1
    assert not (tmp_path / "img.png.md").exists()


# --- markdown shape ------------------------------------------------------


def test_build_pdf_markdown_multipage_has_page_headers_and_link():
    md = build_pdf_markdown(Path("x/doc.pdf"), ["one", "two"])
    assert "## Page 1" in md and "## Page 2" in md
    assert "one" in md and "two" in md
    assert md.startswith("---")  # frontmatter
    assert "source: doc.pdf" in md
    assert "[doc.pdf](<doc.pdf>)" in md  # link to the original, in place


def test_build_pdf_markdown_empty_page_gets_placeholder():
    md = build_pdf_markdown(Path("x/scan.pdf"), [""])
    assert "_(no text detected)_" in md
    assert "[scan.pdf](<scan.pdf>)" in md


def test_build_image_markdown_embeds_image_in_place():
    md = build_image_markdown(Path("x/photo.png"), "some text")
    assert "![[photo.png]]" in md  # embedded by bare filename (left in place)
    assert "some text" in md
    assert "source: photo.png" in md
    assert "type: image" in md
