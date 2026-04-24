from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    chaster_brain_env: str = "development"
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_issuer: str
    supabase_jwks_url: str
    signature_max_age_seconds: int = 300
    groq_api_key: str | None = None
    groq_api_base_url: str = "https://api.groq.com/openai/v1"
    # Groq model id (see https://console.groq.com/docs/models); set GROQ_MODEL in .env.
    groq_model: str = "llama-3.3-70b-versatile"
    cors_allow_origins: str = "http://localhost:5174,http://127.0.0.1:5174"
    # Local testing only: if set, requests with matching X-Chaster-Dev-Secret skip JWT (HMAC + app config still enforced).
    chaster_brain_dev_gateway_secret: str | None = None
    widget_session_secret: str = "dev-widget-session-secret-change-me"
    widget_session_ttl_seconds: int = 900


def get_settings() -> Settings:
    # No lru_cache: .env changes apply without a full process restart (dev UX).
    return Settings()


def get_cors_origins() -> list[str]:
    settings = get_settings()
    return [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
