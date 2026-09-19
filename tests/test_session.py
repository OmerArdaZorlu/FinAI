"""Seans filtresi testleri — DST dahil. Ağ erişimi gerektirmez."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.session import (  # noqa: E402
    acilis_mumu_duzelt,
    bars_per_day,
    exchange_hour,
    regular_hours,
    regular_minutes,
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


def minute_bars(start: str) -> pd.DataFrame:
    """Tek gün, 04:00–19:59 ET arası dakikalık barlar."""
    day = pd.Timestamp(start, tz="America/New_York").replace(hour=4)
    ts = pd.date_range(day, periods=16 * 60, freq="min").tz_convert("UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1_000, "trade_count": 10, "vwap": 100.0,
    })


@pytest.mark.parametrize("start", ["2024-03-05", "2024-03-12"])   # EST, EDT
def test_minutes_keep_0930_to_1559(start):
    got = regular_minutes(minute_bars(start))
    et = got["timestamp"].dt.tz_convert("America/New_York")
    assert len(got) == 390
    assert et.iloc[0].strftime("%H:%M") == "09:30"
    assert et.iloc[-1].strftime("%H:%M") == "15:59"


def test_report_flags_each_hour():
    report = session_report(hourly_bars(days=4))
    assert set(report["seans"]) == {"düzenli", "uzatılmış"}
    assert report.loc[4, "seans"] == "uzatılmış"
    assert report.loc[11, "seans"] == "düzenli"
    assert report["hacim_payi"].sum() == pytest.approx(1.0)



# ------------------------------------------------ 09:00 barının düzeltilmesi --

def test_acilis_mumu_seans_oncesini_dislar():
    """09:00-09:29 dakikalarında fiyat 90'a iniyor (seans öncesi); düzeltilmiş
    09:00 barı bunu görmemeli, 09:30'daki açılışla başlamalı."""
    ts = pd.date_range("2024-03-04 14:00", periods=60, freq="1min", tz="UTC")  # 09:00-09:59 NY
    fiyat = [90.0 if i < 30 else 100.0 + i / 100 for i in range(60)]
    dak = pd.DataFrame({"timestamp": ts, "open": fiyat, "high": fiyat, "low": fiyat,
                        "close": fiyat, "volume": 10, "trade_count": 1, "vwap": fiyat})
    saat = pd.DataFrame({"timestamp": pd.to_datetime(["2024-03-04 14:00", "2024-03-04 15:00"], utc=True),
                         "open": [90.0, 101.0], "high": [100.59, 102.0], "low": [90.0, 100.5],
                         "close": [100.59, 101.5], "volume": [600, 500], "trade_count": [60, 50],
                         "vwap": [95.0, 101.0]})
    d = acilis_mumu_duzelt(saat, dak)
    ilk = d.iloc[0]
    assert (ilk["open"], ilk["low"], ilk["close"]) == (100.30, 100.30, 100.59)
    assert ilk["volume"] == 300
    assert d.iloc[1].equals(saat.iloc[1])                   # 10:00 barına dokunulmaz


def test_dakikasi_olmayan_gunun_acilis_mumu_aynen_kalir():
    saat = hourly_bars(days=1)
    dak = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume",
                                "trade_count", "vwap"])
    dak["timestamp"] = pd.to_datetime(dak["timestamp"], utc=True)
    pd.testing.assert_frame_equal(acilis_mumu_duzelt(saat, dak), saat)
