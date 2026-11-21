# BEIR SciFact (2026-11-19)

5183 abstracts (6659 chunks), 300 test queries, 20 candidates per retriever, reranker scores all fused candidates. CPU only.

| Mode | nDCG@10 | Recall@10 | MRR@10 | p50 latency |
|---|---|---|---|---|
| Vector only | 0.712 | 0.826 | 0.683 | 40 ms |
| Keyword only (Postgres FTS) | 0.390 | 0.536 | 0.348 | 45 ms |
| Hybrid (RRF) | 0.638 | 0.783 | 0.600 | 74 ms |
| Hybrid + rerank | 0.706 | 0.825 | 0.675 | 1631 ms |
