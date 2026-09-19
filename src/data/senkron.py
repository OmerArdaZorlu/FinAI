"""Artımlı bar tazeleme — kaldığı yerden devam eden tek indirme noktası.

Ne işe yarar
------------
Motor her turda Alpaca'dan son 60 günü baştan indiriyordu; gelen ~675 barın
674'ü bir önceki turda da inmişti. Bu modül depoya bakıp "en son nereye kadar
almışım" diye sorar ve yalnızca eksiği ister.

Ölçüm (2026-09-17, tek sembol saatlik):
    baştan indirme : 3.522 ms, 4 HTTP isteği
    artımlı        :   901 ms, 1 HTTP isteği

Katman sınırı
-------------
Bu dosya, **ağa çıkıp depoyu güncelleyen tek yerdir.**

    alpaca.py   ağı bilir, depoyu bilmez
    db.py       depoyu bilir, ağı bilmez
    senkron.py  ikisini birbirine bağlayan tek nokta
    load.py     YALNIZCA okur — asla ağa çıkmaz

`load.py`'ın ağa çıkmama garantisi araştırma tarafının dayanağıdır: backtest
çalıştıran biri farkında olmadan veri indirmemeli. Bu yüzden tazeleme oraya
değil buraya kondu.

İleride veriyi ayrı bir süreç (hatta başka bir dilde bir toplayıcı) yazacak
olursa, değişecek tek yer burasıdır. `motor.py` ve `kural.py` "depodan oku"
dediği için, verinin kim tarafından yazıldığını umursamaz.

İşaretçi neden ayrı tutulmuyor
------------------------------
"En son nereye kadar çektim" bilgisi ayrı bir tabloda da tutulabilirdi. Hız
farkı yok (ikisi de 0,006 ms), ama ayrı tablo aynı bilginin ikinci nüshasıdır:
yazma yarıda kalırsa (süreç ölür, disk dolar) işaretçi "14:00'e kadar aldım"
derken depoda 13:00'e kadar olur ve aradaki barlar sessizce, kalıcı olarak
eksik kalır. `MAX(timestamp)` verinin kendisi olduğu için yalan söyleyemez —
yazma yarıda kalırsa işaretçi de geride kalır ve eksik tekrar istenir.

Hisse bölünmesi ve günlük tam yenileme
--------------------------------------
Barlar bölünmeye göre düzeltilmiş (`adjustment="all"`) iner, ama düzeltme
**indirme anındaki** bilgiyle yapılır. Artımlı çekim eski barları bir daha
istemediği için, bölünmeden önce inmiş barlar eski fiyatta kalır; yeni
barlar bölünmüş fiyatla gelir. Kanal ikisini karıştırır.

`tam_yenileme_saat` verilirse pencerenin tamamı o kadar saatte bir baştan
indirilir; UPSERT eski barları düzeltilmiş değerleriyle ezer. Son tam
yenileme ayrı bir tabloda değil `ingest_log`'da durur
(`source='senkron.tam'`, `requested_end`) — yukarıdaki "işaretçi verinin
kendisi" ilkesiyle aynı sebeple.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd

from .alpaca import BosVeriError, fetch_bars
from .db import DEFAULT_DB_PATH, connect, log_ingest, write_bars

# Alpaca'nın kabul ettiği zaman biçimi (RFC-3339, UTC).
ZAMAN_BICIMI = "%Y-%m-%dT%H:%M:%SZ"


def son_bar_zamani(
    conn: sqlite3.Connection,
    sembol: str,
    *,
    timeframe: str,
    adjustment: str = "all",
) -> dt.datetime | None:
    """Depodaki en yeni barın açılış zamanı; seri hiç yoksa None.

    `WHERE` ile üç sütunu birden hedefler — birincil anahtar
    (symbol, timeframe, adjustment, timestamp) olduğu için bu bir indeks
    aramasıdır, 0,006 ms sürer.

    `GROUP BY` ile tüm depoyu tarayan sürüm 368 ms sürüyordu (1,5 milyon
    dakikalık bar yüzünden). Ölçüldü; bu yüzden sembol başına ayrı sorgu.
    """
    satir = conn.execute(
        "SELECT MAX(timestamp) FROM bars "
        "WHERE symbol = ? AND timeframe = ? AND adjustment = ?",
        (sembol, timeframe, adjustment),
    ).fetchone()
    if not satir or satir[0] is None:
        return None
    return pd.Timestamp(satir[0]).to_pydatetime()


def _tam_yenileme_zamani(
    conn: sqlite3.Connection,
    sembol: str,
    *,
    timeframe: str,
    adjustment: str,
    kesim: dt.datetime,
    saat: float,
) -> bool:
    """Son tam yenilemenin üzerinden `saat` geçti mi (hiç yoksa evet)."""
    satir = conn.execute(
        "SELECT MAX(requested_end) FROM ingest_log WHERE symbol = ? AND timeframe = ? "
        "AND adjustment = ? AND source = 'senkron.tam'",
        (sembol, timeframe, adjustment),
    ).fetchone()
    if not satir or satir[0] is None:
        return True
    son = pd.Timestamp(satir[0]).to_pydatetime()
    return (kesim - son) >= dt.timedelta(hours=saat)


def _tam_barlar(df: pd.DataFrame, *, bar_dakika: int, kesim: dt.datetime) -> pd.DataFrame:
    """`kesim`den sonra kapanan (yarım) barları eler.

    Barlar AÇILIŞ saatiyle etiketli: 11:00 barı 12:00'de kapanır. Alpaca
    saat 11:20'de sorulursa 11:00 barını yine de döndürür, ama o bar henüz
    bitmemiştir. Depoya girerse sonraki okumalar onu tam sanar — ve yarım
    barın "yükseği", henüz olmamış bir zirve demektir.
    """
    biter = df["timestamp"] + pd.Timedelta(minutes=bar_dakika)
    return df.loc[biter <= pd.Timestamp(kesim)].reset_index(drop=True)


def tazele(
    semboller: list[str],
    *,
    timeframe: str,
    bar_dakika: int,
    kesim: dt.datetime,
    db_path: Path | str = DEFAULT_DB_PATH,
    geriye_gun: int = 90,
    adjustment: str = "all",
    verbose: bool = False,
    tam_yenileme_saat: float | None = None,
) -> dict[str, int]:
    """Depoyu `kesim`e kadar günceller; sembol başına yazılan bar sayısı döner.

    Args:
        semboller: Tazelenecek semboller. Bugün tek sembolle çalışıyoruz ama
            arayüz liste alıyor — çoklu sembol gündeme geldiğinde imza
            değişmesin diye.
        timeframe: "1Hour", "1Day", ...
        bar_dakika: Bir barın kaç dakika sürdüğü. Yarım bar elemesi için şart;
            `timeframe` metninden çıkarmak yerine açıkça isteniyor ki
            "15Min" gibi biçimlerde sessizce yanlış hesaplanmasın.
        kesim: Bu ana kadar (dahil kapanmış) barlar istenir. Motor buraya
            `şimdi - 16 dk` verir: ücretsiz SIP 15 dakika gecikmeli.
        geriye_gun: Depo boşsa (ya da tam yenilemede) ne kadar geçmişten
            başlanacağı.
        tam_yenileme_saat: Son tam yenilemeden bu kadar saat geçtiyse
            pencerenin tamamı baştan indirilir (bölünme düzeltmesi). `None`
            → yalnızca artımlı. `0` → şimdi zorla.

    Returns:
        {sembol: yazılan_bar_sayısı}. Yeni bar yoksa 0 — hata değil.

    Not: Toplu (tek istekte çok sembol) çekim burada YOK. `fetch_bars` tek
    sembol alıyor; çoklu sürümü, çoklu sembolle işlem gündeme geldiğinde
    yazılacak. Tek sembolde kazancı da yok zaten.
    """
    yazilan: dict[str, int] = {}

    with connect(db_path) as conn:
        for sembol in semboller:
            yazilan[sembol] = _tek_sembol(
                conn, sembol,
                timeframe=timeframe, bar_dakika=bar_dakika, kesim=kesim,
                geriye_gun=geriye_gun, adjustment=adjustment, verbose=verbose,
                tam_yenileme_saat=tam_yenileme_saat,
            )

    return yazilan


def _tek_sembol(
    conn: sqlite3.Connection,
    sembol: str,
    *,
    timeframe: str,
    bar_dakika: int,
    kesim: dt.datetime,
    geriye_gun: int,
    adjustment: str,
    verbose: bool,
    tam_yenileme_saat: float | None = None,
) -> int:
    son = son_bar_zamani(conn, sembol, timeframe=timeframe, adjustment=adjustment)
    tam_yenile = tam_yenileme_saat is not None and _tam_yenileme_zamani(
        conn, sembol, timeframe=timeframe, adjustment=adjustment,
        kesim=kesim, saat=tam_yenileme_saat)

    if son is None or tam_yenile:
        # Soğuk başlangıç ya da tam yenileme: pencerenin tamamı.
        baslangic = kesim - dt.timedelta(days=geriye_gun)
    else:
        # Son kayıtlı barın kendisinden başla (DAHİL). Yarım kaydedilmiş
        # olma ihtimaline karşı: UPSERT onu doğru değerlerle tazeler.
        baslangic = son
        # O bar zaten kapanmışsa ve ondan sonra yeni bar kapanmamışsa,
        # istenecek bir şey yok — ağa hiç çıkma.
        if son + dt.timedelta(minutes=bar_dakika) * 2 > kesim:
            if verbose:
                print(f"  [{sembol}] yeni bar yok (son: {son:%Y-%m-%d %H:%M} UTC)")
            return 0

    try:
        ham = fetch_bars(
            sembol,
            start=baslangic.strftime(ZAMAN_BICIMI),
            end=kesim.strftime(ZAMAN_BICIMI),
            timeframe=timeframe,
            adjustment=adjustment,
            verbose=verbose,
        )
    except BosVeriError:
        # Aralıkta bar yok: hafta sonu, tatil, ya da henüz kapanan bar yok.
        # Artımlı tazelemede bu normaldir. Gerçek hatalar (yetkilendirme, ağ,
        # HTTP 4xx/5xx) BosVeriError DEĞİL, buradan geçip yukarı çıkar.
        if verbose:
            print(f"  [{sembol}] aralıkta bar dönmedi — atlanıyor")
        return 0

    tam = _tam_barlar(ham, bar_dakika=bar_dakika, kesim=kesim)
    if tam.empty:
        # Gelen her bar yarımdı. write_bars boş tabloda ValidationError
        # yükseltir (schema.py), o yüzden yazmaya hiç kalkışma.
        if verbose:
            print(f"  [{sembol}] gelen {len(ham)} barın hepsi yarım — yazılmadı")
        return 0

    n = write_bars(conn, tam, symbol=sembol, timeframe=timeframe, adjustment=adjustment)

    log_ingest(conn, {
        "symbol": sembol,
        "timeframe": timeframe,
        "adjustment": adjustment,
        "feed": "sip",
        "requested_start": baslangic.strftime(ZAMAN_BICIMI),
        "requested_end": kesim.strftime(ZAMAN_BICIMI),
        "actual_start": tam["timestamp"].iloc[0].strftime(ZAMAN_BICIMI),
        "actual_end": tam["timestamp"].iloc[-1].strftime(ZAMAN_BICIMI),
        "rows_fetched": len(ham),
        "rows_written": n,
        "source": "senkron.tam" if tam_yenile else "senkron.tazele",
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime(ZAMAN_BICIMI),
    })

    if verbose:
        print(f"  [{sembol}] {n} bar yazıldı "
              f"({tam['timestamp'].iloc[0]:%Y-%m-%d %H:%M} → "
              f"{tam['timestamp'].iloc[-1]:%Y-%m-%d %H:%M} UTC)")
    return n
