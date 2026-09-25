from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


def configured(value: str) -> bool:
    v = value.strip().lower()
    return bool(v) and not any(x in v for x in ("your_", "change_me", "placeholder", "example_key"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    database_url: str = "postgresql+psycopg://app:change_me@db:5432/papers"
    redis_url: str = "redis://redis:6379/0"
    app_timezone: str = "Asia/Seoul"
    app_secret_key: str = ""
    app_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_hours: int = 24
    serpapi_api_key: str = ""
    crossref_mailto: str = ""
    llm_provider: Literal["openai", "gemini"] = "openai"
    openai_api_key: str = ""
    openai_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""
    if_provider: Literal["imported"] = "imported"
    max_search_pages_per_source: int = Field(5, ge=1, le=100)
    max_serpapi_requests_per_job: int = Field(8, ge=1)
    max_http_attempts: int = Field(3, ge=1, le=10)
    http_timeout_seconds: int = Field(30, ge=1, le=120)
    max_job_seconds: int = Field(900, ge=10)
    llm_max_calls_per_job: int = Field(100, ge=0)
    llm_max_output_tokens: int = Field(1000, ge=100)
    demo_mode: bool = False
    run_live_api_tests: bool = False
    publisher_allowed_hosts: str = ""

    def provider_status(self):
        provider = self.llm_provider
        return {"google_scholar": configured(self.serpapi_api_key), "arxiv": True,
                "crossref": True, "llm_provider": provider,
                "llm": provider in ("openai", "gemini") and configured(getattr(self, f"{provider}_api_key", ""))
                and configured(getattr(self, f"{provider}_model", "")),
                "if_provider": "imported", "demo_mode": self.demo_mode}


@lru_cache
def settings():
    return Settings()
