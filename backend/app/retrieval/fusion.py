from collections.abc import Hashable, Sequence


def reciprocal_rank_fusion(
    ranked_lists: dict[str, Sequence[Hashable]], k: int = 60
) -> list[tuple[Hashable, float]]:
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    score(d) = sum over retrievers r of 1 / (k + rank_r(d)), rank starting at 1.

    Uses only ranks, so it needs no score calibration between retrievers whose
    scores live on different scales (cosine similarity vs. ts_rank).
    """
    scores: dict[Hashable, float] = {}
    for ids in ranked_lists.values():
        for rank, doc_id in enumerate(ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
