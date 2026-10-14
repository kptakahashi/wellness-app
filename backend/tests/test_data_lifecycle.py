"""End to end over HTTP: ingest -> retention purge -> infer -> answer -> export -> delete -> restore.

This is the "can I get my data back out of a free-tier database" test, run once per commit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.core.models import Card, RawEvent
from app.core.timeutil import now_local


def _payment_event(at: datetime, text: str) -> dict:
    return {"source": "notification", "kind": "notification", "start": at.isoformat(), "payload": {"title": "PayPay", "text": text, "app": "PayPay"}}


def test_requires_token(client):
    assert client.get("/api/status", headers={"X-Api-Token": "wrong"}).status_code == 401


def test_full_lifecycle(client, session):
    today = now_local().date()
    noon = datetime.combine(today, datetime.min.time(), tzinfo=now_local().tzinfo).replace(hour=12, minute=25)
    old = noon - timedelta(days=100)

    # 1. ingest: one payment today, one 100 days ago
    res = client.post(
        "/api/ingest", json={"device_id": "test", "events": [_payment_event(noon, "大戸屋ごはん処 1,150円"), _payment_event(old, "古い店 500円")]}
    )
    assert res.json() == {"ok": True, "inserted": 2, "skipped": 0}
    assert client.post("/api/ingest", json={"device_id": "test", "events": [_payment_event(noon, "大戸屋ごはん処 1,150円")]}).json()["skipped"] == 1

    # 2. retention: the 100-day-old row goes, today's stays
    assert client.post("/api/jobs/purge").json() == {"ok": True, "keep_days": 90, "deleted": 1}
    kinds = session.exec(select(RawEvent.kind)).all()
    assert kinds == ["payment"]

    # 3. infer with the rules backend -> a meal card and a mood card
    res = client.post(f"/api/days/{today.isoformat()}/infer")
    assert res.json()["backend"] == "rules"
    day = client.get(f"/api/days/{today.isoformat()}").json()
    meal = next(c for c in day["cards"] if c["kind"] == "meal")
    assert "大戸屋" in meal["question"]

    # 4. answer with a correction (not the proposed option)
    assert client.post(f"/api/cards/{meal['id']}/answer", json={"answer": "いいえ", "note": "持ち帰り"}).json() == {"ok": True}
    usage = client.get("/api/metrics/usage").json()
    assert usage["streak_nights"] == 1
    week = usage["weeks"][-1]
    assert (week["accepted"], week["corrected"], week["free_text"]) == (0, 1, 0)
    assert week["days_with_data"] == 1 and week["meal_slots_captured"] == 1
    today_row = usage["days"][-1]
    assert today_row["sources"] == ["payment"] and today_row["gap_hours"] == 14  # only 12:25 has a signal

    # 5. export, delete everything, confirm it is gone
    export = client.get("/api/data/export").json()
    assert len(export["raw_events"]) == 1
    assert export["cards"] and any(c["answer"] == "いいえ" for c in export["cards"])
    assert client.delete("/api/data").status_code == 400
    deleted = client.delete("/api/data", params={"confirm": "delete-everything"}).json()["deleted"]
    assert deleted["raw_events"] == 1 and deleted["cards"] >= 2
    assert client.get("/api/status").json()["event_counts"] == {}

    # 6. restore from the export: same dates, same answers
    assert client.post("/api/data/import", json=export).status_code == 400
    restored = client.post("/api/data/import", params={"confirm": "replace"}, json=export).json()
    assert restored["raw_events"] == 1 and restored["shift_days"] == 0
    cards = session.exec(select(Card).where(Card.date == today.isoformat())).all()
    answered = [c for c in cards if c.answer]
    assert len(answered) == 1 and answered[0].answer == "いいえ" and answered[0].note == "持ち帰り"
    assert answered[0].answered_at is not None
    assert client.get("/api/metrics/usage").json()["streak_nights"] == 1


def test_purge_keeps_everything_when_disabled(session, monkeypatch):
    from app.core.config import settings
    from app.services.retention import purge_raw_events

    session.add(RawEvent(source="demo", kind="steps", start_ts=datetime.now(UTC) - timedelta(days=400), payload={"count": 1}, dedupe_key="k1"))
    session.commit()
    monkeypatch.setattr(settings, "raw_event_retention_days", 0)
    assert purge_raw_events(session, keep_days=settings.raw_event_retention_days) == 0
    assert purge_raw_events(session, keep_days=365) == 1
