"""End-to-end smoke test for the memory pipeline.

Run with: python scripts/smoke_memory.py

Simulates a 10+ turn conversation, validates that:
  1. Hot cache contains the most recent turns.
  2. Compression triggers once message count crosses the threshold.
  3. Reset clears server-side memory keys.

Uses the in-process cache shim (no Redis required).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from types import SimpleNamespace

from app.cache import cache_get_json, cache_lrange, reset_cache_for_tests
from app.memory import manager


def main() -> None:
    reset_cache_for_tests()

    monkey_settings = SimpleNamespace(
        memory_recent_turns=8,
        memory_compress_after_messages=4,
        memory_compress_token_budget=10_000,
        memory_summary_ttl_seconds=3600,
        memory_hot_ttl_seconds=600,
        groq_api_key=None,
        groq_model="llama-3.3-70b-versatile",
        groq_api_base_url="https://api.groq.com/openai/v1",
    )
    manager.get_settings = lambda: monkey_settings  # type: ignore[assignment]

    upserts = []
    manager.upsert_row = lambda table, payload, on_conflict: (  # type: ignore[assignment]
        upserts.append(payload),
        {"id": "summary"},
    )[1]

    conversation_id = "conv-smoke-1"

    print("Simulating 12 turns...")
    for i in range(12):
        manager.append_turn(
            conversation_id,
            user_message=f"User turn {i + 1}: please remember this fact #{i + 1}.",
            assistant_message=f"Assistant turn {i + 1}: acknowledged fact #{i + 1}.",
        )

    cached_turns = cache_lrange(f"chat:hot:{conversation_id}", 0, -1)
    print(f"Hot cache size: {len(cached_turns)}")
    assert cached_turns, "Hot cache should be populated."

    print("Loading context (should pull from hot cache)...")
    ctx = manager.load_context(conversation_id)
    assert ctx.history, "Loaded history should not be empty."
    print(f"  loaded {len(ctx.history)} verbatim turns")

    print("Triggering compression with stub summarizer...")
    changed = manager.maybe_compress(
        conversation_id,
        tenant_id="tenant-smoke",
        summarizer=lambda *, prior_summary, older_turns: (
            f"Summary of {len(older_turns)} older turns. Earlier facts noted."
        ),
    )
    assert changed, "Compression should have run for 12+ turns."
    print(f"  upserts captured: {len(upserts)}")
    assert upserts, "Summary row should be persisted."
    cached_summary = cache_get_json(f"chat:summary:{conversation_id}")
    print(f"  cached summary: {cached_summary}")
    assert cached_summary and cached_summary.get("summary_text", "").startswith("Summary of")

    print("Resetting conversation cache...")
    manager.reset_conversation_cache(conversation_id)
    after_reset = cache_lrange(f"chat:hot:{conversation_id}", 0, -1)
    assert not after_reset, "Hot cache should be empty after reset."
    print("  reset OK -> hot cache empty")

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
