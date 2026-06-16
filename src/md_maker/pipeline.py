"""Per-PDF ingestion: MinerU -> image move + link rewrite -> cleaner -> vault."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .cleaner import clean


@dataclass
class Config:
    vault: Path
    assets: Path
    scratch: Path
    backend: str = "pipeline"
    method: str = "auto"
    lang: str = "en"
    effort: str | None = None
    force: bool = False
    keep_scratch: bool = False
    title: str = ""
    target_domain: str = ""
    source_domain: str = ""
    subtask: str = ""


@dataclass
class Done:
    out_path: Path
    bytes_in: int
    bytes_out: int
    n_images: int


@dataclass
class Skipped:
    out_path: Path


@dataclass
class Failed:
    reason: str


Result = Done | Skipped | Failed


IMG_LINK_RE = re.compile(r"images/([^)\s\"']+)")


def _find_mineru() -> str:
    candidate = Path(sys.executable).parent / "mineru"
    if candidate.exists():
        return str(candidate)
    on_path = shutil.which("mineru")
    if on_path:
        return on_path
    raise FileNotFoundError(
        "mineru executable not found. "
        "It should ship as a dependency of md-maker; try `pipx reinstall md-maker`."
    )


def _run_mineru(pdf: Path, cfg: Config) -> subprocess.CompletedProcess[str]:
    args = [
        _find_mineru(),
        "-p", str(pdf),
        "-o", str(cfg.scratch),
        "-b", cfg.backend,
        "-m", cfg.method,
        "-l", cfg.lang,
        "-f", "true",
        "-t", "true",
    ]
    if cfg.effort and cfg.backend.startswith("hybrid"):
        args.extend(["--effort", cfg.effort])
    env = os.environ.copy()
    env.setdefault("MINERU_DEVICE_MODE", "mps")
    return subprocess.run(args, env=env, capture_output=True, text=True)


def _locate_markdown(scratch: Path, stem: str) -> Path | None:
    preferred = scratch / stem / "auto" / f"{stem}.md"
    if preferred.exists():
        return preferred
    matches = list((scratch / stem).rglob("*.md")) if (scratch / stem).exists() else []
    return matches[0] if matches else None


def _move_images(src_dir: Path, assets: Path, stem: str) -> int:
    src_images = src_dir / "images"
    if not src_images.is_dir():
        return 0
    assets.mkdir(parents=True, exist_ok=True)
    n = 0
    for img in src_images.iterdir():
        if not img.is_file():
            continue
        dst = assets / f"{stem}__{img.name}"
        shutil.move(str(img), str(dst))
        n += 1
    return n


def ingest_one(pdf: Path, cfg: Config) -> Result:
    pdf = pdf.resolve()
    stem = pdf.stem
    cfg.vault.mkdir(parents=True, exist_ok=True)
    cfg.assets.mkdir(parents=True, exist_ok=True)
    cfg.scratch.mkdir(parents=True, exist_ok=True)

    out_path = cfg.vault / f"{stem}.md"
    if out_path.exists() and not cfg.force:
        return Skipped(out_path)

    proc = _run_mineru(pdf, cfg)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return Failed("mineru failed: " + " | ".join(tail))

    md_path = _locate_markdown(cfg.scratch, stem)
    if md_path is None:
        return Failed(f"mineru produced no markdown under {cfg.scratch}/{stem}")
    src_dir = md_path.parent

    n_images = _move_images(src_dir, cfg.assets, stem)

    raw = md_path.read_text(encoding="utf-8", errors="replace")
    bytes_in = len(raw.encode("utf-8"))

    raw = IMG_LINK_RE.sub(lambda m: f"{cfg.assets.name}/{stem}__{m.group(1)}", raw)

    cleaned, _ = clean(
        raw,
        title=cfg.title or stem,
        target_domain=cfg.target_domain,
        source_domain=cfg.source_domain,
        subtask=cfg.subtask,
        source_pdf=pdf.name,
    )
    out_path.write_text(cleaned, encoding="utf-8")
    bytes_out = len(cleaned.encode("utf-8"))

    if not cfg.keep_scratch:
        shutil.rmtree(cfg.scratch / stem, ignore_errors=True)

    return Done(out_path, bytes_in, bytes_out, n_images)


def ingest_folder(folder: Path, cfg: Config) -> tuple[int, int, int]:
    pdfs = sorted(p for p in folder.glob("*.pdf") if p.is_file())
    if not pdfs:
        print(f"md_maker: no PDFs in {folder}", file=sys.stderr)
        return 0, 0, 0

    done = skipped = failed = 0
    for i, pdf in enumerate(pdfs, 1):
        prefix = f"[{i}/{len(pdfs)}] {pdf.name}"
        try:
            result = ingest_one(pdf, cfg)
        except Exception as e:
            print(f"{prefix} ... FAILED: {e}", file=sys.stderr)
            failed += 1
            continue

        if isinstance(result, Done):
            pct = (1 - result.bytes_out / result.bytes_in) * 100 if result.bytes_in else 0
            tin = max(1, result.bytes_in // 4)
            tout = max(1, result.bytes_out // 4)
            print(
                f"{prefix} -> {result.out_path}  "
                f"(-{pct:.1f}%, ~{tin} -> ~{tout} tokens, {result.n_images} images)"
            )
            done += 1
        elif isinstance(result, Skipped):
            print(f"{prefix} ... skipped (already vaulted at {result.out_path})")
            skipped += 1
        else:
            print(f"{prefix} ... FAILED: {result.reason}", file=sys.stderr)
            failed += 1

    return done, skipped, failed
