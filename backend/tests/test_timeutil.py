from datetime import UTC, date, datetime

from app.core.timeutil import day_bounds, fmt_hm, local_day_of, parse_ts


def test_parse_ts_iso_with_offset_becomes_utc():
    dt = parse_ts("2026-10-14T21:00:00+09:00")
    assert dt == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_parse_ts_trailing_z():
    assert parse_ts("2026-10-14T12:00:00Z") == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_parse_ts_naive_is_assumed_local():
    # 21:00 JST == 12:00 UTC
    assert parse_ts("2026-10-14T21:00:00") == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_parse_ts_epoch_millis_and_seconds():
    ms = 1_791_979_200_000  # 2026-10-14T12:00:00Z
    assert parse_ts(ms) == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    assert parse_ts(ms // 1000) == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_day_bounds_cover_the_local_day_in_utc():
    start, end = day_bounds(date(2026, 10, 14))
    assert start == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def test_local_day_of_crosses_midnight():
    # 16:00 UTC on the 14th is already the 15th in Tokyo
    assert local_day_of(datetime(2026, 10, 14, 16, 0, tzinfo=UTC)) == date(2026, 10, 15)


def test_fmt_hm():
    assert fmt_hm(datetime(2026, 10, 14, 3, 25, tzinfo=UTC)) == "12:25"
    assert fmt_hm(None) == ""
