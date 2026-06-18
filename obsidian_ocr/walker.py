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

    Raises PermissionError with a clear hint if the root can't be read — on macOS,
    `~/Documents`, `~/Desktop`, etc. are protected and the terminal app must be granted
    access (System Settings -> Privacy & Security -> Files and Folders / Full Disk Access).
    Without this guard the OS denial surfaces as a silent "scanned: 0".
    """
    try:
        import os

        os.scandir(base_dir).close()
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot read {base_dir}: {exc.strerror or exc}. On macOS, grant your "
            f"terminal app access to this folder under System Settings -> Privacy & "
            f"Security -> Files and Folders (or Full Disk Access), then reopen it."
        ) from exc

    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(base_dir).parts
        # Skip dot-dirs (.obsidian, .git, and the old `.\<name>-resources` originals folder)
        # and leftover `\<name>-pages/` render folders from earlier versions — their
        # contents are not user files and must never be OCR'd as fresh targets.
        if any(part.startswith(".") or part.endswith("-pages") for part in rel_parts):
            continue
        if _is_sidecar(path):
            continue
        kind = classify(path)
        yield WorkItem(path=path, kind=kind, sidecar=sidecar_path(path))
