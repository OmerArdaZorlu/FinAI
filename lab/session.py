"""Seans filtresi — gün içi barları düzenli işlem saatlerine indirger.

Neden gerekli
-------------
Alpaca `1Hour` isteğinde **uzatılmış seansı da** döndürür (04:00–20:00 ET).
SPY'da ölçülen sonuç:

* Barların **%55'i** uzatılmış seanstan, ama hacmin yalnızca **%16'sını** taşıyor
* Günlerin **%47'sinde** günün zirvesi, **%48'inde** dibi uzatılmış seansta oluşuyor
* Uzatılmış seans günlük aralığı ortalama **%24** şişiriyor (medyan %13)

Yani filtresiz bir kanal hesabında alt/üst çizgiyi çoğu zaman hacmin binde
birini taşıyan bir bar belirler. Bu gürültü değil **yön hatası**: seyrek işlem
geniş spread'le gelir, uç fiyatlar sistematik olarak dışa taşar, kanal
olduğundan geniş görünür ve fiyat hep "ortalarda" çıkar.

DST
---
Filtre UTC'de sabit saat kullanmaz; `America/New_York`'a çevirip oradan keser.
Yaz/kış saati geçişinde UTC karşılığı 13:30 ↔ 14:30 arasında kayar — sabit UTC
kullanmak yılda iki kez yanlış barlarla çalışmak demektir (TECH_DEBT.md TD-17).

Bilinen sınırlar
----------------
* **09:00 barı aslında yarım saattir** (09:30–10:00). Süresi diğerlerinin yarısı
  ama açılış oynak olduğu için aralığı benzer (1.74 vs 1.85). Dışlamak isterseniz
  `include_open_bar=False`.
* **16:00 barı kapanış müzayedesini taşır** (hacmin %13'ü) ama uzatılmış seans
  işlemlerini de içerir. RTH içinde işlem yapıp kapanıştan önce çıkan bir
  strateji için son eyleme dönüştürülebilir bar 15:00 barıdır.
* **Gece boşluğu filtreyle çözülmez**: 15:00 barından ertesi 09:00 barına kadar
  fiyat hareket eder ve bu hiçbir bara girmez. Saatlik kanal bunu göremez.
"""

from __future__ import annotations

import pandas as pd

EXCHANGE_TZ = "America/New_York"

# Alpaca barları BAŞLANGIÇ saatiyle etiketler. Düzenli seans 09:30–16:00 ET:
#   09:00 barı → 09:30–10:00 (yarım)
#   10:00–15:00 → tam saatler
#   16:00 barı → kapanış müzayedesi + uzatılmış seans
FIRST_RTH_HOUR = 9
LAST_RTH_HOUR = 15


def exchange_hour(df: pd.DataFrame) -> pd.Series:
    """Her barın borsa saatindeki (New York) saat değeri. DST'ye duyarlı."""
    return df["timestamp"].dt.tz_convert(EXCHANGE_TZ).dt.hour


def regular_hours(df: pd.DataFrame, *, include_open_bar: bool = True) -> pd.DataFrame:
    """Yalnızca düzenli seans barlarını döndürür (09:30–16:00 ET).

    Args:
        df: Kanonik bar tablosu, `timestamp` UTC tz-aware.
        include_open_bar: 09:00 barı (09:30–10:00, yarım saat) dahil edilsin mi.

    Returns:
        Filtrelenmiş tablo, indeks sıfırlanmış. Girdi zaten günlük barlardan
        oluşuyorsa (gün başına tek bar) tablo değişmeden döner.
    """
    hour = exchange_hour(df)
    first = FIRST_RTH_HOUR if include_open_bar else FIRST_RTH_HOUR + 1
    mask = hour.between(first, LAST_RTH_HOUR)
    return df.loc[mask].reset_index(drop=True)


def session_report(df: pd.DataFrame) -> pd.DataFrame:
    """Saat bazında bar sayısı ve hacim payı — filtrenin ne kestiğini gösterir."""
    hour = exchange_hour(df)
    grouped = df.assign(saat=hour).groupby("saat")
    out = grouped.agg(bar=("close", "size"), toplam_hacim=("volume", "sum"))
    out["hacim_payi"] = out["toplam_hacim"] / out["toplam_hacim"].sum()
    out["seans"] = [
        "düzenli" if FIRST_RTH_HOUR <= h <= LAST_RTH_HOUR else "uzatılmış"
        for h in out.index
    ]
    return out[["bar", "hacim_payi", "seans"]]


def bars_per_day(df: pd.DataFrame) -> float:
    """Gün başına ortalama bar — filtrenin beklendiği gibi çalıştığının hızlı kontrolü."""
    days = df["timestamp"].dt.tz_convert(EXCHANGE_TZ).dt.date.nunique()
    return len(df) / days if days else 0.0
