from datetime import date

from app.db.client import count_rows, get_single_row, insert_row, upsert_row
from app.models import (
    DashboardStatsResponse,
    IndexDataRequest,
    ParametersUpdateRequest,
    RuntimeControlUpdate,
)


def set_runtime_control(payload: RuntimeControlUpdate) -> dict:
    return upsert_row(
        "brain_runtime_control",
        {
            "tenant_id": payload.tenant_id,
            "is_running": payload.is_running,
            "mode": payload.mode,
            "updated_by": payload.updated_by,
        },
        on_conflict="tenant_id",
    ) or {}


def get_runtime_control(tenant_id: str) -> dict:
    row = get_single_row(
        "brain_runtime_control",
        select="tenant_id,is_running,mode,updated_at",
        filters={"tenant_id": tenant_id},
    )
    if row:
        return row
    return set_runtime_control(RuntimeControlUpdate(tenant_id=tenant_id, is_running=True, mode="automatic"))


def set_parameters(payload: ParametersUpdateRequest) -> dict:
    return upsert_row(
        "brain_parameters",
        {
            "tenant_id": payload.tenant_id,
            "confidence_threshold": payload.confidence_threshold,
            "max_context_chunks": payload.max_context_chunks,
            "response_tone": payload.response_tone,
            "mcp_enabled": payload.mcp_enabled,
            "updated_by": payload.updated_by,
        },
        on_conflict="tenant_id",
    ) or {}


def get_parameters(tenant_id: str) -> dict:
    row = get_single_row(
        "brain_parameters",
        select="tenant_id,confidence_threshold,max_context_chunks,response_tone,mcp_enabled,updated_at",
        filters={"tenant_id": tenant_id},
    )
    if row:
        return row
    return set_parameters(
        ParametersUpdateRequest(
            tenant_id=tenant_id,
            confidence_threshold=0.6,
            max_context_chunks=8,
            response_tone="professional",
            mcp_enabled=True,
        )
    )


def create_index_job(payload: IndexDataRequest) -> dict:
    return insert_row(
        "brain_index_jobs",
        {
            "tenant_id": payload.tenant_id,
            "source_type": payload.source_type,
            "source_ref": payload.source_ref,
            "payload": payload.payload,
            "status": "queued",
            "requested_by": payload.requested_by,
        },
    ) or {}


def _metrics_today(tenant_id: str) -> dict:
    today = str(date.today())
    row = get_single_row(
        "brain_metrics_daily",
        select="total_requests,low_confidence_count",
        filters={"tenant_id": tenant_id, "metric_date": today},
    )
    return row or {"total_requests": 0, "low_confidence_count": 0}


def get_dashboard_stats(tenant_id: str) -> DashboardStatsResponse:
    metrics = _metrics_today(tenant_id)
    return DashboardStatsResponse(
        tenant_id=tenant_id,
        knowledge_chunks=count_rows("knowledge_chunks", {"tenant_id": tenant_id}),
        index_jobs_total=count_rows("brain_index_jobs", {"tenant_id": tenant_id}),
        index_jobs_pending=count_rows("brain_index_jobs", {"tenant_id": tenant_id, "status": "queued"}),
        support_cases_open=count_rows("support_cases", {"tenant_id": tenant_id, "status": "open"}),
        conversations_total=count_rows("conversations", {"tenant_id": tenant_id}),
        ai_requests_today=metrics["total_requests"],
        low_confidence_today=metrics["low_confidence_count"],
    )


def record_ai_request(tenant_id: str, intent: str, confidence: float) -> None:
    today = str(date.today())
    current = get_single_row(
        "brain_metrics_daily",
        select="id,total_requests,faq_requests,personal_requests,low_confidence_count,blocked_request_count,avg_confidence",
        filters={"tenant_id": tenant_id, "metric_date": today},
    )
    if current:
        total = int(current["total_requests"]) + 1
        faq = int(current["faq_requests"]) + (1 if intent == "faq_or_general" else 0)
        personal = int(current["personal_requests"]) + (1 if intent == "complex_personal_request" else 0)
        low_conf = int(current["low_confidence_count"]) + (1 if confidence < 0.5 else 0)
        prev_avg = float(current["avg_confidence"])
        avg_conf = ((prev_avg * (total - 1)) + confidence) / total
        upsert_row(
            "brain_metrics_daily",
            {
                "tenant_id": tenant_id,
                "metric_date": today,
                "total_requests": total,
                "faq_requests": faq,
                "personal_requests": personal,
                "low_confidence_count": low_conf,
                "blocked_request_count": int(current["blocked_request_count"]),
                "avg_confidence": round(avg_conf, 4),
            },
            on_conflict="tenant_id,metric_date",
        )
        return

    upsert_row(
        "brain_metrics_daily",
        {
            "tenant_id": tenant_id,
            "metric_date": today,
            "total_requests": 1,
            "faq_requests": 1 if intent == "faq_or_general" else 0,
            "personal_requests": 1 if intent == "complex_personal_request" else 0,
            "low_confidence_count": 1 if confidence < 0.5 else 0,
            "blocked_request_count": 0,
            "avg_confidence": round(confidence, 4),
        },
        on_conflict="tenant_id,metric_date",
    )
