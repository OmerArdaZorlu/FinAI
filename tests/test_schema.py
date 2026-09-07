"""Bar sözleşmesinin birim testleri — ağ erişimi gerektirmez."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.schema import BAR_COLUMNS, ValidationError, validate_bars  # noqa: E402


def make_bars(n: int = 5) -> pd.DataFrame:
    """Sözleşmeye uyan, sentetik ve geçerli bir bar tablosu."""
    ts = pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC")
    base = 100.0 + pd.Series(range(n), dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": base,
            "high": base + 2.0,
            "low": base - 2.0,
            "close": base + 1.0,
            "volume": [1_000_000] * n,
            "trade_count": [5_000] * n,
            "vwap": base + 0.5,
        }
    )[list(BAR_COLUMNS)]


def test_valid_bars_pass():
    validate_bars(make_bars(), symbol="TEST")


def test_column_order_is_enforced():
    df = make_bars()[["open", "timestamp", "high", "low", "close", "volume", "trade_count", "vwap"]]
    with pytest.raises(ValidationError, match="sütun şeması"):
        validate_bars(df, symbol="TEST")


def test_empty_table_rejected():
    with pytest.raises(ValidationError, match="boş"):
        validate_bars(make_bars(0), symbol="TEST")


def test_naive_timestamp_rejected():
    df = make_bars()
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValidationError, match="tz-naive"):
        validate_bars(df, symbol="TEST")


def test_duplicate_timestamp_rejected():
    df = make_bars()
    df.loc[2, "timestamp"] = df.loc[1, "timestamp"]
    with pytest.raises(ValidationError, match="yinelenen"):
        validate_bars(df, symbol="TEST")


def test_unsorted_timestamp_rejected():
    df = make_bars().iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValidationError, match="artan sırada"):
        validate_bars(df, symbol="TEST")


def test_nan_rejected():
    df = make_bars()
    df.loc[3, "close"] = float("nan")
    with pytest.raises(ValidationError, match="NaN"):
        validate_bars(df, symbol="TEST")


def test_high_below_low_rejected():
    df = make_bars()
    df.loc[1, "high"] = df.loc[1, "low"] - 1.0
    with pytest.raises(ValidationError, match="high < low"):
        validate_bars(df, symbol="TEST")


def test_high_below_close_rejected():
    df = make_bars()
    df.loc[1, "high"] = df.loc[1, "close"] - 0.5
    with pytest.raises(ValidationError, match=r"high < max"):
        validate_bars(df, symbol="TEST")


def test_negative_volume_rejected():
    df = make_bars()
    df.loc[0, "volume"] = -1
    with pytest.raises(ValidationError, match="negatif hacim"):
        validate_bars(df, symbol="TEST")
