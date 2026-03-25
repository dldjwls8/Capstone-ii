from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 앱 기본 ──────────────────────────────────────────────────────────────
    APP_NAME: str = "루트온 API"
    DEBUG: bool = False

    # ── 인증 ─────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24시간

    # ── 데이터베이스 ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://routeon:routeon@db:5432/routeon"

    # ── TMAP API ──────────────────────────────────────────────────────────────
    TMAP_APP_KEY: str = ""
    TMAP_BASE_URL: str = "https://apis.openapi.sk.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
