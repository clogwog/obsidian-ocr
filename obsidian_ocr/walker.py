"""Walk a vault, classify files, and decide sidecar paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
# Already text/searchable in Obsidian -> left alone entirely.
IGNORED_EXTS = {".md", ".html", ".htm", ".txt"}


class Kind(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    IGNORED = "ignored"      # already-searchable text formats
    UNSUPPORTED = "unsupported"  # e.g. video — cannot OCR


@dataclass
class WorkItem:
    path: Path
    kind: Kind
    sidecar: Path  # only meaningful for IMAGE / PDF


def classify(path: Path) -> Kind:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return Kind.IMAGE
    if ext in PDF_EXTS:
        return Kind.PDF
    if ext in IGNORED_EXTS:
        return Kind.IGNORED
    return Kind.UNSUPPORTED


def sidecar_path(path: Path) -> Path:
    """`a/b/f.pdf` -> `a/b/f.pdf.md` (visible sibling, Obsidian-searchable)."""
    return path.with_name(path.name + ".md")


def _is_sidecar(path: Path) -> bool:
    """True if `path` is itself an OCR sidecar (`<name>.<ext>.md`)."""
    if path.suffix.lower() != ".md":
        return False
    # f.pdf.md -> stem "f.pdf" still has a suffix; plain notes (f.md) do not.
    return bool(Path(path.stem).suffix)


def walk(base_dir: Path) -> Iterator[WorkItem]:
    """Yield a WorkItem for every relevant file under base_dir.

    Dot-prefixed directories (e.g. `.obsidian`, `.git`) are skipped.
    """
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(base_dir).parts):
            continue
        if _is_sidecar(path):
            continue
        kind = classify(path)
        yield WorkItem(path=path, kind=kind, sidecar=sidecar_path(path))
