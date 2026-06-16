"""md_maker CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .pipeline import Config, Done, Failed, Skipped, ingest_folder, ingest_one


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="md_maker",
        description="Convert PDF(s) to token-optimized Markdown. "
        "Accepts a single .pdf or a directory of PDFs (top-level only). "
        "Each PDF gets its own <stem>/ folder with Literature_Vault/, assets/, mineru_out/.",
    )
    ap.add_argument("input", type=Path, help="PDF file or directory containing PDFs")
    ap.add_argument("-o", "--out", type=Path, default=Path("."),
                    help="Parent directory for per-PDF output folders (default: current dir)")
    ap.add_argument("-b", "--backend", default="hybrid-engine",
                    choices=["pipeline", "vlm-engine", "hybrid-engine",
                             "vlm-http-client", "hybrid-http-client"],
                    help="MinerU backend (default: hybrid-engine; use 'pipeline' for faster / lower-memory runs)")
    ap.add_argument("-m", "--method", default="auto", choices=["auto", "txt", "ocr"],
                    help="MinerU parsing method (default: auto)")
    ap.add_argument("-l", "--lang", default="en", help="Document language (default: en)")
    ap.add_argument("--effort", default="high", choices=["medium", "high"],
                    help="hybrid-* backend effort level (default: high)")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess even if vault entry already exists")
    ap.add_argument("--keep-scratch", action="store_true",
                    help="Do not delete <stem>/mineru_out/ after run")
    ap.add_argument("--title", default="", help="Frontmatter title override")
    ap.add_argument("--target-domain", default="", help="Frontmatter target_domain override")
    ap.add_argument("--source-domain", default="", help="Frontmatter source_domain override")
    ap.add_argument("--subtask", default="", help="ABSA subtask (ATE|ASC|AOPE|ASTE|ASQP)")
    ap.add_argument("-V", "--version", action="version", version=f"md_maker {__version__}")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    inp: Path = args.input
    if not inp.exists():
        print(f"md_maker: input not found: {inp}", file=sys.stderr)
        return 2

    cfg = Config(
        out=args.out.resolve(),
        backend=args.backend,
        method=args.method,
        lang=args.lang,
        effort=args.effort,
        force=args.force,
        keep_scratch=args.keep_scratch,
        title=args.title,
        target_domain=args.target_domain,
        source_domain=args.source_domain,
        subtask=args.subtask,
    )
    cfg.out.mkdir(parents=True, exist_ok=True)

    if inp.is_dir():
        done, skipped, failed = ingest_folder(inp, cfg)
        print(f"\nmd_maker: {done} processed, {skipped} skipped, {failed} failed. Output root: {cfg.out}")
        return 0 if failed == 0 else 1

    if inp.suffix.lower() != ".pdf":
        print(f"md_maker: expected .pdf, got {inp.suffix}", file=sys.stderr)
        return 2

    result = ingest_one(inp, cfg)
    if isinstance(result, Done):
        pct = (1 - result.bytes_out / result.bytes_in) * 100 if result.bytes_in else 0
        print(f"md_maker: {inp.name} -> {result.out_path}")
        print(f"  bytes: {result.bytes_in} -> {result.bytes_out} (-{pct:.1f}%)")
        print(f"  images moved: {result.n_images}")
        return 0
    if isinstance(result, Skipped):
        print(f"md_maker: skipped (already vaulted at {result.out_path}). Use --force to overwrite.")
        return 0
    print(f"md_maker: FAILED — {result.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
