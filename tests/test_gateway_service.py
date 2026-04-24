import pytest
from fastapi import HTTPException

from app.models import GatewayMessageRequest
from app.gateway import service


def _base_request():
    return GatewayMessageRequest(
        app_id="app-12345678",
        tenant_id="tenant-1",
        message="hello",
        metadata={},
    )


def test_rejects_tenant_mismatch(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {"signature_max_age_seconds": 300})())
    monkeypatch.setattr(service, "validate_supabase_jwt", lambda _token: {"tenant_id": "tenant-x"})
    with pytest.raises(HTTPException) as exc:
        service.validate_request_security(
            _base_request(),
            auth_token="token",
            signature="s",
            timestamp="1713611111",
            nonce="n-1",
            origin="https://widget.example.com",
        )
    assert exc.value.status_code == 403


def test_rejects_origin_mismatch(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {"signature_max_age_seconds": 300})())
    monkeypatch.setattr(service, "validate_supabase_jwt", lambda _token: {"tenant_id": "tenant-1"})
    monkeypatch.setattr(service.replay_guard, "validate", lambda **_kwargs: True)
    monkeypatch.setattr(
        service,
        "get_single_row",
        lambda **_kwargs: {
            "tenant_id": "tenant-1",
            "app_id": "app-12345678",
            "hmac_secret": "secret",
            "allowed_origins": ["https://allowed.example.com"],
            "status": "active",
        },
    )
    with pytest.raises(HTTPException) as exc:
        service.validate_request_security(
            _base_request(),
            auth_token="token",
            signature="s",
            timestamp="1713611111",
            nonce="n-1",
            origin="https://forbidden.example.com",
        )
    assert exc.value.status_code == 403


def test_accepts_sub_when_member_of_tenant(monkeypatch):
    """JWT without tenant_id claim: resolve via tenant_members."""
    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {"signature_max_age_seconds": 300})())
    monkeypatch.setattr(service, "validate_supabase_jwt", lambda _token: {"sub": "user-uuid-1"})
    monkeypatch.setattr(service.replay_guard, "validate", lambda **_kwargs: True)

    def fake_get_single_row(table, select, filters):
        if table == "tenant_members":
            if filters.get("user_id") == "user-uuid-1" and filters.get("tenant_id") == "tenant-1":
                return {"tenant_id": "tenant-1"}
            return None
        if table == "app_configurations":
            return {
                "tenant_id": "tenant-1",
                "app_id": "app-12345678",
                "hmac_secret": "secret",
                "allowed_origins": ["https://allowed.example.com"],
                "status": "active",
            }
        return None

    monkeypatch.setattr(service, "get_single_row", fake_get_single_row)

    import hashlib
    import hmac

    ts = "1713611111"
    nonce = "n-1"
    msg = "hello"
    signed = hmac.new(
        b"secret",
        f"tenant-1:app-12345678:{ts}:{nonce}:{msg}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    result = service.validate_request_security(
        _base_request(),
        auth_token="token",
        signature=signed,
        timestamp=ts,
        nonce=nonce,
        origin="https://allowed.example.com",
    )
    assert result["tenant_id"] == "tenant-1"
    assert result["message"] == "hello"
