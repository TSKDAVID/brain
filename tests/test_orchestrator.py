from app.orchestrator.graph import build_graph
from app.orchestrator import nodes


def test_routes_to_faq_for_general_prompt(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "retrieve_faq_context",
        lambda *_args, **_kwargs: ("FAQ chunk", ["chunk-1"], 0.7),
    )
    monkeypatch.setattr(
        nodes,
        "get_parameters",
        lambda *_args, **_kwargs: {"response_tone": "professional", "mcp_enabled": True},
    )
    monkeypatch.setattr(
        nodes,
        "generate_answer",
        lambda **_kwargs: "Generated FAQ answer",
    )
    graph = build_graph()
    result = graph.invoke(
        {
            "tenant_id": "t1",
            "app_id": "app-12345678",
            "message": "Hello there, what are your hours?",
            "metadata": {},
        }
    )
    assert result["intent"] == "faq_or_general"


def test_routes_to_personal_for_account_prompt(monkeypatch):
    monkeypatch.setattr(nodes, "retrieve_live_company_data", lambda *_args, **_kwargs: "Live data result")
    monkeypatch.setattr(
        nodes,
        "get_parameters",
        lambda *_args, **_kwargs: {"response_tone": "professional", "mcp_enabled": True},
    )
    monkeypatch.setattr(
        nodes,
        "generate_answer",
        lambda **_kwargs: "Generated personal answer",
    )
    graph = build_graph()
    result = graph.invoke(
        {
            "tenant_id": "t1",
            "app_id": "app-12345678",
            "message": "What is my refund status?",
            "metadata": {"ticket_ref": "A-1"},
        }
    )
    assert result["intent"] == "complex_personal_request"
    assert "mcp:company_data" in result["used_sources"]


def test_faq_node_threads_history_and_summary_into_llm(monkeypatch):
    captured: dict = {}

    def fake_generate_answer(**kwargs):
        captured.update(kwargs)
        return "echo"

    monkeypatch.setattr(
        nodes,
        "retrieve_faq_context",
        lambda *_args, **_kwargs: ("FAQ chunk", ["chunk-1"], 0.6),
    )
    monkeypatch.setattr(
        nodes,
        "get_parameters",
        lambda *_args, **_kwargs: {"response_tone": "professional"},
    )
    monkeypatch.setattr(nodes, "generate_answer", fake_generate_answer)

    graph = build_graph()
    graph.invoke(
        {
            "tenant_id": "t1",
            "app_id": "app-12345678",
            "message": "What are the support hours?",
            "metadata": {},
            "summary": "Earlier the user introduced themselves as Sara.",
            "history": [
                {"role": "user", "body": "Hi, I'm Sara."},
                {"role": "assistant", "body": "Hi Sara!"},
            ],
        }
    )

    assert captured["summary"].startswith("Earlier the user")
    history = list(captured["history"])
    assert history == [
        {"role": "user", "content": "Hi, I'm Sara."},
        {"role": "assistant", "content": "Hi Sara!"},
    ]


def test_faq_keeps_llm_answer_when_retrieval_is_weak(monkeypatch):
    """Thin KB context must not trigger the personal low-confidence boilerplate."""
    monkeypatch.setattr(
        nodes,
        "retrieve_faq_context",
        lambda *_args, **_kwargs: ("", [], 0.05),
    )
    monkeypatch.setattr(
        nodes,
        "get_parameters",
        lambda *_args, **_kwargs: {
            "response_tone": "professional",
            "mcp_enabled": True,
            "max_context_chunks": 8,
            "confidence_threshold": 0.6,
        },
    )
    monkeypatch.setattr(nodes, "generate_answer", lambda **_kwargs: "Friendly FAQ reply")

    graph = build_graph()
    result = graph.invoke(
        {
            "tenant_id": "t1",
            "app_id": "app-12345678",
            "message": "hi",
            "metadata": {},
        }
    )
    assert result["intent"] == "faq_or_general"
    assert result["response"] == "Friendly FAQ reply"
    assert "verified context" not in result["response"].lower()
