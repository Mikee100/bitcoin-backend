from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "BTC Trading Signals API"
    default_symbol: str = "BTCUSDT"
    default_timeframe: str = "15m"

    # Email notifications (optional). Set EMAIL_ENABLED=true and SMTP_* to enable.
    email_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"

    @field_validator("email_enabled", mode="before")
    @classmethod
    def parse_email_enabled(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        return bool(v)
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email: str = ""  # Where to send alerts (defaults to smtp_user if set)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

