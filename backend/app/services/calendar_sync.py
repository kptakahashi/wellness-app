"""Pull Google Calendar (or any calendar) through its private iCal URL.

No OAuth dance: Google exposes a secret .ics address per calendar
(Settings > your calendar > "Secret address in iCal format"). We poll it and convert
events in a +/- window into RawEvents of kind `calendar_event`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from icalendar import Calendar
from sqlmodel import Session

from ..core.config import settings
from ..core.timeutil import TZ
from .ingest import BatchIn, EventIn, ingest_batch


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=TZ)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=TZ)
    raise TypeError(type(value))


def fetch_ics(url: str) -> list[EventIn]:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)
    now = datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=30), now + timedelta(days=7)
    out: list[EventIn] = []
    for comp in cal.walk("VEVENT"):
        try:
            start = _as_datetime(comp.decoded("DTSTART"))
            end = _as_datetime(comp.decoded("DTEND")) if comp.get("DTEND") else start + timedelta(hours=1)
        except Exception:
            continue
        if end < lo or start > hi:
            continue
        uid = str(comp.get("UID", ""))
        summary = str(comp.get("SUMMARY", ""))
        attendees = comp.get("ATTENDEE", [])
        if not isinstance(attendees, list):
            attendees = [attendees]
        payload = {
            "title": summary,
            "location": str(comp.get("LOCATION", "") or ""),
            "description": str(comp.get("DESCRIPTION", "") or "")[:500],
            "attendee_count": len(attendees),
            "all_day": not isinstance(comp.decoded("DTSTART"), datetime),
        }
        out.append(
            EventIn(
                source="calendar",
                kind="calendar_event",
                start=start.isoformat(),
                end=end.isoformat(),
                payload=payload,
                dedupe_key=f"{uid}:{start.isoformat()}",
            )
        )
    return out


def sync_calendars(session: Session) -> dict[str, int]:
    urls = [u.strip() for u in settings.calendar_ics_urls.split(",") if u.strip()]
    total = {"inserted": 0, "skipped": 0, "calendars": len(urls)}
    for url in urls:
        events = fetch_ics(url)
        res = ingest_batch(session, BatchIn(device_id="calendar", events=events))
        total["inserted"] += res["inserted"]
        total["skipped"] += res["skipped"]
    return total
