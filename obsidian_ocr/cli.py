"""Command-line entry point and run orchestration."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .config import Config, load_config
from .pdf import render_pages
from .sidecar import build_markdown, write_sidecar
from .walker import Kind, WorkItem, walk


@dataclass
class Stats:
    scanned: int = 0
    ocred: int = 0
    skipped_exists: int = 0
    ignored: int = 0
    unsupported: int = 0
    failed: List[str] = field(default_factory=list)


def _ocr_item(item: WorkItem, client) -> List[str]:
    """Return the list of page texts for an OCR target."""
    if item.kind is Kind.IMAGE:
        return [client.ocr_image(item.path.read_bytes())]
    if item.kind is Kind.PDF:
        return [client.ocr_image(png) for png in render_pages(item.path)]
    raise ValueError(f"not an OCR target: {item.path}")


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
    for item in walk(config.base_dir):
        stats.scanned += 1

        if item.kind is Kind.IGNORED:
            stats.ignored += 1
            continue
        if item.kind is Kind.UNSUPPORTED:
            stats.unsupported += 1
            continue

        if item.sidecar.exists() and not force:
            stats.skipped_exists += 1
            continue

        rel = item.path.relative_to(config.base_dir)
        if dry_run:
            print(f"[dry-run] would OCR {rel}")
            stats.ocred += 1
            continue

        # Feedback: announce the file, then overwrite the same line with the result.
        _progress(f"… OCR  {rel}")
        try:
            pages = _ocr_item(item, client)
            write_sidecar(item.sidecar, build_markdown(item.path, pages))
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
    stats = process(config, client, force=args.force, dry_run=args.dry_run)
    print_overview(stats, time.monotonic() - start)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
