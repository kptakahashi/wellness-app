from datetime import date

from app.inference import rules
from app.services.daycontext import DayContext


def test_yen_parses_japanese_amounts():
    assert rules._yen("大戸屋ごはん処 1,150円 (楽天カード)") == 1150
    assert rules._yen("¥480 セブン-イレブン") == 480
    assert rules._yen("会議 14:00") is None


def test_store_name_prefers_specific_title_over_generic():
    assert rules._store_name({"title": "大戸屋", "text": "1,150円"}) == "大戸屋"
    assert rules._store_name({"title": "新着の入出金", "text": "大戸屋ごはん処 1,150円 (楽天カード)"}) == "大戸屋ごはん処"


def test_guess_food():
    assert rules.guess_food("日高屋 新宿") == "ラーメン・中華"
    assert rules.guess_food("ジム") is None


def _payment(time: str, title: str, text: str) -> dict:
    return {"kind": "payment", "time": time, "title": title, "text": text, "app": "PayPay"}


def test_infer_day_builds_meal_card_from_payment_and_ends_with_mood():
    ctx = DayContext(date=date(2026, 10, 14), payments=[_payment("12:25", "大戸屋", "大戸屋ごはん処 1,150円")])
    out = rules.infer_day(ctx, history=[])

    kinds = [c["kind"] for c in out["cards"]]
    assert kinds[0] == "meal"
    assert kinds[-1] == "mood"
    assert "定食" in out["cards"][0]["question"]
    assert out["cards"][0]["options"] == ["はい", "いいえ"]
    assert any(t["category"] == "meal" for t in out["timeline"])


def test_infer_day_never_asks_more_than_seven_cards():
    payments = [_payment(f"{h:02d}:10", f"店{h}", f"店{h} 800円") for h in range(6, 22)]
    ctx = DayContext(date=date(2026, 10, 14), payments=payments)
    assert len(rules.infer_day(ctx, history=[])["cards"]) <= 7


def test_infer_day_with_no_data_still_returns_mood_card():
    out = rules.infer_day(DayContext(date=date(2026, 10, 14)), history=[])
    assert [c["kind"] for c in out["cards"]] == ["mood"]
    assert out["summary"] == "収集データが少ない日。"


def test_infer_insights_needs_at_least_four_days_per_side():
    rows = [{"date": f"2026-10-{d:02d}", "exercise_minutes": 30 if d % 2 else 0, "hrv_avg": 60 if d % 2 else 40} for d in range(1, 9)]
    out = rules.infer_insights(rows, answers=[])
    assert out["insights"], "8 days split 4/4 with a 50% gap must yield a finding"
    assert "運動した" in out["insights"][0]["statement"]
    assert rules.infer_insights(rows[:5], answers=[])["insights"] == []
