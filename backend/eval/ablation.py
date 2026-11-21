"""Ablation study: switch off one design choice at a time and measure the effect.

Runs against a separate database (`<db>_ablation`), re-indexing the demo docs for
every variant that changes ingestion, so the live data is never touched.

    .venv/bin/python -m eval.ablation       (from backend/)
"""

from __future__ import annotations

import os

# Must happen before any app import: point the app at a throwaway database.
_BASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://kms:kms@localhost:5433/kms")
ABL_DB = _BASE_URL.rsplit("/", 1)[1] + "_ablation"
os.environ["DATABASE_URL"] = _BASE_URL.rsplit("/", 1)[0] + "/" + ABL_DB
os.environ["SEED_DEMO"] = "false"

import json  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

import psycopg  # noqa: E402

HERE = Path(__file__).resolve().parent

# (name, what it tests, setting overrides, query-instruction on?)
VARIANTS: list[tuple[str, str, dict, bool]] = [
    ("Full system", "400-token chunks, 60 overlap, contextual headers, BGE query prefix, 20 candidates", {}, True),
    ("No contextual headers", "embed chunk text without '{title} > {section}'", {"contextual_headers": False}, True),
    ("No query instruction", "embed the raw question without BGE's retrieval prefix", {}, False),
    ("No overlap", "consecutive chunks share no sentences", {"chunk_overlap_tokens": 0}, True),
    ("Smaller chunks (200)", "max 200 tokens per chunk", {"chunk_max_tokens": 200, "chunk_min_tokens": 50}, True),
    ("Larger chunks (800)", "max 800 tokens per chunk", {"chunk_max_tokens": 800, "chunk_min_tokens": 120}, True),
    ("Fewer candidates (10)", "rerank only the top 10 fused candidates", {"candidate_k": 10}, True),
    ("Postgres ts_rank instead of BM25", "keyword search ranked by built-in ts_rank_cd (no IDF)", {"keyword_ranker": "ts_rank"}, True),
]
INGEST_KEYS = {"contextual_headers", "chunk_overlap_tokens", "chunk_max_tokens", "chunk_min_tokens"}
MODES = ["vector", "hybrid", "hybrid_rerank"]


def ensure_database() -> None:
    admin = _BASE_URL.replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (ABL_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{ABL_DB}"')


def reindex() -> dict:
    from eval.demo_index import reindex_demo_docs

    return reindex_demo_docs()


def main() -> None:
    ensure_database()
    from app.config import get_settings
    from app.db import init_db
    from app.retrieval.embedder import get_embedder
    from eval.run_eval import eval_retrieval, load_dataset

    init_db()
    settings = get_settings()
    defaults = {k: getattr(settings, k) for k in INGEST_KEYS | {"candidate_k", "keyword_ranker"}}
    embedder = get_embedder()
    default_instruction = embedder.query_instruction
    items = [it for it in load_dataset() if it["answerable"]]

    rows = []
    last_ingest: dict | None = None
    index_stats: dict = {}
    for name, desc, overrides, instruction in VARIANTS:
        for k, v in {**defaults, **overrides}.items():
            setattr(settings, k, v)
        embedder.query_instruction = default_instruction if instruction else ""
        ingest_cfg = {k: getattr(settings, k) for k in INGEST_KEYS}
        if ingest_cfg != last_ingest:
            print(f"Re-indexing for '{name}'...")
            index_stats = reindex()
            last_ingest = ingest_cfg
        res = eval_retrieval(items, MODES)
        row = {"variant": name, "description": desc, **index_stats}
        for m in MODES:
            row[m] = {k: res[m][k] for k in ("hit@1", "hit@5", "mrr@10", "p50_ms", "top5_context_chars")}
        rows.append(row)
        hr = row["hybrid_rerank"]
        print(f"  {name:32} chunks={row['chunks']:3}  vector={row['vector']['hit@1']:.2f}  "
              f"hybrid={row['hybrid']['hit@1']:.2f}  hybrid+rerank={hr['hit@1']:.2f} mrr={hr['mrr@10']:.2f}")

    (HERE / "ablation.json").write_text(json.dumps(rows, indent=2))
    (HERE / "ablation.md").write_text(to_markdown(rows, len(items)))
    print(f"\nWrote {HERE / 'ablation.md'}")


def to_markdown(rows: list[dict], n: int) -> str:
    base = rows[0]

    def cell(r: dict, mode: str, metric: str) -> str:
        v, b = r[mode][metric], base[mode][metric]
        return f"{v:.2f}" if r is base or abs(v - b) < 0.005 else f"{v:.2f} ({v - b:+.2f})"

    out = [
        f"# Ablation study ({date.today().isoformat()})",
        "",
        f"Each row switches off one design choice relative to the full system and re-runs the {n}-question "
        "retrieval evaluation on the demo documents. Deltas are versus the full system.",
        "",
        "| Variant | Passages | Avg tokens | Vector Hit@1 | Hybrid Hit@1 | Hybrid+rerank Hit@1 | Hybrid+rerank MRR | Top-5 context (chars) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        name = f"**{r['variant']}**" if r is base else r["variant"]
        out.append(
            f"| {name} | {r['chunks']} | {r['avg_tokens']} | {cell(r, 'vector', 'hit@1')} | {cell(r, 'hybrid', 'hit@1')} | "
            f"{cell(r, 'hybrid_rerank', 'hit@1')} | {cell(r, 'hybrid_rerank', 'mrr@10')} | "
            f"{r['hybrid_rerank']['top5_context_chars']:,} |"
        )
    out += ["", "Variants:", ""] + [f"- **{r['variant']}**: {r['description']}" for r in rows]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
