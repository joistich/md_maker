"""Markdown cleaner: strip references, headers, footers, page numbers; inject YAML frontmatter."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REF_HEAD = re.compile(
    r"^\s{0,3}"
    r"(?:#{1,6}\s+|\*\*\s*)?"
    r"(?:[IVXLC]+\.?\s+|\d+\.?\s+)?"
    r"(references|bibliography|works\s+cited|literature\s+cited)"
    r"\s*\**\s*$",
    re.IGNORECASE | re.MULTILINE,
)

PAGE_NUM_PATTERNS = [
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$"),
    re.compile(r"^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
]

MINERU_PAGE_MARKER = re.compile(r"^\s*(?:\{\{\d+\}\}|<!--\s*page\s*\d+\s*-->)\s*$", re.IGNORECASE)
FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
TABLE_LINE_RE = re.compile(r"^\s*\|")
HTML_COMMENT_PAGE = re.compile(r"<!--\s*page\s*\d+\s*-->", re.IGNORECASE)


def cut_references(text: str) -> tuple[str, bool]:
    matches = list(REF_HEAD.finditer(text))
    if not matches:
        return text, False
    cut = matches[-1].start()
    return text[:cut].rstrip() + "\n", True


def _is_page_number(line: str) -> bool:
    return any(p.match(line) for p in PAGE_NUM_PATTERNS)


def _find_repeated_boilerplate(lines: list[str], min_repeats: int = 3) -> set[str]:
    counter: Counter[str] = Counter()
    for ln in lines:
        s = ln.strip()
        if not s or len(s) > 120:
            continue
        if HEADING_RE.match(ln) or TABLE_LINE_RE.match(ln):
            continue
        if s.startswith(("|", "$", "```", "- ", "* ", "+ ", ">")):
            continue
        if s[0].isdigit() and s.endswith("."):
            continue
        counter[s] += 1
    return {s for s, c in counter.items() if c >= min_repeats}


def strip_noise(text: str) -> str:
    lines = text.splitlines()
    boilerplate = _find_repeated_boilerplate(lines)

    out: list[str] = []
    in_fence = False
    in_math = False

    for raw in lines:
        line = raw.replace("\f", "")
        line = HTML_COMMENT_PAGE.sub("", line)

        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        if stripped == "$$":
            in_math = not in_math
            out.append(line)
            continue
        if in_math:
            out.append(line)
            continue

        if MINERU_PAGE_MARKER.match(line):
            continue
        if _is_page_number(line):
            continue
        if stripped and stripped in boilerplate:
            continue

        out.append(line)

    collapsed: list[str] = []
    blanks = 0
    for line in out:
        if line.strip() == "":
            blanks += 1
            if blanks <= 2:
                collapsed.append("")
        else:
            blanks = 0
            collapsed.append(line.rstrip())

    return "\n".join(collapsed).strip() + "\n"


def split_existing_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or not FRONTMATTER_BOUNDARY.match(lines[0]):
        return {}, text
    for i in range(1, len(lines)):
        if FRONTMATTER_BOUNDARY.match(lines[i]):
            fm_lines = lines[1:i]
            body = "\n".join(lines[i + 1 :]).lstrip("\n")
            data: dict[str, str] = {}
            for fm in fm_lines:
                if ":" in fm:
                    k, _, v = fm.partition(":")
                    data[k.strip()] = v.strip().strip('"')
            return data, body
    return {}, text


def _yaml_escape(v: str) -> str:
    if v == "":
        return '""'
    if any(c in v for c in ':#"\n'):
        return '"' + v.replace('"', '\\"') + '"'
    return v


def build_frontmatter(
    existing: dict[str, str],
    *,
    title: str,
    target_domain: str,
    source_domain: str,
    subtask: str,
    source_pdf: str,
) -> str:
    placeholder = "TODO"
    fields = {
        "title": title or existing.get("title") or placeholder,
        "target_domain": target_domain or existing.get("target_domain") or placeholder,
        "source_domain": source_domain or existing.get("source_domain") or placeholder,
        "absa_subtask": subtask or existing.get("absa_subtask") or placeholder,
        "source_pdf": source_pdf or existing.get("source_pdf") or placeholder,
        "ingested_at": existing.get("ingested_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    body = ["---"]
    for k, v in fields.items():
        body.append(f"{k}: {_yaml_escape(str(v))}")
    body.append("---")
    body.append("")
    return "\n".join(body)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def clean(
    raw: str,
    *,
    title: str = "",
    target_domain: str = "",
    source_domain: str = "",
    subtask: str = "",
    source_pdf: str = "",
) -> tuple[str, bool]:
    """Return (cleaned_markdown_with_frontmatter, refs_were_cut)."""
    existing_fm, body = split_existing_frontmatter(raw)
    body, cut_ok = cut_references(body)
    body = strip_noise(body)
    fm = build_frontmatter(
        existing_fm,
        title=title,
        target_domain=target_domain,
        source_domain=source_domain,
        subtask=subtask,
        source_pdf=source_pdf,
    )
    return fm + body, cut_ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Clean a parser-generated Markdown file in-place.")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--title", default="")
    ap.add_argument("--target-domain", default="")
    ap.add_argument("--source-domain", default="")
    ap.add_argument("--subtask", default="", help="ATE | ASC | AOPE | ASTE | ASQP")
    ap.add_argument("--source-pdf", default="")
    args = ap.parse_args(argv)

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2

    raw = args.input.read_text(encoding="utf-8", errors="replace")
    raw_bytes = len(raw.encode("utf-8"))

    cleaned, cut_ok = clean(
        raw,
        title=args.title,
        target_domain=args.target_domain,
        source_domain=args.source_domain,
        subtask=args.subtask,
        source_pdf=args.source_pdf or args.input.stem + ".pdf",
    )
    if not cut_ok:
        print("warn: no References/Bibliography heading found; body unchanged", file=sys.stderr)

    out_path = args.output or args.input.with_suffix(".clean.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cleaned, encoding="utf-8")

    out_bytes = len(cleaned.encode("utf-8"))
    delta = raw_bytes - out_bytes
    pct = (delta / raw_bytes * 100) if raw_bytes else 0
    print(
        f"cleaner: {args.input} -> {out_path}\n"
        f"  bytes: {raw_bytes} -> {out_bytes} (-{delta}, -{pct:.1f}%)\n"
        f"  ~tokens: {estimate_tokens(raw)} -> {estimate_tokens(cleaned)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
