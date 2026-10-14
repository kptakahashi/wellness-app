from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..core.auth import require_token
from ..core.config import settings
from ..core.db import get_session, session_scope
from ..core.models import Card, DaySummary, Insight, RawEvent, Setting
from ..core.timeutil import now_local
from ..inference.engine import generate_insights, infer_day
from ..services import places as places_svc
from ..services import poi as poi_svc
from ..services.calendar_sync import sync_calendars
from ..services.daycontext import build_day_context
from ..services.ingest import BatchIn, ingest_batch
from ..services.jobs import run_evening, run_weekly
from ..services.retention import delete_everything, purge_raw_events
from ..services.snapshot import export_data, import_data
from ..services.usage import collect_day_events, usage_metrics

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# ------------------------------------------------------------------ ingest
@router.post("/ingest")
def ingest(batch: BatchIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    res = ingest_batch(session, batch)
    return {"ok": True, **res}


class VoiceNoteIn(BaseModel):
    text: str
    at: datetime | None = None


@router.post("/notes")
def add_note(note: VoiceNoteIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Morning voice memo or any one-liner. Transcription happens on the phone (keyboard mic)."""
    at = note.at or now_local()
    from ..services.ingest import EventIn

    res = ingest_batch(
        session,
        BatchIn(device_id="web", events=[EventIn(source="voice", kind="voice_note", start=at.isoformat(), payload={"text": note.text})]),
    )
    return {"ok": True, **res}


@router.post("/calendar/sync")
def calendar_sync(session: Session = Depends(get_session)) -> dict[str, Any]:
    from ..core.config import settings as _settings

    if not _settings.calendar_ics_urls.strip():
        return {"ok": False, "error": "CALENDAR_ICS_URLS is not set"}
    try:
        return {"ok": True, **sync_calendars(session)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict[str, Any]:
    today = now_local().date().isoformat()
    counts: dict[str, int] = {}
    for kind in session.exec(select(RawEvent.kind).distinct()):
        counts[kind] = len(session.exec(select(RawEvent.id).where(RawEvent.kind == kind)).all())
    last = session.exec(select(RawEvent.created_at).order_by(RawEvent.created_at.desc()).limit(1)).first()
    pending = len(session.exec(select(Card.id).where(Card.date == today, Card.answer.is_(None))).all())
    return {"today": today, "event_counts": counts, "last_ingest_utc": last, "pending_cards_today": pending}


@router.get("/events")
def list_events(day: str, kind: str | None = None, limit: int = 200, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Raw events for one local day (debugging what a device actually wrote)."""
    from ..core.timeutil import day_bounds

    d = _day_or_400(day)
    start, end = day_bounds(d)
    stmt = select(RawEvent).where(RawEvent.start_ts >= start - timedelta(hours=12), RawEvent.start_ts < end).order_by(RawEvent.start_ts)
    if kind:
        stmt = stmt.where(RawEvent.kind == kind)
    rows = session.exec(stmt.limit(limit)).all()
    return [{"id": r.id, "source": r.source, "kind": r.kind, "start": r.start_ts, "end": r.end_ts, "payload": r.payload} for r in rows]


# ------------------------------------------------------------------ days
def _day_or_400(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "date must be YYYY-MM-DD") from exc


@router.get("/days")
def list_days(limit: int = 31, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(DaySummary).order_by(DaySummary.date.desc()).limit(limit)).all()
    return [{"date": d.date, "status": d.status, "metrics": d.metrics, "summary": d.summary_text, "condition": d.overall_condition} for d in rows]


@router.get("/days/{day}")
def get_day(day: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    d = _day_or_400(day)
    summary = session.exec(select(DaySummary).where(DaySummary.date == d.isoformat())).first()
    cards = session.exec(select(Card).where(Card.date == d.isoformat()).order_by(Card.id)).all()
    ctx = build_day_context(session, d)
    return {
        "date": d.isoformat(),
        "status": summary.status if summary else "collected",
        "summary": summary.summary_text if summary else "",
        "timeline": summary.timeline if summary else [],
        "metrics": summary.metrics if summary else ctx.metrics,
        "backend": summary.inference_backend if summary else "",
        "condition": summary.overall_condition if summary else None,
        "context_text": ctx.to_text(),
        "cards": [c.model_dump() for c in cards],
    }


@router.post("/days/{day}/infer")
def post_infer(day: str, force: bool = False, session: Session = Depends(get_session)) -> dict[str, Any]:
    d = _day_or_400(day)
    summary = infer_day(session, d, force=force)
    cards = session.exec(select(Card).where(Card.date == d.isoformat())).all()
    return {"date": d.isoformat(), "status": summary.status, "backend": summary.inference_backend, "cards": len(cards)}


class ConditionIn(BaseModel):
    condition: int


@router.post("/days/{day}/condition")
def set_condition(day: str, body: ConditionIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    d = _day_or_400(day)
    summary = session.exec(select(DaySummary).where(DaySummary.date == d.isoformat())).first()
    if not summary:
        summary = DaySummary(date=d.isoformat())
    summary.overall_condition = max(1, min(5, body.condition))
    session.add(summary)
    session.commit()
    return {"ok": True}


@router.post("/days/{day}/complete")
def complete_review(day: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    d = _day_or_400(day)
    summary = session.exec(select(DaySummary).where(DaySummary.date == d.isoformat())).first()
    if not summary:
        raise HTTPException(404, "day not inferred yet")
    summary.status = "reviewed"
    summary.reviewed_at = datetime.now(UTC)
    session.add(summary)
    session.commit()
    return {"ok": True}


# ------------------------------------------------------------------ cards
class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=500)


@router.post("/cards/{card_id}/answer")
def answer_card(card_id: int, body: AnswerIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Answer is either one of the options or free text typed by the user (the web UI has a send button)."""
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(404, "card not found")
    answer = body.answer.strip()
    if not answer:
        raise HTTPException(400, "answer is empty")
    card.answer = answer
    card.note = (body.note or "").strip() or None
    card.answered_at = datetime.now(UTC)
    session.add(card)
    if card.kind == "mood" and answer.isdigit():
        summary = session.exec(select(DaySummary).where(DaySummary.date == card.date)).first()
        if summary:
            summary.overall_condition = max(1, min(5, int(answer)))
            session.add(summary)
    if card.kind == "place":
        # Remember the label so this place is never asked about again. "その他" with a note -> the note.
        spot = (card.evidence or {}).get("place") or {}
        label = card.note if answer == "その他" and card.note else answer
        if "lat" in spot and "lon" in spot:
            places_svc.upsert_place(session, float(spot["lat"]), float(spot["lon"]), label, source="user")
    session.commit()
    return {"ok": True}


# ------------------------------------------------------------------ insights
@router.get("/insights")
def list_insights(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(Insight).order_by(Insight.created_at.desc()).limit(20)).all()
    return [r.model_dump() for r in rows]


@router.post("/insights/generate")
def post_insights(days: int = 28, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = generate_insights(session, end=now_local().date(), days=days)
    return [r.model_dump() for r in rows]


# ------------------------------------------------------------------ jobs (for external cron on free hosting that sleeps)
def _run_evening_job() -> None:
    with session_scope() as s:
        run_evening(s)


@router.post("/jobs/evening", status_code=202)
def job_evening(background: BackgroundTasks, force: bool = False, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Prepare today's cards. Returns immediately (external cron services time out in ~30 s);
    the work runs in the background. Idempotent: a second call within 2 hours is a no-op."""
    today = now_local().date().isoformat()
    existing = session.exec(select(DaySummary).where(DaySummary.date == today)).first()
    if existing and existing.generated_at and not force:
        age = datetime.now(UTC) - existing.generated_at.replace(tzinfo=existing.generated_at.tzinfo or UTC)
        if age.total_seconds() < 2 * 3600:
            return {"ok": True, "status": "already_prepared", "generated_at": existing.generated_at}
    background.add_task(_run_evening_job)
    return {"ok": True, "status": "scheduled"}


@router.post("/jobs/weekly", status_code=202)
def job_weekly(background: BackgroundTasks) -> dict[str, Any]:
    def run() -> None:
        with session_scope() as s:
            run_weekly(s)

    background.add_task(run)
    return {"ok": True, "status": "scheduled"}


@router.post("/jobs/purge")
def job_purge(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Delete raw events past RAW_EVENT_RETENTION_DAYS now (the evening job does this too)."""
    keep = settings.raw_event_retention_days
    return {"ok": True, "keep_days": keep, "deleted": purge_raw_events(session, keep_days=keep)}


# ------------------------------------------------------------------ usage (the MVP's two numbers)
@router.get("/metrics/usage")
def get_usage(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Coverage (how much was captured automatically), accuracy (how answers went), continuity (streak)."""
    today = now_local().date()
    start = today - timedelta(days=27)
    cards = session.exec(select(Card).where(Card.date >= start.isoformat(), Card.date <= today.isoformat())).all()
    return usage_metrics(cards, today, days=collect_day_events(session, start, today))


# ------------------------------------------------------------------ my data: export, restore, delete
@router.get("/data/export")
def data_export(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Everything, unchanged, as one JSON document. Save it; `POST /data/import` puts it back."""
    return export_data(session)


@router.post("/data/import")
def data_import(data: dict[str, Any], confirm: str = "", session: Session = Depends(get_session)) -> dict[str, Any]:
    """Replace the whole database with an export. Destructive, so it needs ?confirm=replace."""
    if confirm != "replace":
        raise HTTPException(400, "add ?confirm=replace to overwrite the current database")
    if not isinstance(data.get("raw_events"), list) or "anchor" not in data:
        raise HTTPException(400, "not an export produced by /api/data/export")
    return {"ok": True, **import_data(session, data)}


@router.delete("/data")
def data_delete(confirm: str = "", session: Session = Depends(get_session)) -> dict[str, Any]:
    """Delete every row of personal data. Needs ?confirm=delete-everything."""
    if confirm != "delete-everything":
        raise HTTPException(400, "add ?confirm=delete-everything to delete all data")
    return {"ok": True, "deleted": delete_everything(session)}


# ------------------------------------------------------------------ places
@router.get("/settings/places")
def get_places(session: Session = Depends(get_session)) -> dict[str, Any]:
    return {
        "items": places_svc.load_places(session),
        "poi_tiles": poi_svc.tiles_status(session),
        "poi_source": "osm" if poi_svc.enabled() else "none",
    }


class PlaceIn(BaseModel):
    lat: float
    lon: float
    label: str = Field(min_length=1, max_length=40)
    radius_m: int = Field(default=places_svc.DEFAULT_RADIUS_M, ge=30, le=1000)


@router.put("/settings/places")
def put_place(body: PlaceIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    return {"items": places_svc.upsert_place(session, body.lat, body.lon, body.label, source="user", radius_m=body.radius_m)}


@router.delete("/settings/places")
def delete_place(lat: float, lon: float, session: Session = Depends(get_session)) -> dict[str, Any]:
    items = [p for p in places_svc.load_places(session) if places_svc.dist_m(lat, lon, float(p["lat"]), float(p["lon"])) > 30]
    places_svc.save_places(session, items)
    return {"items": items}


@router.post("/settings/places/detect")
def detect_places(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Re-run home/work detection from the last two weeks of location samples."""
    return {"detected": places_svc.auto_detect(session), "items": places_svc.load_places(session)}


# ------------------------------------------------------------------ settings
@router.get("/settings/routines")
def get_routines(session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(Setting, "routines")
    return row.value if row else {}


@router.put("/settings/routines")
def put_routines(value: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(Setting, "routines") or Setting(key="routines")
    row.value = value
    session.add(row)
    session.commit()
    return row.value
