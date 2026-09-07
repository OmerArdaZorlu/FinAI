"""SQLite katmanının testleri — ağ erişimi gerektirmez, geçici DB kullanır."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import connect, list_series, log_ingest, read_bars, write_bars  # noqa: E402
from src.data.load import load_bars, load_ingest_log  # noqa: E402
from tests.test_schema import make_bars  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def seeded(db):
    df = make_bars(10)
    with connect(db) as conn:
        write_bars(conn, df, symbol="TEST", timeframe="1Day", adjustment="all")
    return db, df


def test_roundtrip_preserves_values(seeded):
    db, original = seeded
    with connect(db) as conn:
        reloaded = read_bars(conn, "TEST")
    pd.testing.assert_frame_equal(original, reloaded)


def test_roundtrip_preserves_utc(seeded):
    db, _ = seeded
    with connect(db) as conn:
        reloaded = read_bars(conn, "TEST")
    assert str(reloaded["timestamp"].dt.tz) == "UTC"


def test_write_is_idempotent(seeded):
    """Aynı indirmeyi iki kez yazmak yinelenen bar üretmemeli."""
    db, original = seeded
    with connect(db) as conn:
        write_bars(conn, original, symbol="TEST", timeframe="1Day", adjustment="all")
        assert len(read_bars(conn, "TEST")) == len(original)


def test_rewrite_updates_existing_row(seeded):
    """Aynı barın düzeltilmiş hâli gelirse eski değer tazelenmeli."""
    db, original = seeded
    revised = original.copy()
    revised.loc[3, "close"] = 999.0
    revised.loc[3, "high"] = 1000.0
    with connect(db) as conn:
        write_bars(conn, revised, symbol="TEST", timeframe="1Day", adjustment="all")
        reloaded = read_bars(conn, "TEST")
    assert reloaded.loc[3, "close"] == 999.0
    assert len(reloaded) == len(original)


def test_adjustment_is_part_of_identity(db):
    """raw ve all AYNI barın FARKLI fiyatıdır; biri diğerini ezmemeli.

    Bu, şemadaki en kolay gözden kaçan karar. adjustment birincil anahtarda
    olmasaydı, bir 'raw' indirme tüm 'all' serisini sessizce bozardı.
    """
    adjusted = make_bars(5)
    raw = adjusted.copy()
    for col in ("open", "high", "low", "close", "vwap"):
        raw[col] = raw[col] * 4.0          # bölünme öncesi ham fiyat

    with connect(db) as conn:
        write_bars(conn, adjusted, symbol="TEST", timeframe="1Day", adjustment="all")
        write_bars(conn, raw, symbol="TEST", timeframe="1Day", adjustment="raw")

        got_all = read_bars(conn, "TEST", adjustment="all")
        got_raw = read_bars(conn, "TEST", adjustment="raw")
        series = list_series(conn)

    assert len(series) == 2, "iki ayrı seri olarak durmalı"
    pd.testing.assert_frame_equal(got_all, adjusted)
    assert got_raw["close"].iloc[0] == pytest.approx(adjusted["close"].iloc[0] * 4.0)


def test_timeframe_is_part_of_identity(db):
    with connect(db) as conn:
        write_bars(conn, make_bars(5), symbol="TEST", timeframe="1Day", adjustment="all")
        write_bars(conn, make_bars(5), symbol="TEST", timeframe="1Hour", adjustment="all")
        assert len(list_series(conn)) == 2


def test_date_range_end_is_inclusive(seeded):
    """--end '2024-01-05' verilince 5 Ocak barı DAHİL gelmeli."""
    db, original = seeded
    with connect(db) as conn:
        window = read_bars(conn, "TEST", start="2024-01-03", end="2024-01-05")
    assert [str(t.date()) for t in window["timestamp"]] == [
        "2024-01-03", "2024-01-04", "2024-01-05",
    ]


def test_ingest_log_is_recorded(db):
    record = {
        "symbol": "TEST", "timeframe": "1Day", "adjustment": "all", "feed": "sip",
        "requested_start": "2024-01-01", "requested_end": "2024-01-10",
        "actual_start": "2024-01-02T00:00:00+00:00",
        "actual_end": "2024-01-11T00:00:00+00:00",
        "rows_fetched": 10, "rows_written": 10,
        "source": "alpaca-data-v2/stocks/bars",
        "fetched_at_utc": "2026-09-07T10:00:00+00:00",
    }
    with connect(db) as conn:
        log_ingest(conn, record)
    log = load_ingest_log(db)
    assert len(log) == 1
    assert log.loc[0, "adjustment"] == "all"
    assert log.loc[0, "rows_written"] == 10


def test_ingest_log_rejects_incomplete_record(db):
    with connect(db) as conn:
        with pytest.raises(ValueError, match="eksik alan"):
            log_ingest(conn, {"symbol": "TEST"})


def test_invalid_bars_never_reach_disk(db):
    """Doğrulamadan geçmeyen veri yazılmamalı — bozuk satır DB'ye sızmamalı."""
    from src.data.schema import ValidationError

    bad = make_bars(5)
    bad.loc[2, "high"] = bad.loc[2, "low"] - 1.0
    with connect(db) as conn:
        with pytest.raises(ValidationError):
            write_bars(conn, bad, symbol="TEST", timeframe="1Day", adjustment="all")
        assert read_bars(conn, "TEST").empty


def test_missing_db_message_is_actionable(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_bars.py"):
        load_bars("SPY", db_path=tmp_path / "yok.db")


def test_missing_series_lists_what_is_available(seeded):
    db, _ = seeded
    with pytest.raises(ValueError, match="TEST"):
        load_bars("YOKSA", db_path=db)
