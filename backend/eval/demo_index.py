"""Index the bundled demo documents into the configured database, synchronously.

Shared by the ablation study and the CI quality gate. Uses the same ingestion
code path as the API, minus the background queue.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import delete, func, select

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_docs"


def reindex_demo_docs() -> dict:
    from app.db import SessionLocal
    from app.ingestion.pipeline import ingest_document
    from app.models import Chunk, Document, DocumentStatus

    with SessionLocal() as db:
        db.execute(delete(Document))
        db.commit()
        for p in sorted(SAMPLE_DIR.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            data = p.read_bytes()
            db.add(
                Document(
                    filename=p.name,
                    mime_type="application/octet-stream",
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    storage_path=str(p),
                    status=DocumentStatus.pending,
                    meta={},
                )
            )
        db.commit()
        ids = db.scalars(select(Document.id)).all()
    for doc_id in ids:
        ingest_document(doc_id)
    with SessionLocal() as db:
        failed = db.scalars(select(Document.filename).where(Document.status != DocumentStatus.ready)).all()
        if failed:
            raise RuntimeError(f"Ingestion failed for {failed}")
        n = db.scalar(select(func.count()).select_from(Chunk))
        avg = db.scalar(select(func.avg(Chunk.token_count)))
    return {"chunks": n, "avg_tokens": round(float(avg))}
