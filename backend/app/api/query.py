from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.generation.llm import LLMNotConfigured
from app.generation.rag import answer_question
from app.models import Chunk, Document, DocumentStatus
from app.retrieval.search import retrieve
from app.schemas import AskRequest, AskResponse, SearchRequest, SearchResponse

router = APIRouter(tags=["query"])


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, db: Session = Depends(get_db)):
    """Retrieval only (no LLM). Handy for debugging and for evaluation."""
    results, timings = retrieve(db, req.query, req.mode, req.top_k, req.document_ids)
    return SearchResponse(query=req.query, mode=req.mode, results=results, timings_ms=timings)


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, db: Session = Depends(get_db)):
    try:
        return answer_question(db, req)
    except LLMNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except APIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM provider error: {e}") from e


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    s = get_settings()
    by_status = dict(
        db.execute(select(Document.status, func.count()).group_by(Document.status)).all()
    )
    return {
        "documents": sum(by_status.values()),
        "documents_ready": by_status.get(DocumentStatus.ready, 0),
        "chunks": db.scalar(select(func.count()).select_from(Chunk)) or 0,
        "embedding_model": s.embedding_model,
        "reranker_model": s.reranker_model,
        "llm_model": s.llm_model,
        "llm_configured": bool(s.llm_api_key) or "localhost" in s.llm_base_url,
    }
