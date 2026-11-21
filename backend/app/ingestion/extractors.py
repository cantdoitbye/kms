"""Format-specific text extraction.

Every extractor returns a flat, ordered list of ``Block`` objects. A block is a
paragraph-like unit tagged with its page number (when the format has pages)
and whether it is a heading. Keeping structure at this stage is what enables
section-aware chunking and page-level citations later.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BlockKind = Literal["heading", "text", "table"]


class ExtractionError(Exception):
    pass


@dataclass
class Block:
    text: str
    kind: BlockKind = "text"
    page: int | None = None


@dataclass
class ExtractedDoc:
    blocks: list[Block]
    num_pages: int | None = None
    meta: dict = field(default_factory=dict)


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def extract(path: Path) -> ExtractedDoc:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".docx":
        return extract_docx(path)
    if ext in {".txt", ".md"}:
        return extract_text(path)
    raise ExtractionError(f"Unsupported file type: {ext}")


# --------------------------------------------------------------------------- PDF
_PDF_BOLD_FLAG = 1 << 4


def extract_pdf(path: Path) -> ExtractedDoc:
    import pymupdf

    try:
        pdf = pymupdf.open(path)
    except Exception as e:  # corrupted / encrypted file
        raise ExtractionError(f"Could not open PDF: {e}") from e

    raw: list[tuple[int, str, float, float, int]] = []  # page, text, max_size, bold_ratio, n_lines
    size_hist: Counter[float] = Counter()

    with pdf:
        num_pages = pdf.page_count
        for page_no, page in enumerate(pdf, start=1):
            layout = page.get_text("dict", sort=True)
            for b in layout["blocks"]:
                if b.get("type") != 0:  # 0 = text, 1 = image
                    continue
                lines, max_size, bold_chars, total_chars = [], 0.0, 0, 0
                for line in b["lines"]:
                    lines.append("".join(s["text"] for s in line["spans"]))
                    for s in line["spans"]:
                        n = len(s["text"].strip())
                        if not n:
                            continue
                        size = round(s["size"], 1)
                        size_hist[size] += n
                        max_size = max(max_size, size)
                        total_chars += n
                        if s["flags"] & _PDF_BOLD_FLAG:
                            bold_chars += n
                text = "\n".join(lines).strip()
                if text:
                    bold_ratio = bold_chars / total_chars if total_chars else 0.0
                    raw.append((page_no, text, max_size, bold_ratio, len(lines)))

    if not raw:
        raise ExtractionError(
            "No extractable text found (scanned/image-only PDF? OCR is out of scope for the MVP)."
        )

    # The most common font size (weighted by characters) is the body text size.
    body_size = size_hist.most_common(1)[0][0]
    blocks = []
    for page_no, text, size, bold_ratio, n_lines in raw:
        kind: BlockKind = (
            "heading" if _looks_like_heading(text, size, bold_ratio, n_lines, body_size) else "text"
        )
        blocks.append(Block(text=text, kind=kind, page=page_no))

    return ExtractedDoc(blocks=blocks, num_pages=num_pages, meta={"body_font_size": body_size})


def _looks_like_heading(text: str, size: float, bold_ratio: float, n_lines: int, body: float) -> bool:
    flat = " ".join(text.split())
    if len(flat) > 120 or len(flat.split()) > 15 or n_lines > 3:
        return False
    if flat.endswith((".", ",", ";", ":")) and not re.match(r"^\d+(\.\d+)*\.?\s", flat):
        return False
    if not re.search(r"[A-Za-z]", flat):
        return False
    larger = size >= body * 1.15
    bold = bold_ratio > 0.8 and size >= body * 0.95
    return larger or bold


# -------------------------------------------------------------------------- DOCX
def extract_docx(path: Path) -> ExtractedDoc:
    from docx import Document as load_docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = load_docx(str(path))
    except Exception as e:
        raise ExtractionError(f"Could not open DOCX: {e}") from e

    blocks: list[Block] = []
    # Walk the body in document order so tables stay where they appear.
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            s = style.lower()
            if s.startswith(("heading", "title")):
                blocks.append(Block(text=text, kind="heading"))
            elif "list" in s:
                blocks.append(Block(text=f"- {text}"))
            else:
                blocks.append(Block(text=text))
        elif tag == "tbl":
            table = Table(el, d)
            rows = []
            for row in table.rows:
                cells: list[str] = []
                for c in row.cells:  # merged cells repeat -> drop consecutive dupes
                    t = c.text.strip()
                    if not cells or cells[-1] != t:
                        cells.append(t)
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(Block(text="\n".join(rows), kind="table"))

    if not blocks:
        raise ExtractionError("DOCX contains no text.")
    return ExtractedDoc(blocks=blocks)


# -------------------------------------------------------------------- TXT / MD
_MD_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
# **bold**, __bold__, *em*, _em_ -> plain text (keeps snake_case and 2*3 intact).
_MD_EMPHASIS = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1|(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _strip_markdown(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    return _MD_EMPHASIS.sub(lambda m: m.group(2) or m.group(3), text)


def extract_text(path: Path) -> ExtractedDoc:
    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    if path.suffix.lower() == ".md":
        content = _strip_markdown(content)

    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para:
            continue
        # A markdown heading may be glued to the paragraph below it.
        lines = para.split("\n")
        m = _MD_HEADING.match(lines[0])
        if m:
            blocks.append(Block(text=m.group(1).strip(), kind="heading"))
            rest = "\n".join(lines[1:]).strip()
            if rest:
                blocks.append(Block(text=rest))
        else:
            blocks.append(Block(text=para))

    if not blocks:
        raise ExtractionError("File is empty.")
    return ExtractedDoc(blocks=blocks)
