import logging
from typing import Iterable

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _fallback_no_llm(retrieved_context: str, user_message: str) -> str:
    excerpt = (retrieved_context or "").strip()[:1200]
    return (
        "Set GROQ_API_KEY on the Chaster Brain API to generate natural-language answers. "
        f"From your indexed content, this excerpt may be relevant to “{user_message}”:\n\n{excerpt}"
    )


def _build_messages(
    *,
    system_prompt: str,
    summary: str,
    history: Iterable[dict[str, str]] | None,
    retrieved_context: str,
    user_message: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if summary and summary.strip():
        messages.append(
            {
                "role": "system",
                "content": (
                    "Conversation summary so far (older turns compressed):\n"
                    f"{summary.strip()}"
                ),
            }
        )
    if history:
        for turn in history:
            role = turn.get("role")
            content = turn.get("content") or turn.get("body") or ""
            if not content:
                continue
            if role not in {"user", "assistant", "system"}:
                role = "user" if role == "visitor" else "assistant"
            messages.append({"role": role, "content": content})
    messages.append(
        {
            "role": "user",
            "content": (
                "CONTEXT (for you to use, not to quote in full):\n"
                f"{retrieved_context}\n\n"
                "USER QUESTION:\n"
                f"{user_message}"
            ),
        }
    )
    return messages


def generate_answer(
    *,
    user_message: str,
    retrieved_context: str,
    response_tone: str,
    summary: str = "",
    history: Iterable[dict[str, str]] | None = None,
) -> str:
    settings = get_settings()
    if not settings.groq_api_key:
        return _fallback_no_llm(retrieved_context, user_message)

    system_prompt = (
        "You are Chaster Brain, a customer support assistant. "
        f"Use a {response_tone} tone. "
        "You will receive optional CONVERSATION SUMMARY, prior chat turns, "
        "CONTEXT snippets (may be partial) and a USER QUESTION. "
        "Reply with a direct answer to that question only. "
        "Use 2-6 short sentences. Do NOT paste the context verbatim or repeat entire policy sections. "
        "If something is unclear, ask one focused clarifying question."
    )
    payload = {
        "model": settings.groq_model,
        "temperature": 0.4,
        "max_tokens": 512,
        "messages": _build_messages(
            system_prompt=system_prompt,
            summary=summary,
            history=history,
            retrieved_context=retrieved_context,
            user_message=user_message,
        ),
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
            body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        )
        if text:
            return text

        logger.warning("Groq returned empty message content; model=%s", settings.groq_model)
        return (
            "The model returned no text. Check GROQ_API_KEY and GROQ_MODEL (e.g. llama-3.1-70b-versatile). "
            f"Context excerpt:\n{(retrieved_context or '')[:900]}"
        )
    except Exception as exc:
        logger.warning("Groq chat failed: %s", exc)
        return (
            "Could not reach the LLM. Verify GROQ_API_KEY and model name. "
            f"Context excerpt:\n{(retrieved_context or '')[:900]}"
        )
