import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_cors_origins, get_settings
from app.control_plane import (
    create_index_job,
    get_dashboard_stats,
    get_parameters,
    get_runtime_control,
    record_ai_request,
    set_parameters,
    set_runtime_control,
)
from app.db.client import get_single_row, insert_row, update_rows
from app.indexing.pipeline import process_document_index_job, process_text_index_job
from app.gateway.service import (
    validate_app_request_signature,
    validate_request_security,
    validate_tenant_access_token,
)
from app.models import (
    DashboardStatsResponse,
    GatewayMessageRequest,
    GatewayMessageResponse,
    IndexDataRequest,
    IndexJobResponse,
    ParametersResponse,
    ParametersUpdateRequest,
    RuntimeControlResponse,
    RuntimeControlUpdate,
    SandboxMessageRequest,
    SandboxMessageResponse,
    WidgetHandshakeRequest,
    WidgetHandshakeResponse,
    WidgetProcessRequest,
    WidgetProcessResponse,
)
from app.orchestrator.graph import build_graph

app = FastAPI(title="Chaster Brain", version="0.1.0")
orchestrator = build_graph()
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def _require_tenant_control_access(authorization: str, tenant_id: str) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    validate_tenant_access_token(
        auth_token=authorization.split(" ", maxsplit=1)[1],
        tenant_id=tenant_id,
    )


@app.get("/v1/control/runtime/{tenant_id}", response_model=RuntimeControlResponse)
def runtime_status(tenant_id: str, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, tenant_id)
    row = get_runtime_control(tenant_id)
    return RuntimeControlResponse(**row)


@app.post("/v1/control/start", response_model=RuntimeControlResponse)
def start_runtime(payload: RuntimeControlUpdate, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, payload.tenant_id)
    row = set_runtime_control(
        RuntimeControlUpdate(
            tenant_id=payload.tenant_id,
            is_running=True,
            mode=payload.mode,
            updated_by=payload.updated_by,
        )
    )
    return RuntimeControlResponse(**row)


@app.post("/v1/control/stop", response_model=RuntimeControlResponse)
def stop_runtime(payload: RuntimeControlUpdate, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, payload.tenant_id)
    row = set_runtime_control(
        RuntimeControlUpdate(
            tenant_id=payload.tenant_id,
            is_running=False,
            mode=payload.mode,
            updated_by=payload.updated_by,
        )
    )
    return RuntimeControlResponse(**row)


@app.get("/v1/control/parameters/{tenant_id}", response_model=ParametersResponse)
def read_parameters(tenant_id: str, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, tenant_id)
    row = get_parameters(tenant_id)
    return ParametersResponse(**row)


@app.post("/v1/control/parameters", response_model=ParametersResponse)
def update_parameters(payload: ParametersUpdateRequest, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, payload.tenant_id)
    row = set_parameters(payload)
    return ParametersResponse(**row)


@app.post("/v1/control/index", response_model=IndexJobResponse)
def index_data(payload: IndexDataRequest, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, payload.tenant_id)
    if payload.source_type == "text":
        content = (payload.payload or {}).get("content")
        if not content or not str(content).strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="payload.content is required (FAQ or policy text). Optional payload.title names the document.",
            )
    elif payload.source_type == "document":
        if not payload.source_ref:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="source_ref (knowledge_base_documents.id) is required for document indexing.",
            )

    row = create_index_job(payload)
    if payload.source_type not in {"text", "document"}:
        return IndexJobResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            source_type=row["source_type"],
            source_ref=row.get("source_ref"),
            status=row["status"],
            requested_at=row.get("requested_at"),
            message="Supported ingestion types are 'text' and 'document'.",
        )

    try:
        update_rows("brain_index_jobs", {"status": "processing"}, {"id": row["id"]})
        if payload.source_type == "text":
            chunks_indexed = process_text_index_job(payload)
        else:
            chunks_indexed = process_document_index_job(payload)
        now = datetime.now(timezone.utc).isoformat()
        update_rows(
            "brain_index_jobs",
            {"status": "completed", "processed_at": now, "error_message": None},
            {"id": row["id"]},
        )
    except ValueError as exc:
        update_rows(
            "brain_index_jobs",
            {"status": "failed", "error_message": str(exc)[:2000]},
            {"id": row["id"]},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        update_rows(
            "brain_index_jobs",
            {"status": "failed", "error_message": str(exc)[:2000]},
            {"id": row["id"]},
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return IndexJobResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        source_type=row["source_type"],
        source_ref=row.get("source_ref"),
        status="completed",
        requested_at=row.get("requested_at"),
        chunks_indexed=chunks_indexed,
        message=None,
    )


@app.get("/v1/control/stats/{tenant_id}", response_model=DashboardStatsResponse)
def dashboard_stats(tenant_id: str, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, tenant_id)
    return get_dashboard_stats(tenant_id)


@app.post("/v1/control/sandbox/message", response_model=SandboxMessageResponse)
def sandbox_message(payload: SandboxMessageRequest, authorization: str = Header(default="", alias="Authorization")):
    _require_tenant_control_access(authorization, payload.tenant_id)
    runtime = get_runtime_control(payload.tenant_id)
    if not runtime.get("is_running", True):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Chaster Brain is currently stopped for this tenant",
        )

    normalized = {
        "tenant_id": payload.tenant_id,
        "app_id": "sandbox-control",
        "message": payload.message,
        "metadata": {"source": "portal_settings_sandbox"},
    }
    state = orchestrator.invoke(normalized)
    record_ai_request(payload.tenant_id, state["intent"], float(state["confidence"]))
    return SandboxMessageResponse(
        tenant_id=payload.tenant_id,
        intent=state["intent"],
        confidence=state["confidence"],
        response=state["response"],
        used_sources=state.get("used_sources", []),
    )


def _resolve_ai_state(tenant_id: str) -> tuple[bool, str]:
    runtime = get_runtime_control(tenant_id)
    is_running = bool(runtime.get("is_running", True))
    if not is_running:
        return False, "human_needed"
    return True, "unresolved"


def _issue_widget_session_token_with_claims(claims_payload: dict) -> tuple[str, str]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.widget_session_ttl_seconds)
    token = jwt.encode(
        {
            "iss": "chaster-brain-widget",
            "type": "widget_session",
            **claims_payload,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.widget_session_secret,
        algorithm="HS256",
    )
    return token, expires_at.isoformat()


def _create_guest_conversation(*, tenant_id: str, guest_name: str | None, guest_email: str | None) -> str | None:
    # Zero-history security rule: every guest handshake gets a fresh conversation id.
    try:
        row = insert_row(
            "conversations",
            {
                "tenant_id": tenant_id,
                "type": "hq_client",
                "name": f"Guest {guest_name or 'Visitor'}",
                "last_message_preview": f"guest_email:{(guest_email or '').lower()}",
            },
        )
    except Exception:
        # Keep handshake available in environments where conversations schema/triggers differ.
        return None
    if not row:
        return None
    return row.get("id")


def _generate_case_number() -> str:
    suffix = secrets.token_hex(3).upper()
    timestamp = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"CASE-{timestamp}{suffix}"


def _ensure_widget_support_case(
    *,
    tenant_id: str,
    guest_name: str | None,
    guest_email: str | None,
    conversation_id: str | None,
) -> str | None:
    try:
        UUID(str(tenant_id))
    except ValueError:
        return None
    if conversation_id:
        try:
            existing = get_single_row(
                "support_cases",
                "id",
                {
                    "tenant_id": tenant_id,
                    "source": "widget",
                    "status": "open",
                    "description": conversation_id,
                },
            )
            if existing and existing.get("id"):
                return str(existing["id"])
        except Exception:
            return None
    try:
        row = insert_row(
            "support_cases",
            {
                "tenant_id": tenant_id,
                "case_number": _generate_case_number(),
                "subject": f"Widget chat from {guest_name or 'Visitor'}",
                "description": conversation_id or "widget-conversation",
                "category": "widget",
                "status": "open",
                "priority": "medium",
                "source": "widget",
                "created_by": None,
                "support_requester_id": None,
            },
        )
    except Exception:
        return None
    if not row:
        return None
    return row.get("id")


def _decode_widget_session_token(token: str, *, tenant_id: str, app_id: str) -> dict:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.widget_session_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "type", "tenant_id", "app_id"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token") from exc

    if claims.get("type") != "widget_session":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid session token type")
    if claims.get("tenant_id") != tenant_id or claims.get("app_id") != app_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Session token tenant/app mismatch")
    return claims


@app.post("/v1/handshake", response_model=WidgetHandshakeResponse)
def handshake(
    payload: WidgetHandshakeRequest,
    authorization: str = Header(default="", alias="Authorization"),
    x_signature: str = Header(default="", alias="X-Signature"),
    x_timestamp: str = Header(default="", alias="X-Timestamp"),
    x_nonce: str = Header(default="", alias="X-Nonce"),
    origin: str = Header(default="", alias="Origin"),
):
    if payload.mode == "logged_in" and not payload.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="user_id is required for logged_in mode")
    if payload.mode == "anonymous" and (not payload.guest_name or not payload.guest_email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="guest_name and guest_email are required for anonymous intake",
        )
    if payload.mode == "anonymous" and not payload.guest_id:
        payload.guest_id = f"guest-{secrets.token_hex(8)}"

    signed_message = f"handshake:{payload.user_id or payload.guest_id or 'unknown'}"
    validate_app_request_signature(
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
        message=signed_message,
        signature=x_signature,
        timestamp=x_timestamp,
        nonce=x_nonce,
        origin=origin,
    )

    # Backward compatibility path: allow passing caller JWT; currently optional for compatibility mode.
    _ = authorization
    conversation_id = _create_guest_conversation(
        tenant_id=payload.tenant_id,
        guest_name=payload.guest_name,
        guest_email=payload.guest_email,
    )
    support_case_id = _ensure_widget_support_case(
        tenant_id=payload.tenant_id,
        guest_name=payload.guest_name,
        guest_email=payload.guest_email,
        conversation_id=conversation_id,
    )
    session_token, expires_at = _issue_widget_session_token_with_claims(
        {
            "tenant_id": payload.tenant_id,
            "app_id": payload.app_id,
            "user_id": payload.user_id,
            "guest_id": payload.guest_id,
            "mode": payload.mode,
            "conversation_id": conversation_id,
            "support_case_id": support_case_id,
            "guest_name": payload.guest_name,
            "guest_email": (payload.guest_email or "").lower() if payload.guest_email else None,
        }
    )
    ai_handling, _state = _resolve_ai_state(payload.tenant_id)
    return WidgetHandshakeResponse(
        session_token=session_token,
        expires_at=expires_at,
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
        user_id=payload.user_id,
        guest_id=payload.guest_id,
        conversation_id=conversation_id,
        support_case_id=support_case_id,
        ai_handling=ai_handling,
    )


@app.post("/v1/process", response_model=WidgetProcessResponse)
def process_widget_message(
    payload: WidgetProcessRequest,
    authorization: str = Header(default="", alias="Authorization"),
    x_signature: str = Header(default="", alias="X-Signature"),
    x_timestamp: str = Header(default="", alias="X-Timestamp"),
    x_nonce: str = Header(default="", alias="X-Nonce"),
    origin: str = Header(default="", alias="Origin"),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing session bearer token")
    session_token = authorization.split(" ", maxsplit=1)[1]
    session_claims = _decode_widget_session_token(
        session_token,
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
    )

    validate_app_request_signature(
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
        message=payload.message,
        signature=x_signature,
        timestamp=x_timestamp,
        nonce=x_nonce,
        origin=origin,
    )

    runtime = get_runtime_control(payload.tenant_id)
    if not runtime.get("is_running", True):
        return WidgetProcessResponse(
            tenant_id=payload.tenant_id,
            app_id=payload.app_id,
            intent="faq_or_general",
            confidence=1.0,
            response="Connecting you to a human support agent.",
            used_sources=[],
            sender_type="human",
            ai_handling=False,
            state="human_needed",
        )

    normalized = {
        "tenant_id": payload.tenant_id,
        "app_id": payload.app_id,
        "message": payload.message,
        "metadata": payload.metadata,
    }
    state = orchestrator.invoke(normalized)
    params = get_parameters(payload.tenant_id)
    if (
        state.get("intent") == "complex_personal_request"
        and float(state["confidence"]) < float(params["confidence_threshold"])
    ):
        state["response"] = (
            "I need a little more verified context to answer accurately. "
            "Please provide one specific identifier (order id, invoice id, or account email)."
        )
    record_ai_request(payload.tenant_id, state["intent"], float(state["confidence"]))
    conversation_id = session_claims.get("conversation_id")
    support_case_id = session_claims.get("support_case_id")
    if conversation_id:
        insert_row(
            "messages",
            {
                "conversation_id": conversation_id,
                "sender_id": None,
                "body": payload.message,
            },
        )
        insert_row(
            "messages",
            {
                "conversation_id": conversation_id,
                "sender_id": None,
                "body": state["response"],
            },
        )
    if support_case_id:
        insert_row(
            "support_case_messages",
            {
                "case_id": support_case_id,
                "sender_id": None,
                "body": payload.message,
                "is_system": False,
                "metadata": {"origin": "widget", "direction": "inbound"},
            },
        )
        insert_row(
            "support_case_messages",
            {
                "case_id": support_case_id,
                "sender_id": None,
                "body": state["response"],
                "is_system": False,
                "metadata": {"origin": "widget", "direction": "assistant"},
            },
        )
    return WidgetProcessResponse(
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
        intent=state["intent"],
        confidence=state["confidence"],
        response=state["response"],
        used_sources=state.get("used_sources", []),
        sender_type="ai",
        conversation_id=conversation_id,
        support_case_id=support_case_id,
        ai_handling=True,
        state="unresolved",
    )


@app.post("/v1/gateway/message", response_model=GatewayMessageResponse)
def process_message(
    payload: GatewayMessageRequest,
    authorization: str = Header(default="", alias="Authorization"),
    x_chaster_dev_secret: str = Header(default="", alias="X-Chaster-Dev-Secret"),
    x_signature: str = Header(default="", alias="X-Signature"),
    x_timestamp: str = Header(default="", alias="X-Timestamp"),
    x_nonce: str = Header(default="", alias="X-Nonce"),
    origin: str = Header(default="", alias="Origin"),
):
    settings = get_settings()
    configured_secret = (settings.chaster_brain_dev_gateway_secret or "").strip()
    header_secret = (x_chaster_dev_secret or "").strip()
    dev_ok = bool(
        configured_secret
        and header_secret
        and secrets.compare_digest(header_secret, configured_secret)
    )

    if dev_ok:
        auth_token = ""
    else:
        if header_secret and not configured_secret:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="X-Chaster-Dev-Secret was sent but CHASTER_BRAIN_DEV_GATEWAY_SECRET is not set on the API",
            )
        if header_secret and configured_secret and not dev_ok:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="X-Chaster-Dev-Secret does not match CHASTER_BRAIN_DEV_GATEWAY_SECRET on the API",
            )
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Missing bearer token (or set matching CHASTER_BRAIN_DEV_GATEWAY_SECRET and X-Chaster-Dev-Secret for local dev)",
            )
        auth_token = authorization.split(" ", maxsplit=1)[1]

    normalized = validate_request_security(
        payload,
        auth_token=auth_token,
        signature=x_signature,
        timestamp=x_timestamp,
        nonce=x_nonce,
        origin=origin,
        dev_bypass_jwt=dev_ok,
    )
    runtime = get_runtime_control(payload.tenant_id)
    if not runtime.get("is_running", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chaster Brain is currently stopped for this tenant")

    state = orchestrator.invoke(normalized)
    params = get_parameters(payload.tenant_id)
    # Low-confidence guard is for personal / account-specific flows, not FAQ greetings or general questions.
    if (
        state.get("intent") == "complex_personal_request"
        and float(state["confidence"]) < float(params["confidence_threshold"])
    ):
        state["response"] = (
            "I need a little more verified context to answer accurately. "
            "Please provide one specific identifier (order id, invoice id, or account email)."
        )
    record_ai_request(payload.tenant_id, state["intent"], float(state["confidence"]))
    return GatewayMessageResponse(
        tenant_id=payload.tenant_id,
        app_id=payload.app_id,
        intent=state["intent"],
        confidence=state["confidence"],
        response=state["response"],
        used_sources=state.get("used_sources", []),
    )
