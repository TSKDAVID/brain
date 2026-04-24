from jwt import PyJWKClient, decode

from app.config import get_settings


def validate_supabase_jwt(token: str) -> dict:
    settings = get_settings()
    jwks_client = PyJWKClient(settings.supabase_jwks_url)
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        issuer=settings.supabase_jwt_issuer,
        options={"verify_aud": False},
    )
