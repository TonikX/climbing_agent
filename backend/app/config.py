from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "production"
    internal_api_key: SecretStr
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "climbing_journal"
    db_user: str = "climbing"
    db_password: SecretStr = SecretStr("")
    db_control_user: str | None = None
    db_control_password: SecretStr | None = None
    public_mode: bool = False
    access_approver_telegram_id: str | None = None
    access_approval_chat_id: str | None = None
    access_retry_hours: int = 24
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr = SecretStr("")
    telegram_bot_id: str = "test"
    cloudru_api_key: SecretStr = SecretStr("")
    cloudru_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    cloudru_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    cloudru_asr_model: str = "openai/whisper-large-v3"
    ai_daily_requests: int = 20
    audio_daily_seconds: int = 600
    audio_max_seconds: int = 120
    ai_queue_per_user: int = 3
    ai_daily_budget_units: int = 0
    ai_call_reservation_units: int = 0
    api_url: str = "http://api:8000"

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def control_database_url(self) -> URL:
        return self.database_url.set(username=self.db_control_user or self.db_user,
                                     password=(self.db_control_password or self.db_password).get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
