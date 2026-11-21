"""Local embedding + reranking models, run with ONNX Runtime via fastembed.

ONNX instead of PyTorch: same model weights, but ~300 MB RAM instead of ~1.2 GB
and a ~4x smaller Docker image, so the API fits on small free-tier hosts.
Models are downloaded once and loaded lazily.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

import numpy as np

from app.config import get_settings

log = logging.getLogger(__name__)
_lock = threading.Lock()  # one inference at a time: predictable memory on small hosts


class Embedder:
    def __init__(self, model_name: str, query_instruction: str, batch_size: int, threads: int | None, cache_dir: str):
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        log.info("Loading embedding model %s", model_name)
        self.model = TextEmbedding(model_name, threads=threads, cache_dir=cache_dir)
        # Separate, non-truncating tokenizer so the chunker sees true token counts.
        self.tokenizer = Tokenizer.from_pretrained(model_name)
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.query_instruction = query_instruction
        self.batch_size = batch_size
        self.dim = int(self.embed_query("dimension probe").shape[0])

    def count_tokens(self, texts: list[str]) -> list[int]:
        if not texts:
            return []
        return [len(e.ids) for e in self.tokenizer.encode_batch(texts, add_special_tokens=False)]

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        # Each batch is padded to its longest text, so embedding texts in length order
        # (then restoring the original order) avoids most of the wasted padding compute.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        with _lock:
            vecs = np.array(
                list(self.model.embed([texts[i] for i in order], batch_size=self.batch_size)), dtype=np.float32
            )
        out = np.empty_like(vecs)
        out[order] = vecs
        return _normalize(out)  # unit vectors -> cosine == dot product

    def embed_query(self, query: str) -> np.ndarray:
        with _lock:
            vec = np.array(next(iter(self.model.embed([self.query_instruction + query]))), dtype=np.float32)
        return _normalize(vec[None, :])[0]


def _normalize(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-12, None)


class Reranker:
    def __init__(self, model_name: str, threads: int | None, cache_dir: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        log.info("Loading reranker model %s", model_name)
        self.model = TextCrossEncoder(model_name, threads=threads, cache_dir=cache_dir)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        # batch_size=1 on purpose: passages vary 50-400 tokens and batching pads every
        # pair to the longest one, which made reranking ~2.5x slower on CPU.
        with _lock:
            return [float(x) for x in self.model.rerank(query, passages, batch_size=1)]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    emb = Embedder(s.embedding_model, s.query_instruction, s.embed_batch_size, s.model_threads, str(s.model_cache_dir))
    if emb.dim != s.embedding_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={s.embedding_dim} but {s.embedding_model} produces {emb.dim}-d vectors"
        )
    return emb


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    return Reranker(s.reranker_model, s.model_threads, str(s.model_cache_dir))
