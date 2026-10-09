from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values can be overridden via environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[2] / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Shared secret between the Android collector / web UI and this server.
    app_token: str = "change-me"

    # Where SQLite lives. On Fly.io this should point at the mounted volume (/data).
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"

    # Inference backend: "agent_sdk" (Claude Code subscription via Agent SDK),
    # "api" (Anthropic API key), or "rules" (no LLM, deterministic fallback).
    inference_backend: str = "agent_sdk"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"

    # Google Calendar private iCal URL(s), comma separated. No OAuth needed.
    calendar_ics_urls: str = ""

    # Local timezone used to bucket events into days.
    timezone: str = "Asia/Tokyo"

    # Hour (local) at which the evening review is prepared automatically.
    evening_prepare_hour: int = 21

    # Demo mode serves synthetic data and never calls an LLM unless configured.
    demo_mode: bool = False

    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "wellness.db"


settings = Settings()
