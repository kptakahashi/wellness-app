"""Export / import the whole database as one JSON document.

Two uses:
- Backup and restore for the owner: `export_data` returns everything as-is; `import_data` puts it
  back unchanged. This is the way out of a free-tier database that may sleep, change or vanish.
- The public demo: `export_snapshot` / `load_snapshot` write and replay `backend/demo/snapshot.json`
  with dates shifted so the last day becomes "today" and today's cards are unanswered again.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..core.models import Card, DaySummary, Insight, RawEvent, Setting

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "demo" / "snapshot.json"
FORMAT_VERSION = 1


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def export_data(session: Session) -> dict[str, Any]:
    """Every row of personal data, as JSON-serialisable dicts. Map-tile caches are not included."""
    anchor = max((d.date for d in session.exec(select(DaySummary))), default=date.today().isoformat())
    return {
        "version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "anchor": anchor,
        "settings": {s.key: s.value for s in session.exec(select(Setting))},
        "raw_events": [
            {
                "source": e.source,
                "kind": e.kind,
                "start_ts": e.start_ts.isoformat(),
                "end_ts": e.end_ts.isoformat() if e.end_ts else None,
                "payload": e.payload,
                "device_id": e.device_id,
                "dedupe_key": e.dedupe_key,
            }
            for e in session.exec(select(RawEvent))
        ],
        "day_summaries": [
            {
                "date": d.date,
                "status": d.status,
                "metrics": d.metrics,
                "timeline": d.timeline,
                "summary_text": d.summary_text,
                "inference_backend": d.inference_backend,
                "overall_condition": d.overall_condition,
            }
            for d in session.exec(select(DaySummary))
        ],
        "cards": [
            {
                "date": c.date,
                "kind": c.kind,
                "question": c.question,
                "options": c.options,
                "proposed": c.proposed,
                "evidence": c.evidence,
                "confidence": c.confidence,
                "time_label": c.time_label,
                "answer": c.answer,
                "note": c.note,
                "answered_at": c.answered_at.isoformat() if c.answered_at else None,
            }
            for c in session.exec(select(Card))
        ],
        "insights": [
            {
                "period_start": i.period_start,
                "period_end": i.period_end,
                "statement": i.statement,
                "evidence": i.evidence,
                "confidence": i.confidence,
                "n_samples": i.n_samples,
            }
            for i in session.exec(select(Insight))
        ],
    }


def import_data(session: Session, data: dict[str, Any], *, today: date | None = None, demo: bool = False) -> dict[str, int]:
    """Replace the database with `data`.

    today=None keeps every date as exported (restore). With a date, all dates are shifted so the
    export's last day lands on `today`. demo=True additionally clears today's answers so the
    demo always has cards to answer.
    """
    delta = (today - date.fromisoformat(data["anchor"])) if today else timedelta(0)

    def sd(s: str) -> str:
        return (date.fromisoformat(s) + delta).isoformat()

    def sdt(v: Any) -> datetime | None:
        d = _dt(v)
        return d + delta if d else None

    for model in (Card, DaySummary, Insight, RawEvent):
        for row in session.exec(select(model)):
            session.delete(row)
    session.commit()

    for k, v in data.get("settings", {}).items():
        session.merge(Setting(key=k, value=v))
    now = datetime.now(UTC)
    today_iso = today.isoformat() if today else None
    for e in data["raw_events"]:
        session.add(
            RawEvent(
                source=e["source"],
                kind=e["kind"],
                start_ts=sdt(e["start_ts"]),
                end_ts=sdt(e["end_ts"]),
                payload=e["payload"],
                device_id=e.get("device_id"),
                dedupe_key=e["dedupe_key"],
                created_at=now,
            )
        )
    for d in data["day_summaries"]:
        reset = demo and sd(d["date"]) == today_iso
        session.add(
            DaySummary(
                date=sd(d["date"]),
                status="inferred" if reset else d["status"],
                metrics=d["metrics"],
                timeline=d["timeline"],
                summary_text=d["summary_text"],
                inference_backend=d["inference_backend"],
                overall_condition=None if reset else d["overall_condition"],
                generated_at=now,
                reviewed_at=None if reset or d["status"] != "reviewed" else now,
            )
        )
    for c in data["cards"]:
        reset = demo and sd(c["date"]) == today_iso
        answered_at = None if reset else (sdt(c.get("answered_at")) or (now if c.get("answer") else None))
        session.add(
            Card(
                date=sd(c["date"]),
                kind=c["kind"],
                question=c["question"],
                options=c["options"],
                proposed=c["proposed"],
                evidence=c["evidence"],
                confidence=c["confidence"],
                time_label=c["time_label"],
                answer=None if reset else c["answer"],
                note=None if reset else c.get("note"),
                answered_at=answered_at,
                created_at=now,
            )
        )
    for i in data["insights"]:
        session.add(
            Insight(
                period_start=sd(i["period_start"]),
                period_end=sd(i["period_end"]),
                statement=i["statement"],
                evidence=i["evidence"],
                confidence=i["confidence"],
                n_samples=i["n_samples"],
                created_at=now,
            )
        )
    session.commit()
    return {
        "raw_events": len(data["raw_events"]),
        "days": len(data["day_summaries"]),
        "cards": len(data["cards"]),
        "insights": len(data["insights"]),
        "shift_days": delta.days,
    }


# ---------------------------------------------------------------- demo snapshot
def export_snapshot(session: Session, path: Path = SNAPSHOT_PATH) -> int:
    data = export_data(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(data["raw_events"])


def load_snapshot(session: Session, path: Path = SNAPSHOT_PATH, today: date | None = None) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return import_data(session, data, today=today or date.today(), demo=True)
