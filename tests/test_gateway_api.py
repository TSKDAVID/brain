from fastapi.testclient import TestClient

from app.main import app


def test_gateway_returns_403_on_missing_bearer():
    client = TestClient(app)
    response = client.post(
        "/v1/gateway/message",
        json={"app_id": "app-12345678", "tenant_id": "tenant-a", "message": "hello", "metadata": {}},
    )
    assert response.status_code == 403


def test_gateway_happy_path(monkeypatch):
    client = TestClient(app)

    def fake_validate_request_security(payload, **kwargs):
        return {
            "tenant_id": payload.tenant_id,
            "app_id": payload.app_id,
            "message": payload.message,
            "metadata": payload.metadata,
        }

    class FakeOrchestrator:
        def invoke(self, normalized):
            return {
                "intent": "faq_or_general",
                "confidence": 0.83,
                "response": "Safe response",
                "used_sources": ["chunk-1"],
            }

    monkeypatch.setattr("app.main.validate_request_security", fake_validate_request_security)
    monkeypatch.setattr("app.main.orchestrator", FakeOrchestrator())
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda _tenant_id: {"tenant_id": "tenant-a", "is_running": True, "mode": "automatic"},
    )
    monkeypatch.setattr(
        "app.main.get_parameters",
        lambda _tenant_id: {"confidence_threshold": 0.6},
    )
    monkeypatch.setattr("app.main.record_ai_request", lambda *_args, **_kwargs: None)

    response = client.post(
        "/v1/gateway/message",
        json={"app_id": "app-12345678", "tenant_id": "tenant-a", "message": "hello", "metadata": {}},
        headers={
            "Authorization": "Bearer token",
            "X-Signature": "sig",
            "X-Timestamp": "1713611111",
            "X-Nonce": "nonce-1",
            "Origin": "https://widget.example.com",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "faq_or_general"
    assert body["confidence"] == 0.83


def test_handshake_happy_path(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("app.main.validate_app_request_signature", lambda **_kwargs: None)
    monkeypatch.setattr("app.main._create_guest_conversation", lambda **_kwargs: "conv-1")
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda _tenant_id: {"tenant_id": "tenant-a", "is_running": True, "mode": "automatic"},
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
        },
        headers={"X-Signature": "sig", "X-Timestamp": "1713611111", "X-Nonce": "nonce-1", "Origin": "https://widget.example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["app_id"] == "app-12345678"
    assert body["session_token"]


def test_process_happy_path(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("app.main.validate_app_request_signature", lambda **_kwargs: None)
    monkeypatch.setattr("app.main._create_guest_conversation", lambda **_kwargs: "conv-1")
    monkeypatch.setattr(
        "app.main.get_runtime_control",
        lambda _tenant_id: {"tenant_id": "tenant-a", "is_running": True, "mode": "automatic"},
    )
    monkeypatch.setattr("app.main.record_ai_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.main.insert_row", lambda *_args, **_kwargs: {"id": "msg-1"})
    monkeypatch.setattr(
        "app.main.get_parameters",
        lambda _tenant_id: {"confidence_threshold": 0.6},
    )

    class FakeOrchestrator:
        def invoke(self, _normalized):
            return {"intent": "faq_or_general", "confidence": 0.9, "response": "answer", "used_sources": []}

    monkeypatch.setattr("app.main.orchestrator", FakeOrchestrator())
    handshake = client.post(
        "/v1/handshake",
        json={
            "app_id": "app-12345678",
            "tenant_id": "tenant-a",
            "mode": "anonymous",
            "guest_id": "guest-1",
            "guest_name": "Test User",
            "guest_email": "test@example.com",
        },
        headers={"X-Signature": "sig", "X-Timestamp": "1713611111", "X-Nonce": "nonce-1", "Origin": "https://widget.example.com"},
    )
    token = handshake.json()["session_token"]

    response = client.post(
        "/v1/process",
        json={"app_id": "app-12345678", "tenant_id": "tenant-a", "message": "hello", "metadata": {}},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Signature": "sig",
            "X-Timestamp": "1713611112",
            "X-Nonce": "nonce-2",
            "Origin": "https://widget.example.com",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "answer"
    assert body["sender_type"] == "ai"


def test_process_requires_valid_session(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("app.main.validate_app_request_signature", lambda **_kwargs: None)
    response = client.post(
        "/v1/process",
        json={"app_id": "app-12345678", "tenant_id": "tenant-a", "message": "hello", "metadata": {}},
        headers={
            "Authorization": "Bearer invalid-token",
            "X-Signature": "sig",
            "X-Timestamp": "1713611112",
            "X-Nonce": "nonce-3",
            "Origin": "https://widget.example.com",
        },
    )
    assert response.status_code == 401


def test_handshake_requires_guest_intake_fields(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr("app.main.validate_app_request_signature", lambda **_kwargs: None)
    response = client.post(
        "/v1/handshake",
        json={"app_id": "app-12345678", "tenant_id": "tenant-a", "mode": "anonymous", "guest_id": "guest-1"},
        headers={"X-Signature": "sig", "X-Timestamp": "1713611111", "X-Nonce": "nonce-x", "Origin": "https://widget.example.com"},
    )
    assert response.status_code == 400
