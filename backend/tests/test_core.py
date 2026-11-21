"""Fast unit tests: no database, no model downloads (token counter is stubbed)."""

from app.generation.rag import extract_citations, normalize_answer
from app.ingestion.chunker import Chunker
from app.ingestion.cleaner import clean_blocks, normalize
from app.ingestion.extractors import Block
from app.retrieval.fusion import reciprocal_rank_fusion


def word_counter(texts):
    return [len(t.split()) for t in texts]


def test_normalize_fixes_hyphenation_ligatures_and_wrapping():
    assert normalize("infor-\nmation ﬁle\nwrapped   line") == "information file wrapped line"


def test_normalize_keeps_list_items_on_separate_lines():
    assert normalize("Items:\n- one\n- two") == "Items:\n- one\n- two"


def test_clean_blocks_drops_page_numbers_and_running_headers():
    blocks = []
    for page in range(1, 5):
        blocks += [
            Block("ACME Corp | Internal", page=page),
            Block(f"Intro paragraph {page}.", page=page),
            Block(f"Body text on page {page}.", page=page),
            Block(f"Closing paragraph {page}.", page=page),
            Block(f"Page {page} of 4", page=page),
        ]
    out = clean_blocks(blocks, num_pages=4)
    texts = [b.text for b in out]
    assert "ACME Corp | Internal" not in texts and not any(t.startswith("Page") for t in texts)
    # Mid-page body text that differs only by numbers must survive.
    assert [t for t in texts if t.startswith("Body")] == [f"Body text on page {p}." for p in range(1, 5)]


def test_chunker_respects_budget_overlap_and_sections():
    sentences = " ".join(f"Sentence number {i} is here." for i in range(60))  # 5 words each
    blocks = [Block("Intro", kind="heading"), Block(sentences), Block("Other", kind="heading"), Block("Short tail text " * 30)]
    chunks = Chunker(word_counter, max_tokens=50, overlap_tokens=10, min_tokens=5).chunk(blocks)

    assert all(c.token_count <= 50 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    intro = [c for c in chunks if c.section == "Intro"]
    other = [c for c in chunks if c.section == "Other"]
    assert intro and other
    # consecutive chunks in the same section share whole trailing sentences
    tail = intro[0].content.split(". ")[-1]
    assert tail.rstrip(".") in intro[1].content
    # no chunk mixes the two sections
    assert not any("Sentence number" in c.content for c in other)


def test_chunker_hard_splits_oversized_sentence():
    blocks = [Block("word " * 500)]
    chunks = Chunker(word_counter, max_tokens=100, overlap_tokens=10, min_tokens=5).chunk(blocks)
    assert len(chunks) >= 5 and all(c.token_count <= 100 for c in chunks)


def test_rrf_rewards_agreement_between_retrievers():
    fused = reciprocal_rank_fusion({"vector": ["a", "b", "c"], "keyword": ["c", "a", "d"]}, k=60)
    ids = [i for i, _ in fused]
    assert ids[0] == "a"  # ranked 1st and 2nd beats 3rd and 1st
    assert set(ids) == {"a", "b", "c", "d"}


def test_extract_citations():
    assert extract_citations("Yes [1]. Also [2, 3] and [3][4].") == {1, 2, 3, 4}


def test_normalize_answer_canonicalises_citation_styles():
    text = normalize_answer("Locked for 14 minutes【2】 and retried【3†source】; see [Source 4]. non‑backward")
    assert text == "Locked for 14 minutes[2] and retried[3]; see [4]. non-backward"
    assert extract_citations(text) == {2, 3, 4}


def test_strip_markdown_keeps_identifiers():
    from app.ingestion.extractors import _strip_markdown

    text = "**Severity:** SEV1 and *very* bad, see [the docs](http://x). Column `tax_region`, 2*3=6, snake_case_name."
    assert _strip_markdown(text) == "Severity: SEV1 and very bad, see the docs. Column `tax_region`, 2*3=6, snake_case_name."


def test_split_claims_keeps_citations_with_their_sentence():
    from app.generation.verify import split_claims

    answer = "The lock lasted 14 minutes. [2] Retries were not idempotent [2][3].\n- **Owner:** Revenue Engineering [1]\nThanks."
    claims = split_claims(answer)
    assert [c["refs"] for c in claims] == [[2], [2, 3], [1]]
    assert claims[0]["text"] == "The lock lasted 14 minutes."
    assert claims[2]["text"] == "Owner: Revenue Engineering"


def test_embed_documents_preserves_input_order():
    """Length-sorted batching must return vectors in the caller's order."""
    import numpy as np

    from app.retrieval.embedder import Embedder

    class FakeModel:
        def embed(self, texts, batch_size):
            return [np.array([len(t), 1.0]) for t in texts]

    e = Embedder.__new__(Embedder)
    e.model, e.batch_size = FakeModel(), 2
    texts = ["ccc", "a", "bbbbb", "dd"]
    vecs = e.embed_documents(texts)
    expected = np.array([[len(t), 1.0] for t in texts])
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    assert np.allclose(vecs, expected)
