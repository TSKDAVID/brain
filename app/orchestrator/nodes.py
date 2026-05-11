from app.control_plane import get_parameters
from app.mcp.client import retrieve_live_company_data
from app.orchestrator.intent_llm import classify_intent
from app.orchestrator.llm import generate_answer
from app.orchestrator.state import OrchestratorState
from app.rag.retriever import retrieve_faq_context
from app.security.sanitizer import sanitize_message


def _normalize_history(state: OrchestratorState) -> list[dict[str, str]]:
    raw = state.get("history") or []
    out: list[dict[str, str]] = []
    for turn in raw:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "")
        body = str(turn.get("body") or turn.get("content") or "")
        if not body:
            continue
        if role not in {"user", "assistant", "system"}:
            role = "user" if role in {"visitor", "guest"} else "assistant"
        out.append({"role": role, "content": body})
    return out


def intent_classifier(state: OrchestratorState) -> OrchestratorState:
    intent, confidence = classify_intent(state["message"])
    state["intent"] = intent
    state["intent_confidence"] = confidence
    return state


def faq_node(state: OrchestratorState) -> OrchestratorState:
    params = get_parameters(state["tenant_id"])
    max_chunks = min(int(params.get("max_context_chunks", 8)), 4)
    context, sources, retrieval_score = retrieve_faq_context(
        state["tenant_id"],
        state["message"],
        max_chunks=max(3, max_chunks),
        max_context_chars=2600,
    )
    cleaned_message = sanitize_message(state["message"])
    state["retrieved_context"] = context
    state["used_sources"] = sources
    state["retrieval_score"] = retrieval_score
    state["response"] = generate_answer(
        user_message=cleaned_message,
        retrieved_context=context,
        response_tone=params.get("response_tone", "professional"),
        summary=state.get("summary", "") or "",
        history=_normalize_history(state),
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
    state["retrieval_score"] = 0.5 if params.get("mcp_enabled", True) else 0.0
    state["response"] = generate_answer(
        user_message=cleaned_message,
        retrieved_context=live_data,
        response_tone=params.get("response_tone", "professional"),
        summary=state.get("summary", "") or "",
        history=_normalize_history(state),
    )
    return state


def confidence_node(state: OrchestratorState) -> OrchestratorState:
    context_length = len(state.get("retrieved_context", ""))
    has_sources = bool(state.get("used_sources"))
    retrieval_score = float(state.get("retrieval_score", 0.0) or 0.0)
    intent_conf = float(state.get("intent_confidence", 0.5) or 0.5)

    if has_sources and context_length > 20:
        # Combine three signals: retrieval similarity, intent confidence,
        # and how much on-topic context we managed to assemble.
        context_factor = min(context_length, 3500) / 3500
        confidence = 0.45 + (retrieval_score * 0.35) + (context_factor * 0.10) + (intent_conf * 0.10)
        confidence = round(min(0.95, max(0.4, confidence)), 2)
    else:
        confidence = 0.42

    state["confidence"] = confidence
    # Low-confidence copy for account-specific flows is applied in API handlers
    # (`/v1/gateway/message`, widget message, sandbox) so FAQ/general answers are
    # never replaced here when retrieval is thin.
    return state
