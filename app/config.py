from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


def _parse_cors_origins(v: str) -> List[str]:
    """Parse CORS_ORIGINS env: comma-separated list, e.g. https://myapp.onrender.com,https://myapp.vercel.app"""
    if not v or not v.strip():
        return []
    return [origin.strip() for origin in v.split(",") if origin.strip()]


class Settings(BaseSettings):
    app_name: str = "BTC Trading Signals API"
    default_symbol: str = "BTCUSDT"
    default_timeframe: str = "15m"

    # CORS: comma-separated origins for production (e.g. your frontend URL on Vercel).
    # Render backend URL is allowed by default when this is set.
    cors_origins: str = ""

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
        extra = "ignore"  # Allow extra env vars (e.g. DATABASE_URL used by database.py)

    def get_cors_origins_list(self) -> List[str]:
        return _parse_cors_origins(self.cors_origins)


@lru_cache()
def get_settings() -> Settings:
    return Settings()

