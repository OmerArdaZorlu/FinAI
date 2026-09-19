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

Eklemeli yükleme
----------------
Geçmiş değişmez; panel her 30 saniyede her şeyi baştan istemez.
`isaretler()` ucuz üç sayı döner (en yeni bar, en yeni karar, son tam
yenileme). Panel yalnızca biri değişince ister: mumları `barlar(sonra=)` ile
yalnızca yenileri alıp sona ekler. Canlı katman küçüktür (en çok birkaç yüz
nokta) ve son kararın yeri, barı depoya gelince kayar (+1 saatten gerçek bir
sonraki seans barına) — o yüzden değişince bütünüyle yeniden istenir.
Backtest katmanı kasada bittiği için hiç yeniden istenmez. Tam yenileme (depo
baştan indirildi, ör. bölünme düzeltmesi) geçmişi gerçekten değiştirir — o
zaman panel bir kez baştan yükler.

Bar aralıkları
--------------
Grafik `1Min`, `1Hour` ve `1Day` gösterebilir (`TF_LISTESI`). Saatlik ve
günlük tablo küçüktür, bütünüyle önbelleğe alınır. Dakikalık 1,5 milyon
satırdır — önbelleğe alınmaz, istenen pencere doğrudan SQL'den okunur
(birincil anahtar `symbol, timeframe, adjustment, timestamp` olduğu için
indeks aramasıdır). Günlük barda seans filtresi uygulanmaz: günlük barın
damgası 00:00 New York'tur, seans filtresinden geçirilse hepsi elenirdi.

Canlı ve backtest çizgileri her zaman SAATLİKTİR — kurallar saatlik
çalışıyor. Panel başka aralıktayken o çizgileri göstermez.

Ekrana göre yükleme
-------------------
Mumlar ve backtest çizgileri **zaman penceresi** ile istenir
(`barlar(bas=, bit=)`, `backtest_katmani(bas=, bit=)`). Panel ekranda
görünen sürenin iki katını ister; geriye sürükleyip başa yaklaşınca bir
parça daha. Dilimleme önbellekteki tablo üzerinde ikili aramayla yapılır —
parça başına milisaniyeler. Biçim sütunludur (`{"time": [...], "open":
[...]}`; boşluk `null`): satır satır sözlük üretip FastAPI'nin
çeviricisinden geçirmek araştırma döneminde ~0.7 sn sürüyordu.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

from src.data.kasa import RESEARCH_END, VAULT_BEGINS
from src.data.senkron import son_bar_zamani
from src.data.schema import BAR_COLUMNS
from src.data.session import EXCHANGE_TZ, regular_hours
from src.engine.kural import Cizgi, Durum, emir_seviyeleri
from src.engine.motor import KURALLAR_KABUL1
from src.engine.tekrar import calistir, cizgiler

from . import varlik

TF_LISTESI = ("1Min", "1Hour", "1Day")
TF_VARSAYILAN = "1Hour"


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


# ----------------------------------------------------------------- İZLEME --

_SEMBOLLER_SQL = """
WITH RECURSIVE s(sembol) AS (
    SELECT MIN(symbol) FROM bars
    UNION ALL
    SELECT (SELECT MIN(symbol) FROM bars WHERE symbol > s.sembol) FROM s
    WHERE s.sembol IS NOT NULL
)
SELECT sembol FROM s WHERE sembol IS NOT NULL
"""

# Son seans + önceki seansın kapanışı için yeter (seans dışı barlar dahil).
_SON_BARLAR_SQL = ("SELECT timestamp, close FROM bars WHERE symbol=? AND timeframe='1Hour' "
                   "AND adjustment='all' ORDER BY timestamp DESC LIMIT 60")


def _fiyat_ve_degisim(c: sqlite3.Connection, sembol: str) -> tuple[float | None, float | None]:
    """Son seans barının kapanışı ve önceki seansın kapanışına göre % değişim."""
    df = pd.DataFrame(c.execute(_SON_BARLAR_SQL, (sembol,)).fetchall(),
                      columns=["timestamp", "close"])
    if df.empty:
        return None, None
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = regular_hours(df.sort_values("timestamp")).reset_index(drop=True)
    if df.empty:
        return None, None
    gun = df["timestamp"].dt.tz_convert(EXCHANGE_TZ).dt.date
    son = float(df["close"].iloc[-1])
    onceki = df["close"][gun < gun.iloc[-1]]
    degisim = (son / float(onceki.iloc[-1]) - 1) * 100 if len(onceki) else None
    return _sayi(son), _sayi(degisim)


def izleme(veri_db: Path, motor_sembolu: str) -> list[dict]:
    """İzleme listesi: depoda saatlik serisi olan semboller, sınıflarıyla.

    Motorun sembolü depoda henüz yoksa da listede. Alpaca'daki pozisyonların
    sembolleri panelde bu listeye eklenir (broker'a burada gidilmez).
    """
    satirlar: list[dict] = []
    with salt_okur(veri_db) as c:
        if c is not None:
            # Tüm tabloyu (1.5 milyon dakikalık bar) tarayan GROUP BY 0.4 sn
            # sürüyordu. Birincil anahtar symbol ile başladığı için semboller
            # indekste atlanarak bulunur, son bar da sembol başına indeks
            # aramasıyla (senkron.son_bar_zamani) okunur.
            for (sembol,) in c.execute(_SEMBOLLER_SQL):
                son = son_bar_zamani(c, sembol, timeframe="1Hour")
                if son is None:
                    continue
                fiyat, degisim = _fiyat_ve_degisim(c, sembol)
                satirlar.append({"sembol": sembol, "sinif": varlik.sinif(sembol),
                                 "fiyat": fiyat, "degisim": degisim,
                                 "son_bar": son.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                                 "motor": sembol == motor_sembolu})
    if not any(s["motor"] for s in satirlar):
        satirlar.append({"sembol": motor_sembolu, "sinif": varlik.sinif(motor_sembolu),
                         "fiyat": None, "degisim": None, "son_bar": None, "motor": True})
    satirlar.sort(key=lambda s: (varlik.SINIFLAR.index(s["sinif"]), s["sembol"]))
    return satirlar


# ------------------------------------------------- BROKER TABLOLARI (okuma) --
# Alpaca'nın ham JSON'u panelin sütunlarına çevrilir. Broker çağrısı
# sunucuda (`sunucu.py`), burada yalnızca biçim.

def _f(x) -> float | None:
    try:
        return _sayi(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def pozisyon_satirlari(ham: list[dict]) -> list[dict]:
    return [{"sembol": p.get("symbol"),
             "sinif": varlik.sinif(p.get("symbol", ""), p.get("asset_class")),
             "yon": "Long" if p.get("side", "long") == "long" else "Short",
             "adet": _f(p.get("qty")),
             "ort_maliyet": _f(p.get("avg_entry_price")),
             "fiyat": _f(p.get("current_price")),
             "piyasa_degeri": _f(p.get("market_value")),
             "kz": _f(p.get("unrealized_pl")),
             "kz_yuzde": (lambda v: None if v is None else round(v * 100, 2))(
                 _f(p.get("unrealized_plpc")))}
            for p in ham]


def emir_satirlari(ham: list[dict]) -> list[dict]:
    return [{"sembol": e.get("symbol"),
             "sinif": varlik.sinif(e.get("symbol", ""), e.get("asset_class")),
             "tip": e.get("type") or e.get("order_type"),
             "limit": _f(e.get("limit_price")),
             "stop": _f(e.get("stop_price")),
             "yon": e.get("side"),
             "adet": _f(e.get("qty")),
             "dolan": _f(e.get("filled_qty")),
             "dolan_fiyat": _f(e.get("filled_avg_price")),
             "durum": e.get("status"),
             "gonderildi": e.get("submitted_at") or e.get("created_at"),
             "kimlik": e.get("client_order_id")}
            for e in ham]


# ------------------------------------------------------------------ BARLAR --

_bar_onbellek: dict[tuple, pd.DataFrame] = {}
_bar_kilit = threading.Lock()


def _seans_barlari(veri_db: Path, sembol: str, tf: str = TF_VARSAYILAN) -> pd.DataFrame:
    """Sembolün barları (`tf`) — dosya değişmedikçe önbellekten.

    Tüm saatlik tabloyu okumak 0.65 sn sürüyor ve mumlar, canlı katman,
    backtest katmanı üçü de bunu istiyor. Dönen tablo PAYLAŞILIR: çağıran
    değiştirmemeli (filtreleyip yeni tablo üretmek serbest).
    """
    if tf == "1Min":            # önbelleğe sığmaz; pencere pencere okunur
        raise ValueError("1Min önbelleğe alınmaz — _pencere_barlari kullan")
    yol = Path(veri_db)
    anahtar = (str(yol), yol.stat().st_mtime_ns if yol.exists() else 0, sembol, tf)
    with _bar_kilit:
        df = _bar_onbellek.get(anahtar)
    if df is None:
        df = _barlari_oku(yol, sembol, tf)
        with _bar_kilit:
            for k in [k for k in _bar_onbellek
                      if k[0] == anahtar[0] and k[2] == sembol and k[3] == tf]:
                del _bar_onbellek[k]
            _bar_onbellek[anahtar] = df
    return df


def _hazirla(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Zaman damgasını çevirir, seans filtresini uygular, grafik zamanını ekler."""
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    # Günlük barın damgası 00:00 New York; seans filtresi hepsini elerdi.
    if tf != "1Day":
        df = regular_hours(df)
    df = df.reset_index(drop=True)
    df["gz"] = grafik_zamani(df["timestamp"]) if len(df) else pd.Series(dtype="int64")
    return df


def _barlari_oku(veri_db: Path, sembol: str, tf: str) -> pd.DataFrame:
    with salt_okur(veri_db) as c:
        if c is None:
            return _hazirla(pd.DataFrame(columns=list(BAR_COLUMNS)), tf)
        df = pd.read_sql_query(
            f"SELECT {', '.join(BAR_COLUMNS)} FROM bars WHERE symbol=? "
            "AND timeframe=? AND adjustment='all' ORDER BY timestamp",
            c, params=[sembol, tf])
    return _hazirla(df, tf)


def _utc_zamani(gz: int) -> pd.Timestamp:
    """Grafik zamanı (New York duvar saati) → UTC damgası."""
    return pd.Timestamp(gz, unit="s").tz_localize(
        EXCHANGE_TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")


def _pencere_barlari(veri_db: Path, sembol: str, tf: str, *, bas: int | None,
                     bit: int | None, sonra: int | None) -> pd.DataFrame:
    """Dakikalık barların istenen penceresi — doğrudan SQL, önbelleksiz.

    Sınırlar bir gün genişletilir: grafik zamanı New York duvar saati, SQL
    damgası UTC; yaz saati geçişinde bir saatlik kayma olabilir. Kesin
    süzme grafik zamanı üzerinde (`_dilim`) yapılır.
    """
    alt = sonra if sonra is not None else bas
    kosul, params = ["symbol=?", "timeframe=?", "adjustment='all'"], [sembol, tf]
    if alt is not None:
        kosul.append("timestamp >= ?")
        params.append((_utc_zamani(alt) - pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000"))
    if bit is not None:
        kosul.append("timestamp <= ?")
        params.append((_utc_zamani(bit) + pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+0000"))
    with salt_okur(veri_db) as c:
        if c is None:
            return _hazirla(pd.DataFrame(columns=list(BAR_COLUMNS)), tf)
        df = pd.read_sql_query(
            f"SELECT {', '.join(BAR_COLUMNS)} FROM bars WHERE {' AND '.join(kosul)} "
            "ORDER BY timestamp", c, params=params)
    return _hazirla(df, tf)


def _tf_dogrula(tf: str | None) -> str:
    tf = tf or TF_VARSAYILAN
    if tf not in TF_LISTESI:
        raise ValueError(f"Bilinmeyen bar aralığı: {tf}")
    return tf


# İki ayrı uç sorgusu: `MIN(x), MAX(x)` tek sorguda indeksten okunamaz,
# SQLite seriyi baştan sona tarar (1,9 milyon dakikalık barda 1,1 sn ölçüldü).
# ORDER BY ... LIMIT 1 ise birincil anahtarda tek adımdır (2 ms).
_UC_SQL = ("SELECT timestamp FROM bars WHERE symbol=? AND timeframe=? AND adjustment='all' "
           "ORDER BY timestamp {} LIMIT 1")


def _sinirlar(veri_db: Path, sembol: str, tf: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Serinin ilk ve son bar damgası (UTC) — tabloyu okumadan."""
    with salt_okur(veri_db) as c:
        if c is None:
            return None
        uclar = [c.execute(_UC_SQL.format(yon), (sembol, tf)).fetchone() for yon in ("ASC", "DESC")]
    if uclar[0] is None:
        return None
    return tuple(pd.Timestamp(u[0]).tz_convert("UTC") if pd.Timestamp(u[0]).tzinfo
                 else pd.Timestamp(u[0], tz="UTC") for u in uclar)


def dolu_araliklar(veri_db: Path, sembol: str) -> list[str]:
    """Bu sembolde verisi olan bar aralıkları — panel düğmeyi buna göre açar."""
    return [tf for tf in TF_LISTESI if _sinirlar(veri_db, sembol, tf) is not None]


def _surum(yol: Path | str) -> int:
    yol = Path(yol)
    return yol.stat().st_mtime_ns if yol.exists() else 0


def _sutun(degerler) -> list:
    """Sayı dizisi → JSON listesi; NaN → null."""
    return [None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)
            for x in degerler]


def _dilim(gz, bas: int | None, bit: int | None, sonra: int | None = None) -> slice:
    """Grafik zamanı dizisinde `bas ≤ t < bit` (ya da `t > sonra`) aralığı — ikili arama."""
    import numpy as np
    gz = np.asarray(gz)
    i0 = int(np.searchsorted(gz, sonra, "right")) if sonra is not None else \
        (int(np.searchsorted(gz, bas, "left")) if bas is not None else 0)
    i1 = int(np.searchsorted(gz, bit, "left")) if bit is not None else len(gz)
    return slice(i0, max(i0, i1))


def _json(veri_) -> bytes:
    return json.dumps(veri_, separators=(",", ":"), allow_nan=False).encode()


def kasa_zamani() -> int:
    """Kasa başlangıcı, grafik zamanıyla (gece yarısı)."""
    return int(pd.Timestamp(VAULT_BEGINS).timestamp())


def kapsam(veri_db: Path, sembol: str, tf: str | None = None) -> dict:
    """Verinin sınırları (grafik zamanı) — panel pencereyi buna göre ister."""
    tf = _tf_dogrula(tf)
    bos = {"ilk": None, "son": None, "son_iso": None, "kasa": kasa_zamani(),
           "tf": tf, "araliklar": dolu_araliklar(veri_db, sembol)}
    if tf == "1Min":
        sinir = _sinirlar(veri_db, sembol, tf)
        if sinir is None:
            return bos
        ilk, son = grafik_zamani(pd.Series(list(sinir)))
        return {**bos, "ilk": int(ilk), "son": int(son), "son_iso": sinir[1].isoformat()}
    df = _seans_barlari(veri_db, sembol, tf)
    if df.empty:
        return bos
    return {**bos, "ilk": int(df["gz"].iloc[0]), "son": int(df["gz"].iloc[-1]),
            "son_iso": df["timestamp"].iloc[-1].isoformat()}


def barlar(veri_db: Path, sembol: str, *, tf: str | None = None, bas: int | None = None,
           bit: int | None = None, sonra: int | None = None) -> bytes:
    """`bas ≤ zaman < bit` mumları (grafik zamanı), sütunlu JSON bayt.

    `sonra` verilirse ondan sonraki mumlar (panel yeni mumları sona ekler).
    Hacim de gönderilir: panelin hacim göstergesi bunu kullanır.
    """
    tf = _tf_dogrula(tf)
    if tf == "1Min":
        df = _pencere_barlari(veri_db, sembol, tf, bas=bas, bit=bit, sonra=sonra)
        son_iso = df["timestamp"].iloc[-1].isoformat() if len(df) else None
        if son_iso is not None and (bit is not None or sonra is not None):
            sinir = _sinirlar(veri_db, sembol, tf)
            son_iso = sinir[1].isoformat() if sinir else son_iso
    else:
        df = _seans_barlari(veri_db, sembol, tf)
        son_iso = df["timestamp"].iloc[-1].isoformat() if len(df) else None
    d = df.iloc[_dilim(df["gz"], bas, bit, sonra)]
    return _json({"son": son_iso, "tf": tf,
                  "time": d["gz"].astype(int).tolist(),
                  **{k: _sutun(d[k].to_numpy(float))
                     for k in ("open", "high", "low", "close", "volume")}})


# ----------------------------------------------------------- ÇİZGİ KATMANI --

CIZGILER = ("tepe", "dip", "alis", "zarar_stop", "takip_stop")


def _cizgi_listesi(zaman: list[int], degerler) -> list[dict]:
    """Boş değer için yalnızca zaman verilir — çizgi orada kopar, uydurulmaz."""
    return [{"time": t, "value": v} if v is not None else {"time": t}
            for t, v in zip(zaman, (_sayi(x) for x in degerler))]


def _surekli_cizgiler(s: pd.DataFrame, df_bar: pd.DataFrame) -> dict[str, pd.Series]:
    """Canlı seviyeler, motorun ilk kararından son bara HER BAR için.

    Motor her saat çalışmıyor (kuru denemeler, kapalı günler). Çalışmadığı
    barlarda tepe / dip / alış, motorla aynı fonksiyonlarla bar verisinden
    hesaplanır (`tekrar.cizgiler`, `kural.emir_seviyeleri`); çalıştığı
    barlarda motorun gerçekte yazdığı değer kullanılır. Pozisyon ve stop
    motorun son kaydından sürdürülür: borsadaki stop emri de motor
    güncelleyene kadar o seviyede durur.

    Dizin: seans barı sırası; son karar depoda henüz olmayan bar içinse
    (`sira == len(barlar)`) o da dahil.
    """
    K = KURALLAR_KABUL1
    n_bar = len(df_bar)
    sira = pd.Index(range(int(s["sira"].min()), max(n_bar, int(s["sira"].max()) + 1)))

    cz = cizgiler(df_bar, K.n) if n_bar else pd.DataFrame({"tepe": [], "dip": []})
    tepe, dip = cz["tepe"].tolist(), cz["dip"].tolist()
    # Depodaki son bardan sonraki barın çizgisi: son n bar
    yeter = n_bar >= K.n
    tepe.append(float(df_bar["high"].iloc[-K.n:].max()) if yeter else math.nan)
    dip.append(float(df_bar["low"].iloc[-K.n:].min()) if yeter else math.nan)
    tepe = pd.Series(tepe).reindex(sira)
    dip = pd.Series(dip).reindex(sira)

    m = s.set_index("sira")
    tepe.update(m["tepe"])
    dip.update(m["dip"])

    durum = m[["pozisyon_acik", "takipte", "koruma"]].reindex(sira).ffill()
    poz = durum["pozisyon_acik"].fillna(0).astype(bool)
    takip = durum["takipte"].fillna(0).astype(bool)
    koruma = durum["koruma"].astype(float)

    alis = pd.Series([emir_seviyeleri(Durum(), Cizgi(t, d), K).alis
                      for t, d in zip(tepe, dip)], index=sira)
    alis.update(m["alis_seviyesi"])
    return {"tepe": tepe, "dip": dip,
            "alis": alis.where(~poz),
            "zarar_stop": koruma.where(poz & ~takip),
            "takip_stop": koruma.where(poz & takip)}


def canli_katman(paper_db: Path, veri_db: Path, sembol: str) -> dict:
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
    s = s.drop_duplicates("sira", keep="last")

    seviyeler = _surekli_cizgiler(s, df_bar)
    ek = dict(zip(s["sira"], s["zaman"]))            # depoda olmayan son bar
    zaman = grafik_zamani(pd.Series([ts.iloc[i] if i < len(ts) else ek[i]
                                     for i in seviyeler["tepe"].index]))
    cizgiler = {ad: _cizgi_listesi(zaman, seviyeler[ad]) for ad in CIZGILER}

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


def _backtest_tam(veri_db: Path, sembol: str) -> dict:
    """Araştırma döneminin tamamı için backtest — dosya değişmedikçe bir kez.

    Kasa başlangıcından sonrası hesaplanmaz bile; hesaplanıp gizlenmez.
    """
    anahtar = (str(veri_db), _surum(veri_db), sembol)
    with _kilit:
        tam = _onbellek.get(anahtar)
    if tam is None:
        butun = _seans_barlari(veri_db, sembol)
        df = butun[butun["timestamp"] < pd.Timestamp(VAULT_BEGINS, tz="UTC")]
        # Araştırma alanının son barı budanır — `lab/splits.split_research_vault
        # (horizon_bars=1)` ile aynı kesim. KABUL-1'in kayıtlı sonucu (9.9004 /
        # 28 işlem) bu kesimle üretildi; grafik aynı sayıyı göstermeli.
        df = df.iloc[:-1].reset_index(drop=True)
        if len(df) <= KURALLAR_KABUL1.n + 1:
            tam = {"df": None}
        else:
            tam = {"df": df, "sonuc": calistir(df, KURALLAR_KABUL1)}
        with _kilit:
            _onbellek.clear()
            _onbellek[anahtar] = tam
    return tam


def backtest_katmani(veri_db: Path, sembol: str, *, bas: int | None = None,
                     bit: int | None = None) -> bytes:
    """Aynı kurallar (`KURALLAR_KABUL1`) geçmiş barlarda — KASA HARİÇ.

    `bas ≤ zaman < bit` penceresi (grafik zamanı); çizgiler sütunlu
    (`{"time": [...], "value": [...]}`, boşluk null). Backtest tüm araştırma
    dönemi için bir kez hesaplanır, pencereye dilimlenir.
    """
    tam = _backtest_tam(veri_db, sembol)
    bos = {"cizgiler": {a: {"time": [], "value": []} for a in CIZGILER},
           "islemler": [], "kasa_baslangici": VAULT_BEGINS,
           "arastirma_sonu": RESEARCH_END, "ozet": None}
    if tam["df"] is None:
        return _json(bos)
    df, sonuc = tam["df"], tam["sonuc"]
    dl = _dilim(df["gz"], bas, bit)

    sev, cz = sonuc.seviyeler, sonuc.cizgiler
    takip = sev["takipte"].astype(bool)
    koruma = sev["koruma"]
    zaman = df["gz"].iloc[dl].astype(int).tolist()
    cizgiler = {ad: {"time": zaman, "value": _sutun(d.iloc[dl].to_numpy(float))} for ad, d in (
        ("tepe", cz["tepe"]), ("dip", cz["dip"]),
        ("alis", sev["alis_seviyesi"]),
        ("zarar_stop", koruma.where(~takip)),
        ("takip_stop", koruma.where(takip)),
    )}

    islemler = []
    for r in sonuc.islemler.itertuples():
        for zamani, fiyat, yon, sebep in ((r.alis_zamani, r.alis, "al", "alış"),
                                          (r.satis_zamani, r.satis, "sat", r.sebep)):
            an = pd.Timestamp(zamani)
            an = an.tz_localize("UTC") if an.tzinfo is None else an
            t = grafik_zamani(pd.Series([an]))[0]
            if (bas is None or t >= bas) and (bit is None or t < bit):
                islemler.append({"time": t, "yon": yon, "fiyat": _sayi(fiyat), "sebep": sebep,
                                 "getiri": _sayi(r.getiri_maliyetli) if yon == "sat" else None})
    islemler.sort(key=lambda x: x["time"])
    return _json({**bos, "cizgiler": cizgiler, "islemler": islemler,
                  "ozet": {"islem": int(len(sonuc.islemler)), "lira": _sayi(sonuc.bakiye.iloc[-1]),
                           "bas": df["timestamp"].iloc[0].isoformat(),
                           "son": df["timestamp"].iloc[-1].isoformat()}})


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


# ---------------------------------------------------------------- İŞARETLER --

def isaretler(veri_db: Path, paper_db: Path, sembol: str) -> dict:
    """Panelin "yeni bir şey var mı" sorusu — üç indeks araması, milisaniyeler.

    * `son_bar`: deponun en yeni saatlik barı (ISO). İlerlerse yeni mum var.
    * `son_sinyal`: `sinyaller` tablosunun en büyük id'si. İlerlerse yeni karar.
    * `tam_yenileme`: son tam yenilemenin (`senkron.tam`) künye id'si.
      Değişirse geçmiş barlar yeniden yazılmıştır — panel baştan yükler.
    """
    sonuc = {"son_bar": None, "son_sinyal": None, "tam_yenileme": None}
    with salt_okur(veri_db) as c:
        if c is not None:
            son = son_bar_zamani(c, sembol, timeframe="1Hour")
            sonuc["son_bar"] = son.strftime("%Y-%m-%dT%H:%M:%S+0000") if son else None
            if _tablo_var(c, "ingest_log"):
                sonuc["tam_yenileme"] = c.execute(
                    "SELECT MAX(id) FROM ingest_log WHERE symbol = ? AND source = 'senkron.tam'",
                    (sembol,)).fetchone()[0]
    with salt_okur(paper_db) as c:
        if c is not None and _tablo_var(c, "sinyaller"):
            sonuc["son_sinyal"] = c.execute("SELECT MAX(id) FROM sinyaller").fetchone()[0]
    return sonuc
