"""Database models.

Design: every collected datum becomes a `RawEvent` with a (source, kind, start, end, payload)
shape. Everything downstream (timeline, cards, insights) is derived from RawEvents, so adding a
new collector (a new ring, a watch, a different payment app) never changes the inference layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class RawEvent(SQLModel, table=True):
    __tablename__ = "raw_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_raw_events_dedupe"),)

    id: int | None = Field(default=None, primary_key=True)
    # health_connect | usage | notification | location | calendar | voice | manual | demo
    source: str = Field(index=True)
    # sleep_session | heart_rate | hrv | resting_hr | steps | exercise | spo2 |
    # app_usage | payment | notification | place_visit | calendar_event | voice_note
    kind: str = Field(index=True)
    start_ts: datetime = Field(index=True)
    end_ts: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    device_id: str | None = None
    dedupe_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DaySummary(SQLModel, table=True):
    __tablename__ = "day_summaries"

    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True, unique=True)  # YYYY-MM-DD local
    # collected -> inferred -> reviewed
    status: str = "collected"
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timeline: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    summary_text: str = ""
    inference_backend: str = ""
    generated_at: datetime | None = None
    reviewed_at: datetime | None = None
    overall_condition: int | None = None  # 1-5, answered in the evening review


class Card(SQLModel, table=True):
    __tablename__ = "cards"

    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True)
    # meal | exercise | stress | mood | sleep | custom
    kind: str
    question: str
    options: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    proposed: str | None = None  # the option the AI believes is right
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    confidence: float = 0.5
    time_label: str | None = None  # "12:30" etc, for display ordering
    answer: str | None = None
    note: str | None = None  # free text correction (optional)
    answered_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Insight(SQLModel, table=True):
    __tablename__ = "insights"

    id: int | None = Field(default=None, primary_key=True)
    period_start: str
    period_end: str
    statement: str
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    confidence: float = 0.5
    n_samples: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
