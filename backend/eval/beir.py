"""Benchmark the retrieval stack on BEIR SciFact (public, standard IR benchmark).

5,183 scientific abstracts, 300 test claims with relevance labels. Uses the same
cleaning, chunking, embedding and retrieval code as the app, but in a separate
database (`<db>_beir`) and with bulk indexing.

Setup (one-off, ~3 MB, CC BY-NC):
    mkdir -p data/benchmarks && cd data/benchmarks
    curl -LO https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip && unzip scifact.zip

Run (from backend/):
    .venv/bin/python -m eval.beir                # index once, then evaluate all modes
    .venv/bin/python -m eval.beir --reindex      # force re-indexing
"""

from __future__ import annotations

import os

_BASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://kms:kms@localhost:5433/kms")
BEIR_DB = _BASE_URL.rsplit("/", 1)[1] + "_beir"
os.environ["DATABASE_URL"] = _BASE_URL.rsplit("/", 1)[0] + "/" + BEIR_DB
os.environ["SEED_DEMO"] = "false"
# Each abstract is one document: the title is already the first line of the text,
# so a "{doc id} > {section}" header would only add noise.
os.environ["CONTEXTUAL_HEADERS"] = "false"

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import statistics  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

import psycopg  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA_CANDIDATES = [
    HERE.parent / "data" / "benchmarks" / "scifact",
    HERE.parent / "data" / "benchmarks" / "scifact_dl" / "scifact",
]
MODES = ["vector", "keyword", "hybrid", "hybrid_rerank"]
LABEL = {"vector": "Vector only", "keyword": "Keyword only (BM25 in SQL)", "hybrid": "Hybrid (RRF)", "hybrid_rerank": "Hybrid + rerank"}


def data_dir() -> Path:
    for d in DATA_CANDIDATES:
        if (d / "corpus.jsonl").exists():
            return d
    raise SystemExit("SciFact not found. See the setup instructions at the top of eval/beir.py.")


def load(d: Path):
    corpus = [json.loads(line) for line in (d / "corpus.jsonl").read_text().splitlines()]
    queries = {q["_id"]: q["text"] for q in map(json.loads, (d / "queries.jsonl").read_text().splitlines())}
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    for line in (d / "qrels" / "test.tsv").read_text().splitlines()[1:]:
        qid, did, score = line.split("\t")
        qrels[qid][did] = int(score)
    return corpus, {qid: queries[qid] for qid in qrels}, qrels


def ensure_database() -> None:
    admin = _BASE_URL.replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (BEIR_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{BEIR_DB}"')


def index(corpus: list[dict]) -> dict:
    from sqlalchemy import delete

    from app.config import get_settings
    from app.db import SessionLocal
    from app.ingestion.chunker import Chunker
    from app.ingestion.cleaner import clean_blocks
    from app.ingestion.extractors import Block
    from app.ingestion.pipeline import contextual_text
    from app.models import Chunk, Document, DocumentStatus
    from app.retrieval.embedder import get_embedder

    s = get_settings()
    emb = get_embedder()
    chunker = Chunker(emb.count_tokens, s.chunk_max_tokens, s.chunk_overlap_tokens, s.chunk_min_tokens)
    t0 = time.perf_counter()
    with SessionLocal() as db:
        db.execute(delete(Document))
        db.commit()
        batch: list[tuple[Document, list]] = []

        def flush() -> None:
            drafts = [(doc, d) for doc, ds in batch for d in ds]
            vecs = emb.embed_documents([contextual_text(doc.filename, d.section, d.content) for doc, d in drafts])
            for doc, _ in batch:
                db.add(doc)
            db.flush()
            db.add_all(
                Chunk(document_id=doc.id, chunk_index=d.chunk_index, content=d.content, token_count=d.token_count,
                      page_start=None, page_end=None, section=d.section, embedding=v, meta={})
                for (doc, d), v in zip(drafts, vecs)
            )
            db.commit()
            batch.clear()

        for i, rec in enumerate(corpus, 1):
            blocks = [Block(rec["title"], kind="heading")] if rec.get("title") else []
            blocks.append(Block(rec["text"]))
            drafts = chunker.chunk(clean_blocks(blocks))
            doc = Document(filename=rec["_id"], mime_type="text/plain", size_bytes=len(rec["text"]),
                           sha256=hashlib.sha256(rec["_id"].encode()).hexdigest(), storage_path="beir:scifact",
                           status=DocumentStatus.ready, num_chunks=len(drafts), meta={})
            batch.append((doc, drafts))
            if len(batch) >= 256:
                flush()
                print(f"  indexed {i}/{len(corpus)}", end="\r", flush=True)
        if batch:
            flush()
        from app.retrieval.bm25 import refresh_term_stats

        refresh_term_stats(db)
    from sqlalchemy import func, select

    with SessionLocal() as db:
        n_chunks = db.scalar(select(func.count()).select_from(Chunk))
    secs = time.perf_counter() - t0
    print(f"  indexed {len(corpus)} docs -> {n_chunks} chunks in {secs:.0f}s")
    return {"docs": len(corpus), "chunks": n_chunks, "index_seconds": round(secs)}


def ndcg_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    dcg = sum(rels.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def evaluate(queries: dict[str, str], qrels: dict, candidates: int, modes: list[str] = MODES) -> dict:
    from app.config import get_settings
    from app.db import SessionLocal
    from app.retrieval.search import retrieve

    get_settings().candidate_k = candidates
    out = {}
    with SessionLocal() as db:
        retrieve(db, "warm up", "hybrid_rerank", 5)
        db.rollback()
        for mode in modes:
            nd, rec, mrr, lat = [], [], [], []
            for qid, text in queries.items():
                results, timings = retrieve(db, text, mode, top_k=candidates)
                db.rollback()
                ranked = list(dict.fromkeys(c.filename for c in results))[:10]  # chunk -> doc, dedupe
                rels = qrels[qid]
                nd.append(ndcg_at_k(ranked, rels))
                rec.append(len(set(ranked) & set(rels)) / len(rels))
                first = next((i for i, d in enumerate(ranked, 1) if d in rels), None)
                mrr.append(1 / first if first else 0.0)
                lat.append(timings["total_retrieval"])
            out[mode] = {
                "ndcg@10": round(statistics.mean(nd), 4),
                "recall@10": round(statistics.mean(rec), 4),
                "mrr@10": round(statistics.mean(mrr), 4),
                "p50_ms": round(statistics.median(lat), 1),
            }
            print(f"  {LABEL[mode]:28} nDCG@10={out[mode]['ndcg@10']:.3f}  R@10={out[mode]['recall@10']:.3f}  "
                  f"MRR@10={out[mode]['mrr@10']:.3f}  p50={out[mode]['p50_ms']:.0f}ms")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--keyword-ranker", choices=["bm25", "ts_rank"], default=None)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--candidates", type=int, default=20, help="candidates per retriever / reranked")
    args = ap.parse_args()

    corpus, queries, qrels = load(data_dir())
    ensure_database()
    from sqlalchemy import func, select

    from app.db import SessionLocal, init_db
    from app.models import Document

    init_db()
    with SessionLocal() as db:
        have = db.scalar(select(func.count()).select_from(Document))
    stats_path = HERE / "beir_index.json"
    if args.reindex or have != len(corpus):
        print(f"Indexing SciFact ({len(corpus)} abstracts)...")
        stats = index(corpus)
        stats_path.write_text(json.dumps(stats))
    else:
        stats = json.loads(stats_path.read_text()) if stats_path.exists() else {"docs": have}
        print(f"Using existing index ({have} docs).")

    from app.config import get_settings
    from app.models import TermStat
    from app.retrieval.bm25 import refresh_term_stats

    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(TermStat)):
            print("Computing BM25 term statistics...")
            refresh_term_stats(db)
    if args.keyword_ranker:
        get_settings().keyword_ranker = args.keyword_ranker
    ranker = get_settings().keyword_ranker
    modes = [m for m in args.modes.split(",") if m in MODES]
    print(f"Evaluating {len(queries)} test queries (top {args.candidates} candidates, keyword ranker: {ranker})...")
    res = evaluate(queries, qrels, args.candidates, modes)
    out_name = "beir_results" if ranker == "bm25" and modes == MODES else f"beir_results_{ranker}_{'-'.join(modes)}"
    (HERE / f"{out_name}.json").write_text(
        json.dumps({"index": stats, "candidates": args.candidates, "keyword_ranker": ranker, "results": res}, indent=2)
    )
    lines = [
        f"# BEIR SciFact ({date.today().isoformat()})",
        "",
        f"{stats.get('docs')} abstracts ({stats.get('chunks', '?')} chunks), {len(queries)} test queries, "
        f"{args.candidates} candidates per retriever, reranker scores all fused candidates, keyword ranker: {ranker}. CPU only.",
        "",
        "| Mode | nDCG@10 | Recall@10 | MRR@10 | p50 latency |",
        "|---|---|---|---|---|",
        *[f"| {LABEL[m]} | {r['ndcg@10']:.3f} | {r['recall@10']:.3f} | {r['mrr@10']:.3f} | {r['p50_ms']:.0f} ms |"
          for m, r in res.items()],
    ]
    (HERE / f"{out_name}.md").write_text("\n".join(lines) + "\n")
    print(f"\nWrote {HERE / (out_name + '.md')}")


if __name__ == "__main__":
    main()
