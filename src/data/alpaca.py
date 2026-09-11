"""Alpaca Market Data API v2 — GEÇMİŞ bar indirici (REST).

Kapsam: yalnızca tarihsel veri. Bu modül canlı WebSocket akışına bağlanmaz,
emir göndermez, broker uç noktasına dokunmaz (ENV-A kuralı,
ENVIRONMENTS.md §2: bu ortamda anahtar emir yetkisi taşımaz).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from .schema import BAR_COLUMNS, validate_bars

DATA_BASE_URL = "https://data.alpaca.markets/v2"
MAX_LIMIT = 10_000          # Alpaca'nın sayfa başına üst sınırı
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.5

# Alpaca JSON alan adları -> kanonik şema adlarımız
_FIELD_MAP = {
    "t": "timestamp",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "n": "trade_count",
    "vw": "vwap",
}


class AlpacaError(RuntimeError):
    """Alpaca API çağrısı kurtarılamaz biçimde başarısız olduğunda."""


@dataclass(frozen=True)
class Credentials:
    key_id: str
    secret_key: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
            "accept": "application/json",
        }


def load_dotenv(path: str | Path = ".env") -> None:
    """.env dosyasındaki KEY=VALUE satırlarını ortama yükler (varsa).

    Zaten tanımlı ortam değişkenlerinin üzerine YAZMAZ — kabuktan verilen
    değer her zaman dosyadakini yener.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_credentials(dotenv_path: str | Path = ".env") -> Credentials:
    """Anahtarları ortamdan (veya .env'den) okur.

    Beklenen değişkenler: APCA_API_KEY_ID, APCA_API_SECRET_KEY
    """
    load_dotenv(dotenv_path)
    key_id = os.environ.get("APCA_API_KEY_ID", "").strip()
    secret = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if not key_id or not secret:
        raise AlpacaError(
            "Alpaca anahtarları bulunamadı.\n"
            f"  {Path(dotenv_path).resolve()} dosyasına şunları ekleyin:\n"
            "    APCA_API_KEY_ID=...\n"
            "    APCA_API_SECRET_KEY=...\n"
            "  (.env zaten .gitignore'da — repoya girmez.)"
        )
    return Credentials(key_id, secret)


def _get_with_retry(url: str, params: dict, headers: dict) -> dict:
    """GET + üstel geri çekilme. 429 ve 5xx yeniden denenir, 4xx anında patlar."""
    last_error = ""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            last_error = f"ağ hatası: {exc}"
        else:
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise AlpacaError(
                    f"Kimlik doğrulama reddedildi (HTTP {resp.status_code}). "
                    "APCA_API_KEY_ID / APCA_API_SECRET_KEY doğru mu?"
                )
            if resp.status_code < 500 and resp.status_code != 429:
                raise AlpacaError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"

        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

    raise AlpacaError(f"{MAX_RETRIES} denemenin ardından başarısız — son hata: {last_error}")


def fetch_bars(
    symbol: str,
    *,
    start: str,
    end: str,
    timeframe: str = "1Day",
    adjustment: str = "all",
    feed: str = "sip",
    credentials: Credentials | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Tek bir sembol için geçmiş barları indirir; kanonik şemada DataFrame döner.

    Args:
        symbol: Örn. "SPY".
        start / end: "YYYY-MM-DD" (dahil / hariç değil — Alpaca her ikisini de kapsar).
        timeframe: "1Day", "1Hour", "15Min" ...
        adjustment: "all" (bölünme + temettü). Araştırmada varsayılan budur;
            "raw" ile eğitilen model, bölünme günlerinde uydurma %50 düşüş görür.
        feed: "sip" (konsolide, tüm borsalar). Ücretsiz planda sorgu bitişi
            15 dakikadan eskiyse tam SIP verilir (bkz. TECH_DEBT.md AK-3).

    Returns:
        BAR_COLUMNS sırasında, timestamp'e göre artan sıralı DataFrame.
    """
    creds = credentials or get_credentials()
    url = f"{DATA_BASE_URL}/stocks/bars"
    params = {
        "symbols": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "adjustment": adjustment,
        "feed": feed,
        "limit": MAX_LIMIT,
        "sort": "asc",
    }

    rows: list[dict] = []
    page = 0
    while True:
        payload = _get_with_retry(url, params, creds.headers)
        batch = (payload.get("bars") or {}).get(symbol) or []
        rows.extend(batch)
        page += 1
        if verbose:
            print(f"  [{symbol}] sayfa {page}: {len(batch):>6} bar (toplam {len(rows)})", flush=True)

        token = payload.get("next_page_token")
        if not token:
            break
        params["page_token"] = token

    if not rows:
        raise AlpacaError(
            f"[{symbol}] {start} — {end} aralığında hiç bar dönmedi. "
            "Sembol, tarih aralığı ve feed ayarını kontrol edin."
        )

    df = pd.DataFrame(rows).rename(columns=_FIELD_MAP)

    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        raise AlpacaError(f"[{symbol}] API yanıtında eksik alan(lar): {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = df[list(BAR_COLUMNS)].sort_values("timestamp").reset_index(drop=True)

    validate_bars(df, symbol=symbol)
    return df
