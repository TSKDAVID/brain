from fastapi.testclient import TestClient

from app.main import app


def test_support_suggest_reply_endpoint(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        "app.main.validate_tenant_access_token",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda tenant_id: {
            "tenant_id": tenant_id,
            "is_running": True,
            "mode": "automatic",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        "app.main.suggest_support_reply",
        lambda **kwargs: ("Thanks for reaching out — we are looking into this.", ["kb-1"]),
    )
    res = client.post(
        "/v1/control/support/suggest-reply",
        headers={"Authorization": "Bearer test-token"},
        json={
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "case_id": "00000000-0000-0000-0000-000000000002",
            "draft_hint": "be brief",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert "looking into this" in body["draft"]
    assert body["used_sources"] == ["kb-1"]
