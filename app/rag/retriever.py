"""FAQ retrieval with token-overlap rerank.

The Postgres trigram RPC is great at fuzzy matching but its order is purely
character-similarity based. Here we layer a cheap, dependency-free rerank that
prefers chunks with stronger keyword overlap to the query, then assemble the
final context within a character budget.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

from app.cache import cache_get_json, cache_set_json
from app.config import get_settings
from app.db.client import get_rows, rpc_rows


_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "to", "and", "or", "for", "in", "on", "at", "by", "with",
        "as", "from", "this", "that", "these", "those", "i", "you", "we",
        "they", "he", "she", "it", "what", "how", "why", "when", "where",
        "do", "does", "did", "can", "could", "would", "should", "have", "has",
        "had", "but", "not", "no", "yes", "your", "my", "our", "their",
        "please", "thanks", "thank", "hi", "hello",
    }
)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {tok.lower() for tok in _WORD_RE.findall(text) if tok.lower() not in _STOPWORDS}


def _query_hash(tenant_id: str, query: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}|{query.strip().lower()}".encode("utf-8")).hexdigest()
    return digest[:24]


def _faq_answer_cache_key(tenant_id: str, query: str) -> str:
    # v2: drop answers cached under older orchestration / prompts.
    return f"faq:ans:v2:{_query_hash(tenant_id, query)}"


def _rerank(rows: Iterable[dict], query: str) -> list[dict]:
    query_terms = _tokens(query)
    if not query_terms:
        return list(rows)
    ranked: list[tuple[float, dict]] = []
    for row in rows:
        text = str(row.get("chunk_text") or "")
        if not text:
            continue
        chunk_terms = _tokens(text)
        if not chunk_terms:
            overlap_score = 0.0
        else:
            shared = len(query_terms & chunk_terms)
            overlap_score = shared / max(1, len(query_terms))
        trgm = float(row.get("similarity") or 0.0)
        # Weighted combination: trigram is the base, overlap pushes well-matched chunks up.
        combined = (trgm * 0.55) + (overlap_score * 0.45)
        annotated = dict(row)
        annotated["_rerank_score"] = round(combined, 4)
        annotated["_overlap_score"] = round(overlap_score, 4)
        ranked.append((combined, annotated))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked]


def _join_chunks_until_budget(rows: list[dict], *, max_chars: int) -> tuple[str, list[str]]:
    parts: list[str] = []
    sources: list[str] = []
    total = 0
    for row in rows:
        text = str(row.get("chunk_text") or "").strip()
        if not text:
            continue
        sep = 2 if parts else 0
        if total + sep + len(text) <= max_chars:
            parts.append(text)
            sources.append(str(row.get("id", "")))
            total += sep + len(text)
            continue
        if not parts:
            parts.append(text[:max_chars])
            sources.append(str(row.get("id", "")))
        break
    return "\n\n".join(parts), sources


def retrieve_faq_context(
    tenant_id: str,
    query: str,
    *,
    max_chunks: int = 5,
    max_context_chars: int = 2800,
) -> tuple[str, list[str], float]:
    """Return `(context, sources, top_score)` for the FAQ path.

    `top_score` is the rerank score of the best chunk in [0,1]; the
    confidence_node uses it as a retrieval-quality signal.
    """

    q = (query or "").strip()
    rows: list[dict] = []
    if q:
        try:
            rows = rpc_rows(
                "match_knowledge_chunks_trgm",
                {
                    "p_tenant_id": tenant_id,
                    "search_query": q,
                    "match_count": max(max_chunks, 8),
                },
            )
        except Exception:
            rows = []

    if not rows:
        try:
            rows = get_rows(
                table="knowledge_chunks",
                select="id,chunk_text",
                filters={"tenant_id": tenant_id},
                limit=max_chunks,
            )
        except Exception:
            rows = []

    if not rows:
        return "No indexed FAQ context found for this tenant.", [], 0.0

    reranked = _rerank(rows, q)[: max(1, max_chunks)]
    top_score = float(reranked[0].get("_rerank_score", 0.0)) if reranked else 0.0
    context, sources = _join_chunks_until_budget(reranked, max_chars=max_context_chars)
    if not context:
        context = "No indexed FAQ context found for this tenant."
        return context, [], 0.0
    return context, sources, top_score


def get_cached_faq_answer(tenant_id: str, query: str) -> dict | None:
    """Look up a cached final FAQ answer (response + sources)."""

    if not (tenant_id and query and query.strip()):
        return None
    cached = cache_get_json(_faq_answer_cache_key(tenant_id, query))
    if isinstance(cached, dict):
        return cached
    return None


def cache_faq_answer(
    tenant_id: str,
    query: str,
    *,
    response: str,
    sources: list[str],
    confidence: float,
) -> None:
    if not (tenant_id and query and response):
        return
    settings = get_settings()
    cache_set_json(
        _faq_answer_cache_key(tenant_id, query),
        {
            "response": response,
            "sources": sources,
            "confidence": confidence,
        },
        ttl_seconds=settings.faq_cache_ttl_seconds,
    )
