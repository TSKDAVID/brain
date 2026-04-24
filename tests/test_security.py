from app.security.hmac_validator import verify_hmac_signature
from app.security.replay_guard import ReplayGuard
from app.security.sanitizer import sanitize_message


def test_sanitizer_removes_script():
    cleaned = sanitize_message("<script>alert(1)</script> hi")
    assert "<script>" not in cleaned
    assert "hi" in cleaned


def test_hmac_validation_round_trip():
    tenant = "tenant-1"
    app_id = "app-12345678"
    timestamp = "1713611111"
    nonce = "nonce-1"
    message = "hello"
    secret = "top-secret"

    import hashlib
    import hmac

    signed = hmac.new(
        secret.encode("utf-8"),
        f"{tenant}:{app_id}:{timestamp}:{nonce}:{message}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert verify_hmac_signature(
        secret_hash=secret,
        tenant_id=tenant,
        app_id=app_id,
        timestamp=timestamp,
        nonce=nonce,
        message=message,
        provided_signature=signed,
    )


def test_replay_guard_blocks_reuse():
    guard = ReplayGuard()
    now = "1713611111"
    assert guard.validate("abc", now, 999999999)
    assert not guard.validate("abc", now, 999999999)
