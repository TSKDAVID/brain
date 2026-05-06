from typing import Any, Literal, TypedDict


Intent = Literal["faq_or_general", "complex_personal_request"]


class OrchestratorState(TypedDict, total=False):
    tenant_id: str
    app_id: str
    message: str
    metadata: dict
    intent: Intent
    intent_confidence: float
    retrieved_context: str
    response: str
    confidence: float
    used_sources: list[str]
    conversation_id: str | None
    summary: str
    history: list[dict[str, str]]
    retrieval_score: float
    rerank_score: float
    cache_hit: bool
    extra: dict[str, Any]
