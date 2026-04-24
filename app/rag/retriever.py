from app.db.client import get_rows, rpc_rows


def _join_chunks_until_budget(rows: list[dict], *, max_chars: int) -> tuple[str, list[str]]:
    """Keep trgm-ranked order; stop before the prompt is flooded with the whole knowledge base."""
    parts: list[str] = []
    sources: list[str] = []
    total = 0
    for row in rows:
        text = str(row.get("chunk_text", "")).strip()
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
) -> tuple[str, list[str]]:
    q = (query or "").strip()
    if q:
        try:
            rows = rpc_rows(
                "match_knowledge_chunks_trgm",
                {
                    "p_tenant_id": tenant_id,
                    "search_query": q,
                    "match_count": max_chunks,
                },
            )
            if rows:
                return _join_chunks_until_budget(rows, max_chars=max_context_chars)
        except Exception:
            pass

    rows = get_rows(
        table="knowledge_chunks",
        select="id,chunk_text",
        filters={"tenant_id": tenant_id},
        limit=max_chunks,
    )
    context, sources = _join_chunks_until_budget(rows, max_chars=max_context_chars)
    if not context:
        context = "No indexed FAQ context found for this tenant."
    return context, sources
