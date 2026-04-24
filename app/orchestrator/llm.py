import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _fallback_no_llm(retrieved_context: str, user_message: str) -> str:
    excerpt = (retrieved_context or "").strip()[:1200]
    return (
        "Set GROQ_API_KEY on the Chaster Brain API to generate natural-language answers. "
        f"From your indexed content, this excerpt may be relevant to “{user_message}”:\n\n{excerpt}"
    )


def generate_answer(*, user_message: str, retrieved_context: str, response_tone: str) -> str:
    settings = get_settings()
    if not settings.groq_api_key:
        return _fallback_no_llm(retrieved_context, user_message)

    system_prompt = (
        "You are Chaster Brain, a customer support assistant. "
        f"Use a {response_tone} tone. "
        "You will receive CONTEXT snippets (may be partial) and a USER QUESTION. "
        "Reply with a direct answer to that question only. "
        "Use 2–6 short sentences. Do NOT paste the context verbatim or repeat entire policy sections. "
        "If the context does not contain the answer, say what is missing in one sentence."
    )
    payload = {
        "model": settings.groq_model,
        "temperature": 0.4,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "CONTEXT (for you to use, not to quote in full):\n"
                    f"{retrieved_context}\n\n"
                    "USER QUESTION:\n"
                    f"{user_message}"
                ),
            },
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
