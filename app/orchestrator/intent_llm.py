"""Hybrid intent classifier.

Order of operations on each call:
    1. Check Redis cache by message hash (10-minute TTL).
    2. Apply cheap rules for obvious cases (greetings, account-style language).
    3. Otherwise call Groq with a tiny prompt that returns just the label.
    4. On any LLM failure, fall back to the rules result.

Returns `(intent, confidence)` so the downstream confidence_node can use the
classifier's certainty as one signal instead of the brittle 0/1 it had before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Tuple

from app.cache import cache_get_json, cache_set_json
from app.config import get_settings

logger = logging.getLogger(__name__)


Intent = str  # "faq_or_general" | "complex_personal_request"

_PERSONAL_MARKERS = (
    "order",
    "refund",
    "invoice",
    "subscription",
    "status",
    "my ",
    "account",
    "ticket",
    "case",
    "billing",
    "charge",
    "payment",
    "renewal",
    "cancel",
    "upgrade",
    "downgrade",
)

_GENERIC_MARKERS = (
    "hours",
    "hello",
    "hi ",
    "hi,",
    "hey",
    "thanks",
    "thank you",
    "policy",
    "policies",
    "shipping",
    "return",
    "what is",
    "how do",
    "do you",
    "can i",
)

# Whole-message greetings / light acknowledgements (substring markers like "hi"
# would false-match inside unrelated words).
_GREETING_RE = re.compile(
    r"(?:"
    r"hi(?:\s+there|\s+everyone|\s+all)?|"
    r"hello(?:\s+there)?|"
    r"hey(?:\s+there)?|"
    r"yo|howdy|greetings|gm|"
    r"thanks?|thank\s+you|thx|ty|"
    r"bye|goodbye|"
    r"good\s+(?:morning|afternoon|evening|night)"
    r")[!,. ]*",
)


def is_light_greeting(message: str) -> bool:
    """Whole-message hi/hello/thanks/etc. Used to skip slow intent LLM and bad reroutes."""
    msg = _normalize(message)
    return bool(msg and _GREETING_RE.fullmatch(msg))


def _normalize(message: str) -> str:
    return (message or "").strip().lower()


def _cache_key(message: str) -> str:
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:24]
    # v3: invalidate stale intent entries (e.g. LLM once mis-routed "hi" to personal).
    return f"intent:v3:{digest}"


def _rule_based_classify(message: str) -> Tuple[Intent, float]:
    msg = _normalize(message)
    if not msg:
        return "faq_or_general", 0.5
    if _GREETING_RE.fullmatch(msg):
        return "faq_or_general", 0.88
    is_personal = any(marker in msg for marker in _PERSONAL_MARKERS)
    is_generic = any(marker in msg for marker in _GENERIC_MARKERS)
    if is_personal and not is_generic:
        return "complex_personal_request", 0.7
    if is_generic and not is_personal:
        return "faq_or_general", 0.75
    if is_personal:
        return "complex_personal_request", 0.6
    return "faq_or_general", 0.55


def _llm_classify(message: str) -> Tuple[Intent, float] | None:
    settings = get_settings()
    if not settings.groq_api_key:
        return None

    import httpx  # local import keeps cold start fast

    system_prompt = (
        "You are an intent router for a customer support assistant. "
        "Classify the user message into exactly one of:\n"
        "- faq_or_general: knowledge-base / how-to / generic info questions, greetings, "
        "policies, hours, product info.\n"
        "- complex_personal_request: anything tied to a specific account, order, invoice, "
        "subscription, payment, refund, or other user-specific data.\n"
        'Respond ONLY with JSON like {"intent": "faq_or_general", "confidence": 0.0-1.0} '
        "with no extra text."
    )
    intent_model = (settings.groq_intent_model or settings.groq_model).strip()
    payload = {
        "model": intent_model,
        "temperature": 0.0,
        "max_tokens": 40,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message[:1500]},
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
            timeout=12.0,
        )
        response.raise_for_status()
        body = response.json()
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not text:
            return None
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
        intent = str(data.get("intent") or "").strip()
        confidence = float(data.get("confidence", 0.7))
        if intent not in {"faq_or_general", "complex_personal_request"}:
            return None
        confidence = max(0.5, min(0.95, confidence))
        return intent, confidence
    except Exception as exc:
        logger.debug(
            "intent_llm: Groq call failed (%s); model=%s; using rules",
            exc,
            intent_model,
        )
        return None


def classify_intent(message: str) -> Tuple[Intent, float]:
    settings = get_settings()
    cache_key = _cache_key(message or "")

    # Instant path: never call Groq for bare greetings / light thanks — avoids
    # misclassification + ~1s latency. (Rules already agree, but the LLM could override.)
    if is_light_greeting(message):
        intent, confidence = "faq_or_general", 0.92
        try:
            cache_set_json(
                cache_key,
                {"intent": intent, "confidence": confidence},
                ttl_seconds=settings.intent_cache_ttl_seconds,
            )
        except Exception:  # pragma: no cover
            pass
        return intent, confidence

    cached = cache_get_json(cache_key)
    if isinstance(cached, dict):
        intent = str(cached.get("intent") or "")
        confidence = float(cached.get("confidence", 0.0))
        if intent in {"faq_or_general", "complex_personal_request"}:
            return intent, confidence

    rule_intent, rule_conf = _rule_based_classify(message)

    llm_result = _llm_classify(message)
    if llm_result is None:
        intent, confidence = rule_intent, rule_conf
    else:
        llm_intent, llm_conf = llm_result
        # If cheap rules are clearly FAQ/general, do not let the LLM promote to personal
        # (common source of slow MCP path + boilerplate replies on harmless text).
        if (
            llm_intent == "complex_personal_request"
            and rule_intent == "faq_or_general"
            and rule_conf >= 0.72
        ):
            intent, confidence = rule_intent, rule_conf
        else:
            intent, confidence = llm_intent, llm_conf
            # Blend: when LLM agrees with rules we are even more confident.
            if intent == rule_intent:
                confidence = min(0.95, max(confidence, rule_conf + 0.05))

    try:
        cache_set_json(
            cache_key,
            {"intent": intent, "confidence": confidence},
            ttl_seconds=settings.intent_cache_ttl_seconds,
        )
    except Exception:  # pragma: no cover - cache best-effort
        pass

    return intent, confidence
