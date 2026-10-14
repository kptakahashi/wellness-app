"""Scheduled work, shared by the in-process scheduler (main.py) and the HTTP job endpoints (routes.py)."""

from __future__ import annotations

import logging

from sqlmodel import Session

from ..core.config import settings
from ..core.timeutil import now_local
from ..inference.engine import generate_insights, infer_day
from .calendar_sync import sync_calendars
from .retention import purge_raw_events

log = logging.getLogger(__name__)


def run_evening(session: Session) -> None:
    """Pull the calendar, infer today's cards, then drop raw data that is past its retention."""
    if settings.calendar_ics_urls.strip():
        try:
            sync_calendars(session)
        except Exception:  # noqa: BLE001
            log.exception("calendar sync failed")
    infer_day(session, now_local().date())
    try:
        removed = purge_raw_events(session, keep_days=settings.raw_event_retention_days)
        if removed:
            log.info("retention: removed %d raw events older than %d days", removed, settings.raw_event_retention_days)
    except Exception:  # noqa: BLE001
        log.exception("retention purge failed")


def run_weekly(session: Session) -> None:
    generate_insights(session, end=now_local().date(), days=28)
