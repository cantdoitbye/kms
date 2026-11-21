import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import DocumentStatus

RetrievalMode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    num_pages: int | None
    num_chunks: int
    meta: dict
    created_at: datetime


class UploadResponse(BaseModel):
    document: DocumentOut
    duplicate: bool = False


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    section: str | None
    score: float
    scores: dict[str, float] = Field(default_factory=dict)  # per-stage scores/ranks for debugging


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: RetrievalMode = "hybrid_rerank"
    document_ids: list[uuid.UUID] | None = None


class SearchResponse(BaseModel):
    query: str
    mode: RetrievalMode
    results: list[ChunkOut]
    timings_ms: dict[str, float]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=15)
    mode: RetrievalMode = "hybrid_rerank"
    document_ids: list[uuid.UUID] | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    verify: bool = True  # check each cited claim against its cited passages


class Citation(BaseModel):
    ref: int  # the [n] marker used in the answer
    chunk: ChunkOut
    cited: bool  # whether the LLM actually referenced it


class ClaimCheck(BaseModel):
    text: str
    refs: list[int]
    verdict: Literal["supported", "unsupported", "uncited", "unchecked"]
    reason: str = ""


class AskResponse(BaseModel):
    question: str
    standalone_question: str
    answer: str
    citations: list[Citation]
    claims: list[ClaimCheck] = Field(default_factory=list)
    timings_ms: dict[str, float]
    usage: dict[str, int]
    model: str
