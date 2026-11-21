import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api import documents, query
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.ingestion.pipeline import requeue_unfinished
from app.models import Chunk, Document, TermStat
from app.retrieval.bm25 import refresh_term_stats
from app.retrieval.embedder import get_embedder, get_reranker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kms")
settings = get_settings()


def _seed_demo_documents() -> None:
    """Load bundled sample docs on first run so reviewers can ask questions immediately."""
    if not settings.seed_demo or not settings.seed_dir.is_dir():
        return
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Document)):
            return
        files = sorted(p for p in settings.seed_dir.iterdir() if p.is_file() and not p.name.startswith("."))
        for p in files:
            try:
                documents.store_document(db, p.name, p.read_bytes())
                log.info("Seeded demo document %s", p.name)
            except Exception as e:  # unsupported file etc.
                log.warning("Skipping seed file %s: %s", p.name, e)


def _ensure_term_stats() -> None:
    """Databases created before BM25 existed have chunks but no term statistics."""
    with SessionLocal() as db:
        has_chunks = db.scalar(select(func.count()).select_from(Chunk))
        has_stats = db.scalar(select(func.count()).select_from(TermStat))
        if has_chunks and not has_stats:
            refresh_term_stats(db)
            log.info("Computed BM25 term statistics")


def _warm_models() -> None:
    # A real forward pass compiles kernels / allocates buffers, so the first user query is fast.
    get_embedder().embed_query("warm up")
    get_reranker().score("warm up", ["warm up"])
    log.info("Models warmed up")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    _ensure_term_stats()
    # Load models in the background so the API (and health check) come up immediately.
    threading.Thread(target=_warm_models, daemon=True).start()
    n = requeue_unfinished()
    if n:
        log.info("Re-queued %d unfinished documents", n)
    _seed_demo_documents()
    yield


app = FastAPI(
    title="KMS-RAG: AI Knowledge Management API",
    version="0.1.0",
    description="Upload documents, then search or ask questions with grounded, cited answers.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents.router)
app.include_router(query.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
