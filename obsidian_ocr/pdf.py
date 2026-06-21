"""Per-page PDF access using PyMuPDF (no system poppler needed).

For each page we prefer any **embedded text layer** (e.g. a PDF already OCR'd by an app
like Scanner Pro, or a born-digital PDF) — that text is exact and free. Only when a page
has no usable text layer do we render it to a PNG so the caller can OCR the image.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# ~150 DPI gives a good legibility/size trade-off for OCR (72 dpi base * 2.08).
_RENDER_ZOOM = 2.08


@dataclass
class PdfPage:
    number: int
    total: int
    # Exactly one of these is set: `text` when the page had a usable embedded text layer,
    # otherwise `image_png` (the rendered page) for the caller to OCR.
    text: Optional[str] = None
    image_png: Optional[bytes] = None


def iter_pages(pdf_path: Path, *, min_text_chars: int) -> Iterator[PdfPage]:
    """Yield a PdfPage per page, preferring the embedded text layer.

    A page whose extracted text has more than `min_text_chars` non-whitespace characters
    is returned as text (no rendering); otherwise it is rendered to PNG bytes for OCR.
    """
    import fitz  # PyMuPDF

    matrix = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
    with fitz.open(pdf_path) as doc:
        total = doc.page_count
        for index, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if len(text) > min_text_chars:
                yield PdfPage(number=index, total=total, text=text)
            else:
                pixmap = page.get_pixmap(matrix=matrix)
                yield PdfPage(number=index, total=total, image_png=pixmap.tobytes("png"))
