"""H-001 — Kanal konumu (range / mean-reversion) hipotezinin ölçüm araçları.

Bu modül **aday** bir özelliğin hesabıdır. Hipotez anlamlı çıkarsa
`src/features.py`'a taşınır (ARCHITECTURE.md §5, adım 4); çıkmazsa burada
kalır ve kayıt defterinde reddedilmiş olarak durur.

Sızıntı sözleşmesi
------------------
Bu dosyada iki tür fonksiyon var ve **karıştırılmamaları hayati**:

* `channel_position()` — ÖZELLİK. Yalnızca **geriye** bakar. Bugün dahil son N
  bar. Gelecekten tek bir sayı bile kullanmaz.
* `forward_return()` / `forward_direction()` — ETİKET (y). Tanımı gereği
  **ileriye** bakar. Bu meşrudur, çünkü hedeftir — ama asla özellik olarak
  kullanılamaz ve `src/features.py`'a girmez (§6, Kural 2).

En sık yapılan hata: yerel dip/tepeyi ortalanmış (centered) pencereyle bulmak —
`scipy.signal.argrelextrema` gibi. Grafiğe bakınca dip bellidir çünkü
sonrasını görürsünüz; canlı sistemde o lüks yoktur. Böyle bir backtest %90
isabetli görünür ve canlıda para kaybeder.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class WindowError(ValueError):
    """Pencere parametresi veriyle uyuşmadığında yükseltilir."""


# ---------------------------------------------------------------- ÖZELLİK --

def channel_position(df: pd.DataFrame, n: int) -> pd.Series:
    """Fiyatın son N barlık kanal içindeki konumu — 0 (dip) ile 1 (tepe) arası.

        kanal_konumu = (Close − min(Low, N)) / (max(High, N) − min(Low, N))

    Pencere **bugün dahil, yalnızca geriye** bakar (`rolling(n)`), dolayısıyla
    canlıda da birebir aynı şekilde hesaplanabilir.

    İlk `n-1` satırda pencere dolmadığı için değer üretilmez — NaN kalır ve
    uydurma bir değerle **doldurulmaz** (§6, Kural 5). Bu satırlar
    `valid_mask()` ile ölçüm dışında bırakılır.

    Args:
        df: Kanonik bar tablosu.
        n: Pencere uzunluğu (bar sayısı).

    Returns:
        `[0, 1]` aralığında, `df` ile aynı indeksli seri. Kanal tamamen düz
        olduğunda (high == low, ör. işlem görmeyen bar) 0.5 döner — o barda
        "dip mi tepe mi" sorusunun tanımlı bir cevabı yoktur.
    """
    if n < 2:
        raise WindowError(f"n >= 2 olmalı, verilen: {n}")
    if n > len(df):
        raise WindowError(f"n={n}, tablodaki bar sayısından ({len(df)}) büyük.")

    lowest = df["low"].rolling(n).min()
    highest = df["high"].rolling(n).max()
    span = highest - lowest

    position = (df["close"] - lowest) / span.where(span > 0)
    position = position.where(span > 0, 0.5)      # düz kanal → tanımsız, ortala
    position = position.where(span.notna())       # pencere dolmadıysa NaN kalsın

    return position.rename(f"kanal_konumu_{n}")


# ------------------------------------------------------------------ ETİKET --

def forward_return(df: pd.DataFrame, k: int) -> pd.Series:
    """K bar sonrasının getirisi — ETİKET (y), özellik DEĞİL.

        y_t = Close_{t+k} / Close_t − 1

    İleriye bakar; bu tanımı gereğidir. Son `k` satırda cevap henüz yoktur,
    NaN kalır.
    """
    if k < 1:
        raise WindowError(f"k >= 1 olmalı, verilen: {k}")
    return (df["close"].shift(-k) / df["close"] - 1.0).rename(f"ileri_getiri_{k}")


def forward_direction(df: pd.DataFrame, k: int, cost: float = 0.0) -> pd.Series:
    """K bar sonrası yukarı mı — ETİKET (y), özellik DEĞİL.

    Yönü hedef almak, uç günlerin kayıp fonksiyonunu domine etmesini engeller:
    %10'luk bir gün de %0.1'lik bir gün de tek gözlem sayılır.

    Args:
        cost: İşlem maliyeti eşiği (ör. 0.0005 = 5 baz puan). Bu eşiği
            geçmeyen hareket "yön" sayılmaz — maliyeti karşılamayan bir
            tahminin doğru çıkması bir işe yaramaz (TECH_DEBT.md TD-11).

    Returns:
        1.0 (yukarı), 0.0 (aşağı/yatay), NaN (cevap yok).
    """
    fwd = forward_return(df, k)
    direction = (fwd > cost).astype(float)
    return direction.where(fwd.notna()).rename(f"ileri_yon_{k}")


# ------------------------------------------------------------- GEÇERLİLİK --

def valid_mask(*series: pd.Series) -> pd.Series:
    """Verilen serilerin hepsinin tanımlı olduğu satırları işaretler.

    Özelliğin ısınma (warm-up) dönemi ile etiketin cevapsız kuyruğunu tek
    seferde eler. Ölçüm yalnızca bu maskenin `True` olduğu satırlarda yapılır.
    """
    if not series:
        raise ValueError("En az bir seri verilmeli.")
    mask = pd.Series(True, index=series[0].index)
    for s in series:
        mask &= s.notna()
    return mask


def build_table(
    df: pd.DataFrame,
    *,
    windows: tuple[int, ...],
    k: int,
    cost: float = 0.0,
) -> pd.DataFrame:
    """Ölçüm tablosunu kurar: zaman + kanal konumu sütunları + etiketler.

    Args:
        df: Kanonik bar tablosu.
        windows: Denenecek N değerleri. **Hepsi baştan yazılır** — sonradan
            "bir de şunu deneyelim" demek, sayaca eklenmemiş bir denemedir
            (ARCHITECTURE.md §7.4).
        k: Etiket ufku (bar).
        cost: Yön etiketinde kullanılacak maliyet eşiği.

    Returns:
        Yalnızca **geçerli** satırları içeren tablo (ısınma ve cevapsız kuyruk
        atılmış). Kaç satır düştüğü `attrs["dropped"]` içinde tutulur.
    """
    out = pd.DataFrame({"timestamp": df["timestamp"], "close": df["close"]})

    features = []
    for n in windows:
        col = channel_position(df, n)
        out[col.name] = col
        features.append(col)

    ret = forward_return(df, k)
    direction = forward_direction(df, k, cost=cost)
    out[ret.name] = ret
    out[direction.name] = direction

    mask = valid_mask(*features, ret)
    result = out.loc[mask].reset_index(drop=True)
    result.attrs["dropped"] = int((~mask).sum())
    result.attrs["windows"] = windows
    result.attrs["k"] = k
    result.attrs["cost"] = cost
    return result
