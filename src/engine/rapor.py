"""Paper koşusunun asıl çıktısı: backtest ne varsaydı, gerçekte ne oldu.

Neden bu rapor
--------------
Backtest, fiyat seviyeye değince o seviyeden işlem yapıldığını varsayar
(`lab/backtest.py`, bar içi varsayımlar). Gerçekte emir biraz farklı fiyattan
dolar. Bu farkın büyüklüğü ancak sanal hesapta ölçülebilir — paper koşusunun
varlık sebebi kâr görmek değil, bu sayıyı öğrenmektir (TECH_DEBT.md TD-10,
TD-11).

    python -m src.engine.rapor
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from . import durum as D
from .broker import LIMIT_AL


def gerceklesmeler(conn: sqlite3.Connection) -> pd.DataFrame:
    """Dolan her emir: istenen seviye, gerçekleşen fiyat, aradaki fark.

    `fark_yuzde` işaretini **aleyhimize** yorumlayın:
      * alışta  + = backtest'in varsaydığından pahalıya aldık
      * satışta − = varsayılandan ucuza sattık
    `kayma_yuzde` bu ikisini tek işarete indirir: pozitif = aleyhimize.
    """
    df = pd.read_sql_query(
        "SELECT * FROM gerceklesmeler ORDER BY gerceklesme_utc", conn)
    if df.empty:
        return df

    df["fark_yuzde"] = (df["gerceklesen_fiyat"] / df["istenen_seviye"] - 1) * 100
    alis = df["tip"] == LIMIT_AL
    df["kayma_yuzde"] = df["fark_yuzde"].where(alis, -df["fark_yuzde"])
    df["tutar"] = df["gerceklesen_fiyat"] * df["adet"]
    return df


def islemler(conn: sqlite3.Connection) -> pd.DataFrame:
    """Kapanmış al-sat çiftleri: giriş, çıkış, getiri.

    Tek pozisyonla çalıştığımız için gerçekleşmeler sırayla al, sat, al, sat
    diye gider; eşleştirme bu sıraya dayanır.
    """
    g = gerceklesmeler(conn)
    if g.empty:
        return pd.DataFrame()

    satirlar, acik = [], None
    for r in g.itertuples():
        if r.tip == LIMIT_AL:
            acik = r
        elif acik is not None:
            satirlar.append({
                "alis_zamani": acik.gerceklesme_utc,
                "alis": acik.gerceklesen_fiyat,
                "satis_zamani": r.gerceklesme_utc,
                "satis": r.gerceklesen_fiyat,
                "adet": acik.adet,
                "getiri_yuzde": (r.gerceklesen_fiyat / acik.gerceklesen_fiyat - 1) * 100,
                "kazanc": (r.gerceklesen_fiyat - acik.gerceklesen_fiyat) * acik.adet,
            })
            acik = None
    return pd.DataFrame(satirlar)


def emir_ozeti(conn: sqlite3.Connection) -> pd.DataFrame:
    """Emirlerin akıbeti. İptal çokluğu hata değildir: alış seviyesi her bar
    değiştiği için emir her tur yenilenir."""
    return pd.read_sql_query(
        "SELECT tip, durum, COUNT(*) AS adet FROM emirler "
        "GROUP BY tip, durum ORDER BY tip, durum", conn)


def metin_rapor(conn: sqlite3.Connection) -> str:
    """Raporun okunur hali."""
    satirlar: list[str] = ["PAPER KOŞUSU — backtest varsayımı vs gerçekleşme", ""]

    g = gerceklesmeler(conn)
    if g.empty:
        satirlar.append("Henüz dolan emir yok. Rapor ilk işlemden sonra anlam kazanır.")
        s = pd.read_sql_query("SELECT COUNT(*) AS n, MIN(bar_zamani) AS ilk, "
                              "MAX(bar_zamani) AS son FROM sinyaller", conn).iloc[0]
        if s["n"]:
            satirlar.append(f"Kaydedilen karar: {s['n']} ({s['ilk']} → {s['son']})")
        return "\n".join(satirlar)

    satirlar.append("GERÇEKLEŞMELER")
    satirlar.append("%-20s %-9s %10s %10s %9s" % (
        "zaman", "tip", "istenen", "gerçekleşen", "kayma%"))
    for r in g.itertuples():
        satirlar.append("%-20s %-9s %10.2f %10.2f %+9.3f" % (
            r.gerceklesme_utc[:19], r.tip, r.istenen_seviye,
            r.gerceklesen_fiyat, r.kayma_yuzde))

    satirlar += ["", "KAYMA (pozitif = aleyhimize, backtest fazla iyimserdi)"]
    satirlar.append("  ortalama %+.3f%%   ortanca %+.3f%%   en kötü %+.3f%%" % (
        g["kayma_yuzde"].mean(), g["kayma_yuzde"].median(), g["kayma_yuzde"].max()))
    satirlar.append("  backtest'te varsayılan tek yönlü maliyet: 0.050%")
    satirlar.append("  ölçülen kaymanın maliyet varsayımını aştığı emir: %d / %d" % (
        int((g["kayma_yuzde"] > 0.05).sum()), len(g)))

    i = islemler(conn)
    if not i.empty:
        satirlar += ["", "KAPANMIŞ İŞLEMLER"]
        for r in i.itertuples():
            satirlar.append("  %s → %s  %.2f → %.2f  x%d  %+.2f%%  (%+.2f $)" % (
                r.alis_zamani[:10], r.satis_zamani[:10], r.alis, r.satis,
                r.adet, r.getiri_yuzde, r.kazanc))
        satirlar.append("  toplam %d işlem, %+.2f $" % (len(i), i["kazanc"].sum()))
    else:
        satirlar += ["", "Kapanmış işlem yok (pozisyon hâlâ açık olabilir)."]

    e = emir_ozeti(conn)
    if not e.empty:
        satirlar += ["", "EMİRLER"]
        for r in e.itertuples():
            satirlar.append(f"  {r.tip:<10} {r.durum:<12} {r.adet}")
        satirlar.append("  (iptal çokluğu normaldir: seviye her bar yenilenir)")

    return "\n".join(satirlar)


def main() -> int:
    cozumleyici = argparse.ArgumentParser(
        description="Paper koşusu raporu — backtest varsayımı vs gerçekleşme.")
    cozumleyici.add_argument("--db", type=Path, default=D.DEFAULT_PAPER_DB_PATH)
    args = cozumleyici.parse_args()

    with D.connect(args.db) as conn:
        print(metin_rapor(conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
