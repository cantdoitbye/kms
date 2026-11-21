"""Retrieval-augmented answering with grounded citations."""

from __future__ import annotations

import re
import time

from sqlalchemy.orm import Session

from app.config import get_settings
from app.generation import prompts
from app.generation.llm import chat
from app.retrieval.search import retrieve
from app.generation.verify import verify_claims
from app.schemas import AskRequest, AskResponse, Citation, ClaimCheck

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Models differ in citation style: gpt-oss emits 【2】 or 【2†source】, others [Source 2].
_ALT_CITATION = re.compile(r"【\s*(\d+)[^】]*】|\[(?:source|src)\s*(\d+)\]", re.IGNORECASE)
_UNICODE_DASHES = str.maketrans({"‐": "-", "‑": "-", " ": " ", " ": " "})


def normalize_answer(text: str) -> str:
    """Canonicalise citation markers to [n] and odd unicode hyphens/spaces to ASCII."""
    text = _ALT_CITATION.sub(lambda m: f"[{m.group(1) or m.group(2)}]", text)
    return text.translate(_UNICODE_DASHES)


def extract_citations(answer: str) -> set[int]:
    refs: set[int] = set()
    for group in _CITATION.findall(answer):
        refs.update(int(x) for x in group.split(","))
    return refs


def answer_question(db: Session, req: AskRequest) -> AskResponse:
    timings: dict[str, float] = {}
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    # 1. Conversational query rewriting: "what about its limitations?" -> standalone query.
    standalone = req.question
    if req.history:
        t = time.perf_counter()
        res = chat(
            [
                {"role": "system", "content": prompts.CONDENSE_SYSTEM},
                {
                    "role": "user",
                    "content": prompts.condense_user_prompt(
                        [h.model_dump() for h in req.history], req.question
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=600,
        )
        standalone = res.text.strip().strip('"') or req.question
        usage["prompt_tokens"] += res.prompt_tokens
        usage["completion_tokens"] += res.completion_tokens
        timings["condense_query"] = round((time.perf_counter() - t) * 1000, 1)

    # 2. Retrieve.
    chunks, rt = retrieve(db, standalone, req.mode, req.top_k, req.document_ids)
    timings.update(rt)

    if not chunks:
        timings["total"] = round(sum(timings.values()), 1)
        return AskResponse(
            question=req.question,
            standalone_question=standalone,
            answer=prompts.NOT_FOUND,
            citations=[],
            timings_ms=timings,
            usage=usage,
            model=get_settings().llm_model,
        )

    # 3. Generate a grounded answer.
    t = time.perf_counter()
    res = chat(
        [
            {"role": "system", "content": prompts.ANSWER_SYSTEM},
            {
                "role": "user",
                "content": prompts.answer_user_prompt(standalone, prompts.format_sources(chunks)),
            },
        ]
    )
    timings["generate"] = round((time.perf_counter() - t) * 1000, 1)
    usage["prompt_tokens"] += res.prompt_tokens
    usage["completion_tokens"] += res.completion_tokens

    # 4. Map [n] markers back to chunks; drop hallucinated reference numbers.
    text = normalize_answer(res.text)
    cited = extract_citations(text)
    valid = set(range(1, len(chunks) + 1))
    answer = _CITATION.sub(
        lambda m: "".join(f"[{n}]" for n in m.group(1).replace(" ", "").split(",") if int(n) in valid),
        text,
    )
    citations = [
        Citation(ref=i, chunk=c, cited=i in cited) for i, c in enumerate(chunks, start=1)
    ]

    # 5. Check every cited claim against the passages it cites.
    claims: list[ClaimCheck] = []
    if req.verify and answer.strip() != prompts.NOT_FOUND:
        t = time.perf_counter()
        checked, vusage = verify_claims(answer, chunks)
        claims = [ClaimCheck(**c) for c in checked]
        usage["prompt_tokens"] += vusage["prompt_tokens"]
        usage["completion_tokens"] += vusage["completion_tokens"]
        timings["verify"] = round((time.perf_counter() - t) * 1000, 1)
    timings["total"] = round(sum(v for k, v in timings.items() if k != "total_retrieval"), 1)

    return AskResponse(
        question=req.question,
        standalone_question=standalone,
        answer=answer,
        citations=citations,
        claims=claims,
        timings_ms=timings,
        usage=usage,
        model=get_settings().llm_model,
    )
