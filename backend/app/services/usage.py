"""The numbers the MVP is judged by.

The product's value is "advice grounded in my real day, at zero effort". That rests on three legs,
and this module measures the first two (the third needs weeks of the first two):

1. Coverage  - how much of the day was captured automatically
     * sources      which of the 7 passive sources reported that day
     * meal slots   breakfast / lunch / dinner slots that produced a card (= some evidence existed)
     * gap hours    waking hours (08:00-23:00) with no behaviour signal at all
2. Accuracy  - how the owner answered the cards
     * accepted     the proposed option was right
     * corrected    another option was picked
     * free_text    nothing fit; typed by hand (the estimate was wrong or the event was never captured)
3. Continuity - consecutive evenings answered (the habit holds)

Everything is a pure function over plain rows so it is cheap to test; `collect_day_events` is the
only part that talks to the database.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from sqlmodel import Session, select

from ..core.models import RawEvent
from ..core.timeutil import day_bounds, local_day_of, to_local


class _CardLike(Protocol):
    date: str
    kind: str
    time_label: str | None
    options: list[str]
    answer: str | None
    proposed: str | None


@dataclass
class DayEvents:
    """What the collectors delivered for one local day, reduced to what coverage needs."""

    date: date
    kinds: set[str] = field(default_factory=set)
    # behaviour spans as (kind, start_hour, end_hour) in local fractional hours
    spans: list[tuple[str, float, float]] = field(default_factory=list)


SOURCES: dict[str, set[str]] = {
    "sleep": {"sleep_session"},
    "heart": {"heart_rate", "hrv", "resting_hr"},
    "steps": {"steps"},
    "payment": {"payment"},
    "place": {"place_visit"},
    "calendar": {"calendar_event"},
    "screen": {"app_usage"},
}
BEHAVIOUR_KINDS = ("payment", "place_visit", "calendar_event", "exercise", "voice_note")
MEAL_SLOTS = (("breakfast", 5, 10), ("lunch", 11, 14), ("dinner", 17, 22))
WAKING_HOURS = range(8, 23)  # 08:00-22:59, 15 hours


def _hour_of(hm: str | None) -> float | None:
    if not hm or ":" not in hm:
        return None
    h, m = hm.split(":")
    try:
        return int(h) + int(m) / 60
    except ValueError:
        return None


def _slot_of(hm: str | None) -> str | None:
    h = _hour_of(hm)
    if h is None:
        return None
    return next((name for name, lo, hi in MEAL_SLOTS if lo <= h < hi), None)


def classify_answer(card: _CardLike) -> str | None:
    """accepted | corrected | free_text, or None when unanswered."""
    if not card.answer:
        return None
    if card.proposed is not None and card.answer == card.proposed:
        return "accepted"
    if card.answer in (card.options or []):
        return "corrected"
    return "free_text"


def day_coverage(ev: DayEvents | None, cards: list[_CardLike]) -> dict[str, Any]:
    sources = sorted(name for name, kinds in SOURCES.items() if ev and ev.kinds & kinds) if ev else []
    meal_cards = [c for c in cards if c.kind == "meal"]
    slots = {s for c in meal_cards if (s := _slot_of(c.time_label))}
    meal_free = sum(1 for c in meal_cards if classify_answer(c) == "free_text")
    gap_hours: int | None = None
    if ev and ev.kinds:
        covered = {h for h in WAKING_HOURS for _, s, e in ev.spans if s < h + 1 and e > h}
        gap_hours = len(WAKING_HOURS) - len(covered)
    return {
        "sources": sources,
        "meal_slots": len(slots),
        "meals_free_text": meal_free,
        "gap_hours": gap_hours,
    }


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def usage_metrics(cards: list[_CardLike], today: date, days: dict[date, DayEvents] | None = None, weeks: int = 4) -> dict[str, Any]:
    days = days or {}
    cards_by_day: dict[date, list[_CardLike]] = defaultdict(list)
    for c in cards:
        cards_by_day[date.fromisoformat(c.date)].append(c)
    answered_days = {d for d, cs in cards_by_day.items() if any(c.answer for c in cs)}

    streak = 0
    cursor = today if today in answered_days else today - timedelta(days=1)
    while cursor in answered_days:
        streak += 1
        cursor -= timedelta(days=1)

    def nights_in(n: int) -> int:
        lo = today - timedelta(days=n - 1)
        return sum(1 for d in answered_days if lo <= d <= today)

    coverage_by_day = {d: day_coverage(days.get(d), cards_by_day.get(d, [])) for d in set(days) | set(cards_by_day)}

    week_rows: list[dict[str, Any]] = []
    this_week = _week_start(today)
    for i in range(weeks - 1, -1, -1):
        ws = this_week - timedelta(weeks=i)
        we = min(ws + timedelta(days=6), today)
        span = [ws + timedelta(days=k) for k in range((we - ws).days + 1)]
        week_cards = [c for d in span for c in cards_by_day.get(d, []) if c.answer]
        verdicts = [classify_answer(c) for c in week_cards]
        data_days = [d for d in span if days.get(d) and days[d].kinds]
        cov = [coverage_by_day[d] for d in data_days]
        week_rows.append(
            {
                "week_start": ws.isoformat(),
                "days_with_data": len(data_days),
                "sources_avg": round(sum(len(c["sources"]) for c in cov) / len(cov), 1) if cov else None,
                "meal_slots_captured": sum(c["meal_slots"] for c in cov),
                "meal_slots_total": 3 * len(data_days),
                "meals_free_text": sum(c["meals_free_text"] for c in cov),
                "gap_hours_avg": round(sum(c["gap_hours"] for c in cov) / len(cov), 1) if cov else None,
                "nights_answered": sum(1 for d in span if d in answered_days),
                "cards_answered": len(week_cards),
                "accepted": verdicts.count("accepted"),
                "corrected": verdicts.count("corrected"),
                "free_text": verdicts.count("free_text"),
            }
        )

    recent = []
    for k in range(6, -1, -1):
        d = today - timedelta(days=k)
        recent.append({"date": d.isoformat(), "answered": d in answered_days, **coverage_by_day.get(d, day_coverage(None, []))})

    return {
        "today": today.isoformat(),
        "streak_nights": streak,
        "nights_last_7": nights_in(7),
        "nights_last_28": nights_in(28),
        "last_answered": max(answered_days).isoformat() if answered_days else None,
        "weeks": week_rows,
        "days": recent,
    }


# ---------------------------------------------------------------- database side
def collect_day_events(session: Session, start: date, end: date) -> dict[date, DayEvents]:
    """One DayEvents per local day in [start, end]. Two cheap passes: distinct kinds per day, and behaviour spans."""
    out: dict[date, DayEvents] = {}
    cur = start
    while cur <= end:
        lo, hi = day_bounds(cur)
        kinds = set(session.exec(select(RawEvent.kind).where(RawEvent.start_ts >= lo, RawEvent.start_ts < hi).distinct()).all())
        out[cur] = DayEvents(date=cur, kinds=kinds)
        cur += timedelta(days=1)

    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    rows = session.exec(
        select(RawEvent.kind, RawEvent.start_ts, RawEvent.end_ts).where(RawEvent.kind.in_(BEHAVIOUR_KINDS), RawEvent.start_ts >= lo, RawEvent.start_ts < hi)
    ).all()
    for kind, s, e in rows:
        d = local_day_of(s)
        if d not in out:
            continue
        ls = to_local(s)
        sh = ls.hour + ls.minute / 60
        le = to_local(e) if e else None
        eh = (le.hour + le.minute / 60) if le and le.date() == ls.date() else (24.0 if le else sh + 0.25)
        out[d].spans.append((kind, sh, max(eh, sh + 0.25)))
    return out
