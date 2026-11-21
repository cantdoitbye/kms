import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.ingestion.extractors import SUPPORTED_EXTENSIONS
from app.ingestion.pipeline import enqueue
from app.retrieval.bm25 import refresh_term_stats
from app.models import Chunk, Document, DocumentStatus
from app.schemas import DocumentOut, UploadResponse

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

_MAGIC = {".pdf": b"%PDF", ".docx": b"PK\x03\x04"}
_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def store_document(db: Session, filename: str, data: bytes) -> tuple[Document, bool]:
    """Validate, dedupe by content hash, persist the file and queue ingestion."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Max {settings.max_upload_mb} MB.")
    magic = _MAGIC.get(ext)
    if magic and not data.startswith(magic):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File content is not a valid {ext} file.")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == sha))
    if existing:
        return existing, True

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{sha}{ext}"
    path.write_bytes(data)

    doc = Document(
        filename=Path(filename).name[:512],
        mime_type=_MIME[ext],
        sha256=sha,
        size_bytes=len(data),
        storage_path=str(path),
        status=DocumentStatus.pending,
        meta={},
    )
    db.add(doc)
    try:
        db.commit()
    except IntegrityError:  # concurrent upload of the same file
        db.rollback()
        return db.scalar(select(Document).where(Document.sha256 == sha)), True
    enqueue(doc.id)
    return doc, False


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile, db: Session = Depends(get_db)):
    data = await file.read()
    doc, duplicate = store_document(db, file.filename or "upload", data)
    return UploadResponse(document=DocumentOut.model_validate(doc), duplicate=duplicate)


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.created_at.desc())).all()


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/{document_id}/chunks")
def list_chunks(document_id: uuid.UUID, offset: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """Inspect how a document was chunked (useful for debugging retrieval)."""
    if not db.get(Document, document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    limit = max(1, min(limit, 200))
    total = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id))
    rows = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "token_count": c.token_count,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section": c.section,
            }
            for c in rows
        ],
    }


@router.post("/{document_id}/reprocess", response_model=DocumentOut)
def reprocess_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    doc.status, doc.error = DocumentStatus.pending, None
    db.commit()
    enqueue(doc.id)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = Path(doc.storage_path)
    db.delete(doc)  # chunks removed by ON DELETE CASCADE
    db.commit()
    refresh_term_stats(db)
    path.unlink(missing_ok=True)
