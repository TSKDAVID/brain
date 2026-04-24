from typing import Literal, TypedDict


Intent = Literal["faq_or_general", "complex_personal_request"]


class OrchestratorState(TypedDict, total=False):
    tenant_id: str
    app_id: str
    message: str
    metadata: dict
    intent: Intent
    retrieved_context: str
    response: str
    confidence: float
    used_sources: list[str]
