# BEIR SciFact (2026-11-19)

5183 abstracts (6659 chunks), 300 test queries, 20 candidates per retriever, reranker scores all fused candidates, keyword ranker: bm25. CPU only.

| Mode | nDCG@10 | Recall@10 | MRR@10 | p50 latency |
|---|---|---|---|---|
| Vector only | 0.712 | 0.826 | 0.683 | 29 ms |
| Keyword only (BM25 in SQL) | 0.696 | 0.818 | 0.663 | 97 ms |
| Hybrid (RRF) | 0.724 | 0.853 | 0.688 | 136 ms |
| Hybrid + rerank | 0.714 | 0.848 | 0.680 | 1171 ms |
