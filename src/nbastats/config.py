"""Configuración central, leída de .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://nbastats:nbastats@localhost:5433/nbastats"
    seasons: str = "2021-22,2022-23,2023-24,2024-25,2025-26"

    kaggle_username: str = ""
    kaggle_key: str = ""

    nba_api_delay_seconds: float = 0.7
    nba_api_timeout_seconds: int = 30
    nba_api_max_retries: int = 5

    backfill_window_days: int = 7

    @property
    def season_list(self) -> list[str]:
        return [s.strip() for s in self.seasons.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
