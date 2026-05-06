from types import SimpleNamespace

from app.cache import cache_lrange, cache_get_json, reset_cache_for_tests
from app.memory import manager


def _settings():
    return SimpleNamespace(
        memory_recent_turns=8,
        memory_compress_after_messages=4,
        memory_compress_token_budget=10_000,
        memory_summary_ttl_seconds=3600,
        memory_hot_ttl_seconds=600,
        groq_api_key=None,
        groq_model="llama-3.3-70b-versatile",
        groq_api_base_url="https://api.groq.com/openai/v1",
    )


def test_append_turn_pushes_to_hot_cache(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(manager, "get_settings", _settings)
    manager.append_turn(
        "conv-1",
        user_message="Hi there",
        assistant_message="Hello back",
    )
    raw = cache_lrange("chat:hot:conv-1", 0, -1)
    # Newest first; user message was pushed last so it sits at the head.
    assert any('"role": "user"' in item for item in raw)
    assert any('"role": "assistant"' in item for item in raw)


def test_load_context_reads_hot_cache_when_present(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(manager, "get_settings", _settings)
    manager.append_turn("conv-2", user_message="ping", assistant_message="pong")

    def fail_supabase(*_args, **_kwargs):
        raise AssertionError("Supabase should not be hit when cache is warm")

    monkeypatch.setattr(manager, "_supabase_history", fail_supabase)

    ctx = manager.load_context("conv-2")
    assert ctx.conversation_id == "conv-2"
    bodies = [turn.body for turn in ctx.history]
    assert "ping" in bodies and "pong" in bodies


def test_load_context_falls_back_to_supabase(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(manager, "get_settings", _settings)
    monkeypatch.setattr(
        manager,
        "_supabase_history",
        lambda _id, *, limit: [
            manager.HistoryTurn(role="user", body="From DB user"),
            manager.HistoryTurn(role="assistant", body="From DB assistant"),
        ],
    )
    monkeypatch.setattr(manager, "_supabase_summary", lambda _id: "")

    ctx = manager.load_context("conv-3")
    assert [turn.body for turn in ctx.history] == ["From DB user", "From DB assistant"]
    # Cache should now be primed.
    assert cache_lrange("chat:hot:conv-3", 0, -1)


def test_maybe_compress_persists_summary(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(manager, "get_settings", _settings)
    long_history = []
    for i in range(12):
        manager.append_turn("conv-4", user_message=f"q{i}", assistant_message=f"a{i}")
        long_history.append(("u", f"q{i}"))
        long_history.append(("a", f"a{i}"))

    upserts: list[dict] = []
    monkeypatch.setattr(
        manager,
        "upsert_row",
        lambda table, payload, on_conflict: (upserts.append({"table": table, "payload": payload, "on_conflict": on_conflict}), {"id": "summary-1"})[1],
    )

    summarize_calls: list[dict] = []

    def fake_summarizer(*, prior_summary, older_turns):
        summarize_calls.append({"prior_summary": prior_summary, "older_turns": older_turns})
        return "Compressed summary."

    changed = manager.maybe_compress(
        "conv-4",
        tenant_id="tenant-1",
        summarizer=fake_summarizer,
    )

    assert changed is True
    assert summarize_calls and summarize_calls[0]["older_turns"]
    assert upserts and upserts[0]["table"] == "brain_conversation_summaries"
    assert upserts[0]["payload"]["summary_text"] == "Compressed summary."
    cached_summary = cache_get_json("chat:summary:conv-4")
    assert cached_summary == {"summary_text": "Compressed summary."}


def test_reset_conversation_cache_clears_keys(monkeypatch):
    reset_cache_for_tests()
    monkeypatch.setattr(manager, "get_settings", _settings)
    manager.append_turn("conv-5", user_message="hello", assistant_message="hi")
    assert cache_lrange("chat:hot:conv-5", 0, -1)
    manager.reset_conversation_cache("conv-5")
    assert cache_lrange("chat:hot:conv-5", 0, -1) == []
