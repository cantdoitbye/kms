from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # --- Storage ---
    database_url: str = "postgresql+psycopg://kms:kms@localhost:5433/kms"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_mb: int = 25
    # On first start with an empty DB, ingest the bundled demo docs.
    seed_demo: bool = True
    seed_dir: Path = BASE_DIR.parent / "sample_docs"

    # --- Embeddings ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # BGE models are trained with an instruction prefix on the *query* side only.
    query_instruction: str = "Represent this sentence for searching relevant passages: "
    embed_batch_size: int = 32
    # ONNX Runtime intra-op threads; None = all cores. Set 1 on tiny shared-CPU hosts.
    model_threads: int | None = None
    model_cache_dir: Path = BASE_DIR / "data" / "models"

    # --- Chunking (measured in embedding-model tokens) ---
    chunk_max_tokens: int = 400
    chunk_overlap_tokens: int = 60
    chunk_min_tokens: int = 80
    # Prepend "{doc title} > {section}" to each chunk before embedding.
    contextual_headers: bool = True

    # --- Retrieval ---
    # "bm25" (IDF-weighted, implemented in SQL) or "ts_rank" (Postgres built-in, no IDF).
    keyword_ranker: str = "bm25"
    candidate_k: int = 20  # candidates fetched from each retriever before fusion
    rrf_k: int = 60  # standard RRF damping constant
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    hnsw_ef_search: int = 80

    # --- LLM (any OpenAI-compatible endpoint: Groq by default, Ollama works too) ---
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    # For reasoning models (gpt-oss, qwen3): "low" keeps latency down; empty = don't send.
    llm_reasoning_effort: str = "low"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
