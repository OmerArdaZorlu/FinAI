#!/usr/bin/env python
"""Geçmiş bar indirici — CLI. Kaynak: Alpaca REST. Hedef: SQLite.

Kullanım:
    python scripts/fetch_bars.py --symbols SPY AAPL --timeframe 1Day --start 2016-01-01

Veriler `data/market_data.db` içindeki `bars` tablosuna UPSERT edilir; aynı
komutu tekrar çalıştırmak veriyi bozmaz, yinelenen bar üretmez. Her indirme
ayrıca `ingest_log` tablosuna künye olarak yazılır.

Bu script yalnızca GEÇMİŞ veri indirir. Canlı akış ayrı bir pipe'tır
(src/data/stream.py, ENV-B/C) ve bu script'le ilgisi yoktur.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.data.alpaca import AlpacaError, fetch_bars, get_credentials  # noqa: E402
from src.data.db import DEFAULT_DB_PATH, connect, list_series, log_ingest, write_bars  # noqa: E402
from src.data.schema import ValidationError  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Alpaca'dan geçmiş bar indirir ve SQLite'a yazar.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--symbols", nargs="+", default=["SPY"], help="Sembol listesi")
    p.add_argument("--timeframe", default="1Day", help="1Day, 1Hour, 15Min ...")
    p.add_argument("--start", default="2016-01-01", help="YYYY-MM-DD (dahil)")
    p.add_argument(
        "--end",
        default=None,
        help="YYYY-MM-DD (dahil). Varsayılan: dün — bugünün yarım barını almamak için.",
    )
    p.add_argument(
        "--adjustment",
        default="all",
        choices=["raw", "split", "dividend", "all"],
        help="Fiyat düzeltmesi. Araştırmada 'all' — 'raw' bölünme gününde sahte çöküş üretir.",
    )
    p.add_argument("--feed", default="sip", choices=["sip", "iex"], help="Veri kaynağı")
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite dosya yolu")
    p.add_argument(
        "--csv-dir",
        type=Path,
        default=None,
        help="Verilirse ayrıca CSV dışa aktarılır (Excel/Sheets ile QC için). "
             "Kaynak-doğru (source of truth) her zaman veritabanıdır.",
    )
    return p.parse_args(argv)


def default_end() -> str:
    """Dün. Bugünün barı henüz kapanmadığı için asla indirilmez."""
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _force_utf8_output() -> None:
    """Windows konsolu varsayılan olarak cp1254'tür; Türkçe karakterler bozulur."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = parse_args(argv)
    if args.end is None:
        args.end = default_end()

    try:
        creds = get_credentials(REPO_ROOT / ".env")
    except AlpacaError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2

    print(
        f"Alpaca REST — geçmiş bar indirme\n"
        f"  semboller : {', '.join(args.symbols)}\n"
        f"  frekans   : {args.timeframe}\n"
        f"  aralık    : {args.start} → {args.end}\n"
        f"  düzeltme  : {args.adjustment}   feed: {args.feed}\n"
        f"  hedef     : {args.db}\n"
    )

    failures = 0
    with connect(args.db) as conn:
        for symbol in args.symbols:
            try:
                df = fetch_bars(
                    symbol,
                    start=args.start,
                    end=args.end,
                    timeframe=args.timeframe,
                    adjustment=args.adjustment,
                    feed=args.feed,
                    credentials=creds,
                )
                written = write_bars(
                    conn, df,
                    symbol=symbol,
                    timeframe=args.timeframe,
                    adjustment=args.adjustment,
                )
                log_ingest(conn, {
                    "symbol": symbol,
                    "timeframe": args.timeframe,
                    "adjustment": args.adjustment,
                    "feed": args.feed,
                    "requested_start": args.start,
                    "requested_end": args.end,
                    "actual_start": df["timestamp"].iloc[0].isoformat(),
                    "actual_end": df["timestamp"].iloc[-1].isoformat(),
                    "rows_fetched": int(len(df)),
                    "rows_written": int(written),
                    "source": "alpaca-data-v2/stocks/bars",
                    "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                })
            except (AlpacaError, ValidationError) as exc:
                print(f"  [{symbol}] BAŞARISIZ: {exc}\n", file=sys.stderr)
                failures += 1
                continue

            span = f"{df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()}"
            print(f"  [{symbol}] OK — {written} bar yazıldı, {span}")

            if args.csv_dir:
                args.csv_dir.mkdir(parents=True, exist_ok=True)
                csv_path = args.csv_dir / f"{symbol}_{args.timeframe}_{args.adjustment}.csv"
                df.to_csv(csv_path, index=False)
                print(f"            CSV dışa aktarıldı → {csv_path}")

        print("\nVeritabanındaki seriler:")
        print(list_series(conn).to_string(index=False))

    if failures:
        print(f"\n{failures} sembol başarısız.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
