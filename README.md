# obsidian-ocr

OCR every image and PDF in an Obsidian vault into **searchable markdown sidecars** using a
local [LM Studio](https://lmstudio.ai/) vision model (default `qwen/qwen3-vl-8b`), driven
through the official [`lmstudio`](https://lmstudio.ai/docs/python) python SDK.

Obsidian only full-text-searches markdown, so the text inside images and PDFs is invisible
to search. This tool walks your vault and, for each image/PDF, writes a markdown sidecar
next to it containing the OCR'd text — so Obsidian indexes and finds it.

## How sidecars work

Originals are **never moved** — the tool only writes a `<name>.md` sidecar next to each
file. The `.md` is a visible, Obsidian-searchable sibling (only dot-*prefixed* paths are
hidden; `f.pdf.md` is not), so its OCR'd text gets indexed.

**Images** (`a/b/c/d/f.png`):

- OCR the image.
- If it contains **no usable text** (4 or fewer non-whitespace characters), the image is
  **left exactly as it is** — no sidecar is written. A hidden, empty `.<name>.notext`
  marker is dropped next to it so re-runs skip it instead of re-OCRing (the marker is only
  written when OCR completed without error).
- If text is found, write `a/b/c/d/f.png.md` containing the OCR text and embedding the
  image **in place** with `![[f.png]]`.

**PDFs** (`a/b/c/d/f.pdf`):

- For each page, if it already has an **embedded text layer** (a born-digital PDF, or one
  already OCR'd by an app like Scanner Pro), that text is used directly — exact and
  instant, no model call.
- Only pages with no usable text layer are rendered to an image and OCR'd (the rendered
  images are transient — only the text is kept).
- Write a single `a/b/c/d/f.pdf.md` with one `## Page N` section per page (pages with no
  detected text show a `_(no text detected)_` placeholder) and a link back to the
  original: `[f.pdf](<f.pdf>)`.
- The PDF is left where it is.

Resulting layout:

```
a/b/c/d/
  f.png        <- original image, untouched
  f.png.md     <- OCR text + embedded image (only if the image had text)
  f.pdf        <- original PDF, untouched
  f.pdf.md     <- per-page OCR text + link to f.pdf
```

If a sidecar already exists the file is skipped (use `--force` to regenerate). Text-less
images get a `.notext` marker (see above) so they are skipped too, not re-OCR'd.

### Migration from older versions

An earlier version *moved* originals into hidden `.<name>-resources/` folders and wrote
rendered pages into `<name>-pages/` folders. On startup the tool automatically reconciles
any such leftovers: it moves each original back into place, deletes the `-pages/` folder,
and removes the stale old-format sidecar so the file is reprocessed normally in the same
run. This is keyed on the `.<name>-resources/` folder, so once migrated a file is never
touched again. `--dry-run` reports what migration would do without changing anything.

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
| `LMSTUDIO_MAX_TOKENS` | `4096` | Max tokens generated per image/page (caps runaway generation) |

## Usage

Start LM Studio and load the vision model, then:

```bash
obsidian-ocr                 # uses OBSIDIAN_BASE_DIR
obsidian-ocr /path/to/vault  # explicit root overrides the env var
obsidian-ocr --dry-run       # show what would be done, write nothing
obsidian-ocr --force         # regenerate even if a sidecar exists
```

An overview is printed at the end (scanned / OCR'd / skipped / no-text / ignored /
unsupported / failed).

## Tests

```bash
pytest -q
```

Tests mock the LM Studio call, so no model or network is needed.
