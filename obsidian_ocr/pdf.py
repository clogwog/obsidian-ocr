"""Render PDF pages to PNG bytes using PyMuPDF (no system poppler needed)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Tuple

# ~150 DPI gives a good legibility/size trade-off for OCR (72 dpi base * 2.08).
_RENDER_ZOOM = 2.08


def render_pages(pdf_path: Path) -> Iterator[Tuple[int, int, bytes]]:
    """Yield (page_number, total_pages, png_bytes) for each page of the PDF."""
    import fitz  # PyMuPDF

    matrix = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
    with fitz.open(pdf_path) as doc:
        total = doc.page_count
        for index, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(matrix=matrix)
            yield index, total, pixmap.tobytes("png")
