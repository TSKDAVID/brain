from fastapi.testclient import TestClient

from app.main import app


def test_runtime_status_endpoint(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda tenant_id: {
            "tenant_id": tenant_id,
            "is_running": True,
            "mode": "automatic",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    res = client.get("/v1/control/runtime/tenant-1")
    assert res.status_code == 200
    assert res.json()["is_running"] is True


def test_parameters_update_endpoint(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        "app.main.set_parameters",
        lambda payload: {
            "tenant_id": payload.tenant_id,
            "confidence_threshold": payload.confidence_threshold,
            "max_context_chunks": payload.max_context_chunks,
            "response_tone": payload.response_tone,
            "mcp_enabled": payload.mcp_enabled,
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    res = client.post(
        "/v1/control/parameters",
        json={
            "tenant_id": "tenant-1",
            "confidence_threshold": 0.72,
            "max_context_chunks": 12,
            "response_tone": "friendly",
            "mcp_enabled": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["confidence_threshold"] == 0.72
