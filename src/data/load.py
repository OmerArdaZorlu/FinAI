"""Araştırma tarafının veri okuma arayüzü.

Jupyter ve train.py bu fonksiyonları kullanır — ham `sqlite3` veya
`pd.read_csv` çağırmayın: tz-aware okuma ve şema doğrulaması burada
garanti edilir.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .db import DEFAULT_DB_PATH, connect, list_series, read_bars
from .schema import validate_bars


def load_bars(
    symbol: str,
    timeframe: str = "1Day",
    *,
    adjustment: str = "all",
    start: str | None = None,
    end: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    validate: bool = True,
) -> pd.DataFrame:
    """Kanonik şemada, timestamp'i UTC tz-aware bir bar tablosu döndürür."""
    if not Path(db_path).is_file():
        raise FileNotFoundError(
            f"{db_path} yok. Önce indirin:\n"
            f"  python scripts/fetch_bars.py --symbols {symbol} --timeframe {timeframe}"
        )

    with connect(db_path) as conn:
        df = read_bars(
            conn, symbol,
            timeframe=timeframe, adjustment=adjustment, start=start, end=end,
        )

    if df.empty:
        with connect(db_path) as conn:
            available = list_series(conn)
        raise ValueError(
            f"[{symbol} {timeframe} {adjustment}] için bar bulunamadı"
            + (f" ({start} → {end} aralığında)." if (start or end) else ".")
            + "\nVeritabanındaki seriler:\n"
            + (available.to_string(index=False) if not available.empty else "  (boş)")
        )

    if validate:
        validate_bars(df, symbol=symbol)
    return df


def load_ingest_log(db_path: Path | str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """İndirme künyeleri — hangi veri ne zaman, hangi parametrelerle çekildi."""
    with connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM ingest_log ORDER BY fetched_at_utc DESC", conn
        )


def available_series(db_path: Path | str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Veritabanında ne var — sembol, frekans, düzeltme, bar sayısı, aralık."""
    with connect(db_path) as conn:
        return list_series(conn)
