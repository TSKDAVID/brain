from fastapi.testclient import TestClient

from app.main import app


HANDSHAKE_HEADERS = {
    "X-Signature": "sig",
    "X-Timestamp": "1713611111",
    "X-Nonce": "nonce-resume",
    "Origin": "https://widget.example.com",
}


def _patch_runtime(monkeypatch):
    monkeypatch.setattr("app.main.validate_app_request_signature", lambda **_kwargs: None)
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda _tenant_id: {"tenant_id": "tenant-a", "is_running": True, "mode": "automatic"},
    )


def test_handshake_resumes_when_conversation_exists(monkeypatch):
    client = TestClient(app)
    _patch_runtime(monkeypatch)

    create_calls: list[dict] = []
    monkeypatch.setattr(
        "app.main._create_guest_conversation",
        lambda **kwargs: (create_calls.append(kwargs), "should-not-be-used")[1],
    )
    monkeypatch.setattr(
        "app.main._try_resume_conversation",
        lambda *, tenant_id, conversation_id: {"id": conversation_id, "tenant_id": tenant_id},
    )
    monkeypatch.setattr(
        "app.main._ensure_widget_support_case",
        lambda **_kwargs: "case-1",
    )

    response = client.post(
        "/v1/handshake",
        json={
            "app_id": "app-12345678",
            "tenant_id": "tenant-a",
            "mode": "anonymous",
            "guest_id": "guest-1",
            "guest_name": "Test User",
            "guest_email": "test@example.com",
            "conversation_id": "00000000-0000-0000-0000-0000000000aa",
        },
        headers=HANDSHAKE_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resumed"] is True
    assert body["conversation_id"] == "00000000-0000-0000-0000-0000000000aa"
    assert create_calls == []  # We must NOT create a fresh conversation


def test_handshake_creates_new_when_resume_unknown(monkeypatch):
    client = TestClient(app)
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        "app.main._try_resume_conversation",
        lambda *, tenant_id, conversation_id: None,
    )
    monkeypatch.setattr("app.main._create_guest_conversation", lambda **_kwargs: "fresh-conv")
    monkeypatch.setattr("app.main._ensure_widget_support_case", lambda **_kwargs: "case-2")

    response = client.post(
        "/v1/handshake",
        json={
            "app_id": "app-12345678",
            "tenant_id": "tenant-a",
            "mode": "anonymous",
            "guest_id": "guest-1",
            "guest_name": "Test User",
            "guest_email": "test@example.com",
            "conversation_id": "11111111-1111-1111-1111-111111111111",
        },
        headers={**HANDSHAKE_HEADERS, "X-Nonce": "nonce-resume-fail"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resumed"] is False
    assert body["conversation_id"] == "fresh-conv"
