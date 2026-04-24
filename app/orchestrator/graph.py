from langgraph.graph import END, StateGraph

from app.orchestrator.nodes import (
    confidence_node,
    faq_node,
    intent_classifier,
    personal_request_node,
)
from app.orchestrator.state import OrchestratorState


def _route_intent(state: OrchestratorState) -> str:
    if state.get("intent") == "complex_personal_request":
        return "personal_request"
    return "faq"


def build_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("intent", intent_classifier)
    graph.add_node("faq", faq_node)
    graph.add_node("personal_request", personal_request_node)
    graph.add_node("confidence", confidence_node)

    graph.set_entry_point("intent")
    graph.add_conditional_edges("intent", _route_intent, {"faq": "faq", "personal_request": "personal_request"})
    graph.add_edge("faq", "confidence")
    graph.add_edge("personal_request", "confidence")
    graph.add_edge("confidence", END)

    return graph.compile()
