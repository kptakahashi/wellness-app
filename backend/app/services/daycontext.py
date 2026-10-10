"""Build a compact, human/LLM-readable picture of one day from RawEvents.

This is the single input to inference. Keeping it as plain structured text means the same
context can be rendered in the UI, logged, and fed to Claude without transformation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

from sqlmodel import Session, select

from ..core.models import Card, RawEvent, Setting
from ..core.timeutil import day_bounds, fmt_hm, local_day_of, to_utc_naive

NOISE_PACKAGES = {"com.android.systemui", "com.google.android.apps.nexuslauncher", "android"}
KNOWN_APPS = {
    "com.twitter.android": "X", "com.google.android.youtube": "YouTube", "jp.naver.line.android": "LINE",
    "com.instagram.android": "Instagram", "com.zhiliaoapp.musically": "TikTok", "com.android.chrome": "Chrome",
    "com.Slack": "Slack", "com.google.android.gm": "Gmail", "com.facebook.katana": "Facebook",
    "com.google.android.apps.maps": "Google マップ", "jp.ne.paypay.android.app": "PayPay",
    "com.moneyforward.android.app": "マネーフォワード", "com.netflix.mediaclient": "Netflix",
    "com.amazon.mShop.android.shopping": "Amazon", "com.spotify.music": "Spotify",
    "com.google.android.apps.photos": "Google フォト", "com.reddit.frontpage": "Reddit", "com.discord": "Discord",
    "com.google.android.apps.docs": "Google ドライブ", "com.microsoft.teams": "Teams",
    "com.google.android.calendar": "Google カレンダー", "jp.co.yahoo.android.yjtop": "Yahoo!",
    "com.gdjztech.ringconn": "RingConn", "com.anthropic.claude": "Claude", "com.openai.chatgpt": "ChatGPT",
    "jp.mercari": "メルカリ", "com.google.android.apps.messaging": "メッセージ",
}


@dataclass
class DayContext:
    date: date
    metrics: dict[str, Any] = field(default_factory=dict)
    sleep: dict[str, Any] | None = None
    hr_series: list[tuple[str, int]] = field(default_factory=list)  # (HH:MM, bpm) sampled
    hrv_series: list[tuple[str, float]] = field(default_factory=list)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    calendar: list[dict[str, Any]] = field(default_factory=list)
    places: list[dict[str, Any]] = field(default_factory=list)
    app_usage: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    routines: dict[str, Any] = field(default_factory=dict)
    event_ids: list[int] = field(default_factory=list)

    def to_text(self) -> str:
        lines: list[str] = [f"日付: {self.date.isoformat()}"]
        if self.sleep:
            s = self.sleep
            lines.append(
                f"睡眠: {s.get('start')}〜{s.get('end')} 合計{s.get('hours', 0):.1f}h "
                f"(深い睡眠 {s.get('deep_min', '?')}分, REM {s.get('rem_min', '?')}分, 覚醒 {s.get('awake_min', '?')}分)"
            )
        m = self.metrics
        if m:
            parts = []
            if "resting_hr" in m:
                parts.append(f"安静時心拍 {m['resting_hr']}")
            if "hrv_avg" in m:
                parts.append(f"HRV平均 {m['hrv_avg']:.0f}ms")
            if "steps" in m:
                parts.append(f"歩数 {m['steps']}")
            if "spo2_avg" in m:
                parts.append(f"SpO2 {m['spo2_avg']:.0f}%")
            if parts:
                lines.append("指標: " + ", ".join(parts))
        if self.hr_series:
            lines.append("心拍の推移(30分ごと): " + ", ".join(f"{t} {bpm}" for t, bpm in self.hr_series))
        if self.hrv_series:
            lines.append("HRVの推移: " + ", ".join(f"{t} {v:.0f}" for t, v in self.hrv_series))
        if self.exercises:
            lines.append("運動(デバイス検出):")
            for e in self.exercises:
                lines.append(f"  - {e['start']}〜{e['end']} {e.get('type', '運動')} {e.get('minutes', '?')}分")
        if self.calendar:
            lines.append("カレンダー:")
            for c in self.calendar:
                extra = f" @{c['location']}" if c.get("location") else ""
                att = f" 参加者{c['attendee_count']}人" if c.get("attendee_count") else ""
                lines.append(f"  - {c['start']}〜{c['end']} {c['title']}{extra}{att}")
        if self.payments:
            lines.append("決済・通知:")
            for p in self.payments:
                lines.append(f"  - {p['time']} [{p.get('app', '')}] {p.get('title', '')} {p.get('text', '')}".rstrip())
        if self.places:
            lines.append("滞在場所:")
            for pl in self.places:
                lines.append(f"  - {pl['start']}〜{pl['end']} {pl.get('name') or pl.get('latlon')} ({pl.get('minutes')}分)")
        if self.app_usage:
            lines.append("スマホ利用(上位):")
            for a in self.app_usage:
                lines.append(f"  - {a['app']}: {a['minutes']}分 (主な時間帯 {a.get('peak_hours', '')})")
        if self.notes:
            lines.append("本人のメモ・音声:")
            for n in self.notes:
                lines.append(f"  - {n['time']} {n['text']}")
        if self.routines:
            lines.append("登録済みのいつもの習慣: " + "; ".join(f"{k}: {v}" for k, v in self.routines.items()))
        return "\n".join(lines)


def _events_for_day(session: Session, day: date) -> list[RawEvent]:
    start, end = day_bounds(day)
    # Sleep sessions that *end* on this day belong to it (went to bed the night before).
    stmt = select(RawEvent).where(
        ((RawEvent.start_ts >= start) & (RawEvent.start_ts < end))
        | ((RawEvent.kind == "sleep_session") & (RawEvent.end_ts >= start) & (RawEvent.end_ts < end))
    )
    return list(session.exec(stmt))


def get_routines(session: Session) -> dict[str, Any]:
    row = session.get(Setting, "routines")
    return row.value if row else {}


def summarize_sleep(rows: list[RawEvent], day: date) -> dict[str, Any] | None:
    """Merge a device's sleep records into one night.

    RingConn (and some other apps) write one record for the whole night *and* one record per
    5-minute stage segment, so naive "longest record" reporting loses the stages. We cluster
    records into nights (gap <= 60 min), drop records that merely contain others, and sum the
    leaf segments by stage. Sleep span = first to last non-awake leaf.
    """
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r.start_ts)
    nights: list[list[RawEvent]] = []
    for r in rows:
        if nights and (r.start_ts - max(x.end_ts or x.start_ts for x in nights[-1])).total_seconds() <= 3600:
            nights[-1].append(r)
        else:
            nights.append([r])

    def dur(r: RawEvent) -> float:
        return ((r.end_ts or r.start_ts) - r.start_ts).total_seconds()

    def stage_of(r: RawEvent) -> str:
        vals = {k: float(r.payload.get(k) or 0) for k in ("deep_min", "rem_min", "light_min", "awake_min")}
        return max(vals, key=vals.get) if any(vals.values()) else "light_min"

    best: dict[str, Any] | None = None
    for night in nights:
        leaves = [
            r for r in night
            if not any(
                o is not r and o.start_ts >= r.start_ts and (o.end_ts or o.start_ts) <= (r.end_ts or r.start_ts) and dur(o) < dur(r)
                for o in night
            )
        ]
        asleep = [r for r in leaves if stage_of(r) != "awake_min"]
        if not asleep:
            continue
        start = min(r.start_ts for r in asleep)
        end = max((r.end_ts or r.start_ts) for r in asleep)
        totals = {k: 0.0 for k in ("deep_min", "rem_min", "light_min", "awake_min")}
        for r in leaves:
            if r.start_ts < start or (r.end_ts or r.start_ts) > end:
                continue  # in-bed awake before/after the sleep itself
            totals[stage_of(r)] += dur(r) / 60
        hours = (end - start).total_seconds() / 3600 - totals["awake_min"] / 60
        cand = {
            "start": fmt_hm(start),
            "end": fmt_hm(end),
            "hours": round(hours, 2),
            "deep_min": round(totals["deep_min"]),
            "rem_min": round(totals["rem_min"]),
            "light_min": round(totals["light_min"]),
            "awake_min": round(totals["awake_min"]),
        }
        score = (local_day_of(end) == day, hours)  # prefer the night that ends on this day, then the longest
        if best is None or score > best["_score"]:
            best = {**cand, "_score": score}
    if best:
        best.pop("_score", None)
    return best


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import cos, radians, sqrt

    dx = (lon2 - lon1) * 111_320 * cos(radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110_540
    return sqrt(dx * dx + dy * dy)


def _cluster_visits(samples: list[tuple[datetime, float, float, str]], radius_m: float = 150, min_minutes: int = 10) -> list[dict[str, Any]]:
    """Consecutive samples within radius_m become one visit. Phone samples every ~15 min."""
    out: list[dict[str, Any]] = []
    cur: list[tuple[datetime, float, float, str]] = []
    for smp in sorted(samples):
        if cur and _dist_m(cur[0][1], cur[0][2], smp[1], smp[2]) > radius_m:
            out.append(cur)
            cur = []
        cur.append(smp)
    if cur:
        out.append(cur)
    visits: list[dict[str, Any]] = []
    for grp in out:
        minutes = (grp[-1][0] - grp[0][0]).total_seconds() / 60 + 15  # each sample stands for ~15 min
        if minutes < min_minutes:
            continue
        names = [g[3] for g in grp if g[3]]
        visits.append(
            {
                "start": fmt_hm(grp[0][0]),
                "end": fmt_hm(grp[-1][0]),
                "name": max(set(names), key=names.count) if names else None,
                "latlon": f"{grp[0][1]:.4f},{grp[0][2]:.4f}",
                "minutes": round(minutes),
            }
        )
    return visits


def build_day_context(session: Session, day: date) -> DayContext:
    ctx = DayContext(date=day, routines=get_routines(session))
    events = _events_for_day(session, day)
    ctx.event_ids = [e.id for e in events if e.id]

    hr_buckets: dict[str, list[int]] = defaultdict(list)
    hrv_buckets: dict[str, list[float]] = defaultdict(list)
    steps = 0
    spo2: list[float] = []
    resting: list[int] = []
    usage: dict[str, dict[str, Any]] = defaultdict(lambda: {"minutes": 0.0, "hours": defaultdict(float)})
    loc_samples: list[tuple[datetime, float, float, str]] = []
    sleep_rows: list[RawEvent] = []

    for e in events:
        p = e.payload
        if e.kind == "sleep_session":
            sleep_rows.append(e)
        elif e.kind == "heart_rate":
            bpm = int(p.get("bpm", 0))
            if bpm:
                local = fmt_hm(e.start_ts)
                h, m = local.split(":")
                hr_buckets[f"{h}:{'00' if int(m) < 30 else '30'}"].append(bpm)
        elif e.kind == "hrv":
            v = float(p.get("rmssd_ms", 0))
            if v:
                hrv_buckets[fmt_hm(e.start_ts)[:2] + ":00"].append(v)
        elif e.kind == "resting_hr":
            resting.append(int(p.get("bpm", 0)))
        elif e.kind == "steps":
            steps += int(p.get("count", 0))
        elif e.kind == "spo2":
            spo2.append(float(p.get("percent", 0)))
        elif e.kind == "exercise":
            minutes = ((e.end_ts or e.start_ts) - e.start_ts).total_seconds() / 60
            ctx.exercises.append(
                {"start": fmt_hm(e.start_ts), "end": fmt_hm(e.end_ts), "type": p.get("type", "運動"), "minutes": round(minutes)}
            )
        elif e.kind in ("payment", "notification"):
            ctx.payments.append(
                {
                    "time": fmt_hm(e.start_ts),
                    "app": p.get("app_label") or p.get("package", ""),
                    "title": p.get("title", ""),
                    "text": (p.get("text") or p.get("big_text") or "")[:160],
                    "kind": e.kind,
                }
            )
        elif e.kind == "calendar_event":
            if p.get("all_day"):
                continue
            ctx.calendar.append(
                {
                    "start": fmt_hm(e.start_ts),
                    "end": fmt_hm(e.end_ts),
                    "title": p.get("title", ""),
                    "location": p.get("location", ""),
                    "attendee_count": p.get("attendee_count", 0),
                }
            )
        elif e.kind == "place_visit":
            minutes = ((e.end_ts or e.start_ts) - e.start_ts).total_seconds() / 60
            if minutes < 10:
                continue
            ctx.places.append(
                {
                    "start": fmt_hm(e.start_ts),
                    "end": fmt_hm(e.end_ts),
                    "name": p.get("name"),
                    "latlon": f"{p.get('lat', 0):.4f},{p.get('lon', 0):.4f}",
                    "minutes": round(minutes),
                }
            )
        elif e.kind == "location_sample":
            loc_samples.append((e.start_ts, float(p.get("lat", 0)), float(p.get("lon", 0)), str(p.get("address") or "")))
        elif e.kind == "app_usage":
            pkg = p.get("package", "")
            if pkg in NOISE_PACKAGES:
                continue
            label = p.get("app_label") or pkg
            if label == pkg or label.startswith(("com.", "jp.", "org.")):
                label = KNOWN_APPS.get(pkg, pkg.rsplit(".", 1)[-1].capitalize())
            minutes = ((e.end_ts or e.start_ts) - e.start_ts).total_seconds() / 60
            usage[label]["minutes"] += minutes
            usage[label]["hours"][fmt_hm(e.start_ts)[:2]] += minutes
        elif e.kind == "voice_note":
            ctx.notes.append({"time": fmt_hm(e.start_ts), "text": p.get("text", "")})

    ctx.sleep = summarize_sleep(sleep_rows, day)
    ctx.places.extend(_cluster_visits(loc_samples))
    ctx.places.sort(key=lambda x: x["start"])
    ctx.hr_series = [(k, round(mean(v))) for k, v in sorted(hr_buckets.items())]
    ctx.hrv_series = [(k, mean(v)) for k, v in sorted(hrv_buckets.items())]
    if resting:
        ctx.metrics["resting_hr"] = min(resting)
    if ctx.hrv_series:
        ctx.metrics["hrv_avg"] = mean(v for _, v in ctx.hrv_series)
    if steps:
        ctx.metrics["steps"] = steps
    if spo2:
        ctx.metrics["spo2_avg"] = mean(spo2)
    if ctx.sleep:
        ctx.metrics["sleep_hours"] = ctx.sleep["hours"]
    ctx.metrics["exercise_minutes"] = sum(e["minutes"] for e in ctx.exercises)
    ctx.metrics["meeting_count"] = len(ctx.calendar)
    ctx.metrics["meeting_minutes"] = 0
    for c in ctx.calendar:
        try:
            sh, sm = map(int, c["start"].split(":"))
            eh, em = map(int, c["end"].split(":"))
            ctx.metrics["meeting_minutes"] += max(0, (eh * 60 + em) - (sh * 60 + sm))
        except ValueError:
            pass

    top = sorted(usage.items(), key=lambda kv: kv[1]["minutes"], reverse=True)[:8]
    ctx.app_usage = [
        {
            "app": label,
            "minutes": round(d["minutes"]),
            "peak_hours": ",".join(f"{h}時" for h, _ in sorted(d["hours"].items(), key=lambda kv: kv[1], reverse=True)[:2]),
        }
        for label, d in top
        if d["minutes"] >= 5
    ]
    ctx.metrics["screen_minutes"] = round(sum(d["minutes"] for _, d in usage.items()))
    late = 0.0
    for _, d in usage.items():
        for h, mins in d["hours"].items():
            if h in {"23", "00", "01", "02"}:
                late += mins
    ctx.metrics["late_night_screen_minutes"] = round(late)
    ctx.metrics["payment_count"] = sum(1 for p in ctx.payments if p["kind"] == "payment")
    return ctx


def previous_answers(session: Session, day: date, days: int = 14) -> list[dict[str, Any]]:
    """Recent answered cards, so the model can learn 'usual' patterns and stop asking."""
    lo = (day - timedelta(days=days)).isoformat()
    rows = session.exec(select(Card).where(Card.date >= lo, Card.date < day.isoformat(), Card.answer.is_not(None))).all()
    return [
        {"date": c.date, "kind": c.kind, "question": c.question, "answer": c.answer, "note": c.note}
        for c in rows
    ][-40:]
