from app.orchestrator.graph import build_graph
from app.orchestrator import nodes


def test_routes_to_faq_for_general_prompt(monkeypatch):
    monkeypatch.setattr(nodes, "retrieve_faq_context", lambda *_args, **_kwargs: ("FAQ chunk", ["chunk-1"]))
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
            "message": "Hello there",
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
