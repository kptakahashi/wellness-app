from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.usage import DayEvents, classify_answer, day_coverage, usage_metrics


@dataclass
class C:
    date: str
    answer: str | None
    proposed: str | None = "はい"
    kind: str = "custom"
    time_label: str | None = None
    options: list[str] = field(default_factory=lambda: ["はい", "いいえ"])


TODAY = date(2026, 10, 14)  # a Wednesday


def _night(d: date, answers: list[str]) -> list[C]:
    return [C(d.isoformat(), a) for a in answers]


# ------------------------------------------------------------------ continuity
def test_empty():
    m = usage_metrics([], TODAY)
    assert m["streak_nights"] == 0
    assert m["nights_last_7"] == 0
    assert m["last_answered"] is None
    assert len(m["weeks"]) == 4
    assert len(m["days"]) == 7 and m["days"][-1]["date"] == TODAY.isoformat()


def test_streak_counts_consecutive_nights_ending_today():
    cards = []
    for i in range(3):
        cards += _night(TODAY - timedelta(days=i), ["はい"])
    cards += _night(TODAY - timedelta(days=5), ["はい"])  # gap on day 4 breaks it
    m = usage_metrics(cards, TODAY)
    assert m["streak_nights"] == 3
    assert m["nights_last_7"] == 4
    assert m["last_answered"] == TODAY.isoformat()


def test_streak_survives_when_tonight_is_not_answered_yet():
    cards = _night(TODAY - timedelta(days=1), ["はい"]) + _night(TODAY - timedelta(days=2), ["はい"])
    assert usage_metrics(cards, TODAY)["streak_nights"] == 2


def test_unanswered_cards_do_not_count():
    assert usage_metrics([C(TODAY.isoformat(), None)], TODAY)["streak_nights"] == 0


# ------------------------------------------------------------------ accuracy
def test_classify_answer():
    assert classify_answer(C("2026-10-14", "はい")) == "accepted"
    assert classify_answer(C("2026-10-14", "いいえ")) == "corrected"
    assert classify_answer(C("2026-10-14", "カレーうどん")) == "free_text"
    assert classify_answer(C("2026-10-14", None)) is None


def test_weekly_answer_breakdown():
    monday = TODAY - timedelta(days=TODAY.weekday())
    cards = [
        C(monday.isoformat(), "はい"),
        C(monday.isoformat(), "いいえ"),
        C(monday.isoformat(), "持ち帰りの弁当"),
        C((monday + timedelta(days=1)).isoformat(), "はい"),
    ]
    w = usage_metrics(cards, TODAY)["weeks"][-1]
    assert w["week_start"] == monday.isoformat()
    assert (w["nights_answered"], w["cards_answered"]) == (2, 4)
    assert (w["accepted"], w["corrected"], w["free_text"]) == (2, 1, 1)


# ------------------------------------------------------------------ coverage
def _full_day(d: date) -> DayEvents:
    return DayEvents(
        date=d,
        kinds={"sleep_session", "heart_rate", "steps", "payment", "place_visit", "calendar_event", "app_usage"},
        spans=[("calendar_event", 9.0, 12.0), ("payment", 12.4, 12.65), ("place_visit", 13.0, 18.0), ("payment", 19.0, 19.25)],
    )


def test_day_coverage_sources_meals_and_gaps():
    d = TODAY
    cards = [
        C(d.isoformat(), "はい", kind="meal", time_label="12:25"),
        C(d.isoformat(), "焼きそば", kind="meal", time_label="19:00"),  # free text: estimate missed
        C(d.isoformat(), "3", kind="mood", proposed="3", options=["1", "2", "3", "4", "5"]),
    ]
    cov = day_coverage(_full_day(d), cards)
    assert cov["sources"] == ["calendar", "heart", "payment", "place", "screen", "sleep", "steps"]
    assert cov["meal_slots"] == 2  # lunch + dinner, no breakfast evidence
    assert cov["meals_free_text"] == 1
    # waking hours 08-22: covered 09-12, 12, 13-17, 19 -> 8,18,20,21,22 are empty
    assert cov["gap_hours"] == 5


def test_day_coverage_without_data():
    cov = day_coverage(None, [])
    assert cov == {"sources": [], "meal_slots": 0, "meals_free_text": 0, "gap_hours": None}
    assert day_coverage(DayEvents(date=TODAY), [])["gap_hours"] is None


def test_weekly_coverage_aggregates_only_days_with_data():
    monday = TODAY - timedelta(days=TODAY.weekday())
    days = {monday: _full_day(monday), monday + timedelta(days=1): DayEvents(date=monday + timedelta(days=1), kinds={"heart_rate"})}
    cards = [C(monday.isoformat(), "はい", kind="meal", time_label="12:25")]
    w = usage_metrics(cards, TODAY, days=days)["weeks"][-1]
    assert w["days_with_data"] == 2
    assert w["sources_avg"] == 4.0  # (7 + 1) / 2
    assert (w["meal_slots_captured"], w["meal_slots_total"]) == (1, 6)
    assert w["gap_hours_avg"] == 10.0  # (5 + 15) / 2
    today_row = usage_metrics(cards, TODAY, days=days)["days"][-1]
    assert today_row["date"] == TODAY.isoformat() and today_row["sources"] == []
