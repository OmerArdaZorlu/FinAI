"""Kuralları geçmiş barlar üzerinde sırayla uygulayan döngü (backtest çekirdeği).

Neden `src/` altında
--------------------
Bu döngü önce `lab/backtest.py`'deydi. Arayüzün "backtest katmanı" aynı
döngüye ihtiyaç duyuyor, ama arayüz üretim kodu ve **`src/` asla `lab/`'ı
import etmez** (üretim ↔ araştırma sınırı). `Kurallar` ve `session.py`'de
yapılanın aynısı: parça buraya taşındı, `lab/backtest.py` yeniden dışa
veriyor. Tek kopya kalır; defterler ve testler değişmez.

Kurallar burada DA değil — `kural.py`'de. Bu dosya çizgileri hesaplar, barları
sırayla `uygula()`'ya verir ve para/hisse muhasebesini tutar. Bar içi
varsayımlar ve sızıntı kuralı `lab/backtest.py` başlığında anlatılıyor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .kural import (
    AL,
    SEBEP_DONEM_SONU,
    Bar,
    Cizgi,
    Durum,
    Kurallar,
    emir_seviyeleri,
    uygula,
)

__all__ = ["Sonuc", "cizgiler", "bollinger_cizgiler", "calistir"]


@dataclass(frozen=True)
class Sonuc:
    """Denemenin çıktısı."""

    islemler: pd.DataFrame    # her al-sat bir satır
    bakiye: pd.Series         # her bar sonunda paranın değeri (1.0 = başlangıç)
    cizgiler: pd.DataFrame    # timestamp, tepe, dip — grafikte çizmek için
    kurallar: Kurallar
    # Her bar sonunda geçerli seviyeler (2026-09-11 eklendi):
    #   alis_seviyesi — pozisyon yokken o barda alış seviyesi
    #   koruma        — pozisyon varken bir sonraki barda geçerli satış seviyesi
    #                   (zararına satış ya da takip eden stop)
    #   takipte       — takip eden stop devrede mi
    seviyeler: pd.DataFrame | None = None


def cizgiler(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Tepe ve dip çizgisi — yalnızca ÖNCEKİ `n` bardan (bugün hariç)."""
    if n < 2:
        raise ValueError(f"n >= 2 olmalı, verilen: {n}")
    return pd.DataFrame({
        "timestamp": df["timestamp"],
        "tepe": df["high"].rolling(n).max().shift(1),
        "dip": df["low"].rolling(n).min().shift(1),
    })


def bollinger_cizgiler(df: pd.DataFrame, n: int, k: float = 2.0) -> pd.DataFrame:
    """Ortalamayı takip eden bant — yalnızca ÖNCEKİ `n` kapanıştan (bugün hariç).

        orta = son n kapanışın ortalaması
        tepe = orta + k × sapma      dip = orta − k × sapma

    Fiyat yükselince ortalama da yükselir, dip çizgisi fiyatın arkasından
    yukarı gelir. Donchian'da ise dip, fiyat ne kadar yükselirse yükselsin
    n bar boyunca eski en düşük seviyede kalır.
    """
    if n < 2:
        raise ValueError(f"n >= 2 olmalı, verilen: {n}")
    orta = df["close"].rolling(n).mean().shift(1)
    sapma = df["close"].rolling(n).std().shift(1)
    return pd.DataFrame({
        "timestamp": df["timestamp"],
        "tepe": orta + k * sapma,
        "dip": orta - k * sapma,
        "orta": orta,
    })


def calistir(df: pd.DataFrame, kurallar: Kurallar) -> Sonuc:
    """Sistemi bar bar uygular.

    Args:
        df: Kanonik bar tablosu (`timestamp`, `open`, `high`, `low`, `close`),
            zamana göre sıralı.
        kurallar: Sistem ayarları.
    """
    k = kurallar
    if k.cizgi == "donchian":
        lines = cizgiler(df, k.n)
    else:
        lines = bollinger_cizgiler(df, k.n, k.sapma_katsayisi)
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    tepe = lines["tepe"].to_numpy(float)
    dip = lines["dip"].to_numpy(float)
    ts = df["timestamp"].to_numpy()

    nakit = 1.0
    adet = 0.0                 # elimizdeki hisse (kesirli)
    durum = Durum()            # kuralın gördüğü pozisyon hali
    giris_i = -1
    giris_fiyat = np.nan
    islemler: list[dict] = []
    bakiye = np.empty(len(df))
    alis_kayit = np.full(len(df), np.nan)
    koruma_kayit = np.full(len(df), np.nan)
    takip_kayit = np.zeros(len(df), dtype=bool)

    def kaydet_satis(i: int, fiyat: float, sebep: str) -> None:
        """Kapanan işlemi deftere yazar. Para muhasebesi çağıranda."""
        islemler.append({
            "alis_zamani": ts[giris_i], "alis": giris_fiyat,
            "satis_zamani": ts[i], "satis": fiyat, "sebep": sebep,
            "bar": i - giris_i,
            "getiri": fiyat / giris_fiyat - 1,
            "getiri_maliyetli": (fiyat * (1 - k.maliyet))
                                / (giris_fiyat * (1 + k.maliyet)) - 1,
        })

    for i in range(len(df)):
        if np.isnan(tepe[i]):          # çizgiler henüz oluşmadı
            bakiye[i] = nakit
            continue

        cizgi = Cizgi(tepe[i], dip[i])
        bar = Bar(o[i], h[i], lo[i], c[i])

        # Motorun bu bar için koyacağı emirler — grafikte göstermek için kaydet.
        if not durum.acik:
            alis_kayit[i] = emir_seviyeleri(durum, cizgi, k).alis

        durum, olaylar = uygula(durum, bar, cizgi, k)

        for olay in olaylar:
            if olay.eylem == AL:
                giris_i = i
                giris_fiyat = olay.fiyat
                adet = nakit / (olay.fiyat * (1 + k.maliyet))
                nakit = 0.0
            else:
                nakit = adet * olay.fiyat * (1 - k.maliyet)
                kaydet_satis(i, olay.fiyat, olay.sebep)
                adet = 0.0

        # Açık pozisyon, o anki kapanıştan satılsaydı ne ederdi
        bakiye[i] = nakit + adet * c[i] * (1 - k.maliyet)
        if adet:
            koruma_kayit[i] = durum.stop
            takip_kayit[i] = durum.takipte

    if adet:
        nakit = adet * c[-1] * (1 - k.maliyet)
        kaydet_satis(len(df) - 1, c[-1], SEBEP_DONEM_SONU)
        adet = 0.0
        durum = Durum()
        bakiye[-1] = nakit

    return Sonuc(
        islemler=pd.DataFrame(islemler),
        bakiye=pd.Series(bakiye, index=pd.DatetimeIndex(ts), name="bakiye"),
        cizgiler=lines,
        kurallar=k,
        seviyeler=pd.DataFrame({
            "timestamp": df["timestamp"].to_numpy(),
            "alis_seviyesi": alis_kayit,
            "koruma": koruma_kayit,
            "takipte": takip_kayit,
        }, index=df.index),
    )
