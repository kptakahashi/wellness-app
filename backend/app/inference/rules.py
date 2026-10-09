"""Deterministic fallback inference. No LLM.

Produces a serviceable timeline and cards from the DayContext alone so the product works
offline, in demo mode, and as a safety net when the LLM call fails. Claude's job is to do
this better (store-name -> dish inference, splitting group bills, natural phrasing).
"""

from __future__ import annotations

import re
from statistics import mean, median
from typing import Any

from ..services.daycontext import DayContext

FOOD_WORDS = {
    "ラーメン": "ラーメン", "らーめん": "ラーメン", "蕎麦": "そば", "そば": "そば", "うどん": "うどん",
    "カレー": "カレー", "寿司": "寿司", "すし": "寿司", "焼肉": "焼肉", "居酒屋": "居酒屋(お酒あり)",
    "スターバックス": "コーヒー", "スタバ": "コーヒー", "ドトール": "コーヒー", "タリーズ": "コーヒー",
    "セブン": "コンビニ(軽食)", "ファミリーマート": "コンビニ(軽食)", "ファミマ": "コンビニ(軽食)",
    "ローソン": "コンビニ(軽食)", "マクドナルド": "ハンバーガー", "マック": "ハンバーガー", "モス": "ハンバーガー",
    "吉野家": "牛丼", "松屋": "牛丼・定食", "すき家": "牛丼", "サイゼ": "イタリアン", "ガスト": "ファミレス",
    "大戸屋": "定食", "やよい軒": "定食", "丸亀": "うどん", "日高屋": "ラーメン・中華", "餃子の王将": "中華",
    "Uber Eats": "デリバリー", "出前館": "デリバリー", "酒": "お酒", "ビール": "ビール", "ワイン": "ワイン",
}
GYM_WORDS = ("ジム", "gym", "fitness", "フィットネス", "エニタイム", "ゴールドジム", "筋トレ", "ラン", "ヨガ", "プール")
MEAL_WINDOWS = [("朝食", 5, 10), ("昼食", 11, 14), ("夕食", 17, 22)]


def _hm_to_h(hm: str) -> float:
    try:
        h, m = hm.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return -1


def _yen(text: str) -> int | None:
    m = re.search(r"([0-9][0-9,]{1,7})\s*円|[¥￥]\s*([0-9][0-9,]{1,7})", text)
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).replace(",", "")
    return int(raw) if raw.isdigit() else None


GENERIC_TITLES = ("新着の入出金", "お支払い", "ご利用", "決済", "通知", "支払い完了")


def _store_name(p: dict[str, Any]) -> str:
    title = (p.get("title") or "").strip()
    text = (p.get("text") or "").strip()
    if title and not any(g in title for g in GENERIC_TITLES):
        return title[:24]
    # "大戸屋ごはん処 1,150円 (楽天カード)" -> "大戸屋ごはん処"
    m = re.match(r"\s*(.+?)\s*[0-9][0-9,]*\s*円", text)
    if m:
        return m.group(1)[:24]
    return (text.split(" ")[0] or title or p.get("app") or "")[:24]


def guess_food(text: str) -> str | None:
    for k, v in FOOD_WORDS.items():
        if k.lower() in text.lower():
            return v
    return None


def infer_day(ctx: DayContext, history: list[dict[str, Any]]) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []

    if ctx.sleep:
        timeline.append(
            {"time": ctx.sleep["start"], "end": ctx.sleep["end"], "label": f"睡眠 {ctx.sleep['hours']:.1f}h",
             "category": "sleep", "confidence": 0.95, "source": "ring"}
        )

    # --- meals from payments ---
    meals_seen: set[str] = set()
    for p in ctx.payments:
        if p["kind"] != "payment":
            continue
        text = f"{p['title']} {p['text']} {p['app']}"
        hour = _hm_to_h(p["time"])
        slot = next((name for name, lo, hi in MEAL_WINDOWS if lo <= hour < hi), None)
        food = guess_food(text)
        yen = _yen(text)
        if not slot and not food:
            continue
        label_food = food or ("食事" if slot else "飲食")
        amount = f" {yen:,}円" if yen else ""
        store = _store_name(p)
        timeline.append(
            {"time": p["time"], "label": f"{slot or '飲食'}: {label_food}推定 ({store}{amount})",
             "category": "meal", "confidence": 0.6 if food else 0.4, "source": "payment"}
        )
        if slot in meals_seen:
            continue
        meals_seen.add(slot or p["time"])
        companions = [c for c in ctx.calendar if abs(_hm_to_h(c["start"]) - hour) < 1.5 and c.get("attendee_count", 0) > 1]
        if companions and yen and yen > 3000:
            n = companions[0]["attendee_count"]
            cards.append(
                {"kind": "meal", "time": p["time"],
                 "question": f"{p['time']} {store}{amount}は{n}人の会食の分で、あなたの分は約{yen // n:,}円分でしたか?",
                 "options": ["はい", "もっと食べた", "もっと少ない"], "proposed": "はい", "confidence": 0.5,
                 "evidence": f"カレンダー「{companions[0]['title']}」(参加者{n}人)と時刻が一致"}
            )
        else:
            q = f"{p['time']} {store}{amount}、{label_food}でしたか?" if food else f"{p['time']} {store}{amount}は{slot}でしたか?"
            cards.append(
                {"kind": "meal", "time": p["time"], "question": q,
                 "options": ["はい", "いいえ"], "proposed": "はい", "confidence": 0.6 if food else 0.45,
                 "evidence": "決済通知の店名と時刻から推定"}
            )

    # --- meals from calendar when no payment ---
    for c in ctx.calendar:
        t = c["title"]
        if any(w in t for w in ("ランチ", "会食", "飲み", "ディナー", "食事", "懇親")) and not any(
            abs(_hm_to_h(p["time"]) - _hm_to_h(c["start"])) < 1.5 for p in ctx.payments
        ):
            timeline.append({"time": c["start"], "end": c["end"], "label": f"{t}(予定)", "category": "meal", "confidence": 0.5, "source": "calendar"})
            cards.append(
                {"kind": "meal", "time": c["start"], "question": f"{c['start']}の「{t}」は予定通り行きましたか?",
                 "options": ["はい", "いいえ"], "proposed": "はい", "confidence": 0.5, "evidence": "カレンダーの予定。決済は検出されず"}
            )

    # --- exercise ---
    hr_vals = [b for _, b in ctx.hr_series]
    baseline = median(hr_vals) if hr_vals else 0
    elevated = [(t, b) for t, b in ctx.hr_series if baseline and b > baseline * 1.35 and 6 <= _hm_to_h(t) <= 23]
    gym_cal = [c for c in ctx.calendar if any(w.lower() in c["title"].lower() for w in GYM_WORDS)]
    gym_place = [p for p in ctx.places if p.get("name") and any(w.lower() in str(p["name"]).lower() for w in GYM_WORDS)]
    for e in ctx.exercises:
        timeline.append({"time": e["start"], "end": e["end"], "label": f"運動: {e['type']} {e['minutes']}分", "category": "exercise", "confidence": 0.9, "source": "ring"})
    if ctx.exercises:
        e = ctx.exercises[0]
        routine = ctx.routines.get("exercise")
        cards.append(
            {"kind": "exercise", "time": e["start"],
             "question": f"{e['start']}〜{e['end']}の運動は" + (f"いつもの「{routine}」でしたか?" if routine else "何でしたか?"),
             "options": ["はい", "別のメニュー"] if routine else ["筋トレ", "有酸素", "両方", "運動ではない"],
             "proposed": "はい" if routine else "有酸素", "confidence": 0.7, "evidence": f"デバイスが{e['type']}を{e['minutes']}分検出"}
        )
    elif elevated or gym_cal or gym_place:
        t = elevated[0][0] if elevated else (gym_cal[0]["start"] if gym_cal else gym_place[0]["start"])
        why = []
        if elevated:
            why.append(f"心拍が{elevated[0][1]}bpmまで上昇")
        if gym_cal:
            why.append(f"予定「{gym_cal[0]['title']}」")
        if gym_place:
            why.append(f"{gym_place[0]['name']}に{gym_place[0]['minutes']}分滞在")
        timeline.append({"time": t, "label": "運動の可能性", "category": "exercise", "confidence": 0.5, "source": "hr/calendar"})
        cards.append(
            {"kind": "exercise", "time": t, "question": f"{t}ごろ、運動しましたか?",
             "options": ["はい", "いいえ"], "proposed": "はい", "confidence": 0.5, "evidence": "、".join(why)}
        )

    # --- work / stress ---
    for c in ctx.calendar:
        if c in gym_cal:
            continue
        timeline.append({"time": c["start"], "end": c["end"], "label": c["title"], "category": "work", "confidence": 0.9, "source": "calendar"})
    busy = ctx.metrics.get("meeting_minutes", 0)
    if busy >= 180 or ctx.metrics.get("meeting_count", 0) >= 4:
        cards.append(
            {"kind": "stress", "time": "", "question": f"今日は会議が{ctx.metrics.get('meeting_count', 0)}件・計{busy // 60}時間でした。ストレスは?",
             "options": ["低", "中", "高"], "proposed": "中", "confidence": 0.4, "evidence": "カレンダーの会議密度"}
        )

    # --- screen ---
    late = ctx.metrics.get("late_night_screen_minutes", 0)
    if late >= 30:
        top = ctx.app_usage[0]["app"] if ctx.app_usage else "スマホ"
        timeline.append({"time": "23:00", "label": f"深夜のスマホ利用 {late}分 (主に{top})", "category": "screen", "confidence": 0.9, "source": "usage"})
    for a in ctx.app_usage[:1]:
        if a["minutes"] >= 120:
            cards.append(
                {"kind": "stress", "time": "", "question": f"{a['app']}を{a['minutes']}分使っていました。息抜きでしたか、だらだらでしたか?",
                 "options": ["息抜き", "だらだら", "仕事・必要"], "proposed": "息抜き", "confidence": 0.4, "evidence": "アプリ利用統計"}
            )

    for pl in ctx.places:
        if pl in gym_place:
            continue
        timeline.append({"time": pl["start"], "end": pl["end"], "label": f"滞在: {pl.get('name') or pl['latlon']}", "category": "move", "confidence": 0.7, "source": "location"})

    # --- mood (always last) ---
    guess = 3
    if ctx.sleep:
        if ctx.sleep["hours"] >= 7:
            guess += 1
        elif ctx.sleep["hours"] < 6:
            guess -= 1
    if late >= 60:
        guess -= 1
    guess = max(1, min(5, guess))
    cards.append(
        {"kind": "mood", "time": "", "question": "今日全体の調子は?", "options": ["1", "2", "3", "4", "5"],
         "proposed": str(guess), "confidence": 0.3, "evidence": "睡眠時間と深夜利用からの仮の推定"}
    )

    timeline.sort(key=lambda x: _hm_to_h(x["time"]))
    parts = []
    if ctx.sleep:
        parts.append(f"睡眠{ctx.sleep['hours']:.1f}時間")
    if ctx.metrics.get("meeting_count"):
        parts.append(f"会議{ctx.metrics['meeting_count']}件")
    if ctx.metrics.get("payment_count"):
        parts.append(f"決済{ctx.metrics['payment_count']}件")
    if ctx.metrics.get("exercise_minutes"):
        parts.append(f"運動{ctx.metrics['exercise_minutes']}分")
    if ctx.metrics.get("screen_minutes"):
        parts.append(f"スマホ{ctx.metrics['screen_minutes']}分")
    summary = "、".join(parts) + "の1日。" if parts else "収集データが少ない日。"
    return {"summary": summary, "timeline": timeline, "cards": cards[:7]}


def infer_insights(rows: list[dict[str, Any]], answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Very small correlation finder: split days by a boolean condition and compare a metric."""
    out: list[dict[str, Any]] = []

    def compare(name_true: str, cond, metric: str, metric_label: str, unit: str = ""):
        a = [r[metric] for r in rows if cond(r) and r.get(metric) is not None]
        b = [r[metric] for r in rows if not cond(r) and r.get(metric) is not None]
        if len(a) >= 4 and len(b) >= 4:
            ma, mb = mean(a), mean(b)
            if mb and abs(ma - mb) / abs(mb) >= 0.08:
                diff = (ma - mb) / mb * 100
                out.append(
                    {"statement": f"{name_true}日は、それ以外の日より{metric_label}が平均{abs(diff):.0f}%{'高い' if diff > 0 else '低い'}。",
                     "evidence": f"{name_true}: {len(a)}日 平均{ma:.1f}{unit} / それ以外: {len(b)}日 平均{mb:.1f}{unit}",
                     "confidence": min(0.9, 0.4 + 0.05 * min(len(a), len(b))), "n_samples": len(a) + len(b)}
                )

    compare("運動した", lambda r: (r.get("exercise_minutes") or 0) >= 20, "hrv_avg", "HRV", "ms")
    compare("運動した", lambda r: (r.get("exercise_minutes") or 0) >= 20, "next_sleep_hours", "翌日の睡眠時間", "h")
    compare("深夜にスマホを60分以上使った", lambda r: (r.get("late_night_screen_minutes") or 0) >= 60, "next_sleep_hours", "翌日の睡眠時間", "h")
    compare("深夜にスマホを60分以上使った", lambda r: (r.get("late_night_screen_minutes") or 0) >= 60, "next_condition", "翌日の調子", "")
    compare("会議が4件以上の", lambda r: (r.get("meeting_count") or 0) >= 4, "condition", "その日の調子", "")
    compare("睡眠7時間以上の", lambda r: (r.get("sleep_hours") or 0) >= 7, "condition", "調子", "")
    compare("睡眠7時間以上の", lambda r: (r.get("sleep_hours") or 0) >= 7, "hrv_avg", "HRV", "ms")
    return {"insights": out[:6]}
