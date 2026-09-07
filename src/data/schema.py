"""Kanonik bar şeması ve doğrulama.

Bu modül, diske yazılan her geçmiş veri dosyasının uyması gereken tek
sözleşmedir. Sütun adları ve SIRASI sabittir; değişmesi model uyumsuzluğu
sayılır (bkz. ARCHITECTURE.md §6, Değişmez Kural 4).
"""

from __future__ import annotations

import pandas as pd

# Sabit sıralı şema. Sıra değiştirilemez.
BAR_COLUMNS: tuple[str, ...] = (
    "timestamp",     # UTC, tz-aware, barın AÇILIŞ zamanı
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
)

NUMERIC_COLUMNS: tuple[str, ...] = BAR_COLUMNS[1:]


class ValidationError(ValueError):
    """Bar verisi sözleşmeyi ihlal ettiğinde yükseltilir."""


def validate_bars(df: pd.DataFrame, *, symbol: str = "?") -> None:
    """Bar tablosunu sözleşmeye göre denetler; ihlalde ValidationError yükseltir.

    Sessizce düzeltme YAPMAZ. Bozuk veri, sessizce temizlenmiş veriden iyidir:
    ilkini fark ederiz, ikincisi modele yalan söyletir.
    """
    problems: list[str] = []

    if tuple(df.columns) != BAR_COLUMNS:
        raise ValidationError(
            f"[{symbol}] sütun şeması uyuşmuyor.\n"
            f"  beklenen: {BAR_COLUMNS}\n"
            f"  gelen   : {tuple(df.columns)}"
        )

    if df.empty:
        raise ValidationError(f"[{symbol}] tablo boş — istenen aralıkta bar yok.")

    ts = df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        problems.append("timestamp datetime tipinde değil")
    elif ts.dt.tz is None:
        problems.append("timestamp tz-naive — UTC olarak tz-aware olmalı")

    if ts.duplicated().any():
        dupes = ts[ts.duplicated()].head(3).tolist()
        problems.append(f"yinelenen timestamp ({ts.duplicated().sum()} adet, ilk: {dupes})")

    if not ts.is_monotonic_increasing:
        problems.append("timestamp artan sırada değil")

    for col in NUMERIC_COLUMNS:
        n_null = int(df[col].isna().sum())
        if n_null:
            problems.append(f"{col}: {n_null} adet NaN (tolerans sıfır)")

    ohlc = ["open", "high", "low", "close"]
    if df[ohlc].notna().all().all():
        nonpositive = int((df[ohlc] <= 0).any(axis=1).sum())
        if nonpositive:
            problems.append(f"{nonpositive} barda OHLC <= 0")

        bad_hl = int((df["high"] < df["low"]).sum())
        if bad_hl:
            problems.append(f"{bad_hl} barda high < low")

        bad_hi = int((df["high"] < df[["open", "close"]].max(axis=1)).sum())
        if bad_hi:
            problems.append(f"{bad_hi} barda high < max(open, close)")

        bad_lo = int((df["low"] > df[["open", "close"]].min(axis=1)).sum())
        if bad_lo:
            problems.append(f"{bad_lo} barda low > min(open, close)")

    neg_vol = int((df["volume"] < 0).sum())
    if neg_vol:
        problems.append(f"{neg_vol} barda negatif hacim")

    if problems:
        raise ValidationError(
            f"[{symbol}] {len(problems)} sorun bulundu:\n  - " + "\n  - ".join(problems)
        )
