"""Conversation memory manager.

Responsibilities:
    - Load the recent verbatim turns + rolling summary for a conversation
      so the orchestrator can include them in the LLM prompt.
    - Persist new turns into Supabase `messages` while keeping a small hot
      cache in Redis for fast retrieval on the next request.
    - Compress older turns into a rolling summary when the conversation grows
      past a configured threshold (token budget OR turn count).

Storage layout:
    - Verbatim history -> `public.messages` (already used by /v1/process).
    - Rolling summary  -> `public.brain_conversation_summaries`
      (new migration, one row per conversation).
    - Hot cache (Redis or in-memory shim):
        * `chat:hot:{conversation_id}`     -> list of JSON-encoded turns
        * `chat:summary:{conversation_id}` -> JSON {summary_text, version, ...}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.cache import (
    cache_delete,
    cache_get_json,
    cache_lpush,
    cache_lrange,
    cache_ltrim,
    cache_set_json,
)
from app.config import get_settings
from app.db.client import get_rows, get_single_row, upsert_row

logger = logging.getLogger(__name__)


HOT_LIST_MAX = 40  # Cap hot cache so it never grows unbounded for long chats.
SUMMARIZER_KEEP_RECENT = 8


@dataclass
class HistoryTurn:
    role: str  # "user" | "assistant" | "system"
    body: str

    def to_chat_message(self) -> dict[str, str]:
        if self.role == "user":
            role = "user"
        elif self.role == "assistant":
            role = "assistant"
        else:
            role = "system"
        return {"role": role, "content": self.body}


@dataclass
class ConversationContext:
    conversation_id: str | None
    summary: str = ""
    history: list[HistoryTurn] = field(default_factory=list)
    estimated_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """Rough token estimate without pulling in a tokenizer."""

    if not text:
        return 0
    return max(1, len(text) // 4)


def _hot_key(conversation_id: str) -> str:
    return f"chat:hot:{conversation_id}"


def _summary_key(conversation_id: str) -> str:
    return f"chat:summary:{conversation_id}"


def _serialize_turn(turn: HistoryTurn) -> str:
    return json.dumps({"role": turn.role, "body": turn.body}, ensure_ascii=False)


def _deserialize_turns(items: Iterable[str]) -> list[HistoryTurn]:
    out: list[HistoryTurn] = []
    for raw in items:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        role = str(data.get("role") or "")
        body = str(data.get("body") or "")
        if role and body:
            out.append(HistoryTurn(role=role, body=body))
    return out


def _hot_history(conversation_id: str, *, limit: int) -> list[HistoryTurn]:
    raw = cache_lrange(_hot_key(conversation_id), 0, max(0, limit - 1))
    if not raw:
        return []
    # Items were left-pushed (newest first); reverse for chronological order.
    return list(reversed(_deserialize_turns(raw)))


def _hot_summary(conversation_id: str) -> str | None:
    payload = cache_get_json(_summary_key(conversation_id))
    if isinstance(payload, dict):
        text = str(payload.get("summary_text") or "").strip()
        return text or None
    return None


def _supabase_history(conversation_id: str, *, limit: int) -> list[HistoryTurn]:
    rows = get_rows(
        table="messages",
        select="id,sender_id,body,created_at",
        filters={"conversation_id": conversation_id},
        limit=max(1, limit),
        order="created_at.desc",
    )
    if not rows:
        return []
    rows = list(reversed(rows))
    out: list[HistoryTurn] = []
    for row in rows:
        body = str(row.get("body") or "").strip()
        if not body:
            continue
        sender = row.get("sender_id")
        role = "assistant" if sender is None else "user"
        out.append(HistoryTurn(role=role, body=body))
    return out


def _supabase_summary(conversation_id: str) -> str:
    row = get_single_row(
        "brain_conversation_summaries",
        select="summary_text",
        filters={"conversation_id": conversation_id},
    )
    if not row:
        return ""
    return str(row.get("summary_text") or "")


def load_context(
    conversation_id: str | None,
    *,
    recent_turns: int | None = None,
) -> ConversationContext:
    """Return rolling summary + recent verbatim turns for a conversation.

    Hot cache is consulted first; on miss, Supabase is queried and the cache
    re-warmed so the next request is fast.
    """

    settings = get_settings()
    desired = recent_turns if recent_turns is not None else settings.memory_recent_turns
    desired_pairs = max(1, desired) * 2  # user+assistant per turn

    if not conversation_id:
        return ConversationContext(conversation_id=None)

    history = _hot_history(conversation_id, limit=desired_pairs)
    summary = _hot_summary(conversation_id)

    if not history:
        try:
            history = _supabase_history(conversation_id, limit=desired_pairs)
        except Exception as exc:
            logger.warning("memory.load_context: Supabase history fetch failed (%s)", exc)
            history = []
        if history:
            try:
                cache_lpush(
                    _hot_key(conversation_id),
                    [_serialize_turn(turn) for turn in reversed(history)],
                    ttl_seconds=settings.memory_hot_ttl_seconds,
                )
                cache_ltrim(_hot_key(conversation_id), 0, HOT_LIST_MAX - 1)
            except Exception as exc:  # pragma: no cover - cache best-effort
                logger.debug("memory.load_context: cache prime failed (%s)", exc)

    if summary is None:
        try:
            persisted_summary = _supabase_summary(conversation_id)
        except Exception as exc:
            logger.warning("memory.load_context: Supabase summary fetch failed (%s)", exc)
            persisted_summary = ""
        summary = persisted_summary or ""
        if summary:
            try:
                cache_set_json(
                    _summary_key(conversation_id),
                    {"summary_text": summary},
                    ttl_seconds=settings.memory_summary_ttl_seconds,
                )
            except Exception:  # pragma: no cover - cache best-effort
                pass
    else:
        summary = summary or ""

    estimated = estimate_tokens(summary) + sum(estimate_tokens(turn.body) for turn in history)
    return ConversationContext(
        conversation_id=conversation_id,
        summary=summary,
        history=history,
        estimated_tokens=estimated,
    )


def append_turn(
    conversation_id: str | None,
    *,
    user_message: str,
    assistant_message: str,
) -> None:
    """Push the freshly exchanged turn into the hot cache.

    Persistence to Supabase `messages` already happens in the /v1/process
    endpoint; we only refresh the cache here so the next call sees the latest
    turn without a database round-trip.
    """

    if not conversation_id:
        return
    settings = get_settings()
    items: list[str] = []
    if assistant_message and assistant_message.strip():
        items.append(_serialize_turn(HistoryTurn(role="assistant", body=assistant_message.strip())))
    if user_message and user_message.strip():
        items.append(_serialize_turn(HistoryTurn(role="user", body=user_message.strip())))
    if not items:
        return
    try:
        cache_lpush(_hot_key(conversation_id), items, ttl_seconds=settings.memory_hot_ttl_seconds)
        cache_ltrim(_hot_key(conversation_id), 0, HOT_LIST_MAX - 1)
    except Exception as exc:  # pragma: no cover - cache best-effort
        logger.debug("memory.append_turn: cache push failed (%s)", exc)


def reset_conversation_cache(conversation_id: str | None) -> None:
    if not conversation_id:
        return
    cache_delete(_hot_key(conversation_id))
    cache_delete(_summary_key(conversation_id))


def _format_history_for_summary(turns: list[HistoryTurn]) -> str:
    lines = []
    for turn in turns:
        role = "User" if turn.role == "user" else "Assistant" if turn.role == "assistant" else "System"
        body = turn.body.strip().replace("\n", " ")
        lines.append(f"{role}: {body}")
    return "\n".join(lines)


def _summarize_via_groq(*, prior_summary: str, older_turns: list[HistoryTurn]) -> str:
    """Compress older turns into a 250-400 token rolling summary using Groq.

    Returns the new summary text on success or the prior summary on failure.
    """

    settings = get_settings()
    if not settings.groq_api_key or not older_turns:
        return prior_summary

    import httpx  # local import to keep startup time fast

    transcript = _format_history_for_summary(older_turns)
    system_prompt = (
        "You compress customer-support chat history into a tight rolling summary. "
        "Keep facts the assistant must remember (user identity hints, order ids, prior decisions, "
        "open questions, agreed next steps). Drop pleasantries. "
        "Reply with plain prose, 4-8 sentences max, no headings, no markdown."
    )
    user_prompt = (
        "PRIOR SUMMARY (may be empty):\n"
        f"{prior_summary or '(none)'}\n\n"
        "NEW TURNS TO INCORPORATE:\n"
        f"{transcript}\n\n"
        "Write the updated rolling summary now."
    )
    payload = {
        "model": settings.groq_model,
        "temperature": 0.2,
        "max_tokens": 480,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        response = httpx.post(
            f"{settings.groq_api_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45.0,
        )
        response.raise_for_status()
        body = response.json()
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return text or prior_summary
    except Exception as exc:
        logger.warning("memory.summarize: Groq call failed (%s)", exc)
        return prior_summary


def maybe_compress(
    conversation_id: str | None,
    *,
    tenant_id: str,
    summarizer: Any | None = None,
) -> bool:
    """Compress older turns into the rolling summary when budgets are exceeded.

    Returns True when a new summary was produced, False otherwise.
    The `summarizer` param exists for tests; callers in production omit it.
    """

    if not conversation_id:
        return False
    settings = get_settings()
    context = load_context(conversation_id, recent_turns=settings.memory_recent_turns)

    over_messages = len(context.history) > settings.memory_compress_after_messages
    over_tokens = context.estimated_tokens > settings.memory_compress_token_budget
    if not (over_messages or over_tokens):
        return False

    keep_recent = SUMMARIZER_KEEP_RECENT
    if len(context.history) <= keep_recent:
        return False
    older = context.history[: len(context.history) - keep_recent]
    if not older:
        return False

    summarize = summarizer or _summarize_via_groq
    new_summary = summarize(prior_summary=context.summary, older_turns=older)
    if not new_summary or new_summary == context.summary:
        return False

    try:
        upsert_row(
            "brain_conversation_summaries",
            {
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "summary_text": new_summary,
                "summarized_message_count": len(older),
            },
            on_conflict="conversation_id",
        )
    except Exception as exc:
        logger.warning("memory.maybe_compress: persist failed (%s)", exc)
        return False

    try:
        cache_set_json(
            _summary_key(conversation_id),
            {"summary_text": new_summary},
            ttl_seconds=settings.memory_summary_ttl_seconds,
        )
        # Trim hot cache to the kept-recent slice (newest first ordering).
        cache_ltrim(_hot_key(conversation_id), 0, max(0, keep_recent - 1))
    except Exception as exc:  # pragma: no cover - cache best-effort
        logger.debug("memory.maybe_compress: cache update failed (%s)", exc)

    return True
