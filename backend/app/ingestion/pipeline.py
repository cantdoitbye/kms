"""Ingestion pipeline: extract -> clean -> chunk -> embed -> store.

Runs on a single background worker thread. That serialises the CPU-heavy
embedding step and is enough for an MVP; in production this would be a proper
task queue (Celery / RQ / Arq) with retries.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.chunker import Chunker
from app.ingestion.cleaner import clean_blocks
from app.ingestion.extractors import extract
from app.models import Chunk, Document, DocumentStatus
from app.retrieval.bm25 import refresh_term_stats
from app.retrieval.embedder import get_embedder

log = logging.getLogger(__name__)
settings = get_settings()

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


def enqueue(document_id: uuid.UUID) -> None:
    _executor.submit(_safe_ingest, document_id)


def requeue_unfinished() -> int:
    """On startup, resume documents that were mid-flight when the server stopped."""
    with SessionLocal() as db:
        ids = db.scalars(
            select(Document.id).where(
                Document.status.in_([DocumentStatus.pending, DocumentStatus.processing])
            )
        ).all()
    for doc_id in ids:
        enqueue(doc_id)
    return len(ids)


def contextual_text(filename: str, section: str | None, content: str) -> str:
    """Prepend lightweight document context before embedding.

    A chunk like "It increased by 12%" is ambiguous on its own; adding the
    document title and section heading gives the embedding the missing context.
    Only the *embedded* text gets this header; the stored content stays clean.
    """
    if not settings.contextual_headers:
        return content
    title = Path(filename).stem.replace("_", " ").replace("-", " ")
    header = f"{title} > {section}" if section else title
    return f"{header}\n\n{content}"


def _safe_ingest(document_id: uuid.UUID) -> None:
    try:
        ingest_document(document_id)
    except Exception:  # never let the worker thread die
        log.exception("Ingestion crashed for %s", document_id)


def ingest_document(document_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.status, doc.error = DocumentStatus.processing, None
        db.commit()

        timings: dict[str, float] = {}
        t0 = time.perf_counter()

        def tick(name: str) -> None:
            nonlocal t0
            now = time.perf_counter()
            timings[name] = round((now - t0) * 1000, 1)
            t0 = now

        extracted = extract(Path(doc.storage_path))
        tick("extract_ms")

        blocks = clean_blocks(extracted.blocks, extracted.num_pages)
        tick("clean_ms")

        embedder = get_embedder()
        chunker = Chunker(
            embedder.count_tokens,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
        )
        drafts = chunker.chunk(blocks)
        if not drafts:
            raise ValueError("No text content left after cleaning.")
        tick("chunk_ms")

        vectors = embedder.embed_documents(
            [contextual_text(doc.filename, d.section, d.content) for d in drafts]
        )
        tick("embed_ms")

        # Idempotent: wipe any chunks from a previous (failed/re-)run first.
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        db.add_all(
            Chunk(
                document_id=doc.id,
                chunk_index=d.chunk_index,
                content=d.content,
                token_count=d.token_count,
                page_start=d.page_start,
                page_end=d.page_end,
                section=d.section,
                embedding=vec,
                meta={},
            )
            for d, vec in zip(drafts, vectors)
        )
        tick("store_ms")

        tokens = [d.token_count for d in drafts]
        doc.num_pages = extracted.num_pages
        doc.num_chunks = len(drafts)
        doc.status = DocumentStatus.ready
        doc.meta = {
            **extracted.meta,
            "timings_ms": timings,
            "num_blocks_raw": len(extracted.blocks),
            "num_blocks_clean": len(blocks),
            "num_headings": sum(b.kind == "heading" for b in blocks),
            "total_tokens": sum(tokens),
            "avg_chunk_tokens": round(sum(tokens) / len(tokens), 1),
            "max_chunk_tokens": max(tokens),
            "embedding_model": settings.embedding_model,
        }
        db.commit()
        refresh_term_stats(db)  # BM25 document frequencies
        log.info("Ingested %s: %d chunks in %s", doc.filename, len(drafts), timings)
    except Exception as e:
        db.rollback()
        log.warning("Ingestion failed for %s: %s", document_id, e)
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status, doc.error = DocumentStatus.failed, str(e)[:2000]
            db.commit()
    finally:
        db.close()
