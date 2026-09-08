"""H-001 kanal konumu — sızıntı ve doğruluk testleri. Ağ erişimi gerektirmez."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.h001 import (  # noqa: E402
    WindowError,
    build_table,
    channel_position,
    forward_direction,
    forward_return,
    valid_mask,
)


def make_bars(n: int = 60, seed: int = 0) -> pd.DataFrame:
    """Rastgele yürüyüş — gerçekçi ama sentetik barlar."""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    spread = rng.uniform(0.3, 1.2, n)
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
        "open": close + rng.normal(0, 0.2, n),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.integers(1_000, 10_000, n),
        "trade_count": rng.integers(10, 100, n),
        "vwap": close,
    })


# ------------------------------------------------------------ SIZINTI --

def test_feature_does_not_depend_on_the_future():
    """EN KRİTİK TEST: geleceği değiştir, bugünün değeri değişmemeli.

    Ortalanmış pencere (argrelextrema tarzı) kullanılsaydı bu test patlardı.
    """
    df = make_bars(60)
    original = channel_position(df, n=20)

    tampered = df.copy()
    cut = 40
    tampered.loc[cut:, "high"] *= 5.0      # geleceği tanınmaz hâle getir
    tampered.loc[cut:, "low"] *= 0.2
    tampered.loc[cut:, "close"] *= 3.0
    after = channel_position(tampered, n=20)

    pd.testing.assert_series_equal(original.iloc[:cut], after.iloc[:cut])


def test_label_does_depend_on_the_future():
    """Etiket ileriye BAKMALI — aksi halde hedef değil, özellik olurdu."""
    df = make_bars(60)
    original = forward_return(df, k=1)

    tampered = df.copy()
    tampered.loc[41:, "close"] *= 2.0
    after = forward_return(tampered, k=1)

    assert original.iloc[40] != after.iloc[40], "etiket geleceği görmüyor"


def test_warmup_rows_are_nan_not_filled():
    """Pencere dolmadan değer üretilmemeli; uydurma değerle doldurulmamalı."""
    pos = channel_position(make_bars(60), n=20)
    assert pos.iloc[:19].isna().all()
    assert pos.iloc[19:].notna().all()


def test_label_tail_is_nan():
    """Son k satırda cevap yok."""
    ret = forward_return(make_bars(60), k=3)
    assert ret.iloc[-3:].isna().all()
    assert ret.iloc[:-3].notna().all()


# ----------------------------------------------------------- DOĞRULUK --

def test_position_is_bounded():
    pos = channel_position(make_bars(300, seed=7), n=20).dropna()
    assert pos.min() >= 0.0 and pos.max() <= 1.0


def test_close_at_channel_low_gives_zero():
    df = make_bars(30)
    df.loc[:, "low"] = 50.0            # sabit taban
    df.loc[29, "close"] = 50.0         # kapanış tam tabanda
    assert channel_position(df, n=20).iloc[29] == pytest.approx(0.0)


def test_close_at_channel_high_gives_one():
    df = make_bars(30)
    df.loc[:, "high"] = 500.0
    df.loc[29, "close"] = 500.0
    assert channel_position(df, n=20).iloc[29] == pytest.approx(1.0)


def test_flat_channel_returns_half():
    """high == low: 'dip mi tepe mi' sorusunun tanımlı cevabı yok."""
    df = make_bars(30)
    for col in ("open", "high", "low", "close", "vwap"):
        df[col] = 100.0
    assert channel_position(df, n=20).iloc[29] == pytest.approx(0.5)


def test_window_uses_exactly_n_bars():
    """N barlık pencere, N+1 bar öncesini görmemeli."""
    df = make_bars(30)
    df.loc[:, "low"] = 90.0
    df.loc[5, "low"] = 10.0            # yalnızca 5. barda derin bir dip
    pos = channel_position(df, n=10)
    # 14. bar penceresi (5..14) dibi görür; 16. bar (7..16) görmez
    assert pos.iloc[14] != pos.iloc[16]
    lowest_at_16 = df["low"].iloc[7:17].min()
    assert lowest_at_16 == pytest.approx(90.0)


# -------------------------------------------------------------- ETİKET --

def test_direction_respects_cost_threshold():
    """Maliyeti geçmeyen hareket 'yön' sayılmamalı."""
    df = make_bars(10)
    df["close"] = [100.0, 100.05, 101.0, 99.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    no_cost = forward_direction(df, k=1, cost=0.0)
    with_cost = forward_direction(df, k=1, cost=0.001)   # 10 baz puan
    assert no_cost.iloc[0] == 1.0       # +%0.05 → maliyetsiz yukarı
    assert with_cost.iloc[0] == 0.0     # maliyeti geçmiyor → yön yok
    assert with_cost.iloc[1] == 1.0     # +%0.95 → geçiyor


# --------------------------------------------------------------- TABLO --

def test_build_table_drops_invalid_rows_only():
    df = make_bars(200, seed=3)
    table = build_table(df, windows=(20, 50), k=1)
    assert table.notna().all().all(), "geçerli tabloda NaN kalmamalı"
    # 50 barlık ısınma + 1 barlık cevapsız kuyruk
    assert len(table) == 200 - 49 - 1
    assert table.attrs["dropped"] == 50


def test_build_table_keeps_all_requested_windows():
    table = build_table(make_bars(200, seed=4), windows=(20, 50, 100), k=1)
    for n in (20, 50, 100):
        assert f"kanal_konumu_{n}" in table.columns


def test_rejects_impossible_window():
    with pytest.raises(WindowError):
        channel_position(make_bars(10), n=50)
    with pytest.raises(WindowError):
        channel_position(make_bars(60), n=1)
    with pytest.raises(WindowError):
        forward_return(make_bars(60), k=0)


def test_valid_mask_requires_all_series():
    a = pd.Series([1.0, np.nan, 3.0])
    b = pd.Series([1.0, 2.0, np.nan])
    assert valid_mask(a, b).tolist() == [True, False, False]
