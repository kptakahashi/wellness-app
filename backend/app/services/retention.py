"""Hold as little as possible: purge old raw data, and delete everything on request.

RawEvents are the only bulky, sensitive table (heart-rate samples, notification text, locations).
Everything the product shows later is derived into DaySummary.metrics, Card and Insight, so raw
rows can go after a while without losing trends.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session

from ..core.models import Card, DaySummary, Insight, PoiTile, RawEvent, Setting


def purge_raw_events(session: Session, *, keep_days: int, now: datetime | None = None) -> int:
    """Delete RawEvents that started more than `keep_days` ago. Returns the number of rows removed."""
    if keep_days <= 0:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=keep_days)
    result = session.execute(delete(RawEvent).where(RawEvent.start_ts < cutoff))
    session.commit()
    return int(result.rowcount or 0)


def delete_everything(session: Session) -> dict[str, int]:
    """Remove every row of personal data, including remembered places and cached map tiles."""
    counts: dict[str, int] = {}
    for model in (RawEvent, DaySummary, Card, Insight, PoiTile, Setting):
        result = session.execute(delete(model))
        counts[model.__tablename__] = int(result.rowcount or 0)
    session.commit()
    return counts
