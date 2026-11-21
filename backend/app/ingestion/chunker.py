"""Structure-aware, token-budgeted chunking with sentence-level overlap.

Algorithm
---------
1. Walk the blocks, tracking the current section heading.
2. Break every block into *units* (sentences). Anything still longer than the
   token budget is hard-split on word boundaries.
3. Greedily pack units into chunks of at most ``max_tokens`` *embedding-model*
   tokens (so we never silently exceed the encoder's context window).
4. A new section starts a new chunk (unless the current chunk is still tiny),
   so chunks don't mix unrelated topics.
5. Within a section, consecutive chunks share ``overlap_tokens`` worth of
   whole trailing sentences, so facts on a boundary are retrievable from both.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ingestion.extractors import Block

TokenCounter = Callable[[list[str]], list[int]]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


@dataclass
class Unit:
    text: str
    tokens: int
    page: int | None
    section: str | None
    block_id: int


@dataclass
class ChunkDraft:
    content: str
    token_count: int
    page_start: int | None
    page_end: int | None
    section: str | None
    chunk_index: int = 0


class Chunker:
    def __init__(
        self,
        count_tokens: TokenCounter,
        max_tokens: int = 400,
        overlap_tokens: int = 60,
        min_tokens: int = 80,
    ):
        if overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        self.count_tokens = count_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens

    # ----------------------------------------------------------------- public
    def chunk(self, blocks: list[Block]) -> list[ChunkDraft]:
        units = self._to_units(blocks)
        drafts = self._pack(units)
        if drafts:
            counts = self.count_tokens([d.content for d in drafts])
            for i, (d, n) in enumerate(zip(drafts, counts)):
                d.chunk_index, d.token_count = i, n
        return drafts

    # -------------------------------------------------------------- internals
    def _to_units(self, blocks: list[Block]) -> list[Unit]:
        pieces: list[tuple[str, int | None, str | None, int]] = []
        section: str | None = None
        for block_id, b in enumerate(blocks):
            if b.kind == "heading":
                section = b.text[:500]
                pieces.append((b.text, b.page, section, block_id))
                continue
            if b.kind == "table":
                # Keep table rows together; split row-wise only if needed.
                sentences = b.text.split("\n")
            else:
                sentences = [s for s in _SENTENCE_SPLIT.split(b.text) if s.strip()]
            for s in sentences:
                pieces.append((s.strip(), b.page, section, block_id))

        if not pieces:
            return []
        counts = self.count_tokens([p[0] for p in pieces])
        units: list[Unit] = []
        for (text, page, sec, bid), n in zip(pieces, counts):
            if n <= self.max_tokens:
                units.append(Unit(text, n, page, sec, bid))
            else:
                units.extend(self._hard_split(text, page, sec, bid))
        return units

    def _hard_split(self, text: str, page, section, block_id) -> list[Unit]:
        """Fallback for pathological 'sentences' (tables, code, missing punctuation)."""
        words = text.split()
        # Start with a conservative words-per-piece guess, shrink until every piece fits.
        step = max(1, int(self.max_tokens * 0.6))
        while True:
            parts = [" ".join(words[i : i + step]) for i in range(0, len(words), step)]
            counts = self.count_tokens(parts)
            if max(counts) <= self.max_tokens or step == 1:
                return [Unit(p, n, page, section, block_id) for p, n in zip(parts, counts)]
            step = max(1, step // 2)

    def _pack(self, units: list[Unit]) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        cur: list[Unit] = []
        cur_tokens = 0

        for u in units:
            section_changed = bool(cur) and u.section != cur[-1].section
            too_big = cur_tokens + u.tokens > self.max_tokens
            if cur and (too_big or (section_changed and cur_tokens >= self.min_tokens)):
                drafts.append(self._emit(cur))
                if section_changed:
                    cur, cur_tokens = [], 0
                else:
                    cur = self._overlap_tail(cur)
                    cur_tokens = sum(x.tokens for x in cur)
                    if cur_tokens + u.tokens > self.max_tokens:
                        cur, cur_tokens = [], 0
            cur.append(u)
            cur_tokens += u.tokens

        if cur:
            drafts.append(self._emit(cur))
        return drafts

    def _overlap_tail(self, cur: list[Unit]) -> list[Unit]:
        tail: list[Unit] = []
        total = 0
        for u in reversed(cur):
            if total + u.tokens > self.overlap_tokens:
                break
            tail.insert(0, u)
            total += u.tokens
        # Never return the whole chunk as overlap (would loop forever on tiny chunks).
        return tail if len(tail) < len(cur) else tail[1:]

    @staticmethod
    def _emit(units: list[Unit]) -> ChunkDraft:
        parts: list[str] = []
        for i, u in enumerate(units):
            if i == 0:
                parts.append(u.text)
            elif u.block_id == units[i - 1].block_id:
                parts.append(" " + u.text)
            else:
                parts.append("\n\n" + u.text)
        pages = [u.page for u in units if u.page is not None]
        # A chunk can span several short sections; label it with all of them.
        sections = list(dict.fromkeys(u.section for u in units if u.section))
        section = "; ".join(sections)[:500] if sections else None
        return ChunkDraft(
            content="".join(parts).strip(),
            token_count=sum(u.tokens for u in units),
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            section=section,
        )
