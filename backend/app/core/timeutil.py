from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.timezone)


def now_local() -> datetime:
    return datetime.now(TZ)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ)


def to_utc_naive(dt: datetime) -> datetime:
    """Normalise to timezone-aware UTC (name kept for history; values are aware, not naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_ts(value: str | int | float | datetime) -> datetime:
    """Accept ISO strings, epoch millis, or datetimes; return naive UTC."""
    if isinstance(value, datetime):
        return to_utc_naive(value)
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(secs, tz=UTC)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Assume local time if the collector did not send an offset.
        dt = dt.replace(tzinfo=TZ)
    return to_utc_naive(dt)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return aware-UTC [start, end) for a local calendar day."""
    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    return to_utc_naive(start), to_utc_naive(end)


def local_day_of(dt_utc: datetime) -> date:
    return to_local(dt_utc).date()


def fmt_hm(dt_utc_naive: datetime | None) -> str:
    if dt_utc_naive is None:
        return ""
    return to_local(dt_utc_naive).strftime("%H:%M")
