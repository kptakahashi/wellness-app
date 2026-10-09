"""Export / import a whole database as JSON, shifting dates so the last day becomes 'today'.

Used for the public demo: we run the real Claude inference once on the synthetic world, commit the
result as `backend/demo/snapshot.json`, and every demo boot replays it anchored to the current date.
No LLM calls, no API cost, but the cards still read like Claude wrote them.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..core.models import Card, DaySummary, Insight, RawEvent, Setting

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "demo" / "snapshot.json"


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def export_snapshot(session: Session, path: Path = SNAPSHOT_PATH) -> int:
    anchor = max((d.date for d in session.exec(select(DaySummary))), default=date.today().isoformat())
    data = {
        "anchor": anchor,
        "settings": {s.key: s.value for s in session.exec(select(Setting))},
        "raw_events": [
            {"source": e.source, "kind": e.kind, "start_ts": e.start_ts.isoformat(), "end_ts": e.end_ts.isoformat() if e.end_ts else None,
             "payload": e.payload, "device_id": e.device_id, "dedupe_key": e.dedupe_key}
            for e in session.exec(select(RawEvent))
        ],
        "day_summaries": [
            {"date": d.date, "status": d.status, "metrics": d.metrics, "timeline": d.timeline, "summary_text": d.summary_text,
             "inference_backend": d.inference_backend, "overall_condition": d.overall_condition}
            for d in session.exec(select(DaySummary))
        ],
        "cards": [
            {"date": c.date, "kind": c.kind, "question": c.question, "options": c.options, "proposed": c.proposed, "evidence": c.evidence,
             "confidence": c.confidence, "time_label": c.time_label, "answer": c.answer, "note": c.note}
            for c in session.exec(select(Card))
        ],
        "insights": [
            {"period_start": i.period_start, "period_end": i.period_end, "statement": i.statement, "evidence": i.evidence,
             "confidence": i.confidence, "n_samples": i.n_samples}
            for i in session.exec(select(Insight))
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(data["raw_events"])


def load_snapshot(session: Session, path: Path = SNAPSHOT_PATH, today: date | None = None) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    today = today or date.today()
    delta = today - date.fromisoformat(data["anchor"])
    shift_days = delta.days

    def sd(s: str) -> str:
        return (date.fromisoformat(s) + delta).isoformat()

    def sdt(v: Any) -> datetime | None:
        d = _dt(v)
        return d + timedelta(days=shift_days) if d else None

    for model in (Card, DaySummary, Insight, RawEvent):
        for row in session.exec(select(model)):
            session.delete(row)
    session.commit()

    for k, v in data.get("settings", {}).items():
        session.merge(Setting(key=k, value=v))
    now = datetime.now(timezone.utc)
    for e in data["raw_events"]:
        session.add(RawEvent(source=e["source"], kind=e["kind"], start_ts=sdt(e["start_ts"]), end_ts=sdt(e["end_ts"]), payload=e["payload"],
                             device_id=e.get("device_id"), dedupe_key=e["dedupe_key"], created_at=now))
    for d in data["day_summaries"]:
        is_today = sd(d["date"]) == today.isoformat()
        session.add(DaySummary(date=sd(d["date"]), status="inferred" if is_today else d["status"], metrics=d["metrics"], timeline=d["timeline"],
                               summary_text=d["summary_text"], inference_backend=d["inference_backend"],
                               overall_condition=None if is_today else d["overall_condition"], generated_at=now,
                               reviewed_at=None if is_today else now))
    for c in data["cards"]:
        is_today = sd(c["date"]) == today.isoformat()
        session.add(Card(date=sd(c["date"]), kind=c["kind"], question=c["question"], options=c["options"], proposed=c["proposed"],
                         evidence=c["evidence"], confidence=c["confidence"], time_label=c["time_label"],
                         answer=None if is_today else c["answer"], note=None if is_today else c.get("note"),
                         answered_at=None if is_today else now, created_at=now))
    for i in data["insights"]:
        session.add(Insight(period_start=sd(i["period_start"]), period_end=sd(i["period_end"]), statement=i["statement"], evidence=i["evidence"],
                            confidence=i["confidence"], n_samples=i["n_samples"], created_at=now))
    session.commit()
    return {"raw_events": len(data["raw_events"]), "days": len(data["day_summaries"]), "cards": len(data["cards"]), "insights": len(data["insights"]), "shift_days": shift_days}
