"""Draft support replies from case thread + tenant knowledge base."""

from __future__ import annotations

from app.db.client import get_rows, get_single_row
from app.orchestrator.graph import build_graph
from app.rag.retriever import retrieve_faq_context

_orchestrator = build_graph()


def _format_thread(messages: list[dict], *, limit: int = 24) -> str:
    lines: list[str] = []
    for row in messages[-limit:]:
        if row.get("is_system"):
            continue
        body = str(row.get("body") or "").strip()
        if not body:
            continue
        who = "Client" if row.get("sender_id") else "Support"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def suggest_support_reply(
    *,
    tenant_id: str,
    case_id: str,
    draft_hint: str | None = None,
) -> tuple[str, list[str]]:
    case = get_single_row(
        "support_cases",
        "id,tenant_id,subject,description,status,category",
        {"id": case_id},
    )
    if not case:
        raise ValueError("case not found")
    if str(case.get("tenant_id")) != str(tenant_id):
        raise ValueError("case tenant mismatch")

    messages = get_rows(
        "support_case_messages",
        "sender_id,body,is_system,created_at",
        {"case_id": case_id},
        limit=50,
        order="created_at.asc",
    )
    thread = _format_thread(messages)
    subject = str(case.get("subject") or "").strip()
    description = str(case.get("description") or "").strip()
    search_q = " ".join(filter(None, [subject, description, thread[-500:] if thread else ""]))
    kb_context, sources, _score = retrieve_faq_context(tenant_id, search_q)

    prompt_parts = [
        "You are drafting a professional support reply for a B2B customer case.",
        f"Subject: {subject}",
        f"Category: {case.get('category', 'other')}",
    ]
    if description:
        prompt_parts.append(f"Case description: {description}")
    if thread:
        prompt_parts.append("Conversation so far:\n" + thread)
    if kb_context:
        prompt_parts.append("Relevant knowledge base excerpts:\n" + kb_context)
    if draft_hint and draft_hint.strip():
        prompt_parts.append(f"Agent notes for this draft: {draft_hint.strip()}")
    prompt_parts.append(
        "Write only the reply message body (no subject line, no greeting prefix like 'Dear', "
        "no signature block). Be concise, empathetic, and actionable."
    )
    composed = "\n\n".join(prompt_parts)

    state = _orchestrator.invoke(
        {
            "tenant_id": tenant_id,
            "app_id": "support-suggest-reply",
            "message": composed,
            "metadata": {"source": "support_suggest_reply", "case_id": case_id},
        }
    )
    draft = str(state.get("response") or "").strip()
    if not draft:
        draft = (
            "Thank you for your patience. We are reviewing your case and will follow up "
            "with the next steps shortly."
        )
    return draft, list(sources or [])
