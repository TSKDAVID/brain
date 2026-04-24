import hashlib
import hmac


def verify_hmac_signature(
    *,
    secret_hash: str,
    tenant_id: str,
    app_id: str,
    timestamp: str,
    nonce: str,
    message: str,
    provided_signature: str,
) -> bool:
    message_to_sign = f"{tenant_id}:{app_id}:{timestamp}:{nonce}:{message}".encode("utf-8")
    expected = hmac.new(secret_hash.encode("utf-8"), message_to_sign, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_signature)
