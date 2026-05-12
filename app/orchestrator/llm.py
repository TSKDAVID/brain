import logging
from typing import Iterable

import httpx

from app.config import get_settings
from app.orchestrator.intent_llm import is_light_greeting

logger = logging.getLogger(__name__)


def _kb_context_is_empty(retrieved_context: str) -> bool:
    c = (retrieved_context or "").strip().lower()
    if not c:
        return True
    return "no indexed faq context" in c


def _instant_greeting_reply(response_tone: str) -> str:
    t = (response_tone or "professional").lower()
    if "friendly" in t or "casual" in t:
        return "Hey! Thanks for reaching out. What can I help you with today?"
    if "formal" in t:
        return "Hello. How may I assist you today?"
    return "Hi! I'm here to help—what would you like to know?"


def _is_memory_recall_request(user_message: str) -> bool:
    msg = (user_message or "").strip().lower()
    if not msg:
        return False
    markers = (
        "what did i say",
        "what did i just say",
        "what was my last message",
        "repeat what i said",
        "do you remember what i said",
    )
    return any(m in msg for m in markers)


def _memory_recall_reply(history: Iterable[dict[str, str]] | None) -> str | None:
    if not history:
        return None
    user_turns: list[str] = []
    for turn in history:
        role = str(turn.get("role") or "")
        if role != "user":
            continue
        body = str(turn.get("content") or turn.get("body") or "").strip()
        if body:
            user_turns.append(body)
    if not user_turns:
        return None
    last = user_turns[-1]
    return f'You said: "{last}".'


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
                "Knowledge-base CONTEXT (may be partial; not the live chat log):\n"
                f"{retrieved_context}\n\n"
                "LATEST USER MESSAGE — answer this text. Use prior turns in this request for meaning of "
                "'it', 'that', 'which one', 'either', 'the first option', short yes/no follow-ups, etc.:\n"
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

    has_prior_turns = bool(history) and any(
        (str(t.get("content") or t.get("body") or "")).strip() for t in history
    )
    if _is_memory_recall_request(user_message):
        recalled = _memory_recall_reply(history)
        if recalled:
            return recalled
    if (
        is_light_greeting(user_message)
        and _kb_context_is_empty(retrieved_context)
        and not has_prior_turns
    ):
        return _instant_greeting_reply(response_tone)

    system_prompt = (
        "You are Chaster Brain, a customer support assistant. "
        f"Use a {response_tone} tone. "
        "You will receive optional CONVERSATION SUMMARY, prior chat turns, "
        "knowledge-base CONTEXT snippets (may be partial), and a LATEST USER MESSAGE. "
        "Treat the summary and prior turns as authoritative memory of this same chat: "
        "build on them, refer back to facts the user already gave, and never claim you "
        "cannot remember earlier messages in this thread. "
        "Your last assistant message in the thread is especially binding: if you offered choices "
        "(e.g. return vs exchange, A vs B) and the user replies with a short follow-up like "
        "'which would you suggest', 'which one', 'the first', or 'both sound fine', interpret that "
        "as choosing among those options—answer directly with a recommendation or clear next step. "
        "Do not ask what they mean by 'options' or say you lack context when your previous message defined them. "
        "Reply with a direct answer to the LATEST USER MESSAGE. "
        "Use 2-6 short sentences. Do NOT paste the context verbatim or repeat entire policy sections. "
        "For greetings or small talk, reply warmly in one or two short sentences without asking for "
        "order numbers, invoice IDs, or account email unless the user clearly asked about their own order, "
        "billing, or private account data. "
        "If the user asks to speak with a human, live agent, or person, acknowledge the request, "
        "briefly recap what they need help with from the thread, and say you are routing them or that a teammate will join shortly "
        "(use the same tone; do not refuse because you are an AI). "
        "Only if the question is still ambiguous after using the thread, ask one focused clarifying question."
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
