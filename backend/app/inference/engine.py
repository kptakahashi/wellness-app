"""Orchestrates: DayContext -> (Claude | rules) -> DaySummary + Cards; and weekly insights."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from ..core.config import settings
from ..core.models import Card, DaySummary, Insight
from ..services import places, poi
from ..services.daycontext import build_day_context, previous_answers
from . import prompts, rules
from .claude_client import InferenceError, complete_json
from .schema import DAY_INFERENCE_SCHEMA, INSIGHT_SCHEMA

log = logging.getLogger(__name__)


# Questions the user never wants again: the identity of a place, and whether they slept.
PLACE_IDENTITY_RE = re.compile(r"(自宅|お家|ご自宅|家|職場|会社|オフィス)\s*(です|でした|だった|にい|に居|ですよね|でしょう)")
SLEEP_RE = re.compile(r"(寝て|眠って|就寝|睡眠|寝た|眠った|眠れ|眠り|寝つ|起きた|起床)")


def _drop_unwanted(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in cards:
        q = str(c.get("question", ""))
        if c.get("kind") == "sleep" or SLEEP_RE.search(q):
            continue  # sleep comes from Health Connect, never from a question
        if PLACE_IDENTITY_RE.search(q):
            continue  # place labels are handled by the one-time place card
        out.append(c)
    return out


def prepare_places(session: Session, day: date) -> None:
    """Learn home/work from the last two weeks and cache OSM tiles for the places visited that day."""
    try:
        places.auto_detect(session)
    except Exception:  # noqa: BLE001
        log.exception("place auto-detect failed")
    if not poi.enabled():
        return
    try:
        ctx = build_day_context(session, day)
        pts = [(v["lat"], v["lon"]) for v in ctx.places if v.get("lat") is not None and not v.get("label")]
        if pts:
            poi.ensure_tiles(session, pts)
    except Exception:  # noqa: BLE001
        log.exception("poi tile fetch failed")


def infer_day(session: Session, day: date, force: bool = False) -> DaySummary:
    existing = session.exec(select(DaySummary).where(DaySummary.date == day.isoformat())).first()
    if existing and existing.status == "reviewed" and not force:
        return existing

    prepare_places(session, day)
    ctx = build_day_context(session, day)
    history = previous_answers(session, day)
    backend_used = "rules"
    try:
        data, backend_used = complete_json(
            prompts.DAY_SYSTEM,
            prompts.DAY_USER_TEMPLATE.format(
                context=ctx.to_text(),
                history="\n".join(f"- {h['date']} {h['question']} → {h['answer']}" + (f" ({h['note']})" if h.get("note") else "") for h in history) or "(なし)",
            ),
            DAY_INFERENCE_SCHEMA,
        )
    except InferenceError as exc:
        if settings.inference_backend != "rules":
            log.warning("falling back to rules: %s", exc)
        data = rules.infer_day(ctx, history)

    cards_out = _drop_unwanted(list(data.get("cards", [])))
    try:
        cards_out = places.place_cards(session, ctx.places, places.load_places(session)) + cards_out
    except Exception:  # noqa: BLE001
        log.exception("place cards failed")
    data["cards"] = cards_out

    summary = existing or DaySummary(date=day.isoformat())
    summary.metrics = ctx.metrics
    summary.timeline = data.get("timeline", [])
    summary.summary_text = data.get("summary", "")
    summary.inference_backend = backend_used
    summary.generated_at = datetime.now(UTC)
    if summary.status != "reviewed":
        summary.status = "inferred"
    session.add(summary)

    # Replace unanswered cards; keep answered ones and don't ask the same thing twice.
    for old in session.exec(select(Card).where(Card.date == day.isoformat(), Card.answer.is_(None))):
        session.delete(old)
    answered = session.exec(select(Card).where(Card.date == day.isoformat(), Card.answer.is_not(None))).all()
    taken = {(a.kind, a.time_label or "") for a in answered}
    for c in data.get("cards", []):
        key = (c.get("kind", "custom"), c.get("time") or "")
        if key in taken:
            continue
        taken.add(key)
        options = [str(o) for o in c.get("options", ["はい", "いいえ"])]
        if c.get("kind") == "mood":
            options = ["1", "2", "3", "4", "5"]
        proposed = str(c.get("proposed") or options[0])
        if proposed not in options:
            options.append(proposed)
        evidence: dict[str, Any] = {"text": c.get("evidence", "")}
        if c.get("place"):
            evidence["place"] = c["place"]
        session.add(
            Card(
                date=day.isoformat(),
                kind=c.get("kind", "custom"),
                question=c["question"],
                options=options,
                proposed=proposed,
                evidence=evidence,
                confidence=float(c.get("confidence", 0.5)),
                time_label=c.get("time") or None,
            )
        )
    session.commit()
    session.refresh(summary)
    return summary


def _daily_rows(session: Session, start: date, end: date) -> list[dict[str, Any]]:
    days = session.exec(select(DaySummary).where(DaySummary.date >= start.isoformat(), DaySummary.date <= end.isoformat())).all()
    by_date = {d.date: d for d in days}
    cards = session.exec(select(Card).where(Card.date >= start.isoformat(), Card.date <= end.isoformat(), Card.answer.is_not(None))).all()
    answers_by_date: dict[str, list[Card]] = {}
    for c in cards:
        answers_by_date.setdefault(c.date, []).append(c)

    rows: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        d = by_date.get(key)
        nxt = by_date.get((cur + timedelta(days=1)).isoformat())
        row: dict[str, Any] = {"date": key}
        if d:
            row.update(
                {
                    k: d.metrics.get(k)
                    for k in (
                        "sleep_hours",
                        "hrv_avg",
                        "resting_hr",
                        "steps",
                        "exercise_minutes",
                        "meeting_count",
                        "meeting_minutes",
                        "screen_minutes",
                        "late_night_screen_minutes",
                    )
                }
            )
            row["condition"] = d.overall_condition
        if nxt:
            row["next_sleep_hours"] = nxt.metrics.get("sleep_hours")
            row["next_hrv_avg"] = nxt.metrics.get("hrv_avg")
            row["next_condition"] = nxt.overall_condition
        for c in answers_by_date.get(key, []):
            if c.kind == "stress":
                row["stress"] = c.answer
            if c.kind == "exercise" and c.answer:
                row["exercise_confirmed"] = c.answer
        rows.append(row)
        cur += timedelta(days=1)
    return rows


def generate_insights(session: Session, end: date | None = None, days: int = 28) -> list[Insight]:
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    rows = _daily_rows(session, start, end)
    cards = session.exec(select(Card).where(Card.date >= start.isoformat(), Card.date <= end.isoformat(), Card.answer.is_not(None))).all()
    answers = [{"date": c.date, "kind": c.kind, "q": c.question, "a": c.answer, "note": c.note} for c in cards]

    try:
        data, _ = complete_json(
            prompts.INSIGHT_SYSTEM,
            prompts.INSIGHT_USER_TEMPLATE.format(
                start=start.isoformat(),
                end=end.isoformat(),
                rows="\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                answers="\n".join(f"- {a['date']} [{a['kind']}] {a['q']} → {a['a']}" + (f" ({a['note']})" if a.get("note") else "") for a in answers)
                or "(なし)",
            ),
            INSIGHT_SCHEMA,
        )
    except InferenceError:
        data = rules.infer_insights(rows, answers)

    for old in session.exec(select(Insight).where(Insight.period_start == start.isoformat(), Insight.period_end == end.isoformat())):
        session.delete(old)
    out: list[Insight] = []
    for i in data.get("insights", []):
        row = Insight(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            statement=i["statement"],
            evidence={"text": i.get("evidence", "")},
            confidence=float(i.get("confidence", 0.5)),
            n_samples=int(i.get("n_samples", 0)),
        )
        session.add(row)
        out.append(row)
    session.commit()
    return out
