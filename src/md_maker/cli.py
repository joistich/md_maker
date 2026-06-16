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
        "Accepts a single .pdf or a directory of PDFs (top-level only).",
    )
    ap.add_argument("input", type=Path, help="PDF file or directory containing PDFs")
    ap.add_argument("-o", "--vault", type=Path, default=Path("Literature_Vault"),
                    help="Output directory for cleaned Markdown (default: ./Literature_Vault)")
    ap.add_argument("-a", "--assets", type=Path, default=Path("assets"),
                    help="Directory for extracted images (default: ./assets)")
    ap.add_argument("--scratch", type=Path, default=Path("mineru_out"),
                    help="Scratch directory for raw MinerU output (default: ./mineru_out)")
    ap.add_argument("-b", "--backend", default="pipeline",
                    choices=["pipeline", "vlm-engine", "hybrid-engine",
                             "vlm-http-client", "hybrid-http-client"],
                    help="MinerU backend (default: pipeline)")
    ap.add_argument("-m", "--method", default="auto", choices=["auto", "txt", "ocr"],
                    help="MinerU parsing method (default: auto)")
    ap.add_argument("-l", "--lang", default="en", help="Document language (default: en)")
    ap.add_argument("--effort", choices=["medium", "high"],
                    help="hybrid-* backend effort level")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess even if vault entry already exists")
    ap.add_argument("--keep-scratch", action="store_true",
                    help="Do not delete mineru_out/<stem>/ after run")
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
        vault=args.vault.resolve(),
        assets=args.assets.resolve(),
        scratch=args.scratch.resolve(),
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

    if inp.is_dir():
        done, skipped, failed = ingest_folder(inp, cfg)
        print(f"\nmd_maker: {done} processed, {skipped} skipped, {failed} failed. Vault: {cfg.vault}")
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
