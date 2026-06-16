# md_maker

> Turn a folder of academic PDFs into a clean, token-optimized Markdown vault — one command, layout-aware, MPS-accelerated.

[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.12-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20(MPS)%20%7C%20Linux%20%7C%20CPU-lightgrey.svg)](#requirements)
[![Parser](https://img.shields.io/badge/parser-MinerU%203-orange.svg)](https://github.com/opendatalab/MinerU)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)

`md_maker` is a thin orchestrator on top of [MinerU](https://github.com/opendatalab/MinerU) that takes academic PDFs (LaTeX math, two-column layouts, benchmark tables, figures) and produces clean Markdown with YAML frontmatter — ready for retrieval, prompt-stuffing, or any LLM API where token budget matters.

It was built for an NLP / Cross-Domain ABSA thesis literature workflow, but nothing in the pipeline is ABSA-specific. Frontmatter fields just default to thesis-relevant placeholders.

---

## Features

- **One command** — `md_maker paper.pdf` or `md_maker paper/`.
- **Folder mode** — drop a directory in, get a Markdown for every PDF inside.
- **Layout-aware** — MinerU `pipeline` backend preserves equations, tables, and figure refs.
- **Token-stripped** — references / bibliography section cut, running headers and footers removed, page numbers gone.
- **Frontmatter-injected** — `title`, `target_domain`, `source_domain`, `absa_subtask`, `source_pdf`, `ingested_at` (with `TODO` placeholders you fill in by hand).
- **MPS-accelerated** on Apple Silicon (auto-sets `MINERU_DEVICE_MODE=mps`).
- **Idempotent** — already-vaulted files are skipped; `--force` to reprocess.
- **Distributable** as a regular Python package via `pipx`.

---

## Requirements

- Python **3.10 – 3.12** (MinerU/torch wheels don't cover 3.13+ yet).
- macOS (Apple Silicon) recommended for MPS; CUDA and CPU also work.
- ~1 GB free disk for MinerU model weights, downloaded on first run.
- [`pipx`](https://pipx.pypa.io/) for the recommended install.

---

## Install

```bash
# macOS / Apple Silicon
brew install python@3.12 pipx
pipx ensurepath        # restart your shell after this

pipx install git+https://github.com/joistich/md_maker
```

Local dev install:

```bash
git clone https://github.com/joistich/md_maker.git
cd md_maker
pipx install -e .
```

Verify:

```bash
md_maker --version
md_maker --help
```

---

## Usage

### Single PDF

```bash
md_maker paper.pdf
```

Output:
- `./paper/Literature_Vault/paper.md`
- `./paper/assets/*.jpg`

### Folder of PDFs

```bash
cd ~/where_my_papers_live
md_maker papers/
```

Iterates every `*.pdf` directly under `papers/` (no recursion by design). Each file becomes its own sibling folder. Failures are isolated — one bad PDF won't kill the batch.

### Output layout

Each PDF produces a self-contained directory named after its stem, written under the `--out` dir (default: current working directory).

```
$PWD/
├── paper_a/
│   ├── Literature_Vault/
│   │   └── paper_a.md
│   ├── assets/
│   │   ├── img-0.jpg
│   │   └── img-1.jpg
│   └── mineru_out/         # scratch (auto-deleted unless --keep-scratch)
└── paper_b/
    ├── Literature_Vault/paper_b.md
    └── assets/img-0.png
```

Use `-o some/dir` to write everything under `some/dir/<stem>/...` instead of cwd.

### Sample frontmatter

```yaml
---
title: paper_a
target_domain: TODO
source_domain: TODO
absa_subtask: TODO
source_pdf: paper_a.pdf
ingested_at: 2026-06-14
---
```

---

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `input` | — | PDF file or directory |
| `-o, --out DIR` | `.` | Parent directory; each PDF gets its own `<stem>/` subfolder inside |
| `-b, --backend` | `pipeline` | `pipeline`, `vlm-engine`, `hybrid-engine`, … |
| `-m, --method` | `auto` | `auto`, `txt`, `ocr` |
| `-l, --lang` | `en` | Document language hint |
| `--effort` | — | `medium` or `high` (hybrid-* backends only) |
| `--force` | off | Reprocess even if `<stem>.md` already vaulted |
| `--keep-scratch` | off | Keep `mineru_out/<stem>/` for debugging |
| `--title` / `--target-domain` / `--source-domain` / `--subtask` | — | Override frontmatter fields |
| `-V, --version` | — | Print version |

---

## How it works

For every PDF, `md_maker`:

1. Creates `<out>/<stem>/{Literature_Vault,assets,mineru_out}/`.
2. Shells out to MinerU with `MINERU_DEVICE_MODE=mps` into that scratch dir.
3. Moves figure / table images from MinerU's `images/` into the paper's own `assets/`.
4. Rewrites `images/foo.jpg` references in the Markdown to `../assets/foo.jpg` (vault file sits one level deep, so the link climbs out).
5. Cuts everything after the last `References` / `Bibliography` / `Works Cited` heading.
6. Strips repeated short lines (catches running headers like *"Proceedings of ACL 2024"*), page numbers (`1`, `- 12 -`, `Page 3 of 8`), and MinerU page markers.
7. Prepends YAML frontmatter, merging anything already present.
8. Writes `<out>/<stem>/Literature_Vault/<stem>.md` and reports byte / token delta.

Code/math fences and tables are protected throughout — content inside ` ``` `, `$$…$$`, or `|`-tables is never touched.

---

## Claude Code skill

The repo ships a Claude Code skill at `.claude/skills/ingest-paper/SKILL.md`. Inside a Claude Code session in this project:

```
/ingest-paper paper.pdf
/ingest-paper papers_folder/
```

…runs the same pipeline. The skill simply delegates to `md_maker "$1"`.

---

## Troubleshooting

- **First run is slow.** MinerU pulls hundreds of MB of layout / table / OCR model weights into `~/.cache/huggingface` and `~/.mineru/`. Subsequent runs are cached.
- **`mps` fallback warnings from torch.** Harmless — a handful of ops fall back to CPU automatically.
- **Scanned PDFs come out empty.** Re-run with `-m ocr`.
- **Chart-heavy / figure-heavy papers.** Try `-b hybrid-engine --effort high` (more memory, better chart parsing).
- **"No References heading found" warning.** The cleaner couldn't match the heading regex — inspect the raw Markdown (`--keep-scratch`) and either edit the file or open an issue with the offending heading wording.
- **Already in the vault.** The file is skipped. Pass `--force` to overwrite.

---

## Development

```bash
git clone https://github.com/joistich/md_maker.git
cd md_maker
pipx install -e .

# Edit src/md_maker/*.py — changes pick up immediately.
md_maker some.pdf
```

Project layout:

```
md_maker/
├── pyproject.toml
├── README.md
├── src/md_maker/
│   ├── __init__.py
│   ├── cli.py           # argparse + dispatch
│   ├── pipeline.py      # MinerU subprocess + image move + link rewrite
│   └── cleaner.py       # refs cut, header/footer/page strip, frontmatter
└── .claude/skills/ingest-paper/SKILL.md
```

---

## Roadmap / non-goals

Wanted:
- Real token counts (tiktoken / claude tokenizer) instead of `bytes // 4`.
- BibTeX export of the cut references section.
- Optional Notion / Obsidian frontmatter shape.

Explicitly **not** planned:
- Recursive folder mode by default (use `find ... | xargs -I{} md_maker {}` if you need it).
- Backwards-compat with the old `clean_paper.py` standalone script (superseded).

---

## License

[MIT](LICENSE).

---

## Acknowledgements

- [MinerU](https://github.com/opendatalab/MinerU) — the layout-aware parser doing all the heavy lifting.
- Built on Apple Silicon (M4 Max) — MPS support via `torch>=2.2`.
