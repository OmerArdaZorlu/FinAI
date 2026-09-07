"""SQLite kalıcılık katmanı — geçmiş barlar ve indirme künyesi.

Tasarım kararları
-----------------
* **Tek dosya, düz tablo.** ARCHITECTURE.md §1: append-only, indeksli flat tablo.
* **Zaman TEXT (ISO-8601 UTC).** SQLite'ın datetime tipi yoktur. ISO-8601 UTC
  metni hem sözlüksel olarak hem kronolojik olarak aynı sırada dizilir, gözle
  okunur ve tz belirsizliği taşımaz. Epoch integer daha ucuz olurdu ama her
  hata ayıklamada zihinsel çeviri gerektirir.
* **`adjustment` birincil anahtarın PARÇASI.** Aynı sembol/zaman/frekans, farklı
  düzeltmeyle FARKLI fiyattır. Anahtara dahil edilmezse `raw` indirme `all`
  indirmeyi sessizce ezer ve model bölünme günlerinde sahte çöküş görür.
* **UPSERT (idempotent).** Aynı komutu iki kez çalıştırmak veriyi bozmaz;
  yinelenen bar üretmez, mevcut satırı tazeler.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import pandas as pd

from .schema import BAR_COLUMNS, validate_bars

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "market_data.db"

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Geçmiş ve canlı barların ortak deposu. Sütun adları src/data/schema.py
-- içindeki BAR_COLUMNS ile birebir aynıdır; ayrışırlarsa testler patlar.
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT    NOT NULL,
    timeframe   TEXT    NOT NULL,          -- '1Day', '1Hour', ...
    adjustment  TEXT    NOT NULL,          -- 'all' | 'raw' | 'split' | 'dividend'
    timestamp   TEXT    NOT NULL,          -- ISO-8601 UTC, barın AÇILIŞ zamanı
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL,
    trade_count INTEGER NOT NULL,
    vwap        REAL    NOT NULL,
    PRIMARY KEY (symbol, timeframe, adjustment, timestamp)
) WITHOUT ROWID;

-- Aralık taramaları için: "SPY 1Day all, 2016→2026" tipik sorgumuz.
CREATE INDEX IF NOT EXISTS idx_bars_series_time
    ON bars (symbol, timeframe, adjustment, timestamp);

-- İndirme künyesi. ASLA güncellenmez, yalnızca eklenir: her indirmenin
-- ne zaman, hangi parametrelerle yapıldığının değiştirilemez kaydı.
CREATE TABLE IF NOT EXISTS ingest_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    adjustment      TEXT NOT NULL,
    feed            TEXT NOT NULL,
    requested_start TEXT NOT NULL,
    requested_end   TEXT NOT NULL,
    actual_start    TEXT NOT NULL,
    actual_end      TEXT NOT NULL,
    rows_fetched    INTEGER NOT NULL,
    rows_written    INTEGER NOT NULL,
    source          TEXT NOT NULL,
    fetched_at_utc  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ingest_symbol_time
    ON ingest_log (symbol, fetched_at_utc);
"""

# bars tablosundaki sütun sırası: seri kimliği + kanonik bar şeması
_BAR_INSERT_COLUMNS = ("symbol", "timeframe", "adjustment", *BAR_COLUMNS)


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Şeması hazır bir bağlantı açar; çıkışta commit + close yapar."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.executescript(SCHEMA_SQL)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Veritabanını ve tabloları oluşturur (varsa dokunmaz)."""
    with connect(db_path):
        pass
    return Path(db_path)


def write_bars(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    adjustment: str,
) -> int:
    """Barları UPSERT eder; yazılan satır sayısını döndürür.

    df, kanonik BAR_COLUMNS şemasında olmalıdır — yazmadan önce doğrulanır.
    """
    validate_bars(df, symbol=symbol)

    out = df.copy()
    # tz-aware datetime -> ISO-8601 UTC metin. Saniye çözünürlüğü yeterli;
    # Alpaca bar zamanları saniye altı bileşen taşımaz.
    out["timestamp"] = out["timestamp"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    out.insert(0, "adjustment", adjustment)
    out.insert(0, "timeframe", timeframe)
    out.insert(0, "symbol", symbol)
    out = out[list(_BAR_INSERT_COLUMNS)]

    placeholders = ", ".join("?" * len(_BAR_INSERT_COLUMNS))
    columns = ", ".join(_BAR_INSERT_COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in BAR_COLUMNS[1:])
    sql = (
        f"INSERT INTO bars ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(symbol, timeframe, adjustment, timestamp) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, out.itertuples(index=False, name=None))
    return len(out)


def log_ingest(conn: sqlite3.Connection, record: dict) -> None:
    """İndirme künyesini append-only kütüğe yazar."""
    fields = (
        "symbol", "timeframe", "adjustment", "feed",
        "requested_start", "requested_end", "actual_start", "actual_end",
        "rows_fetched", "rows_written", "source", "fetched_at_utc",
    )
    missing = [f for f in fields if f not in record]
    if missing:
        raise ValueError(f"ingest_log kaydında eksik alan(lar): {missing}")
    conn.execute(
        f"INSERT INTO ingest_log ({', '.join(fields)}) "
        f"VALUES ({', '.join('?' * len(fields))})",
        tuple(record[f] for f in fields),
    )


def read_bars(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    timeframe: str = "1Day",
    adjustment: str = "all",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Bir seriyi kanonik şemada, timestamp'i UTC tz-aware olarak okur."""
    sql = (
        f"SELECT {', '.join(BAR_COLUMNS)} FROM bars "
        "WHERE symbol = ? AND timeframe = ? AND adjustment = ?"
    )
    params: list[object] = [symbol, timeframe, adjustment]
    if start:
        sql += " AND timestamp >= ?"
        params.append(start)
    if end:
        # Kapsayıcı üst sınır: '2024-01-31' verilince o günün barı da gelmeli.
        # Metin karşılaştırmasında bunu doğru yapmanın tek temiz yolu, ertesi
        # günün başlangıcıyla KESİN KÜÇÜK karşılaştırmasıdır.
        sql += " AND timestamp < ?"
        params.append((date.fromisoformat(end[:10]) + timedelta(days=1)).isoformat())
    sql += " ORDER BY timestamp"

    df = pd.read_sql_query(sql, conn, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df[list(BAR_COLUMNS)]


def list_series(conn: sqlite3.Connection) -> pd.DataFrame:
    """Veritabanındaki tüm serilerin özeti — ne var, ne kadar, hangi aralıkta."""
    return pd.read_sql_query(
        "SELECT symbol, timeframe, adjustment, COUNT(*) AS bars, "
        "       MIN(timestamp) AS first_bar, MAX(timestamp) AS last_bar "
        "FROM bars GROUP BY symbol, timeframe, adjustment "
        "ORDER BY symbol, timeframe, adjustment",
        conn,
    )
