# Evaluation results (2026-11-19)

40 hand-labelled questions over the 4 demo documents (`eval/dataset.jsonl`). A retrieved passage is relevant if it contains the labelled evidence text.

## Retrieval

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR@10 | p50 latency |
|---|---|---|---|---|---|
| Vector only | 0.62 | 0.97 | 1.00 | 0.79 | 16 ms |
| Keyword only | 0.85 | 0.95 | 1.00 | 0.91 | 4 ms |
| Hybrid (RRF) | 0.82 | 0.97 | 1.00 | 0.90 | 22 ms |
| Hybrid + rerank | 0.95 | 1.00 | 1.00 | 0.97 | 635 ms |

### Hit@1 by question type

| Mode | identifier (n=4) | lexical (n=12) | paraphrase (n=24) |
|---|---|---|---|
| Vector only | 0.50 | 0.83 | 0.54 |
| Keyword only | 0.75 | 0.92 | 0.83 |
| Hybrid (RRF) | 0.75 | 0.92 | 0.79 |
| Hybrid + rerank | 0.75 | 1.00 | 0.96 |

*paraphrase*: question wording differs from the document. *lexical*: shares key words. *identifier*: hinges on an exact token such as `INC-2047`, `L5` or `SEV2`.

## Answers (hybrid + rerank, LLM-judged)

| Metric | Score |
|---|---|
| Correct (contains the labelled fact) | 1.00 |
| Faithful (all claims supported by passages) | 1.00 |
| Citation hit (a cited passage holds the evidence) | 1.00 |
| Abstains on unanswerable questions (3) | 1.00 |
| p50 end-to-end latency | 10.6 s |
| Cited claims confirmed by the citation checker (44 claims) | 0.97 |
| Answers containing an uncited sentence | 0.05 |
