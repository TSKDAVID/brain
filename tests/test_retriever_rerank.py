from types import SimpleNamespace

from app.cache import reset_cache_for_tests
from app.rag import retriever


def _settings():
    return SimpleNamespace(faq_cache_ttl_seconds=300)


def test_rerank_prefers_higher_overlap():
    rows = [
        {"id": "a", "chunk_text": "Refund policy: refunds processed in 7-10 days.", "similarity": 0.4},
        {"id": "b", "chunk_text": "Shipping policy: orders ship within 24 hours.", "similarity": 0.6},
    ]
    reranked = retriever._rerank(rows, "How long for a refund?")
    assert reranked[0]["id"] == "a"


def test_retrieve_faq_context_uses_rerank(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(
        retriever,
        "rpc_rows",
        lambda *_args, **_kwargs: [
            {"id": "high-trgm", "chunk_text": "Random shipping notice.", "similarity": 0.9},
            {"id": "matching", "chunk_text": "Refunds are issued in 10 days.", "similarity": 0.55},
        ],
    )
    monkeypatch.setattr(retriever, "get_rows", lambda **_kwargs: [])

    context, sources, score = retriever.retrieve_faq_context(
        "tenant-1",
        "When will I get my refund?",
        max_chunks=2,
    )
    assert "Refunds are issued" in context
    assert "matching" in sources
    assert score > 0.0


def test_faq_answer_cache_round_trip(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(retriever, "get_settings", _settings)
    retriever.cache_faq_answer(
        "tenant-1",
        "How long does shipping take?",
        response="Usually 24 hours.",
        sources=["s1"],
        confidence=0.9,
    )
    cached = retriever.get_cached_faq_answer("tenant-1", "How long does shipping take?")
    assert cached == {
        "response": "Usually 24 hours.",
        "sources": ["s1"],
        "confidence": 0.9,
    }


def test_faq_answer_cache_miss():
    cached = retriever.get_cached_faq_answer("tenant-1", "Some other question")
    assert cached is None
