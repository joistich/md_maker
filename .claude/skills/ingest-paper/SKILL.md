---
name: ingest-paper
description: Convert academic PDF(s) to token-optimized Markdown in the ABSA thesis vault. Wraps the installed `md_maker` CLI (MinerU + MPS + reference/header/footer stripping + YAML frontmatter). Use when the user types /ingest-paper <file.pdf|folder> or asks to ingest, parse, or vault PDF papers.
---

# Ingest Paper Skill

## Trigger

User invokes `/ingest-paper <file.pdf>` or `/ingest-paper <folder>`, or asks something equivalent ("ingest this paper", "vault this PDF", "process the papers in this folder").

## Workflow

```bash
md_maker "$1"
```

That single command:
- Accepts a `.pdf` file or a directory of PDFs (top-level only, no recursion).
- Creates `./<stem>/Literature_Vault/<stem>.md`, `./<stem>/assets/*`, and a scratch `./<stem>/mineru_out/` (deleted after).
- Override the parent dir with `-o some/dir` (output then lands under `some/dir/<stem>/...`).
- Uses Apple Silicon MPS via `MINERU_DEVICE_MODE=mps` (set automatically).
- Skips files already vaulted unless `--force`.

If the user passed extra hints in chat, forward them as flags:
- `--title`, `--target-domain`, `--source-domain`, `--subtask`
- `-b hybrid-engine --effort high` for chart/figure-heavy papers
- `-m ocr` for scanned PDFs

## After the run

Report:
- Vault path(s) created.
- Reminder that `target_domain`, `source_domain`, `absa_subtask` start as `TODO` in the frontmatter — user should fill in.
- Any failures from the per-file progress lines.

## Prerequisites

`md_maker` must be on PATH. If not:

```bash
brew install python@3.12 pipx
pipx ensurepath
pipx install -e /Users/aungbhonepyae/Proj/md_maker
```

## Gotchas

- **First-run model download**: hundreds of MB of MinerU weights; slow on first PDF.
- **MPS fallback warnings** from torch are harmless.
- **Scanned PDFs**: re-run with `-m ocr`.
- **Re-ingestion**: pass `--force` to overwrite an existing vault entry; otherwise the file is skipped.
