"""Environment-driven configuration. No secrets live in source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional
    def load_dotenv(*_args, **_kwargs):
        return False


DEFAULT_HOST = "localhost:1234"
DEFAULT_MODEL = "qwen/qwen3-vl-8b"
# Hard ceiling on tokens generated per image/page, so a runaway generation can't hang the
# run. Generous enough for a dense full page; raise via LMSTUDIO_MAX_TOKENS if needed.
DEFAULT_MAX_TOKENS = 4096


@dataclass
class Config:
    """Resolved runtime configuration."""

    base_dir: Path
    lmstudio_host: str
    lmstudio_model: str
    lmstudio_max_tokens: int


def load_config(cli_root: Optional[str] = None) -> Config:
    """Build a Config from the environment, with an optional CLI root override.

    Resolution order for the scan root: explicit CLI arg > OBSIDIAN_BASE_DIR env.
    Raises ValueError if neither is provided.
    """
    load_dotenv()

    root = cli_root or os.environ.get("OBSIDIAN_BASE_DIR")
    if not root:
        raise ValueError(
            "No scan root given. Pass a directory argument or set OBSIDIAN_BASE_DIR."
        )

    base_dir = Path(root).expanduser()
    if not base_dir.is_dir():
        raise ValueError(f"Scan root is not a directory: {base_dir}")

    try:
        max_tokens = int(os.environ.get("LMSTUDIO_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    except ValueError:
        raise ValueError("LMSTUDIO_MAX_TOKENS must be an integer.")

    return Config(
        base_dir=base_dir,
        lmstudio_host=os.environ.get("LMSTUDIO_HOST", DEFAULT_HOST),
        lmstudio_model=os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL),
        lmstudio_max_tokens=max_tokens,
    )
