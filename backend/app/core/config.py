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

    # Where SQLite lives when DATABASE_URL is not set.
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"

    # Optional Postgres URL (e.g. Neon free tier). When unset, SQLite in data_dir is used.
    # Accepts postgres:// or postgresql:// and normalises to the psycopg driver.
    database_url: str | None = None

    # Inference backend: "agent_sdk" (Claude Code subscription via Agent SDK) or
    # "rules" (no LLM, deterministic fallback). No API-key backend: free tiers only.
    inference_backend: str = "agent_sdk"
    claude_model: str = "claude-opus-5-5"

    # Raw events older than this many days are deleted every evening. Daily metrics
    # (DaySummary), cards and insights are kept, so trends survive. 0 = keep forever.
    raw_event_retention_days: int = 90

    # Google Calendar private iCal URL(s), comma separated. No OAuth needed.
    calendar_ics_urls: str = ""

    # Local timezone used to bucket events into days.
    timezone: str = "Asia/Tokyo"

    # Hour (local) at which the evening review is prepared automatically.
    evening_prepare_hour: int = 21

    # Demo mode serves synthetic data and never calls an LLM unless configured.
    demo_mode: bool = False

    # Naming the shop/facility behind a stay. "osm": download named places for ~5 km tiles from
    # OpenStreetMap (free, no key, no coordinates of individual visits leave the server) and match
    # locally. "none": addresses only.
    poi_source: str = "osm"
    poi_tile_deg: float = 0.02  # ~2 km square; dense city tiles stay small enough for the public API
    overpass_urls: str = "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter"

    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "wellness.db"

    @property
    def sqlalchemy_url(self) -> str:
        url = (self.database_url or "").strip()
        if not url:
            return f"sqlite:///{self.db_path}"
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url


settings = Settings()
