from types import SimpleNamespace

from app.orchestrator import llm


def test_build_messages_marks_latest_user_for_coreference():
    msgs = llm._build_messages(
        system_prompt="sys",
        summary="",
        history=[{"role": "assistant", "body": "Would you prefer a return or an exchange?"}],
        retrieved_context="KB snippet",
        user_message="which one would you suggest",
    )
    last = msgs[-1]
    assert last["role"] == "user"
    assert "LATEST USER MESSAGE" in last["content"]
    assert "which one would you suggest" in last["content"]


def test_greeting_skips_groq_when_kb_empty(monkeypatch):
    class Boom:
        @staticmethod
        def post(*_args, **_kwargs):
            raise AssertionError("Groq chat should not be called for instant greeting")

    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(groq_api_key="k", groq_model="m"))
    monkeypatch.setattr(llm, "httpx", Boom)
    out = llm.generate_answer(
        user_message="hi",
        retrieved_context="No indexed FAQ context found for this tenant.",
        response_tone="professional",
    )
    assert "help" in out.lower() or "hi" in out.lower()


def test_memory_recall_uses_prior_user_turn_without_groq(monkeypatch):
    class Boom:
        @staticmethod
        def post(*_args, **_kwargs):
            raise AssertionError("Groq chat should not be called for memory recall")

    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(groq_api_key="k", groq_model="m"))
    monkeypatch.setattr(llm, "httpx", Boom)
    out = llm.generate_answer(
        user_message="what did i say",
        retrieved_context="No indexed FAQ context found for this tenant.",
        response_tone="professional",
        history=[
            {"role": "user", "body": "hello"},
            {"role": "assistant", "body": "Hi! I'm here to help."},
        ],
    )
    assert 'You said: "hello".' == out
