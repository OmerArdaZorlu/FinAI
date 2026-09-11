"""Seans filtresi testleri — DST dahil. Ağ erişimi gerektirmez."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.session import (  # noqa: E402
    bars_per_day,
    exchange_hour,
    regular_hours,
    session_report,
)


def hourly_bars(days: int = 5, start: str = "2024-03-01") -> pd.DataFrame:
    """Uzatılmış seans dahil, 04:00–19:00 ET arası saatlik barlar."""
    stamps = []
    day = pd.Timestamp(start, tz="America/New_York")
    for _ in range(days):
        for hour in range(4, 20):
            stamps.append(day.replace(hour=hour))
        day += pd.Timedelta(days=1)
    ts = pd.DatetimeIndex(stamps).tz_convert("UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1_000, "trade_count": 10, "vwap": 100.0,
    })


def test_keeps_only_regular_session():
    got = regular_hours(hourly_bars(days=3))
    hours = sorted(exchange_hour(got).unique())
    assert hours == [9, 10, 11, 12, 13, 14, 15]


def test_seven_bars_per_day():
    assert bars_per_day(regular_hours(hourly_bars(days=10))) == pytest.approx(7.0)


def test_can_drop_the_half_length_open_bar():
    got = regular_hours(hourly_bars(days=3), include_open_bar=False)
    assert sorted(exchange_hour(got).unique()) == [10, 11, 12, 13, 14, 15]


def test_extended_hours_are_removed():
    before = hourly_bars(days=5)
    after = regular_hours(before)
    assert len(before) == 5 * 16
    assert len(after) == 5 * 7


def test_filter_is_dst_aware():
    """ABD'de DST 10 Mart 2024'te başlar; UTC karşılığı 14:30'dan 13:30'a kayar.

    Sabit UTC saatiyle kesilseydi, geçişin bir yanında yanlış barlar seçilirdi.
    """
    winter = regular_hours(hourly_bars(days=2, start="2024-03-05"))   # EST (UTC-5)
    summer = regular_hours(hourly_bars(days=2, start="2024-03-12"))   # EDT (UTC-4)

    assert bars_per_day(winter) == pytest.approx(7.0)
    assert bars_per_day(summer) == pytest.approx(7.0)

    # Aynı borsa saati, FARKLI UTC saati — filtrenin çevirdiğinin kanıtı
    winter_utc = sorted(winter["timestamp"].dt.hour.unique())
    summer_utc = sorted(summer["timestamp"].dt.hour.unique())
    assert winter_utc != summer_utc
    assert winter_utc[0] == 14 and summer_utc[0] == 13


def test_daily_bars_pass_through_unchanged():
    """Günlük tabloya uygulanınca bar kaybı olmamalı."""
    ts = pd.date_range("2024-01-02", periods=20, freq="B", tz="America/New_York")
    ts = ts.map(lambda t: t.replace(hour=9)).tz_convert("UTC")
    daily = pd.DataFrame({
        "timestamp": ts,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1_000, "trade_count": 10, "vwap": 100.0,
    })
    assert len(regular_hours(daily)) == len(daily)


def test_report_flags_each_hour():
    report = session_report(hourly_bars(days=4))
    assert set(report["seans"]) == {"düzenli", "uzatılmış"}
    assert report.loc[4, "seans"] == "uzatılmış"
    assert report.loc[11, "seans"] == "düzenli"
    assert report["hacim_payi"].sum() == pytest.approx(1.0)
