"""Markdown cleaner: strip references, headers, footers, page numbers; inject YAML frontmatter."""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
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


HTML_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
SUP_LETTER_RE = re.compile(r"<sup>([A-Za-z])</sup>")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
CONTENT_HEADING_RE = re.compile(
    r"^#{1,3}\s+(?:\d+\.?\s+)?(abstract|introduction|background|related\s+work|"
    r"motivation|preliminaries|problem\s+(?:definition|formulation)|methodology|"
    r"proposed\s+approach|approach|method|methods|model)\b",
    re.IGNORECASE | re.MULTILINE,
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_buf: list[str] | None = None
        self.has_spans = False
        self.bad = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell_buf = []
            for name, value in attrs:
                if name in ("rowspan", "colspan") and value and value.strip() not in ("", "1"):
                    self.has_spans = True
        elif tag == "br" and self._cell_buf is not None:
            self._cell_buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell_buf is not None and self._row is not None:
            text = " ".join("".join(self._cell_buf).split())
            text = text.replace("|", r"\|")
            self._row.append(text)
            self._cell_buf = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_buf is not None:
            self._cell_buf.append(data)

    def error(self, message: str) -> None:
        self.bad = True


def _html_table_to_markdown(block: str) -> str:
    parser = _TableParser()
    try:
        parser.feed(block)
        parser.close()
    except Exception:
        return block
    if parser.bad or parser.has_spans or not parser.rows:
        return block
    width = max(len(r) for r in parser.rows)
    if width < 2:
        return block
    norm = [r + [""] * (width - len(r)) for r in parser.rows]
    header = norm[0]
    sep = ["---"] * width
    body = norm[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def convert_html_tables(text: str) -> str:
    return HTML_TABLE_RE.sub(lambda m: _html_table_to_markdown(m.group(0)), text)


def strip_sup_letters(text: str) -> str:
    return SUP_LETTER_RE.sub(r"\1", text)


def strip_front_chrome(text: str) -> str:
    """Drop everything before the first real content heading.

    Detects the first H1 with the same wording as the canonical paper title,
    or any heading whose text matches Abstract/Introduction/etc. Keeps that
    heading and the body after it. If no anchor is found, returns text
    unchanged (safer than over-amputating).
    """
    content_match = CONTENT_HEADING_RE.search(text)
    h1_matches = list(H1_RE.finditer(text))

    candidates: list[int] = []
    if content_match:
        candidates.append(content_match.start())

    if len(h1_matches) >= 2:
        first_h1 = h1_matches[0].group(1).strip().casefold()
        for m in h1_matches[1:]:
            if m.group(1).strip().casefold() == first_h1:
                candidates.append(m.start())
                break

    if not candidates:
        return text

    cut = min(candidates)
    return text[cut:].lstrip()


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
    body = strip_front_chrome(body)
    body, cut_ok = cut_references(body)
    body = strip_noise(body)
    body = convert_html_tables(body)
    body = strip_sup_letters(body)
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
