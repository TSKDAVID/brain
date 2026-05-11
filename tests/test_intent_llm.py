from types import SimpleNamespace

from app.cache import reset_cache_for_tests
from app.orchestrator import intent_llm


def _settings_without_groq():
    return SimpleNamespace(
        groq_api_key=None,
        groq_api_base_url="https://api.groq.com/openai/v1",
        groq_model="llama-3.3-70b-versatile",
        groq_intent_model="openai/gpt-oss-20b",
        intent_cache_ttl_seconds=600,
    )


def _settings_with_groq():
    return SimpleNamespace(
        groq_api_key="test-key",
        groq_api_base_url="https://api.groq.com/openai/v1",
        groq_model="llama-3.3-70b-versatile",
        groq_intent_model="openai/gpt-oss-20b",
        intent_cache_ttl_seconds=600,
    )


def test_rules_classify_personal(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_without_groq)
    intent, confidence = intent_llm.classify_intent("Where is my refund?")
    assert intent == "complex_personal_request"
    assert confidence >= 0.6


def test_rules_classify_general(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_without_groq)
    intent, _confidence = intent_llm.classify_intent("What are your support hours?")
    assert intent == "faq_or_general"


def test_rules_classify_bare_hi(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_without_groq)
    intent, confidence = intent_llm.classify_intent("hi")
    assert intent == "faq_or_general"
    assert confidence >= 0.85


def test_hi_short_circuits_before_llm(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_with_groq)

    def boom(_msg):
        raise AssertionError("intent LLM should not run for bare hi")

    monkeypatch.setattr(intent_llm, "_llm_classify", boom)
    intent, confidence = intent_llm.classify_intent("hi")
    assert intent == "faq_or_general"
    assert confidence >= 0.9


def test_rules_faq_overrides_llm_personal(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_with_groq)
    monkeypatch.setattr(
        intent_llm,
        "_llm_classify",
        lambda _m: ("complex_personal_request", 0.85),
    )
    intent, _confidence = intent_llm.classify_intent("What are your support hours?")
    assert intent == "faq_or_general"


def test_classify_intent_uses_cache(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_without_groq)
    calls: list[str] = []

    real_rules = intent_llm._rule_based_classify

    def counting_rules(message):
        calls.append(message)
        return real_rules(message)

    monkeypatch.setattr(intent_llm, "_rule_based_classify", counting_rules)
    intent_llm.classify_intent("Where is my refund?")
    intent_llm.classify_intent("Where is my refund?")
    assert len(calls) == 1


def test_llm_blends_with_rules(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_with_groq)
    monkeypatch.setattr(
        intent_llm,
        "_llm_classify",
        lambda _msg: ("faq_or_general", 0.7),
    )
    intent, confidence = intent_llm.classify_intent("Hello, what are your hours?")
    assert intent == "faq_or_general"
    # Rules also say faq_or_general -> we should boost above LLM raw score.
    assert confidence >= 0.7


def test_llm_failure_falls_back_to_rules(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(intent_llm, "get_settings", _settings_with_groq)
    monkeypatch.setattr(intent_llm, "_llm_classify", lambda _msg: None)
    intent, _ = intent_llm.classify_intent("I need a refund for my order")
    assert intent == "complex_personal_request"
