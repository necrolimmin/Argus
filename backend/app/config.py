from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGUS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://argus:argus@db:5432/argus"

    # Signs JWTs and media links. Must be long and random in production.
    secret_key: str = "change-me"
    # Fernet key for camera passwords. Derived from secret_key when empty,
    # but set it explicitly so rotating secret_key does not lose passwords.
    encryption_key: str = ""
    access_token_minutes: int = 12 * 60

    # First administrator, created on startup if no users exist.
    admin_username: str = "admin"
    admin_password: str = "admin"

    go2rtc_url: str = "http://go2rtc:1984"
    # How the recognizer reaches go2rtc's RTSP restream.
    go2rtc_rtsp_url: str = "rtsp://go2rtc:8554"
    recognizer_url: str = "http://recognizer:8100"
    # Network discovery service (Docker: host networking). Empty = run
    # discovery inside the backend, which is what development on one PC uses.
    scanner_url: str = ""
    # Shared secret between backend and recognizer for /api/internal.
    service_token: str = "change-me-too"

    media_dir: Path = Path("/data/media")

    retention_days: int = 60
    dedup_seconds: int = 60
    match_threshold: float = 0.45
    timezone: str = "Asia/Tashkent"

    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
