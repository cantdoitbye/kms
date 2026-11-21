"""CI quality gate: index the demo docs, run the retrieval eval, fail on regressions.

Thresholds sit just below the current scores (Hit@1 0.95, MRR 0.97 for
hybrid + rerank) so a real regression fails the build but noise does not.

    .venv/bin/python -m eval.gate
"""

from __future__ import annotations

import sys

THRESHOLDS = {
    "hybrid_rerank": {"hit@1": 0.90, "mrr@10": 0.93, "hit@5": 0.97},
    "hybrid": {"hit@1": 0.80, "mrr@10": 0.88},
}


def main() -> int:
    from app.db import init_db
    from eval.demo_index import reindex_demo_docs
    from eval.run_eval import eval_retrieval, load_dataset

    init_db()
    print("Indexed demo docs:", reindex_demo_docs())
    items = [it for it in load_dataset() if it["answerable"]]
    results = eval_retrieval(items, list(THRESHOLDS))

    failures = []
    for mode, limits in THRESHOLDS.items():
        for metric, floor in limits.items():
            got = results[mode][metric]
            status = "ok  " if got >= floor else "FAIL"
            print(f"{status} {mode:14} {metric:7} {got:.3f} (min {floor:.2f})")
            if got < floor:
                failures.append(f"{mode} {metric}")
    if failures:
        print("\nRetrieval quality regressed:", ", ".join(failures))
        print("Misses:", *results["hybrid_rerank"]["misses"], sep="\n  - ")
        return 1
    print("\nRetrieval quality gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
