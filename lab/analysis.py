"""Hipotez ölçüm araçları — dilim tablosu, baseline, monotonluk.

Hipotezden bağımsızdır: "şu sütunun içinde, şu hedef hakkında bilgi var mı?"
sorusunu soran her hipotez bunları kullanır.

Bu modül **model eğitmez.** Amacı, model eklemeden önce sinyalin ham hâlde
görünüp görünmediğini ölçmek. Basit tabloda hiçbir şey yoksa, model onu
bulmaz — sadece gürültüyü ezberler.

Zayıf kanıt vs güçlü kanıt
--------------------------
* **Zayıf:** Yalnızca bir uç dilim parlıyor. On dilime bakıp en iyisini seçmek
  zaten on denemedir; birinin şansla parlaması beklenen bir şeydir.
* **Güçlü:** İlişki **monotonik** — dipten tepeye düzenli bir eğim var.
  Bu şansla kolay oluşmaz, gerçek bir mekanizmanın imzasıdır.

Bu yüzden birincil istatistik `rank_correlation()`'dır (dilim seçimi
içermez, dolayısıyla p-hacking'e kapalı); `bin_table()` yalnızca gözle
görmek içindir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RankResult:
    """Spearman sıra korelasyonu ve yaklaşık anlamlılığı."""

    rho: float          # −1..+1. Mean-reversion hipotezi NEGATİF bekler.
    t_stat: float
    p_value: float      # normal yaklaşıklık — küçük örneklemde kabaca doğru
    n: int
    effective_n: int    # örtüşen pencereler için düzeltilmiş

    def __repr__(self) -> str:  # pragma: no cover - yalnızca gösterim
        return (
            f"RankResult(rho={self.rho:+.4f}, p≈{self.p_value:.4g}, "
            f"n={self.n}, n_eff={self.effective_n})"
        )


def rank_correlation(
    x: pd.Series,
    y: pd.Series,
    *,
    horizon_bars: int = 1,
) -> RankResult:
    """Spearman sıra korelasyonu — H-001'in birincil istatistiği.

    Dilim/eşik seçimi içermez: tek bir sayı, tüm veriden. Bu yüzden
    "en iyi dilimi seçme" serbestliği yoktur.

    Args:
        x: Özellik (ör. kanal konumu).
        y: Hedef (ör. ileri getiri).
        horizon_bars: Etiket ufku. `k > 1` ise ardışık gözlemler örtüşür ve
            bağımsız değildir; anlamlılık bu yüzden `n/k` üzerinden hesaplanır.
            Bu muhafazakâr ama dürüst bir düzeltmedir.

    Returns:
        `RankResult`. `p_value` normal yaklaşıklıkla hesaplanır (scipy yok).
    """
    pair = pd.concat([x, y], axis=1).dropna()
    n = len(pair)
    if n < 10:
        raise ValueError(f"Anlamlı korelasyon için çok az satır: {n}")

    rho = float(pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman"))

    # Örtüşen pencereler bağımsız gözlem değildir.
    effective_n = max(int(n / max(horizon_bars, 1)), 3)

    if abs(rho) >= 1.0:
        t_stat = math.inf
    else:
        t_stat = rho * math.sqrt((effective_n - 2) / (1 - rho**2))

    # İki yönlü p, normal yaklaşıklık
    p_value = math.erfc(abs(t_stat) / math.sqrt(2))

    return RankResult(rho=rho, t_stat=t_stat, p_value=p_value, n=n, effective_n=effective_n)


def baseline(y: pd.Series, cost: float = 0.0) -> pd.Series:
    """Karşılaştırma tabanı: hiçbir şey bilmeseydik ne olurdu?

    Her sonucun yanında bu durmalı. "%54 yukarı" tek başına anlamsızdır;
    taban %53 ise hipotez bir şey söylemiyordur.
    """
    y = y.dropna()
    return pd.Series(
        {
            "bar": len(y),
            "ortalama_getiri": y.mean(),
            "medyan_getiri": y.median(),
            "yukari_orani": float((y > cost).mean()),
            "std": y.std(),
        }
    )


def bin_table(
    x: pd.Series,
    y: pd.Series,
    *,
    n_bins: int = 10,
    cost: float = 0.0,
) -> pd.DataFrame:
    """Özelliği dilimlere ayırıp her dilimde hedefin davranışını gösterir.

    Görsel/sezgisel amaçlıdır. Karar **`rank_correlation()`** ile verilir —
    dilim tablosuna bakıp en iyi dilimi seçmek p-hacking'dir.
    """
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(pair) < n_bins * 5:
        raise ValueError(f"{len(pair)} satır, {n_bins} dilim için çok az.")

    # Sabit aralıklar: kanal konumu zaten [0,1]'de tanımlı, qcut yerine cut
    # kullanmak dilim sınırlarını veriden bağımsız tutar.
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    pair["dilim"] = pd.cut(pair["x"], bins=edges, include_lowest=True)

    grouped = pair.groupby("dilim", observed=True)["y"]
    table = pd.DataFrame(
        {
            "bar": grouped.size(),
            "ortalama_getiri": grouped.mean(),
            "medyan_getiri": grouped.median(),
            "yukari_orani": grouped.apply(lambda s: float((s > cost).mean())),
            "std": grouped.std(),
        }
    )
    return table


def subperiod_report(
    table: pd.DataFrame,
    *,
    feature_col: str,
    target_col: str,
    horizon_bars: int,
    subperiods,
) -> pd.DataFrame:
    """Etkinin her rejimde görünüp görünmediğini raporlar.

    Tek bir alt dönemde çıkan etki, o rejime özgüdür — genel bir yasa değildir.
    İşaretin üç dönemde de aynı olması, tek dönemdeki güçlü sonuçtan daha
    değerlidir.

    Args:
        subperiods: `(isim, alt_tablo)` üreten bir iterable
            (bkz. `lab.splits.iter_subperiods`).
    """
    rows = []
    for name, part in subperiods:
        if len(part) < 30:
            rows.append({"donem": name, "bar": len(part), "rho": np.nan,
                         "p": np.nan, "not": "çok az bar"})
            continue
        res = rank_correlation(part[feature_col], part[target_col],
                               horizon_bars=horizon_bars)
        rows.append({
            "donem": name,
            "bar": res.n,
            "rho": res.rho,
            "p": res.p_value,
            "not": "",
        })
    return pd.DataFrame(rows)
