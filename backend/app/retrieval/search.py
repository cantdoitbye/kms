"""Retrieval: dense (pgvector), lexical (Postgres FTS), RRF fusion, cross-encoder rerank."""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Sequence

from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document
from app.retrieval.bm25 import bm25_search
from app.retrieval.embedder import get_embedder, get_reranker
from app.retrieval.fusion import reciprocal_rank_fusion
from app.schemas import ChunkOut, RetrievalMode

settings = get_settings()


def _doc_filter(stmt, document_ids: Sequence[uuid.UUID] | None):
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(list(document_ids)))
    return stmt


def vector_search(
    db: Session, query_vec, k: int, document_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, float]]:
    """Top-k chunks by cosine similarity using the HNSW index."""
    db.execute(text(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}"))
    # pgvector >= 0.8: keep scanning the graph when a WHERE filter removes candidates.
    db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = Chunk.embedding.cosine_distance(query_vec)
    # Content as a final tie-breaker keeps rankings identical across databases.
    stmt = select(Chunk.id, distance.label("dist")).order_by(distance, Chunk.content).limit(k)
    rows = db.execute(_doc_filter(stmt, document_ids)).all()
    return [(r.id, 1.0 - float(r.dist)) for r in rows]


def keyword_search(
    db: Session, query: str, k: int, document_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, float]]:
    """Top-k chunks by keyword relevance: BM25 by default, Postgres ts_rank_cd as fallback.

    plainto_tsquery ANDs every term, which is far too strict for natural-language
    questions, so we rewrite it into an OR query and let ts_rank_cd reward chunks
    that match more (and closer) terms.
    """
    if settings.keyword_ranker == "bm25":
        return bm25_search(db, query, k, document_ids)
    and_query = cast(func.plainto_tsquery("english", query), Text)
    tsq = func.to_tsquery("english", func.replace(and_query, "&", "|"))
    rank = func.ts_rank_cd(Chunk.tsv, tsq, 32)  # 32 => rank / (rank + 1), in [0, 1)
    stmt = select(Chunk.id, rank.label("rank")).where(Chunk.tsv.op("@@")(tsq))
    # ts_rank ties are common; without a tie-breaker their order depends on physical
    # row order, which made results (and the CI gate) differ between databases.
    stmt = _doc_filter(stmt, document_ids).order_by(rank.desc(), Chunk.content).limit(k)
    return [(r.id, float(r.rank)) for r in db.execute(stmt).all()]


def _load_chunks(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Chunk, str]]:
    if not ids:
        return {}
    rows = db.execute(
        select(Chunk, Document.filename).join(Document).where(Chunk.id.in_(ids))
    ).all()
    return {c.id: (c, filename) for c, filename in rows}


def _to_out(chunk: Chunk, filename: str, score: float, scores: dict[str, float]) -> ChunkOut:
    return ChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        section=chunk.section,
        score=round(score, 6),
        scores={k: round(v, 6) for k, v in scores.items()},
    )


def retrieve(
    db: Session,
    query: str,
    mode: RetrievalMode = "hybrid_rerank",
    top_k: int = 5,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> tuple[list[ChunkOut], dict[str, float]]:
    timings: dict[str, float] = {}

    def tick(name: str, t0: float) -> float:
        now = time.perf_counter()
        timings[name] = round((now - t0) * 1000, 1)
        return now

    t = time.perf_counter()
    per_chunk: dict[uuid.UUID, dict[str, float]] = {}
    ranked: dict[str, list[uuid.UUID]] = {}
    n_candidates = top_k if mode in ("vector", "keyword") else max(settings.candidate_k, top_k)

    if mode in ("vector", "hybrid", "hybrid_rerank"):
        qvec = get_embedder().embed_query(query)
        t = tick("embed_query", t)
        hits = vector_search(db, qvec, n_candidates, document_ids)
        t = tick("vector_search", t)
        ranked["vector"] = [cid for cid, _ in hits]
        for rank, (cid, sim) in enumerate(hits, 1):
            per_chunk.setdefault(cid, {}).update(vector_sim=sim, vector_rank=rank)

    if mode in ("keyword", "hybrid", "hybrid_rerank"):
        hits = keyword_search(db, query, n_candidates, document_ids)
        t = tick("keyword_search", t)
        ranked["keyword"] = [cid for cid, _ in hits]
        for rank, (cid, r) in enumerate(hits, 1):
            per_chunk.setdefault(cid, {}).update(keyword_rank_score=r, keyword_rank=rank)

    if mode in ("vector", "keyword"):
        ordered = [(cid, per_chunk[cid]["vector_sim" if mode == "vector" else "keyword_rank_score"])
                   for cid in ranked[mode]]
    else:
        fused = reciprocal_rank_fusion(ranked, k=settings.rrf_k)
        for rank, (cid, s) in enumerate(fused, 1):
            per_chunk[cid].update(rrf=s, rrf_rank=rank)
        ordered = [(cid, s) for cid, s in fused][: n_candidates]
        t = tick("fusion", t)

    chunks = _load_chunks(db, [cid for cid, _ in ordered])
    t = tick("load_chunks", t)

    if mode == "hybrid_rerank" and ordered:
        candidates = [cid for cid, _ in ordered if cid in chunks]
        logits = get_reranker().score(query, [chunks[cid][0].content for cid in candidates])
        t = tick("rerank", t)
        rescored = []
        for cid, logit in zip(candidates, logits):
            prob = 1.0 / (1.0 + math.exp(-logit))  # squash for a readable 0-1 relevance
            per_chunk[cid]["rerank"] = prob
            rescored.append((cid, prob))
        ordered = sorted(rescored, key=lambda x: x[1], reverse=True)
        for rank, (cid, _) in enumerate(ordered, 1):
            per_chunk[cid]["rerank_rank"] = rank

    results = [
        _to_out(chunks[cid][0], chunks[cid][1], score, per_chunk.get(cid, {}))
        for cid, score in ordered[:top_k]
        if cid in chunks
    ]
    timings["total_retrieval"] = round(sum(timings.values()), 1)
    return results, timings
