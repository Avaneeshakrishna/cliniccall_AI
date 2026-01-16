from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/ai_receptionist"
    )
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""
    voice_api_token: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    public_base_url: str = ""
    internal_api_base_url: str = "http://localhost:8000"
    enable_twilio: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
