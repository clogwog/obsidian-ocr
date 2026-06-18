"""Command-line entry point and run orchestration."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import Config, load_config
from .migrate import migrate
from .pdf import render_pages
from .sidecar import (
    build_image_markdown,
    build_pdf_markdown,
    notext_marker_path,
    write_notext_marker,
    write_sidecar,
)
from .walker import Kind, WorkItem, walk

# An image whose OCR yields this few non-whitespace characters is treated as text-less.
MIN_TEXT_CHARS = 4


@dataclass
class Stats:
    scanned: int = 0
    ocred: int = 0
    skipped_exists: int = 0
    no_text: int = 0
    ignored: int = 0
    unsupported: int = 0
    failed: List[str] = field(default_factory=list)


def _ocr_pdf(item: WorkItem, client, on_page=None) -> List[str]:
    """Render each PDF page to an image, OCR it, and return the text per page.

    The rendered images are transient — only their OCR text is kept. `on_page(page,
    total)` is called before each page is sent to the model so the caller can show
    progress (one model call per page).
    """
    texts = []
    for page, total, png in render_pages(item.path):
        if on_page:
            on_page(page, total)
        texts.append(client.ocr_image(png))
    return texts


def _progress(msg: str) -> None:
    """Write an in-progress line (no newline) that a later _result overwrites."""
    # \r returns to column 0; \033[K clears to end of line for clean overwrites.
    sys.stdout.write(f"\r\033[K{msg}")
    sys.stdout.flush()


def _result(msg: str) -> None:
    """Overwrite the current progress line with a final result, then commit it."""
    sys.stdout.write(f"\r\033[K{msg}\n")
    sys.stdout.flush()


def process(
    config: Config,
    client,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> Stats:
    """Walk the vault and OCR every image/PDF lacking a sidecar."""
    stats = Stats()

    # Reconcile any leftovers from the old "move original" layout before scanning, so
    # restored files get processed in the same run.
    mig = migrate(config.base_dir, dry_run=dry_run)
    if mig.restored or mig.pages_removed or mig.sidecars_removed:
        print(
            f"Migrated old layout: restored {mig.restored} original(s), "
            f"removed {mig.pages_removed} -pages folder(s) and "
            f"{mig.sidecars_removed} stale sidecar(s)."
        )
    for warning in mig.warnings:
        print(f"  ! {warning}")

    for item in walk(config.base_dir):
        stats.scanned += 1

        if item.kind is Kind.IGNORED:
            stats.ignored += 1
            continue
        if item.kind is Kind.UNSUPPORTED:
            stats.unsupported += 1
            continue

        # Skip if already done: a sidecar exists, or (for an image) a prior run already
        # found it text-less and left a `.notext` marker.
        if not force and (
            item.sidecar.exists()
            or (item.kind is Kind.IMAGE and notext_marker_path(item.path).exists())
        ):
            stats.skipped_exists += 1
            continue

        rel = item.path.relative_to(config.base_dir)
        if dry_run:
            print(f"[dry-run] would OCR {rel}")
            stats.ocred += 1
            continue

        # Feedback: announce the file, then overwrite the same line with the result.
        # PDFs report per-page progress since each page is a separate model call.
        def on_page(page, total, _rel=rel):
            suffix = f" (page {page}/{total})" if total > 1 else ""
            _progress(f"… OCR  {_rel}{suffix}")

        _progress(f"… OCR  {rel}")
        try:
            if item.kind is Kind.IMAGE:
                on_page(1, 1)
                text = client.ocr_image(item.path.read_bytes())
                # Too little text to be worth a sidecar -> leave the image untouched but
                # drop a hidden `.notext` marker so we never re-OCR it. Reached only when
                # ocr_image returned without raising, so the marker means "checked, empty".
                if len(text.strip()) <= MIN_TEXT_CHARS:
                    write_notext_marker(item.path)
                    _result(f"·  skip {rel} (no text)")
                    stats.no_text += 1
                    continue
                write_sidecar(item.sidecar, build_image_markdown(item.path, text))
            else:  # Kind.PDF -- always write one sidecar, leave the PDF in place.
                page_texts = _ocr_pdf(item, client, on_page=on_page)
                write_sidecar(item.sidecar, build_pdf_markdown(item.path, page_texts))
            _result(f"✓ OCR  {rel} -> {item.sidecar.name}")
            stats.ocred += 1
        except Exception as exc:  # one bad file must not abort the run
            _result(f"✗ FAIL {rel}: {exc}")
            stats.failed.append(str(rel))

    return stats


def print_overview(stats: Stats, elapsed: float) -> None:
    print("\n=== obsidian-ocr overview ===")
    print(f"  scanned:        {stats.scanned}")
    print(f"  OCR'd:          {stats.ocred}")
    print(f"  skipped (done): {stats.skipped_exists}")
    print(f"  no text (left): {stats.no_text}")
    print(f"  ignored (text): {stats.ignored}")
    print(f"  unsupported:    {stats.unsupported}")
    print(f"  failed:         {len(stats.failed)}")
    for name in stats.failed:
        print(f"    - {name}")
    print(f"  elapsed:        {elapsed:.1f}s")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="obsidian-ocr",
        description="OCR images and PDFs into Obsidian-searchable markdown sidecars.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        help="Vault directory to scan (overrides OBSIDIAN_BASE_DIR).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate sidecars even if they exist."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would happen; write nothing."
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.root)
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # unreachable; parser.error exits

    client = None
    if not args.dry_run:
        from .lmstudio import OcrClient

        client = OcrClient(config.lmstudio_host, config.lmstudio_model)

    print(f"Scanning {config.base_dir} (model={config.lmstudio_model})")
    start = time.monotonic()
    try:
        stats = process(config, client, force=args.force, dry_run=args.dry_run)
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print_overview(stats, time.monotonic() - start)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
