"""Text normalisation and boilerplate removal."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.ingestion.extractors import Block

_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
# Join wrapped lines, but keep line breaks that start a list item.
_SOFT_BREAK = re.compile(r"\n(?!\s*(?:[-*•▪◦]|\d+[.)])\s)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t ]+")


def normalize(text: str, join_lines: bool = True) -> str:
    text = unicodedata.normalize("NFKC", text)  # also expands ligatures like "ﬁ" -> "fi"
    text = text.replace("­", "")  # soft hyphen
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # "informa-\ntion" -> "information"
    if join_lines:
        text = _SOFT_BREAK.sub(" ", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def _signature(text: str) -> str:
    """Normalise a block so running headers/footers match across pages."""
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def clean_blocks(blocks: list[Block], num_pages: int | None = None) -> list[Block]:
    """Normalise text and drop page numbers and repeated running headers/footers."""
    repeated: set[str] = set()
    edge_ids: set[int] = set()
    if num_pages and num_pages >= 3:
        # A short block that appears on >= 50% of pages is almost certainly a header/footer.
        # Only blocks at the top/bottom edge of a page can be running headers/footers.
        by_page: dict[int, list[Block]] = {}
        for b in blocks:
            if b.page is not None:
                by_page.setdefault(b.page, []).append(b)
        pages_per_sig: dict[str, set[int]] = {}
        for page, page_blocks in by_page.items():
            for b in page_blocks[:2] + page_blocks[-2:]:
                if len(b.text) < 200:
                    pages_per_sig.setdefault(_signature(b.text), set()).add(page)
        counts = Counter({sig: len(pages) for sig, pages in pages_per_sig.items()})
        repeated = {sig for sig, n in counts.items() if n >= max(3, num_pages * 0.5)}
        edge_ids = {id(b) for pb in by_page.values() for b in pb[:2] + pb[-2:]}

    out: list[Block] = []
    for b in blocks:
        if _PAGE_NUMBER.match(b.text):
            continue
        if repeated and id(b) in edge_ids and _signature(b.text) in repeated:
            continue
        text = normalize(b.text, join_lines=b.kind != "table")
        if not text:
            continue
        if b.kind == "heading":
            text = " ".join(text.split())
        out.append(Block(text=text, kind=b.kind, page=b.page))
    return out
