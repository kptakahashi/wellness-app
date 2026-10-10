"""Turn collector payloads into RawEvents.

The Android collector posts batches shaped like:
    {"device_id": "...", "events": [{"source": "...", "kind": "...", "start": ..., "end": ..., "payload": {...}}]}
Every event gets a dedupe key so re-sending the same window is harmless.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..core.models import RawEvent
from ..core.timeutil import parse_ts

PAYMENT_HINTS = ("円", "¥", "￥", "ご利用", "お支払い", "支払い", "決済", "利用金額", "paid", "payment")


class EventIn(BaseModel):
    source: str
    kind: str
    start: str | int | float | datetime
    end: str | int | float | datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = None


class BatchIn(BaseModel):
    device_id: str | None = None
    events: list[EventIn]


def _dedupe_key(ev: EventIn, start: datetime, end: datetime | None) -> str:
    if ev.dedupe_key:
        return f"{ev.source}:{ev.kind}:{ev.dedupe_key}"
    stable = {k: v for k, v in ev.payload.items() if k not in {"synced_at"}}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha1(f"{ev.source}|{ev.kind}|{start.isoformat()}|{end}|{blob}".encode()).hexdigest()[:16]
    return f"{ev.source}:{ev.kind}:{start.isoformat()}:{h}"


def classify_notification(payload: dict[str, Any]) -> str:
    """A notification becomes a `payment` event when it looks like one."""
    text = " ".join(str(payload.get(k, "")) for k in ("title", "text", "big_text", "package"))
    low = text.lower()
    if any(h.lower() in low for h in PAYMENT_HINTS):
        return "payment"
    return "notification"


def ingest_batch(session: Session, batch: BatchIn) -> dict[str, int]:
    """Bulk insert: one SELECT for existing keys, one COMMIT. Falls back to per-row on conflicts."""
    rows: list[RawEvent] = []
    seen: set[str] = set()
    for ev in batch.events:
        start = parse_ts(ev.start)
        end = parse_ts(ev.end) if ev.end is not None else None
        kind = ev.kind
        if ev.source == "notification" and kind == "notification":
            kind = classify_notification(ev.payload)
        row = RawEvent(
            source=ev.source,
            kind=kind,
            start_ts=start,
            end_ts=end,
            payload=ev.payload,
            device_id=batch.device_id,
            dedupe_key=_dedupe_key(ev, start, end),
        )
        if row.dedupe_key in seen:
            continue
        seen.add(row.dedupe_key)
        rows.append(row)

    existing: set[str] = set()
    keys = [r.dedupe_key for r in rows]
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        existing.update(session.exec(select(RawEvent.dedupe_key).where(RawEvent.dedupe_key.in_(chunk))).all())

    new_rows = [r for r in rows if r.dedupe_key not in existing]
    skipped = len(rows) - len(new_rows)
    inserted = 0
    try:
        session.add_all(new_rows)
        session.commit()
        inserted = len(new_rows)
    except IntegrityError:
        session.rollback()
        for r in new_rows:
            session.add(r)
            try:
                session.commit()
                inserted += 1
            except IntegrityError:
                session.rollback()
                skipped += 1
    return {"inserted": inserted, "skipped": skipped}
