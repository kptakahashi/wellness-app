"""Remembered places: home, work, gym, favourite shops.

The user should be asked "is this your home?" at most once per place, and never for home at
all, because home can be found without asking: it is where the phone spends the night.

Labels live in the `settings` row "places":
    {"items": [{"lat": 35.69, "lon": 139.70, "label": "自宅", "radius_m": 150, "source": "auto"|"user",
                "updated": "2026-10-12"}]}
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from math import cos, radians, sqrt
from typing import Any

from sqlmodel import Session, select

from ..core.models import RawEvent, Setting
from ..core.timeutil import to_local

PLACES_KEY = "places"
DEFAULT_RADIUS_M = 150
HOME_LABEL = "自宅"
WORK_LABEL = "職場"

# Options shown on the one-time "what is this place?" card.
PLACE_OPTIONS = [HOME_LABEL, WORK_LABEL, "ジム", "飲食店・カフェ", "買い物", "その他"]


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * 111_320 * cos(radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110_540
    return sqrt(dx * dx + dy * dy)


def load_places(session: Session) -> list[dict[str, Any]]:
    row = session.get(Setting, PLACES_KEY)
    items = (row.value or {}).get("items", []) if row else []
    return [p for p in items if isinstance(p, dict) and "lat" in p and "lon" in p and p.get("label")]


def save_places(session: Session, items: list[dict[str, Any]]) -> None:
    row = session.get(Setting, PLACES_KEY) or Setting(key=PLACES_KEY)
    row.value = {"items": items}
    session.add(row)
    session.commit()


def find_place(places: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any] | None:
    """Nearest remembered place whose radius covers (lat, lon)."""
    best: tuple[float, dict[str, Any]] | None = None
    for p in places:
        d = dist_m(lat, lon, float(p["lat"]), float(p["lon"]))
        if d <= float(p.get("radius_m", DEFAULT_RADIUS_M)) and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def label_for(places: list[dict[str, Any]], lat: float, lon: float) -> str | None:
    p = find_place(places, lat, lon)
    return str(p["label"]) if p else None


def upsert_place(session: Session, lat: float, lon: float, label: str, source: str = "user", radius_m: int = DEFAULT_RADIUS_M) -> list[dict[str, Any]]:
    """Set the label of the place at (lat, lon). A user label always wins over an auto label."""
    label = label.strip()[:40]
    items = load_places(session)
    existing = find_place(items, lat, lon)
    today = date.today().isoformat()
    if existing:
        if existing.get("source") == "user" and source == "auto":
            return items
        existing.update({"label": label, "source": source, "updated": today})
    else:
        items.append({"lat": round(lat, 5), "lon": round(lon, 5), "label": label, "radius_m": radius_m, "source": source, "updated": today})
    save_places(session, items)
    return items


# ---------------------------------------------------------------- clustering helpers
def _location_samples(session: Session, days: int) -> list[tuple[datetime, float, float, int]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.exec(select(RawEvent).where(RawEvent.kind == "location_sample", RawEvent.start_ts >= since)).all()
    out: list[tuple[datetime, float, float, int]] = []
    for r in rows:
        p = r.payload or {}
        try:
            lat, lon = float(p.get("lat")), float(p.get("lon"))
        except (TypeError, ValueError):
            continue
        if not lat and not lon:
            continue
        out.append((r.start_ts, lat, lon, int(p.get("accuracy_m") or 0)))
    return out


def _greedy_clusters(points: list[tuple[datetime, float, float, int]], radius_m: float = DEFAULT_RADIUS_M) -> list[dict[str, Any]]:
    """Assign every sample to the first cluster centre within radius_m (order-independent enough for our use)."""
    clusters: list[dict[str, Any]] = []
    for ts, lat, lon, _acc in points:
        for c in clusters:
            if dist_m(lat, lon, c["lat"], c["lon"]) <= radius_m:
                n = c["n"]
                c["lat"] = (c["lat"] * n + lat) / (n + 1)
                c["lon"] = (c["lon"] * n + lon) / (n + 1)
                c["n"] = n + 1
                c["days"].add(to_local(ts).date())
                break
        else:
            clusters.append({"lat": lat, "lon": lon, "n": 1, "days": {to_local(ts).date()}})
    return clusters


def auto_detect(session: Session, days: int = 14) -> dict[str, Any]:
    """Infer home (where the phone is between 01:00 and 05:00) and work (weekday 10:00-16:00).

    Writes auto labels unless a user label already covers the spot. Returns what it decided.
    """
    samples = _location_samples(session, days)
    if not samples:
        return {}
    result: dict[str, Any] = {}

    night = [s for s in samples if 1 <= to_local(s[0]).hour < 5]
    home = None
    if night:
        clusters = sorted(_greedy_clusters(night), key=lambda c: (len(c["days"]), c["n"]), reverse=True)
        top = clusters[0]
        if len(top["days"]) >= 3:
            home = top
            upsert_place(session, top["lat"], top["lon"], HOME_LABEL, source="auto")
            result["home"] = {"lat": round(top["lat"], 5), "lon": round(top["lon"], 5), "nights": len(top["days"])}

    work = [s for s in samples if to_local(s[0]).weekday() < 5 and 10 <= to_local(s[0]).hour < 16]
    if work:
        clusters = sorted(_greedy_clusters(work), key=lambda c: (len(c["days"]), c["n"]), reverse=True)
        for c in clusters:
            if home and dist_m(c["lat"], c["lon"], home["lat"], home["lon"]) <= 300:
                continue  # working from home is not "work"
            if len(c["days"]) >= 5:
                upsert_place(session, c["lat"], c["lon"], WORK_LABEL, source="auto")
                result["work"] = {"lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "days": len(c["days"])}
            break
    return result


def visit_days(session: Session, lat: float, lon: float, days: int = 30, radius_m: float = DEFAULT_RADIUS_M) -> int:
    """How many distinct days the phone was seen within radius_m of (lat, lon)."""
    seen: set[date] = set()
    for ts, la, lo, _ in _location_samples(session, days):
        if dist_m(lat, lon, la, lo) <= radius_m:
            seen.add(to_local(ts).date())
    return len(seen)


def place_cards(session: Session, visits: list[dict[str, Any]], places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One-time cards for places worth remembering: unlabeled, and either a long stay or recurring.

    Returned in the same shape as inference cards. The evidence carries the coordinates so the
    answer handler can store the label.
    """
    out: list[dict[str, Any]] = []
    asked: list[tuple[float, float]] = []
    for v in visits:
        if v.get("label") or v.get("lat") is None:
            continue
        lat, lon = float(v["lat"]), float(v["lon"])
        if any(dist_m(lat, lon, a[0], a[1]) <= DEFAULT_RADIUS_M for a in asked):
            continue
        minutes = int(v.get("minutes") or 0)
        recurring = visit_days(session, lat, lon) >= 2
        if minutes < 60 and not recurring:
            continue  # one-off short visits: the POI candidates are enough, no question
        asked.append((lat, lon))
        pois = v.get("pois") or []
        where = v.get("name") or (pois[0]["name"] if pois else None) or f"{lat:.4f},{lon:.4f}"
        proposed = "その他"
        if pois:
            cat = pois[0].get("category", "")
            if "ジム" in cat:
                proposed = "ジム"
            elif any(k in cat for k in ("飲食", "カフェ", "居酒屋", "ファストフード")):
                proposed = "飲食店・カフェ"
            elif any(k in cat for k in ("コンビニ", "スーパー", "店", "モール", "ドラッグ")):
                proposed = "買い物"
        hint = f"候補: {', '.join(p['name'] for p in pois[:3])}" if pois else "店名の候補なし"
        out.append(
            {
                "kind": "place",
                "time": v.get("start") or "",
                "question": f"{v.get('start')}〜{v.get('end')} に{where}にいました({minutes}分)。ここは?",
                "options": PLACE_OPTIONS,
                "proposed": proposed,
                "confidence": 0.5,
                "evidence": f"{hint}。一度答えると次からは聞きません(自由入力で店名も可)",
                "place": {"lat": round(lat, 5), "lon": round(lon, 5), "name": where},
            }
        )
        if len(out) >= 2:
            break
    return out


def recurring_counts(session: Session, days: int = 30) -> dict[tuple[float, float], int]:
    counts: dict[tuple[float, float], set[date]] = defaultdict(set)
    for c in _greedy_clusters(_location_samples(session, days)):
        counts[(round(c["lat"], 4), round(c["lon"], 4))] = c["days"]
    return {k: len(v) for k, v in counts.items()}
