"""Arayüzün veri katmanı — YALNIZCA okur.

Veritabanları `mode=ro` ile açılır: SQLite bu bağlantı üzerinden yazmayı
reddeder. Arayüzdeki bir hata işlem kaydını bozamasın, ve veritabanına tek
yazar motor olsun diye (AK-4). `durum.connect` bu yüzden kullanılmıyor — o
her açılışta şema betiğini çalıştırır, yani yazar.

Grafik zamanı
-------------
lightweight-charts zamanı UTC gösterir. Borsa saatleri New York'ta; eksende
"09:30" görünsün diye zaman damgası New York duvar saatine çevrilip UTC'ymiş
gibi verilir. Yalnızca gösterim içindir.

Kasa
----
Backtest katmanı **kasa başlangıcında durur** (`src/data/kasa.py`). Kasayı
açma kararı henüz verilmedi; grafiğe bakmak da kasaya bakmaktır ve geri
alınamaz. Mumlar ise gösterilir — motor zaten güncel fiyatla çalışıyor.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

from src.data.kasa import RESEARCH_END, VAULT_BEGINS
from src.data.schema import BAR_COLUMNS
from src.data.session import EXCHANGE_TZ, regular_hours
from src.engine.motor import KURALLAR_KABUL1
from src.engine.tekrar import calistir

ARALIKLAR = {
    "60g": "Son 60 gün",
    "1y": "Son 1 yıl",
    "arastirma": "Araştırma dönemi (kasa hariç)",
}


# --------------------------------------------------------------- BAĞLANTI --

@contextmanager
def salt_okur(yol: Path | str) -> Iterator[sqlite3.Connection | None]:
    """Salt-okur bağlantı. Dosya yoksa None verir (arayüz boş gösterir)."""
    yol = Path(yol)
    if not yol.is_file():
        yield None
        return
    conn = sqlite3.connect(f"file:{yol.resolve().as_posix()}?mode=ro", uri=True,
                           timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _tablo_var(conn: sqlite3.Connection, ad: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ad,)).fetchone() is not None


# ------------------------------------------------------------------- ZAMAN --

def grafik_zamani(ts: pd.Series) -> list[int]:
    """UTC zaman damgalarını New York duvar saatine çevirip saniye olarak verir."""
    yerel = pd.to_datetime(ts, utc=True).dt.tz_convert(EXCHANGE_TZ).dt.tz_localize(None)
    return (yerel.astype("int64") // 10**9).tolist()


def _sayi(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, 4)


# ---------------------------------------------------------------- HİSSELER --

def hisseler(veri_db: Path, paper_db: Path, motor_sembolu: str) -> list[dict]:
    """Depodaki saatlik seriler + motorun izlediği sembolün pozisyonu."""
    semboller: list[dict] = []
    with salt_okur(veri_db) as c:
        if c is not None:
            for r in c.execute(
                "SELECT symbol, MAX(timestamp) AS son FROM bars "
                "WHERE timeframe='1Hour' AND adjustment='all' GROUP BY symbol "
                "ORDER BY symbol"):
                semboller.append({"sembol": r["symbol"], "son_bar": r["son"],
                                  "motor": r["symbol"] == motor_sembolu})
    if not any(s["motor"] for s in semboller):
        semboller.insert(0, {"sembol": motor_sembolu, "son_bar": None, "motor": True})

    pozisyon = {"acik": False, "adet": 0}
    with salt_okur(paper_db) as c:
        if c is not None and _tablo_var(c, "motor_durumu"):
            r = c.execute("SELECT * FROM motor_durumu WHERE id=1").fetchone()
            if r is not None and r["acik"]:
                pozisyon = {"acik": True, "adet": r["adet"],
                            "giris": _sayi(r["giris_fiyat"]), "stop": _sayi(r["stop"]),
                            "takipte": bool(r["takipte"])}
    for s in semboller:
        s["pozisyon"] = pozisyon if s["motor"] else None
    # Motorun sembolü en üstte.
    semboller.sort(key=lambda s: (not s["motor"], s["sembol"]))
    return semboller


# ------------------------------------------------------------------ BARLAR --

def _aralik_sinirlari(aralik: str, son: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    if aralik == "arastirma":
        return (pd.Timestamp("2016-01-01", tz="UTC"),
                pd.Timestamp(VAULT_BEGINS, tz="UTC"))
    gun = 365 if aralik == "1y" else 60
    return son - pd.Timedelta(days=gun), son + pd.Timedelta(days=1)


def _seans_barlari(veri_db: Path, sembol: str) -> pd.DataFrame:
    with salt_okur(veri_db) as c:
        if c is None:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        df = pd.read_sql_query(
            f"SELECT {', '.join(BAR_COLUMNS)} FROM bars WHERE symbol=? "
            "AND timeframe='1Hour' AND adjustment='all' ORDER BY timestamp",
            c, params=[sembol])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return regular_hours(df).reset_index(drop=True)


def barlar(veri_db: Path, sembol: str, aralik: str = "60g") -> dict:
    """Mum verisi, seçilen aralıkta."""
    df = _seans_barlari(veri_db, sembol)
    if df.empty:
        return {"mumlar": [], "bas": None, "son": None}
    bas, son = _aralik_sinirlari(aralik, df["timestamp"].iloc[-1])
    df = df[(df["timestamp"] >= bas) & (df["timestamp"] < son)]
    zaman = grafik_zamani(df["timestamp"])
    mumlar = [{"time": t, "open": o, "high": h, "low": lo, "close": c}
              for t, o, h, lo, c in zip(zaman, df["open"], df["high"], df["low"], df["close"])]
    return {"mumlar": mumlar,
            "bas": df["timestamp"].iloc[0].isoformat() if len(df) else None,
            "son": df["timestamp"].iloc[-1].isoformat() if len(df) else None}


# ----------------------------------------------------------- ÇİZGİ KATMANI --

CIZGILER = ("tepe", "dip", "alis", "zarar_stop", "takip_stop")


def _cizgi_listesi(zaman: list[int], degerler) -> list[dict]:
    """Boş değer için yalnızca zaman verilir — çizgi orada kopar, uydurulmaz."""
    return [{"time": t, "value": v} if v is not None else {"time": t}
            for t, v in zip(zaman, (_sayi(x) for x in degerler))]


def _kopuk_cizgi(s: pd.DataFrame, ts: pd.Series, degerler: pd.Series) -> list[dict]:
    """Canlı seviye çizgisi; motorun çalışmadığı aralıklarda kopar.

    Basamaklı çizgide değer, bir sonraki noktaya kadar yatay çizilir. Motor
    iki gün çalışmadıysa (ör. iki ayrı kuru deneme) iki karar arası "seviye
    iki gün sabit durdu" gibi görünüyordu. Ardışık olmayan kararın ardına,
    kendi barının bittiği yere boş nokta konur: seviye yalnızca o bar
    boyunca çizilir. (Boş noktada çizgiyi koparmak tarayıcının işi —
    `uygulama.js:kopukVeri`.)
    """
    noktalar: list[dict] = []
    siralar = s["sira"].tolist()
    zamanlar = s["zaman"].tolist()
    for i, (sira, zaman, deger) in enumerate(zip(siralar, zamanlar, degerler)):
        v = _sayi(deger)
        t = grafik_zamani(pd.Series([zaman]))[0]
        noktalar.append({"time": t, "value": v} if v is not None else {"time": t})
        sonraki = siralar[i + 1] if i + 1 < len(siralar) else None
        if v is None or sonraki == sira + 1:
            continue
        # Barın bitişi: bir sonraki seans barı; depoda yoksa (motorun şu anki
        # kararı, bar henüz oluşmadı) +1 saat.
        bitis = ts.iloc[sira + 1] if sira + 1 < len(ts) else zaman + pd.Timedelta(hours=1)
        if i + 1 < len(zamanlar) and bitis >= zamanlar[i + 1]:
            continue
        noktalar.append({"time": grafik_zamani(pd.Series([bitis]))[0]})
    return noktalar


def canli_katman(paper_db: Path, veri_db: Path, sembol: str, aralik: str = "60g") -> dict:
    """Motorun GERÇEKTE gördüğü seviyeler (`sinyaller`) ve gerçek işlemler.

    Bir sinyal satırı, `bar_zamani` barı kapandıktan sonra verilen karardır;
    koyduğu emirler bir sonraki barda geçerlidir. Bu yüzden çizgi o bara
    (bar_zamani + 1 saat) çizilir — backtest'in seviye kaydıyla aynı hizada.
    """
    bos = {"cizgiler": {a: [] for a in CIZGILER}, "islemler": [], "sinyal_sayisi": 0}
    with salt_okur(paper_db) as c:
        if c is None or not _tablo_var(c, "sinyaller"):
            return bos
        s = pd.read_sql_query("SELECT * FROM sinyaller ORDER BY id", c)
        g = pd.read_sql_query(
            "SELECT g.*, e.bar_zamani AS emir_bari FROM gerceklesmeler g "
            "LEFT JOIN emirler e ON e.client_order_id = g.client_order_id ORDER BY g.id", c) \
            if _tablo_var(c, "gerceklesmeler") else pd.DataFrame()
    if s.empty:
        return bos

    # Aynı bar için birden çok tur olduysa sonuncusu geçerli.
    s = s.drop_duplicates("bar_zamani", keep="last").copy()
    df_bar = _seans_barlari(veri_db, sembol)
    ts = df_bar["timestamp"].reset_index(drop=True)

    # Karar, bar_zamani'ndan sonraki İLK SEANS barında geçerli. Günün son barı
    # (15:00) için bu ertesi sabahtır — "+1 saat" 16:00 gibi olmayan bir mum
    # üretip grafiğe boş sütun ekliyordu. Depoda henüz olmayan bar için +1 saat.
    bz = pd.to_datetime(s["bar_zamani"], utc=True, format="ISO8601")
    s["sira"] = ts.searchsorted(bz, side="right") if len(ts) else 0
    s["zaman"] = [ts.iloc[i] if i < len(ts) else b + pd.Timedelta(hours=1)
                  for i, b in zip(s["sira"], bz)]
    s = s.drop_duplicates("zaman", keep="last")
    son = ts.iloc[-1] if len(ts) else s["zaman"].iloc[-1]
    bas, bit = _aralik_sinirlari(aralik, son)
    s = s[(s["zaman"] >= bas) & (s["zaman"] < bit)]

    poz = s["pozisyon_acik"].astype(bool)
    takip = s["takipte"].astype(bool)
    cizgiler = {ad: _kopuk_cizgi(s, ts, degerler) for ad, degerler in (
        ("tepe", s["tepe"]),
        ("dip", s["dip"]),
        ("alis", s["alis_seviyesi"].where(~poz)),
        ("zarar_stop", s["koruma"].where(poz & ~takip)),
        ("takip_stop", s["koruma"].where(poz & takip)),
    )}

    islemler = []
    if not g.empty:
        # Gerçek dolum anı kaydedilmiyor; motor dolumu bir sonraki turda fark
        # ediyor. İşaret, emrin geçerli olduğu bara konur — yaklaşık yer.
        bar = pd.to_datetime(g["emir_bari"].fillna(g["bar_zamani"]), utc=True,
                             format="ISO8601") + pd.Timedelta(hours=1)
        for t, r in zip(grafik_zamani(bar), g.itertuples()):
            islemler.append({"time": t, "yon": "al" if r.tip == "limit_al" else "sat",
                             "fiyat": _sayi(r.gerceklesen_fiyat), "adet": int(r.adet),
                             "istenen": _sayi(r.istenen_seviye),
                             "sebep": "alış" if r.tip == "limit_al" else "stop"})
    return {"cizgiler": cizgiler, "islemler": islemler, "sinyal_sayisi": int(len(s))}


_onbellek: dict[tuple, dict] = {}
_kilit = threading.Lock()


def backtest_katmani(veri_db: Path, sembol: str, aralik: str = "60g") -> dict:
    """Aynı kurallar (`KURALLAR_KABUL1`) geçmiş barlarda — KASA HARİÇ.

    Kasa başlangıcından sonrası hesaplanmaz bile; hesaplanıp gizlenmez.
    Sonuç, veri dosyası değişmedikçe önbellekten döner.
    """
    anahtar = (str(veri_db), Path(veri_db).stat().st_mtime if Path(veri_db).exists() else 0, sembol)
    with _kilit:
        tam = _onbellek.get(anahtar)
    if tam is None:
        butun = _seans_barlari(veri_db, sembol)
        son_veri = butun["timestamp"].iloc[-1] if len(butun) else None
        df = butun[butun["timestamp"] < pd.Timestamp(VAULT_BEGINS, tz="UTC")]
        # Araştırma alanının son barı budanır — `lab/splits.split_research_vault
        # (horizon_bars=1)` ile aynı kesim. KABUL-1'in kayıtlı sonucu (9.9004 /
        # 28 işlem) bu kesimle üretildi; grafik aynı sayıyı göstermeli.
        df = df.iloc[:-1].reset_index(drop=True)
        if len(df) <= KURALLAR_KABUL1.n + 1:
            tam = {"df": None}
        else:
            tam = {"df": df, "sonuc": calistir(df, KURALLAR_KABUL1), "son_veri": son_veri}
        with _kilit:
            _onbellek.clear()
            _onbellek[anahtar] = tam

    bos = {"cizgiler": {a: [] for a in CIZGILER}, "islemler": [],
           "kasa_baslangici": VAULT_BEGINS, "arastirma_sonu": RESEARCH_END, "ozet": None}
    if tam["df"] is None:
        return bos
    df, sonuc = tam["df"], tam["sonuc"]

    bas, bit = _aralik_sinirlari(aralik, tam["son_veri"])
    maske = ((df["timestamp"] >= bas) & (df["timestamp"] < bit)).to_numpy()

    sev = sonuc.seviyeler
    cz = sonuc.cizgiler
    takip = sev["takipte"].astype(bool)
    koruma = sev["koruma"]
    zaman = grafik_zamani(df["timestamp"][maske])
    cizgiler = {
        "tepe": _cizgi_listesi(zaman, cz["tepe"][maske]),
        "dip": _cizgi_listesi(zaman, cz["dip"][maske]),
        "alis": _cizgi_listesi(zaman, sev["alis_seviyesi"][maske]),
        "zarar_stop": _cizgi_listesi(zaman, koruma.where(~takip)[maske]),
        "takip_stop": _cizgi_listesi(zaman, koruma.where(takip)[maske]),
    }

    islemler = []
    tr = sonuc.islemler
    if not tr.empty:
        for r in tr.itertuples():
            for zamani, fiyat, yon, sebep in (
                (r.alis_zamani, r.alis, "al", "alış"),
                (r.satis_zamani, r.satis, "sat", r.sebep),
            ):
                an = pd.Timestamp(zamani).tz_localize("UTC") if pd.Timestamp(zamani).tzinfo is None \
                    else pd.Timestamp(zamani)
                if bas <= an < bit:
                    islemler.append({"time": grafik_zamani(pd.Series([an]))[0], "yon": yon,
                                     "fiyat": _sayi(fiyat), "sebep": sebep,
                                     "getiri": _sayi(r.getiri_maliyetli) if yon == "sat" else None})
    islemler.sort(key=lambda x: x["time"])

    return {**bos, "cizgiler": cizgiler, "islemler": islemler,
            "ozet": {"islem": int(len(tr)), "lira": _sayi(sonuc.bakiye.iloc[-1]),
                     "bas": df["timestamp"].iloc[0].isoformat(),
                     "son": df["timestamp"].iloc[-1].isoformat()}}


# ------------------------------------------------------------------ TURLAR --

def son_turlar(paper_db: Path, adet: int = 20) -> list[dict]:
    with salt_okur(paper_db) as c:
        if c is None or not _tablo_var(c, "turlar"):
            return []
        return [dict(r) for r in c.execute(
            "SELECT baslangic_utc, sonuc, substr(ozet,1,200) AS ozet, "
            "substr(hata,1,300) AS hata FROM turlar ORDER BY id DESC LIMIT ?", (adet,))]



# ---------------------------------------------------------------- UYARILAR --

def son_uyarilar(paper_db: Path, adet: int = 20) -> list[dict]:
    """Panelin uyarı tablosu — en yeni önce. Tablo yoksa (eski veritabanı) boş."""
    with salt_okur(paper_db) as c:
        if c is None or not _tablo_var(c, "uyarilar"):
            return []
        return [dict(r) for r in c.execute(
            "SELECT ilk_utc, son_utc, seviye, konu, substr(mesaj,1,1000) AS mesaj, tekrar "
            "FROM uyarilar ORDER BY son_utc DESC, id DESC LIMIT ?", (adet,))]
