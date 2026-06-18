"""One-time migration from the old layout to the in-place layout.

Earlier versions **moved** each original into a hidden `.<name>-resources/` folder,
wrote rendered pages into a visible `<name>-pages/` folder, and emitted an old-format
sidecar referencing both. The current tool leaves originals in place, so this pass
reconciles a vault touched by the old version:

  for `a/b/f.pdf`:
    .f.pdf-resources/f.pdf   -> moved back to  a/b/f.pdf
    f.pdf-pages/             -> deleted
    f.pdf.md (old format)    -> deleted, so normal processing regenerates it

It is keyed on the existence of a `.<name>-resources/` folder, so once a file is
migrated a re-run won't touch it again.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

RESOURCE_SUFFIX = "-resources"
PAGES_SUFFIX = "-pages"


@dataclass
class MigrationStats:
    restored: int = 0          # originals moved back into place
    pages_removed: int = 0     # leftover <name>-pages/ folders deleted
    sidecars_removed: int = 0  # stale old-format sidecars deleted
    warnings: List[str] = field(default_factory=list)


def _resource_dirs(base_dir: Path) -> List[Path]:
    """All `.<name>-resources` folders under base_dir (sorted, deepest-first is irrelevant)."""
    return sorted(
        p
        for p in base_dir.rglob(f"*{RESOURCE_SUFFIX}")
        if p.is_dir() and p.name.startswith(".")
    )


def migrate(base_dir: Path, *, dry_run: bool = False) -> MigrationStats:
    """Restore originals, drop leftover render folders and stale sidecars."""
    stats = MigrationStats()

    for res_dir in _resource_dirs(base_dir):
        # `.f.pdf-resources` -> original filename `f.pdf`
        name = res_dir.name[1:][: -len(RESOURCE_SUFFIX)]
        parent = res_dir.parent
        original_src = res_dir / name
        original_dest = parent / name
        pages_dir = parent / f"{name}{PAGES_SUFFIX}"
        old_sidecar = parent / f"{name}.md"
        rel = res_dir.relative_to(base_dir)

        if not original_src.exists():
            stats.warnings.append(f"{rel}: no original named {name!r} inside; left as-is")
            continue
        if original_dest.exists():
            stats.warnings.append(
                f"{rel}: {name!r} already exists in place; left the resources folder alone"
            )
            continue

        if dry_run:
            print(f"[dry-run] would restore {parent.relative_to(base_dir)}/{name}")
            stats.restored += 1
            if pages_dir.is_dir():
                stats.pages_removed += 1
            if old_sidecar.exists():
                stats.sidecars_removed += 1
            continue

        # 1) move the original back beside where its sidecar lives
        shutil.move(str(original_src), str(original_dest))
        stats.restored += 1
        # 2) drop the now-empty (expected) resources folder
        shutil.rmtree(res_dir, ignore_errors=True)
        # 3) delete the leftover rendered-pages folder
        if pages_dir.is_dir():
            shutil.rmtree(pages_dir, ignore_errors=True)
            stats.pages_removed += 1
        # 4) delete the stale old-format sidecar so normal processing regenerates it
        if old_sidecar.exists():
            old_sidecar.unlink()
            stats.sidecars_removed += 1

    return stats
