from app.control_plane import get_parameters
from app.mcp.client import retrieve_live_company_data
from app.orchestrator.llm import generate_answer
from app.orchestrator.state import OrchestratorState
from app.rag.retriever import retrieve_faq_context
from app.security.sanitizer import sanitize_message


def intent_classifier(state: OrchestratorState) -> OrchestratorState:
    msg = state["message"].lower()
    complex_markers = ["order", "refund", "invoice", "subscription", "status", "my ", "account"]
    is_complex = any(marker in msg for marker in complex_markers)
    state["intent"] = "complex_personal_request" if is_complex else "faq_or_general"
    return state


def faq_node(state: OrchestratorState) -> OrchestratorState:
    params = get_parameters(state["tenant_id"])
    # Fewer, tighter chunks for the LLM so answers vary with the question instead of echoing the whole policy.
    max_chunks = min(int(params.get("max_context_chunks", 8)), 4)
    context, sources = retrieve_faq_context(
        state["tenant_id"],
        state["message"],
        max_chunks=max(3, max_chunks),
        max_context_chars=2600,
    )
    cleaned_message = sanitize_message(state["message"])
    state["retrieved_context"] = context
    state["used_sources"] = sources
    state["response"] = generate_answer(
        user_message=cleaned_message,
        retrieved_context=context,
        response_tone=params.get("response_tone", "professional"),
    )
    return state


def personal_request_node(state: OrchestratorState) -> OrchestratorState:
    params = get_parameters(state["tenant_id"])
    cleaned_message = sanitize_message(state["message"])
    if params.get("mcp_enabled", True):
        live_data = retrieve_live_company_data(cleaned_message, state.get("metadata", {}))
        sources = ["mcp:company_data"]
    else:
        live_data = "MCP live data retrieval is disabled for this tenant."
        sources = ["mcp:disabled"]
    state["retrieved_context"] = live_data
    state["used_sources"] = sources
    state["response"] = generate_answer(
        user_message=cleaned_message,
        retrieved_context=live_data,
        response_tone=params.get("response_tone", "professional"),
    )
    return state


def confidence_node(state: OrchestratorState) -> OrchestratorState:
    context_length = len(state.get("retrieved_context", ""))
    has_sources = bool(state.get("used_sources"))
    if has_sources and context_length > 20:
        # Rough signal: more on-topic context → slightly higher (still capped).
        confidence = round(min(0.92, 0.55 + min(context_length, 3500) / 3500 * 0.32), 2)
    else:
        confidence = 0.42
    state["confidence"] = confidence
    if confidence < 0.5:
        state["response"] = (
            "I want to be precise here. I need a bit more verified context before giving a final answer. "
            "Please share a specific reference (order id, invoice id, or account email)."
        )
    return state
