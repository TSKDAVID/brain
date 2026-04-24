from typing import Any, Literal

from pydantic import BaseModel, Field


IntentType = Literal["faq_or_general", "complex_personal_request"]
ConversationState = Literal["unresolved", "resolved", "human_muted", "human_needed"]


class GatewayMessageRequest(BaseModel):
    app_id: str = Field(min_length=8, max_length=128)
    tenant_id: str
    message: str = Field(min_length=1, max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GatewayMessageResponse(BaseModel):
    tenant_id: str
    app_id: str
    intent: IntentType
    confidence: float
    response: str
    used_sources: list[str] = Field(default_factory=list)


class WidgetHandshakeRequest(BaseModel):
    app_id: str = Field(min_length=8, max_length=128)
    tenant_id: str
    mode: Literal["anonymous", "logged_in"] = "anonymous"
    user_id: str | None = None
    guest_id: str | None = None
    guest_name: str | None = Field(default=None, max_length=120)
    guest_email: str | None = Field(default=None, max_length=320)


class WidgetHandshakeResponse(BaseModel):
    session_token: str
    expires_at: str
    tenant_id: str
    app_id: str
    user_id: str | None = None
    guest_id: str | None = None
    conversation_id: str | None = None
    support_case_id: str | None = None
    ai_handling: bool = True


class WidgetProcessRequest(BaseModel):
    app_id: str = Field(min_length=8, max_length=128)
    tenant_id: str
    message: str = Field(min_length=1, max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WidgetProcessResponse(BaseModel):
    tenant_id: str
    app_id: str
    intent: IntentType
    confidence: float
    response: str
    used_sources: list[str] = Field(default_factory=list)
    sender_type: Literal["ai", "human"] = "ai"
    conversation_id: str | None = None
    support_case_id: str | None = None
    ai_handling: bool = True
    state: ConversationState = "unresolved"


class OrchestratorInput(BaseModel):
    tenant_id: str
    app_id: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeControlUpdate(BaseModel):
    tenant_id: str
    is_running: bool
    mode: Literal["automatic", "manual"] = "manual"
    updated_by: str | None = None


class RuntimeControlResponse(BaseModel):
    tenant_id: str
    is_running: bool
    mode: str
    updated_at: str | None = None


class ParametersUpdateRequest(BaseModel):
    tenant_id: str
    confidence_threshold: float = Field(ge=0, le=1)
    max_context_chunks: int = Field(ge=1, le=30)
    response_tone: str = Field(min_length=2, max_length=50)
    mcp_enabled: bool = True
    updated_by: str | None = None


class ParametersResponse(BaseModel):
    tenant_id: str
    confidence_threshold: float
    max_context_chunks: int
    response_tone: str
    mcp_enabled: bool
    updated_at: str | None = None


class IndexDataRequest(BaseModel):
    tenant_id: str
    source_type: Literal["text", "url", "document"]
    source_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None


class IndexJobResponse(BaseModel):
    id: str
    tenant_id: str
    source_type: str
    source_ref: str | None = None
    status: str
    requested_at: str | None = None
    chunks_indexed: int | None = None
    message: str | None = None


class DashboardStatsResponse(BaseModel):
    tenant_id: str
    knowledge_chunks: int
    index_jobs_total: int
    index_jobs_pending: int
    support_cases_open: int
    conversations_total: int
    ai_requests_today: int
    low_confidence_today: int


class SandboxMessageRequest(BaseModel):
    tenant_id: str
    message: str = Field(min_length=1, max_length=10000)


class SandboxMessageResponse(BaseModel):
    tenant_id: str
    intent: IntentType
    confidence: float
    response: str
    used_sources: list[str] = Field(default_factory=list)
