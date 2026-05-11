from types import SimpleNamespace

from app.orchestrator import llm


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
