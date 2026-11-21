"""Okapi BM25 implemented in SQL on top of Postgres full-text search.

Postgres' built-in ts_rank / ts_rank_cd have no inverse document frequency: a
match on "the protein" counts as much as a match on "PrP". On BEIR SciFact that
made keyword search score 0.39 nDCG@10 versus ~0.66 for standard BM25.

Everything BM25 needs is already in Postgres:
  - term frequency: the position list stored per lexeme in each chunk's tsvector
  - document frequency: ts_stat() over all tsvectors, cached in `term_stats`
  - document length: the chunk's token count

score(d, q) = sum over query terms t of
    idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * len(d) / avg_len))
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

K1 = 1.2
B = 0.75


def refresh_term_stats(db: Session) -> None:
    """Recompute document frequencies. Called after every ingestion/deletion.

    A full recompute is fine at MVP scale (~0.5 s for 6.6k chunks); at larger scale
    this would become an incremental update or a dedicated BM25 index (e.g. ParadeDB).
    """
    db.execute(text("DELETE FROM term_stats"))
    db.execute(text("INSERT INTO term_stats (lexeme, df) SELECT word, ndoc FROM ts_stat('SELECT tsv FROM chunks')"))
    db.commit()


_BM25_SQL = """
WITH corpus AS (
    SELECT count(*)::float AS n, greatest(avg(token_count), 1)::float AS avg_len FROM chunks
),
qterms AS (
    SELECT DISTINCT q.lexeme,
           ln(1 + (corpus.n - ts.df + 0.5) / (ts.df + 0.5)) AS idf
    FROM unnest(to_tsvector('english', :query)) AS q
    JOIN term_stats ts ON ts.lexeme = q.lexeme
    CROSS JOIN corpus
),
candidates AS (
    SELECT c.id, c.content, c.token_count, c.tsv
    FROM chunks c
    WHERE c.tsv @@ to_tsquery('english', replace(plainto_tsquery('english', :query)::text, '&', '|'))
    {doc_filter}
)
SELECT cand.id,
       sum(qt.idf * (tf.n * (:k1 + 1))
           / (tf.n + :k1 * (1 - :b + :b * cand.token_count / corpus.avg_len))) AS score
FROM candidates cand
CROSS JOIN corpus
CROSS JOIN LATERAL (
    SELECT u.lexeme, coalesce(array_length(u.positions, 1), 1)::float AS n FROM unnest(cand.tsv) AS u
) AS tf
JOIN qterms qt ON qt.lexeme = tf.lexeme
GROUP BY cand.id, cand.content
ORDER BY score DESC, cand.content
LIMIT :k
"""


def bm25_search(
    db: Session, query: str, k: int, document_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, float]]:
    params: dict = {"query": query, "k": k, "k1": K1, "b": B}
    doc_filter = ""
    if document_ids:
        doc_filter = "AND c.document_id = ANY(:doc_ids)"
        params["doc_ids"] = list(document_ids)
    rows = db.execute(text(_BM25_SQL.format(doc_filter=doc_filter)), params).all()
    return [(r.id, float(r.score)) for r in rows]
