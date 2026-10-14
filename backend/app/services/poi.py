"""Name the shop or facility behind a stay, using OpenStreetMap.

Privacy: we never send a visit's coordinates anywhere. Instead we download every named POI in a
~2 km tile around the user's area once (Overpass API, free, no key), cache it in the database,
and match visits against the cache locally. The only thing OSM learns is which 2 km squares the
user has ever been in. Set POI_SOURCE=none to disable.

Overpass usage policy: identify the client, stay far below 10k queries/day, pause on 429.
A personal instance fetches a handful of tiles in its whole life.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from math import floor
from typing import Any

import httpx
from sqlmodel import Session, select

from ..core.config import settings
from ..core.models import PoiTile
from .places import dist_m

log = logging.getLogger(__name__)

USER_AGENT = "wellness-app/0.1 (personal health log; https://github.com/kptakahashi/wellness-app)"
TILE_TTL = timedelta(days=90)
_failed_at: dict[str, float] = {}  # tile key -> monotonic time of last failed fetch

# amenity values that are never "a place you stayed at"
NOISE_AMENITY = {
    "parking",
    "bench",
    "vending_machine",
    "toilets",
    "bicycle_parking",
    "post_box",
    "telephone",
    "waste_basket",
    "drinking_water",
    "shelter",
    "parking_entrance",
    "parking_space",
    "charging_station",
    "recycling",
    "fountain",
    "grave_yard",
    "bicycle_rental",
    "car_sharing",
    "taxi",
    "loading_dock",
    "motorcycle_parking",
    "smoking_area",
    "water_point",
    "hunting_stand",
    "clock",
    "atm",
}

# tag -> Japanese category. First match wins; unknown values fall back to the tag's generic label.
CATEGORY_JA: dict[str, dict[str, str]] = {
    "amenity": {
        "restaurant": "飲食店",
        "cafe": "カフェ",
        "fast_food": "ファストフード",
        "bar": "バー",
        "pub": "居酒屋・バー",
        "izakaya": "居酒屋",
        "food_court": "フードコート",
        "ice_cream": "アイス",
        "hospital": "病院",
        "clinic": "クリニック",
        "dentist": "歯科",
        "doctors": "クリニック",
        "pharmacy": "薬局",
        "bank": "銀行",
        "school": "学校",
        "university": "大学",
        "college": "学校",
        "kindergarten": "幼稚園・保育園",
        "library": "図書館",
        "cinema": "映画館",
        "theatre": "劇場",
        "place_of_worship": "寺社・教会",
        "community_centre": "公民館",
        "townhall": "役所",
        "post_office": "郵便局",
        "gym": "ジム",
        "fitness_centre": "ジム",
        "public_bath": "銭湯・温泉",
        "nightclub": "クラブ",
        "karaoke_box": "カラオケ",
        "coworking_space": "コワーキング",
        "veterinary": "動物病院",
        "fuel": "ガソリンスタンド",
        "car_wash": "洗車",
        "marketplace": "市場",
        "social_facility": "福祉施設",
        "childcare": "保育",
        "arts_centre": "文化施設",
        "events_venue": "イベント会場",
        "conference_centre": "会議場",
        "police": "交番・警察",
        "bus_station": "バスターミナル",
    },
    "shop": {
        "convenience": "コンビニ",
        "supermarket": "スーパー",
        "mall": "ショッピングモール",
        "department_store": "百貨店",
        "chemist": "ドラッグストア",
        "drugstore": "ドラッグストア",
        "bakery": "パン屋",
        "books": "書店",
        "clothes": "衣料品店",
        "electronics": "家電量販店",
        "hairdresser": "美容室",
        "beauty": "サロン",
        "variety_store": "100円ショップ・雑貨",
        "alcohol": "酒屋",
        "coffee": "コーヒー豆",
        "sports": "スポーツ用品",
        "bicycle": "自転車店",
        "car": "自動車販売",
        "furniture": "家具店",
        "hardware": "ホームセンター",
        "doityourself": "ホームセンター",
        "pet": "ペットショップ",
        "optician": "メガネ店",
        "massage": "マッサージ",
        "laundry": "コインランドリー",
        "dry_cleaning": "クリーニング",
        "greengrocer": "八百屋",
        "butcher": "精肉店",
        "seafood": "鮮魚店",
        "confectionery": "菓子店",
        "tea": "お茶",
        "mobile_phone": "携帯ショップ",
        "second_hand": "リサイクルショップ",
        "anime": "アニメショップ",
        "video_games": "ゲーム店",
    },
    "leisure": {
        "fitness_centre": "ジム",
        "sports_centre": "スポーツ施設",
        "swimming_pool": "プール",
        "park": "公園",
        "garden": "庭園",
        "stadium": "スタジアム",
        "pitch": "グラウンド",
        "playground": "公園(遊び場)",
        "bowling_alley": "ボウリング",
        "golf_course": "ゴルフ場",
        "sauna": "サウナ",
        "dance": "ダンススタジオ",
        "amusement_arcade": "ゲームセンター",
        "water_park": "プール",
        "ice_rink": "スケート場",
        "escape_game": "脱出ゲーム",
        "fitness_station": "トレーニング器具",
    },
    "tourism": {
        "hotel": "ホテル",
        "museum": "博物館・美術館",
        "attraction": "観光地",
        "guest_house": "宿",
        "hostel": "ホステル",
        "gallery": "ギャラリー",
        "zoo": "動物園",
        "aquarium": "水族館",
        "theme_park": "テーマパーク",
        "viewpoint": "展望スポット",
    },
    "healthcare": {"*": "医療機関"},
    "office": {"*": "オフィス"},
    "railway": {"station": "駅"},
    "public_transport": {"station": "駅"},
}
GENERIC_JA = {
    "amenity": "施設",
    "shop": "店",
    "leisure": "レジャー施設",
    "tourism": "観光施設",
    "healthcare": "医療機関",
    "office": "オフィス",
    "railway": "駅",
    "public_transport": "駅",
}

# Categories where people actually spend time, ranked above e.g. a bank or a pharmacy next door.
STAY_CATEGORIES = {
    "飲食店",
    "カフェ",
    "ファストフード",
    "バー",
    "居酒屋・バー",
    "居酒屋",
    "フードコート",
    "ジム",
    "スポーツ施設",
    "プール",
    "コンビニ",
    "スーパー",
    "ショッピングモール",
    "百貨店",
    "病院",
    "クリニック",
    "歯科",
    "駅",
    "オフィス",
    "学校",
    "大学",
    "映画館",
    "カラオケ",
    "銭湯・温泉",
    "サウナ",
    "コワーキング",
    "ホテル",
    "美容室",
    "図書館",
    "公園",
    "家電量販店",
    "書店",
}


def enabled() -> bool:
    return settings.poi_source.lower() == "osm" and not settings.demo_mode


def tile_key(lat: float, lon: float) -> str:
    size = settings.poi_tile_deg
    return f"{floor(lat / size) * size:.3f},{floor(lon / size) * size:.3f}"


def tile_bbox(key: str) -> tuple[float, float, float, float]:
    s, w = (float(x) for x in key.split(","))
    size = settings.poi_tile_deg
    return s, w, s + size, w + size


def _category(tags: dict[str, str]) -> str | None:
    for tag, table in CATEGORY_JA.items():
        val = tags.get(tag)
        if not val:
            continue
        if tag == "amenity" and val in NOISE_AMENITY:
            return None
        if tag in ("railway", "public_transport") and val != "station":
            continue
        return table.get(val) or table.get("*") or GENERIC_JA[tag]
    return None


def _overpass_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"({s:.4f},{w:.4f},{n:.4f},{e:.4f})"
    selectors = [
        'nwr["name"]["amenity"]',
        'nwr["name"]["shop"]',
        'nwr["name"]["leisure"]',
        'nwr["name"]["tourism"]',
        'nwr["name"]["healthcare"]',
        'nwr["name"]["railway"="station"]',
        'nwr["name"]["public_transport"="station"]',
    ]
    body = "".join(f"{sel}{box};" for sel in selectors)
    return f"[out:json][timeout:120];({body});out center qt;"


def _post_overpass(q: str) -> list[dict[str, Any]]:
    """Try each configured endpoint in turn (the main instance is often busy: 504/429)."""
    last: Exception | None = None
    for url in [u.strip() for u in settings.overpass_urls.split(",") if u.strip()]:
        try:
            with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), headers={"User-Agent": USER_AGENT}) as client:
                res = client.post(url, data={"data": q})
            if res.status_code in (429, 504, 503):
                raise RuntimeError(f"{url} busy ({res.status_code})")
            res.raise_for_status()
            return res.json().get("elements", [])
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.info("overpass endpoint failed, trying next: %s", exc)
            time.sleep(5)
    raise RuntimeError(f"all overpass endpoints failed: {last}")


def fetch_tile(key: str) -> list[dict[str, Any]]:
    """Download one tile from Overpass. Raises on failure."""
    elements = _post_overpass(_overpass_query(tile_bbox(key)))
    out: list[dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name:ja") or tags.get("name") or "").strip()
        if not name:
            continue
        cat = _category(tags)
        if not cat:
            continue
        lat = el.get("lat") if el.get("type") == "node" else (el.get("center") or {}).get("lat")
        lon = el.get("lon") if el.get("type") == "node" else (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        item = {"n": name[:60], "c": cat, "la": round(float(lat), 5), "lo": round(float(lon), 5)}
        brand = tags.get("brand:ja") or tags.get("brand")
        if brand and brand not in name:
            item["b"] = brand[:40]
        en = tags.get("name:en") or tags.get("brand:en")
        if en:
            item["e"] = en[:60]  # card statements often romanise the merchant (MITSUBISHI, OOTOYA)
        out.append(item)
    return out


def ensure_tiles(session: Session, points: list[tuple[float, float]], max_fetch: int = 2) -> int:
    """Make sure the tiles covering `points` are cached. Fetches at most `max_fetch` tiles. Returns fetched count."""
    if not enabled():
        return 0
    keys: list[str] = []
    for lat, lon in points:
        k = tile_key(lat, lon)
        if k not in keys:
            keys.append(k)
    fetched = 0
    now = datetime.now(UTC)
    for k in keys:
        row = session.get(PoiTile, k)
        if row and row.fetched_at and (now - row.fetched_at.replace(tzinfo=row.fetched_at.tzinfo or UTC)) < TILE_TTL:
            continue
        if time.monotonic() - _failed_at.get(k, -1e9) < 3600:
            continue
        if fetched >= max_fetch:
            break
        try:
            pois = fetch_tile(k)
        except Exception as exc:  # noqa: BLE001
            _failed_at[k] = time.monotonic()
            log.warning("poi tile %s fetch failed: %s", k, exc)
            continue
        row = row or PoiTile(key=k)
        row.pois = pois
        row.fetched_at = now
        session.add(row)
        session.commit()
        fetched += 1
        log.info("poi tile %s cached with %d places", k, len(pois))
        time.sleep(2)  # be polite to the public Overpass instance
    return fetched


def _tiles_around(session: Session, lat: float, lon: float) -> list[dict[str, Any]]:
    """POIs from the tile of (lat, lon) and, near a tile edge, its neighbours (if cached)."""
    keys = {tile_key(lat + dy, lon + dx) for dy in (-0.003, 0, 0.003) for dx in (-0.003, 0, 0.003)}
    out: list[dict[str, Any]] = []
    for k in keys:
        row = session.get(PoiTile, k)
        if row:
            out.extend(row.pois or [])
    return out


def nearby(session: Session, lat: float, lon: float, radius_m: float = 80, limit: int = 3) -> list[dict[str, Any]]:
    """Named places within radius_m, best first. Cached tiles only: never hits the network."""
    if settings.poi_source.lower() != "osm":
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for p in _tiles_around(session, lat, lon):
        d = dist_m(lat, lon, p["la"], p["lo"])
        if d > radius_m:
            continue
        score = d + (0 if p["c"] in STAY_CATEGORIES else 40)
        scored.append((score, {"name": p["n"], "category": p["c"], "distance_m": round(d), "brand": p.get("b"), "name_en": p.get("e")}))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored[:limit]]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    for ch in (" ", "　", "店", "・", "-", "ー", "(", ")", "（", "）"):
        s = s.replace(ch, "")
    return s


def _lcs_len(a: str, b: str) -> int:
    """Length of the longest common substring."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def match_store(pois: list[dict[str, Any]], store_text: str) -> dict[str, Any] | None:
    """Does a payment's text mention one of the candidate POIs?

    Payment notifications read like "大戸屋 渋谷店で1,150円のお支払い"; OSM has "大戸屋ごはん処 渋谷店".
    We compare normalised strings by longest common substring: at least 3 characters, and either
    4+ characters or a third of the POI name (so "大戸屋" settles "大戸屋ごはん処 渋谷店").
    English names cover romanised card statements ("OOTOYA SHIBUYA").
    """
    t = _norm(store_text)
    if len(t) < 2:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for p in pois:
        for cand in (p.get("name"), p.get("brand"), p.get("name_en")):
            n = _norm(cand or "")
            if len(n) < 2:
                continue
            k = _lcs_len(n, t)
            if k >= 3 and (k >= 4 or k * 3 >= len(n)) and (best is None or k > best[0]):
                best = (k, p)
    return best[1] if best else None


def tiles_status(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(select(PoiTile)).all()
    return [{"tile": r.key, "places": len(r.pois or []), "fetched_at": r.fetched_at} for r in rows]
