from fastapi import HTTPException, status

from app.config import get_settings
from app.db.client import get_single_row
from app.models import GatewayMessageRequest
from app.security.hmac_validator import verify_hmac_signature
from app.security.jwt_validator import validate_supabase_jwt
from app.security.replay_guard import ReplayGuard
from app.security.sanitizer import sanitize_message, sanitize_metadata

replay_guard = ReplayGuard()


def _tenant_matches_jwt(claims: dict, request_tenant_id: str) -> bool:
    """
    Supabase access tokens usually do not include tenant_id.
    If present, it must match. Otherwise resolve via tenant_members (user sub).
    """
    jwt_tenant = claims.get("tenant_id")
    if jwt_tenant:
        return jwt_tenant == request_tenant_id

    sub = claims.get("sub")
    if not sub:
        return False

    row = get_single_row(
        "tenant_members",
        "tenant_id",
        {"user_id": sub, "tenant_id": request_tenant_id},
    )
    return row is not None


def validate_app_request_signature(
    *,
    tenant_id: str,
    app_id: str,
    message: str,
    signature: str,
    timestamp: str,
    nonce: str,
    origin: str,
) -> None:
    settings = get_settings()
    if not replay_guard.validate(
        nonce=nonce,
        timestamp=timestamp,
        max_age_seconds=settings.signature_max_age_seconds,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Replay guard rejected request")

    config = get_single_row(
        table="app_configurations",
        select="tenant_id,app_id,hmac_secret,allowed_origins,status",
        filters={"app_id": app_id},
    )
    if not config:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Unknown app_id")
    if config["tenant_id"] != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid tenant binding")
    if config["status"] != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="App is inactive")
    if origin not in (config.get("allowed_origins") or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Origin not allowed")

    is_valid_hmac = verify_hmac_signature(
        secret_hash=config["hmac_secret"],
        tenant_id=tenant_id,
        app_id=app_id,
        timestamp=timestamp,
        nonce=nonce,
        message=message,
        provided_signature=signature,
    )
    if not is_valid_hmac:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid signature")


def validate_request_security(
    request: GatewayMessageRequest,
    *,
    auth_token: str,
    signature: str,
    timestamp: str,
    nonce: str,
    origin: str,
    dev_bypass_jwt: bool = False,
) -> dict:
    if not dev_bypass_jwt:
        claims = validate_supabase_jwt(auth_token)
        if not _tenant_matches_jwt(claims, request.tenant_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    validate_app_request_signature(
        tenant_id=request.tenant_id,
        app_id=request.app_id,
        message=request.message,
        signature=signature,
        timestamp=timestamp,
        nonce=nonce,
        origin=origin,
    )

    return {
        "tenant_id": request.tenant_id,
        "app_id": request.app_id,
        "message": sanitize_message(request.message),
        "metadata": sanitize_metadata(request.metadata),
    }


def validate_tenant_access_token(*, auth_token: str, tenant_id: str) -> None:
    claims = validate_supabase_jwt(auth_token)
    if not _tenant_matches_jwt(claims, tenant_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
