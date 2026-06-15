# obsidian-ocr

OCR every image and PDF in an Obsidian vault into **searchable markdown sidecars** using a
local [LM Studio](https://lmstudio.ai/) vision model (default `qwen/qwen3-vl-8b`), driven
through the official [`lmstudio`](https://lmstudio.ai/docs/python) python SDK.

Obsidian only full-text-searches markdown, so the text inside images and PDFs is invisible
to search. This tool walks your vault and, for each image/PDF, writes a markdown sidecar
next to it containing the OCR'd text — so Obsidian indexes and finds it.

## How sidecars work

For `a/b/c/d/f.pdf`:

1. It writes the OCR text to `a/b/c/d/f.pdf.md` — a **visible** markdown file (Obsidian
   hides dot-prefixed paths, so the `.md` itself is never dot-prefixed; that's what keeps
   it searchable).
2. On success, it moves the original into a per-file hidden folder beside the sidecar:
   `a/b/c/d/.f.pdf-resources/f.pdf`. Each file gets its own `.<name>-resources/` folder,
   so a note and its resources move together.
3. The sidecar links to the moved original with a relative markdown link
   `[f.pdf](<.f.pdf-resources/f.pdf>)`. Because the original now lives in a hidden folder,
   a plain link (angle-bracketed to tolerate spaces) is used instead of an `![[ ]]` embed,
   which Obsidian can't resolve from a hidden folder.

Resulting layout:

```
a/b/c/d/
  f.pdf.md                 <- OCR text, visible & searchable in Obsidian
  .f.pdf-resources/
    f.pdf                  <- original, moved here (hidden from the Obsidian tree)
```

If the sidecar already exists the file is skipped (use `--force` to regenerate). Once an
original has been moved into its `.<name>-resources/` folder it lives in a hidden dir, so
re-runs won't reprocess it.

## Setup

```bash
git clone git@github.com:clogwog/obsidian-ocr.git
cd obsidian-ocr
python3 -m venv venv
source venv/bin/activate
pip install -e .       # installs deps + the `obsidian-ocr` command
cp .env.example .env   # then edit OBSIDIAN_BASE_DIR
```

`pip install -e .` installs the package in editable mode and puts the `obsidian-ocr`
console command on your `PATH`. If you only want the dependencies without the command,
use `pip install -r requirements.txt` and run it as `python -m obsidian_ocr.cli` instead.

> The command is `obsidian-ocr` (with a hyphen), runnable from any directory once the
> venv is active. `obsidian_ocr` (underscore) is the Python package folder — don't try to
> execute it with `./obsidian_ocr`.

No secrets live in the code — all configuration comes from the environment, so the repo is
safe to publish.

## Configuration (environment)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OBSIDIAN_BASE_DIR` | _(required if no CLI arg)_ | Root directory to scan |
| `LMSTUDIO_HOST` | `localhost:1234` | LM Studio server `host:port` (lmstudio SDK) |
| `LMSTUDIO_MODEL` | `qwen/qwen3-vl-8b` | Vision model name |

## Usage

Start LM Studio and load the vision model, then:

```bash
obsidian-ocr                 # uses OBSIDIAN_BASE_DIR
obsidian-ocr /path/to/vault  # explicit root overrides the env var
obsidian-ocr --dry-run       # show what would be done, write nothing
obsidian-ocr --force         # regenerate even if a sidecar exists
```

An overview is printed at the end (scanned / OCR'd / skipped / unsupported / failed).

## Tests

```bash
pytest -q
```

Tests mock the LM Studio call, so no model or network is needed.
