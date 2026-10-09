"""Generate ~3 weeks of realistic synthetic data so the product can be demoed without a phone.

Usage (from backend/):
    python scripts/seed_demo.py            # seed + infer every day with the configured backend
    python scripts/seed_demo.py --answer   # also auto-answer cards (accept the proposed option)

The synthetic world deliberately bakes in a few patterns so insights have something to find:
    * ramen/donburi lunch  -> afternoon HRV drops, "眠い" more likely
    * late-night phone use -> shorter sleep that night
    * gym days             -> better next-morning condition
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, session_scope  # noqa: E402
from app.core.models import Card, DaySummary, Insight, RawEvent, Setting  # noqa: E402
from app.core.timeutil import TZ, now_local  # noqa: E402
from app.inference.engine import generate_insights, infer_day  # noqa: E402
from app.services.ingest import BatchIn, EventIn, ingest_batch  # noqa: E402

random.seed(7)

LUNCH = [
    ("ラーメン二郎 新宿", 1000, "ramen"), ("日高屋 新宿西口", 880, "ramen"), ("松屋 新宿", 790, "donburi"),
    ("吉野家", 650, "donburi"), ("大戸屋ごはん処", 1150, "teishoku"), ("やよい軒", 980, "teishoku"),
    ("サブウェイ", 890, "light"), ("セブン-イレブン", 620, "light"), ("丸亀製麺", 720, "udon"),
]
BREAKFAST = [("セブン-イレブン", 480), ("ファミリーマート", 430), ("スターバックス", 650)]
DINNER = [("Uber Eats", 1800), ("ローソン", 760), ("サイゼリヤ", 1400), ("自炊", 0)]
IZAKAYA = [("鳥貴族 新宿東口", 11800, 4), ("土間土間", 15600, 5), ("串カツ田中", 9200, 3)]
APPS = [("YouTube", "com.google.android.youtube"), ("X", "com.twitter.android"), ("Slack", "com.Slack"), ("Chrome", "com.android.chrome"), ("LINE", "jp.naver.line.android"), ("原神", "com.miHoYo.GenshinImpact")]
MEETINGS = ["定例MTG", "1on1", "顧客打合せ", "企画レビュー", "部門会議", "採用面談", "週次報告"]


def ts(d: date, h: int, m: int = 0) -> str:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).isoformat()


def ev(source: str, kind: str, start: str, end: str | None = None, **payload) -> EventIn:
    return EventIn(source=source, kind=kind, start=start, end=end, payload=payload)


def make_day(d: date, prev_late_screen: int, gym_yesterday: bool) -> tuple[list[EventIn], int, bool]:
    events: list[EventIn] = []
    wd = d.weekday()
    weekend = wd >= 5

    # --- sleep (ends this morning). Shorter after late-night screen use.
    sleep_h = random.gauss(7.0, 0.5) - (0.9 if prev_late_screen >= 60 else 0) + (0.3 if gym_yesterday else 0)
    sleep_h = max(4.5, min(9.0, sleep_h))
    wake_h, wake_m = (7, random.randint(0, 40)) if not weekend else (8, random.randint(20, 59))
    wake = datetime(d.year, d.month, d.day, wake_h, wake_m, tzinfo=TZ)
    bed = wake - timedelta(hours=sleep_h)
    deep = int(sleep_h * 60 * random.uniform(0.15, 0.25))
    events.append(ev("health_connect", "sleep_session", bed.isoformat(), wake.isoformat(), deep_min=deep, rem_min=int(sleep_h * 60 * 0.22), light_min=int(sleep_h * 60 * 0.5), awake_min=random.randint(5, 30)))
    events.append(ev("health_connect", "resting_hr", ts(d, 4), bpm=random.randint(52, 60) + (3 if prev_late_screen >= 60 else 0)))
    base_hrv = random.gauss(48, 6) + (4 if gym_yesterday else 0) - (5 if prev_late_screen >= 60 else 0)
    for h in range(int(bed.hour), int(bed.hour) + 7):
        hh = h % 24
        day = d if hh < 12 else d - timedelta(days=1)
        events.append(ev("health_connect", "hrv", ts(day, hh, 30), rmssd_ms=round(max(15, random.gauss(base_hrv, 5)), 1)))

    # --- lunch & its effect
    lunch = random.choice(LUNCH)
    heavy = lunch[2] in ("ramen", "donburi")
    lunch_h, lunch_m = 12, random.randint(10, 50)
    if not weekend or random.random() < 0.6:
        events.append(ev("notification", "notification", ts(d, lunch_h, lunch_m), package="jp.ne.paypay.android.app", app_label="PayPay", title=f"{lunch[0]}", text=f"{lunch[1]:,}円のお支払いが完了しました"))

    # --- breakfast
    if random.random() < 0.8:
        b = random.choice(BREAKFAST)
        events.append(ev("notification", "notification", ts(d, wake_h + 1, random.randint(0, 30)), package="com.moneyforward.android.app", app_label="マネーフォワード ME", title="新着の入出金", text=f"{b[0]} {b[1]:,}円 (楽天カード)"))

    # --- dinner / izakaya with calendar
    izakaya = (wd in (2, 4)) and random.random() < 0.6
    if izakaya:
        name, amount, people = random.choice(IZAKAYA)
        events.append(ev("calendar", "calendar_event", ts(d, 19), ts(d, 21, 30), title="チーム飲み", location=name, attendee_count=people, all_day=False))
        events.append(ev("notification", "notification", ts(d, 21, random.randint(20, 50)), package="jp.ne.paypay.android.app", app_label="PayPay", title=name, text=f"{amount:,}円のお支払いが完了しました"))
        events.append(ev("location", "place_visit", ts(d, 19, 5), ts(d, 21, 40), name=name, lat=35.6938, lon=139.7034))
    else:
        dn = random.choice(DINNER)
        if dn[1]:
            events.append(ev("notification", "notification", ts(d, 19, random.randint(0, 59)), package="com.moneyforward.android.app", app_label="マネーフォワード ME", title="新着の入出金", text=f"{dn[0]} {dn[1]:,}円 (楽天カード)"))

    # --- calendar meetings (weekday)
    n_meet = 0
    if not weekend:
        n_meet = random.choice([1, 2, 3, 4, 5, 6])
        hours = random.sample([9, 10, 11, 13, 14, 15, 16, 17], n_meet)
        for h in sorted(hours):
            events.append(ev("calendar", "calendar_event", ts(d, h), ts(d, h, 50), title=random.choice(MEETINGS), location="", attendee_count=random.randint(0, 6), all_day=False))
        events.append(ev("location", "place_visit", ts(d, 9, 20), ts(d, 18, 30), name="オフィス", lat=35.6895, lon=139.6917))

    # --- exercise: Mon/Wed/Fri evening gym, sometimes skipped
    gym = wd in (0, 2, 4) and random.random() < 0.75 and not izakaya
    if gym:
        events.append(ev("calendar", "calendar_event", ts(d, 18, 30), ts(d, 19, 30), title="ジム", location="エニタイムフィットネス", attendee_count=0, all_day=False))
        events.append(ev("location", "place_visit", ts(d, 18, 35), ts(d, 19, 40), name="エニタイムフィットネス 新宿", lat=35.69, lon=139.70))
        if random.random() < 0.6:
            events.append(ev("health_connect", "exercise", ts(d, 18, 40), ts(d, 19, 30), type="筋力トレーニング"))

    # --- heart rate every 30 min
    for h in range(0, 24):
        for m in (0, 30):
            t = h + m / 60
            if bed.hour <= 23 and (t < wake.hour or t >= bed.hour) or (bed.hour < 6 and t < wake.hour):
                bpm = random.randint(50, 62)
            elif gym and 18.6 <= t <= 19.5:
                bpm = random.randint(120, 150)
            elif 9 <= t <= 18 and not weekend:
                bpm = random.randint(68, 84) + (6 if n_meet >= 4 else 0)
            else:
                bpm = random.randint(62, 78)
            if heavy and 13.5 <= t <= 15.5:
                bpm += 6
            events.append(ev("health_connect", "heart_rate", ts(d, h, m), bpm=bpm))
    # afternoon HRV dip after heavy lunch
    for h in (14, 15, 16):
        v = base_hrv - (10 if heavy else 2) + random.gauss(0, 3)
        events.append(ev("health_connect", "hrv", ts(d, h, 15), rmssd_ms=round(max(15, v), 1)))

    # --- steps
    for h in range(7, 23):
        c = random.randint(100, 900) if not weekend else random.randint(50, 600)
        if gym and h in (18, 19):
            c += 1500
        events.append(ev("health_connect", "steps", ts(d, h), ts(d, h, 59), count=c))

    # --- app usage; late-night binge some nights
    late_screen = 0
    for label, pkg in APPS:
        if label == "原神" and random.random() < 0.6:
            continue
        for _ in range(random.randint(2, 6)):
            h = random.choice([8, 12, 13, 18, 20, 21, 22])
            mins = random.randint(3, 25)
            events.append(ev("usage", "app_usage", ts(d, h, random.randint(0, 30)), ts(d, h, min(59, random.randint(0, 30) + mins)), package=pkg, app_label=label))
    if random.random() < 0.35:
        late_screen = random.randint(45, 110)
        label, pkg = random.choice([APPS[0], APPS[1], APPS[5]])
        remaining = late_screen
        h = 23
        while remaining > 0:
            chunk = min(55, remaining)
            events.append(ev("usage", "app_usage", ts(d, h, 2), ts(d, h, 2 + chunk), package=pkg, app_label=label))
            remaining -= chunk
            h = 0 if h == 23 else h + 1

    # --- morning voice note (sometimes)
    if random.random() < 0.5:
        text = random.choice(["わりとすっきり", "頭が重い", "まあ普通", "ちょっと眠い", "体が軽い"]) if sleep_h >= 6.5 else random.choice(["眠い", "頭が重い", "だるい"])
        events.append(ev("voice", "voice_note", ts(d, wake_h, wake_m + 5 if wake_m < 55 else 59), text=text))

    return events, late_screen, gym


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--answer", action="store_true", help="auto-answer cards with the proposed option")
    ap.add_argument("--reset", action="store_true", help="wipe existing data first")
    ap.add_argument("--export", metavar="PATH", help="after seeding, export everything as a date-shiftable JSON snapshot")
    args = ap.parse_args()

    init_db()
    with session_scope() as s:
        if args.reset:
            for model in (Card, DaySummary, Insight, RawEvent):
                for row in s.query(model).all():  # type: ignore[attr-defined]
                    s.delete(row)
            s.commit()
        s.merge(Setting(key="routines", value={"exercise": "月水金 18:30 ジムで筋トレ50分", "breakfast": "コンビニのおにぎりとコーヒー"}))
        s.commit()

        today = now_local().date()  # local calendar day, not the server's UTC day
        start = today - timedelta(days=args.days - 1)
        late, gym = 0, False
        for i in range(args.days):
            d = start + timedelta(days=i)
            events, late, gym = make_day(d, late, gym)
            res = ingest_batch(s, BatchIn(device_id="demo", events=events))
            print(f"{d} ingested {res['inserted']} (skipped {res['skipped']})")

        for i in range(args.days):
            d = start + timedelta(days=i)
            summary = infer_day(s, d, force=True)
            cards = s.query(Card).filter(Card.date == d.isoformat()).all()  # type: ignore[attr-defined]
            print(f"{d} inferred via {summary.inference_backend}: {len(cards)} cards")
            if args.answer and d < today:
                for c in cards:
                    c.answer = c.proposed
                    c.answered_at = datetime.now(timezone.utc)
                    s.add(c)
                    if c.kind == "mood" and c.answer and c.answer.isdigit():
                        summary.overall_condition = int(c.answer)
                summary.status = "reviewed"
                s.add(summary)
                s.commit()

        if args.answer:
            ins = generate_insights(s, end=today, days=args.days)
            print(f"insights: {len(ins)}")
            for i in ins:
                print(" -", i.statement)

        if args.export:
            from app.services.snapshot import export_snapshot

            n = export_snapshot(s, Path(args.export))
            print(f"exported {n} raw events to {args.export}")


if __name__ == "__main__":
    main()
