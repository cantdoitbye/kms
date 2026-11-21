"""Offline evaluation of retrieval (and optionally answers).

Retrieval metrics (no LLM needed)
    A passage counts as relevant if it comes from the labelled file and contains
    the labelled evidence string. Labelling by evidence text instead of chunk id
    means the dataset stays valid when chunking parameters change.
    - Hit@k (= Recall@k with one relevant fact per question)
    - MRR@10
    - p50 retrieval latency
    reported for each retrieval mode, overall and per question type.

Answer metrics (--answers, needs LLM_API_KEY)
    - Correct: answer contains the labelled fact (LLM judge)
    - Faithful: every claim in the answer is supported by the retrieved passages (LLM judge)
    - Citation hit: at least one cited passage contains the evidence (deterministic)
    - Abstention: unanswerable questions get the "couldn't find" reply

Usage (from backend/):
    .venv/bin/python -m eval.run_eval
    .venv/bin/python -m eval.run_eval --answers
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.db import SessionLocal
from app.generation import prompts
from app.generation.llm import chat
from app.generation.rag import answer_question
from app.retrieval.search import retrieve
from app.schemas import AskRequest

HERE = Path(__file__).resolve().parent
MODES = ["vector", "keyword", "hybrid", "hybrid_rerank"]
MODE_LABEL = {"vector": "Vector only", "keyword": "Keyword only", "hybrid": "Hybrid (RRF)", "hybrid_rerank": "Hybrid + rerank"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def load_dataset() -> list[dict]:
    return [json.loads(line) for line in (HERE / "dataset.jsonl").read_text().splitlines() if line.strip()]


def is_relevant(chunk, item) -> bool:
    return chunk.filename == item["filename"] and norm(item["evidence"]) in norm(chunk.content)


def first_hit_rank(results, item) -> int | None:
    for rank, c in enumerate(results, start=1):
        if is_relevant(c, item):
            return rank
    return None


def eval_retrieval(items: list[dict], modes: list[str] = MODES) -> dict:
    from sqlalchemy import func, select

    from app.models import TermStat
    from app.retrieval.bm25 import refresh_term_stats

    out: dict = {}
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(TermStat)):
            refresh_term_stats(db)  # BM25 needs document frequencies
        retrieve(db, "warm up", "hybrid_rerank", 5)  # load models before timing
        db.rollback()
        for mode in modes:
            ranks, lat, ctx, by_type = [], [], [], defaultdict(list)
            for it in items:
                results, timings = retrieve(db, it["question"], mode, 10)
                db.rollback()  # end the read transaction (SET LOCAL scope)
                r = first_hit_rank(results, it)
                ctx.append(sum(len(c.content) for c in results[:5]))
                ranks.append(r)
                by_type[it["type"]].append(r)
                lat.append(timings["total_retrieval"])
            out[mode] = {
                **metrics(ranks),
                "p50_ms": round(statistics.median(lat), 1),
                "top5_context_chars": round(statistics.mean(ctx)),
                "by_type": {t: metrics(rs) for t, rs in by_type.items()},
                "misses": [it["question"] for it, r in zip(items, ranks) if r is None or r > 5],
            }
    return out


def metrics(ranks: list[int | None]) -> dict:
    n = len(ranks)
    hit = lambda k: sum(1 for r in ranks if r is not None and r <= k) / n  # noqa: E731
    return {
        "n": n,
        "hit@1": round(hit(1), 3),
        "hit@3": round(hit(3), 3),
        "hit@5": round(hit(5), 3),
        "mrr@10": round(sum(1 / r for r in ranks if r is not None) / n, 3),
    }


JUDGE_SYSTEM = """You grade answers produced by a retrieval-augmented assistant. Reply with JSON only:
{"correct": true|false, "faithful": true|false, "reason": "<one short sentence>"}
- correct: the answer states the reference fact (paraphrase is fine; extra correct detail is fine).
- faithful: every factual claim in the answer is supported by the provided passages."""


def judge(question: str, answer: str, reference: str, passages: str) -> dict:
    res = chat(
        [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": f"Question: {question}\nReference fact: {reference}\n\nPassages:\n{passages}\n\nAnswer to grade:\n{answer}",
            },
        ],
        temperature=0.0,
        max_tokens=800,
        json_mode=True,
    )
    try:
        return json.loads(res.text)
    except json.JSONDecodeError:
        return {"correct": False, "faithful": False, "reason": "judge returned invalid JSON"}


def eval_answers(items: list[dict], limit: int | None, pause: float) -> dict:
    answerable = [it for it in items if it["answerable"]][:limit]
    unanswerable = [it for it in items if not it["answerable"]]
    rows = []
    with SessionLocal() as db:
        for it in answerable + unanswerable:
            resp = answer_question(db, AskRequest(question=it["question"]))
            db.rollback()
            row = {"question": it["question"], "answer": resp.answer, "answerable": it["answerable"]}
            row["claims"] = [c.model_dump() for c in resp.claims]
            if it["answerable"]:
                cited = [c.chunk for c in resp.citations if c.cited]
                row["citation_hit"] = any(is_relevant(c, it) for c in cited)
                passages = prompts.format_sources([c.chunk for c in resp.citations])
                time.sleep(pause)
                row.update(judge(it["question"], resp.answer, it["evidence"], passages))
            else:
                row["abstained"] = prompts.NOT_FOUND.lower().rstrip(".") in resp.answer.lower()
            row["latency_ms"] = resp.timings_ms.get("total")
            rows.append(row)
            print(f"  {'ok ' if row.get('correct', row.get('abstained')) else 'BAD'} {it['question']}")
            time.sleep(pause)  # stay under free-tier rate limits

    a = [r for r in rows if r["answerable"]]
    u = [r for r in rows if not r["answerable"]]
    return {
        "n_answerable": len(a),
        "correct": round(sum(r.get("correct", False) for r in a) / len(a), 3) if a else None,
        "faithful": round(sum(r.get("faithful", False) for r in a) / len(a), 3) if a else None,
        "citation_hit": round(sum(r["citation_hit"] for r in a) / len(a), 3) if a else None,
        "n_unanswerable": len(u),
        "abstention": round(sum(r["abstained"] for r in u) / len(u), 3) if u else None,
        "p50_latency_ms": round(statistics.median(r["latency_ms"] for r in rows), 1) if rows else None,
        **claim_stats(a),
        "rows": rows,
    }


def claim_stats(rows: list[dict]) -> dict:
    claims = [c for r in rows for c in r.get("claims", [])]
    checked = [c for c in claims if c["verdict"] in ("supported", "unsupported")]
    if not claims:
        return {}
    return {
        "claims_total": len(claims),
        "claim_support_rate": round(sum(c["verdict"] == "supported" for c in checked) / len(checked), 3) if checked else None,
        "answers_with_uncited_sentence": round(
            sum(any(c["verdict"] == "uncited" for c in r.get("claims", [])) for r in rows) / len(rows), 3
        ),
    }


def to_markdown(ret: dict, ans: dict | None, n: int) -> str:
    lines = [
        f"# Evaluation results ({date.today().isoformat()})",
        "",
        f"{n} hand-labelled questions over the 4 demo documents (`eval/dataset.jsonl`). "
        "A retrieved passage is relevant if it contains the labelled evidence text.",
        "",
        "## Retrieval",
        "",
        "| Mode | Hit@1 | Hit@3 | Hit@5 | MRR@10 | p50 latency |",
        "|---|---|---|---|---|---|",
    ]
    for m in MODES:
        r = ret[m]
        lines.append(f"| {MODE_LABEL[m]} | {r['hit@1']:.2f} | {r['hit@3']:.2f} | {r['hit@5']:.2f} | {r['mrr@10']:.2f} | {r['p50_ms']:.0f} ms |")

    types = sorted(next(iter(ret.values()))["by_type"])
    lines += ["", "### Hit@1 by question type", "", "| Mode | " + " | ".join(f"{t} (n={ret[MODES[0]]['by_type'][t]['n']})" for t in types) + " |",
              "|---|" + "---|" * len(types)]
    for m in MODES:
        lines.append(f"| {MODE_LABEL[m]} | " + " | ".join(f"{ret[m]['by_type'][t]['hit@1']:.2f}" for t in types) + " |")
    lines += [
        "",
        "*paraphrase*: question wording differs from the document. *lexical*: shares key words. "
        "*identifier*: hinges on an exact token such as `INC-2047`, `L5` or `SEV2`.",
    ]

    if ans:
        lines += [
            "",
            "## Answers (hybrid + rerank, LLM-judged)",
            "",
            "| Metric | Score |",
            "|---|---|",
            f"| Correct (contains the labelled fact) | {ans['correct']:.2f} |",
            f"| Faithful (all claims supported by passages) | {ans['faithful']:.2f} |",
            f"| Citation hit (a cited passage holds the evidence) | {ans['citation_hit']:.2f} |",
            f"| Abstains on unanswerable questions ({ans['n_unanswerable']}) | {ans['abstention']:.2f} |",
            f"| p50 end-to-end latency | {ans['p50_latency_ms'] / 1000:.1f} s |",
            *([f"| Cited claims confirmed by the citation checker ({ans['claims_total']} claims) | {ans['claim_support_rate']:.2f} |",
               f"| Answers containing an uncited sentence | {ans['answers_with_uncited_sentence']:.2f} |"]
              if ans.get("claim_support_rate") is not None else []),
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", action="store_true", help="also evaluate generated answers (needs LLM key)")
    ap.add_argument("--limit", type=int, default=None, help="max answerable questions for --answers")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between LLM calls (rate limits)")
    args = ap.parse_args()

    from app.db import init_db

    init_db()  # idempotent: creates any tables added since the DB was created
    items = load_dataset()
    answerable = [it for it in items if it["answerable"]]
    print(f"Evaluating retrieval on {len(answerable)} questions...")
    ret = eval_retrieval(answerable)
    for m in MODES:
        r = ret[m]
        print(f"  {MODE_LABEL[m]:16} hit@1={r['hit@1']:.2f} hit@5={r['hit@5']:.2f} mrr={r['mrr@10']:.2f} p50={r['p50_ms']}ms")

    ans = None
    if args.answers:
        print("Evaluating answers...")
        ans = eval_answers(items, args.limit, args.pause)
    elif (HERE / "results.json").exists():
        # Retrieval-only run: keep the last (slow, rate-limited) answer evaluation.
        ans = json.loads((HERE / "results.json").read_text()).get("answers")

    (HERE / "results.json").write_text(json.dumps({"retrieval": ret, "answers": ans}, indent=2))
    (HERE / "results.md").write_text(to_markdown(ret, ans, len(answerable)))
    print(f"\nWrote {HERE / 'results.md'}")


if __name__ == "__main__":
    main()
