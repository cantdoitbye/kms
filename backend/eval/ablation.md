# Ablation study (2026-11-19)

Each row switches off one design choice relative to the full system and re-runs the 40-question retrieval evaluation on the demo documents. Deltas are versus the full system.

| Variant | Passages | Avg tokens | Vector Hit@1 | Hybrid Hit@1 | Hybrid+rerank Hit@1 | Hybrid+rerank MRR | Top-5 context (chars) |
|---|---|---|---|---|---|---|---|
| **Full system** | 25 | 154 | 0.62 | 0.82 | 0.95 | 0.97 | 4,211 |
| No contextual headers | 25 | 154 | 0.65 (+0.03) | 0.82 | 0.95 | 0.97 | 4,201 |
| No query instruction | 25 | 154 | 0.60 (-0.03) | 0.80 (-0.02) | 0.95 | 0.97 | 4,230 |
| No overlap | 25 | 151 | 0.68 (+0.05) | 0.85 (+0.03) | 0.97 (+0.03) | 0.99 (+0.01) | 4,232 |
| Smaller chunks (200) | 32 | 125 | 0.68 (+0.05) | 0.88 (+0.05) | 0.95 | 0.97 | 3,119 |
| Larger chunks (800) | 21 | 182 | 0.62 | 0.85 (+0.03) | 0.95 | 0.97 | 5,526 |
| Fewer candidates (10) | 25 | 154 | 0.62 | 0.82 | 0.95 | 0.97 | 4,185 |
| Postgres ts_rank instead of BM25 | 25 | 154 | 0.62 | 0.85 (+0.03) | 0.95 | 0.97 | 4,211 |

Variants:

- **Full system**: 400-token chunks, 60 overlap, contextual headers, BGE query prefix, 20 candidates
- **No contextual headers**: embed chunk text without '{title} > {section}'
- **No query instruction**: embed the raw question without BGE's retrieval prefix
- **No overlap**: consecutive chunks share no sentences
- **Smaller chunks (200)**: max 200 tokens per chunk
- **Larger chunks (800)**: max 800 tokens per chunk
- **Fewer candidates (10)**: rerank only the top 10 fused candidates
- **Postgres ts_rank instead of BM25**: keyword search ranked by built-in ts_rank_cd (no IDF)
