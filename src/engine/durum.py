"""Motorun kalıcı hafızası — pozisyon durumu ve işlem kütüğü (SQLite).

Neden ayrı veritabanı
---------------------
Araştırma verisi `data/market_data.db`'de durur ve sık sık yeniden indirilir,
silinir, taşınır. Canlı işlem kaydı onun yanında duramaz: karışırsa hangi
emrin gerçekten gönderildiği belirsizleşir (ENVIRONMENTS.md §5, "DB: ayrı beta
dosyası"). Bu modül `data/paper.db`'ye yazar, araştırma veritabanına hiç
dokunmaz.

Neden kalıcı
------------
Takip eden stop bizim sürecimizde duruyor. Motor çökerse `zirve` ve `stop`
RAM'le birlikte kaybolur; yeniden başladığında hangi seviyeden koruduğunu
bilemez (TECH_DEBT.md TD-06). Bu yüzden durum her bar sonunda diske yazılır ve
açılışta buradan yüklenir.

Tablolar
--------
* `motor_durumu`   — tek satır, üzerine yazılır. Pozisyonun o anki hali.
* `sinyaller`      — her saatlik karar. Yalnızca eklenir.
* `emirler`        — gönderilen her emir, tekrarsız kimliğiyle.
* `gerceklesmeler` — dolan emirler: istenen seviye ile gerçekleşen fiyat yan
                     yana. Paper koşusunun asıl çıktısı (TD-10, TD-11).

Zaman biçimi `src/data/db.py` ile aynıdır: ISO-8601 UTC metni.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .kural import Durum

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPER_DB_PATH = REPO_ROOT / "data" / "paper.db"

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

-- Tek satır: motorun o anki pozisyon hali. id her zaman 1.
CREATE TABLE IF NOT EXISTS motor_durumu (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    acik             INTEGER NOT NULL,      -- 0 | 1
    giris_fiyat      REAL,
    stop             REAL,
    takipte          INTEGER NOT NULL,      -- 0 | 1
    zirve            REAL,
    mesafe           REAL,
    adet             INTEGER NOT NULL,      -- elimizdeki hisse (tam hisse)
    son_islenen_bar  TEXT,                  -- ISO-8601 UTC; tekrar islememek icin
    guncellendi_utc  TEXT NOT NULL
);

-- Her saatlik karar. ASLA guncellenmez.
CREATE TABLE IF NOT EXISTS sinyaller (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bar_zamani      TEXT NOT NULL,          -- kararin dayandigi kapanmis bar
    tepe            REAL,
    dip             REAL,
    alis_seviyesi   REAL,                   -- pozisyon yokken
    zarar_stop      REAL,                   -- pozisyon yokken
    koruma          REAL,                   -- pozisyon varken
    pozisyon_acik   INTEGER NOT NULL,
    takipte         INTEGER NOT NULL,
    aciklama        TEXT,
    yazildi_utc     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sinyal_bar ON sinyaller (bar_zamani);

-- Gonderilen emirler. client_order_id tekrarsizdir: ayni kimlikle ikinci emir
-- broker tarafindan reddedilir, boylece cift emir imkansizdir (TD-07).
CREATE TABLE IF NOT EXISTS emirler (
    client_order_id TEXT PRIMARY KEY,
    broker_order_id TEXT,
    bar_zamani      TEXT NOT NULL,
    tip             TEXT NOT NULL,          -- 'limit_al' | 'stop_sat'
    seviye          REAL NOT NULL,          -- limit ya da stop fiyati
    ek_seviye       REAL,                   -- limit_al icin: dolunca kurulacak
                                            -- zararina satis seviyesi. Alista
                                            -- sabitlenir, dolan emirle birlikte
                                            -- duruma yazilir.
    adet            INTEGER NOT NULL,
    durum           TEXT NOT NULL,          -- 'gonderildi' | 'dolu' | 'iptal' | 'red'
    gonderildi_utc  TEXT NOT NULL,
    guncellendi_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emir_bar ON emirler (bar_zamani);

-- Dolan emirler. Backtest'in varsaydigi seviye ile gercekte olan fiyat yan yana.
CREATE TABLE IF NOT EXISTS gerceklesmeler (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id   TEXT NOT NULL,
    bar_zamani        TEXT NOT NULL,
    tip               TEXT NOT NULL,
    istenen_seviye    REAL NOT NULL,        -- backtest bu fiyati varsayardi
    gerceklesen_fiyat REAL NOT NULL,        -- gercekte bu fiyattan oldu
    adet              INTEGER NOT NULL,
    gerceklesme_utc   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gerc_emir ON gerceklesmeler (client_order_id);
"""


def simdi_utc() -> str:
    """Şimdinin ISO-8601 UTC metni — tüm zaman sütunlarının biçimi."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _sayi(deger: float | None) -> float | None:
    """NaN -> NULL. SQLite'ta NaN diye bir şey yok, NULL kullanılır."""
    return None if deger is None or math.isnan(deger) else float(deger)


def _nan(deger: float | None) -> float:
    """NULL -> NaN. Okuma yönü."""
    return math.nan if deger is None else float(deger)


@contextmanager
def connect(db_path: Path | str = DEFAULT_PAPER_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Şeması hazır bağlantı; çıkışta commit + close.

    `src/data/db.py:connect` ile aynı desen — orada neden böyle yapıldığı
    anlatılıyor.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_PAPER_DB_PATH) -> Path:
    """Veritabanını ve tabloları oluşturur (varsa dokunmaz)."""
    with connect(db_path):
        pass
    return Path(db_path)


# ----------------------------------------------------------------- DURUM --

def durum_yukle(conn: sqlite3.Connection) -> tuple[Durum, int, str | None]:
    """Kayıtlı durumu okur.

    Returns:
        (durum, elimizdeki hisse adedi, son işlenen bar zamanı). Hiç kayıt
        yoksa boş bir durum döner — motor ilk kez çalışıyor demektir.
    """
    satir = conn.execute("SELECT * FROM motor_durumu WHERE id = 1").fetchone()
    if satir is None:
        return Durum(), 0, None

    durum = Durum(
        acik=bool(satir["acik"]),
        giris_fiyat=_nan(satir["giris_fiyat"]),
        stop=_nan(satir["stop"]),
        takipte=bool(satir["takipte"]),
        zirve=_nan(satir["zirve"]),
        mesafe=_nan(satir["mesafe"]),
    )
    return durum, int(satir["adet"]), satir["son_islenen_bar"]


def durum_kaydet(
    conn: sqlite3.Connection,
    durum: Durum,
    *,
    adet: int,
    son_islenen_bar: str | None,
) -> None:
    """Durumu diske yazar. Tek satır, üzerine yazılır."""
    conn.execute(
        """
        INSERT INTO motor_durumu
            (id, acik, giris_fiyat, stop, takipte, zirve, mesafe, adet,
             son_islenen_bar, guncellendi_utc)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            acik=excluded.acik, giris_fiyat=excluded.giris_fiyat,
            stop=excluded.stop, takipte=excluded.takipte,
            zirve=excluded.zirve, mesafe=excluded.mesafe, adet=excluded.adet,
            son_islenen_bar=excluded.son_islenen_bar,
            guncellendi_utc=excluded.guncellendi_utc
        """,
        (int(durum.acik), _sayi(durum.giris_fiyat), _sayi(durum.stop),
         int(durum.takipte), _sayi(durum.zirve), _sayi(durum.mesafe),
         int(adet), son_islenen_bar, simdi_utc()),
    )


# -------------------------------------------------------------- SİNYALLER --

def sinyal_yaz(
    conn: sqlite3.Connection,
    *,
    bar_zamani: str,
    tepe: float,
    dip: float,
    alis_seviyesi: float,
    zarar_stop: float,
    koruma: float,
    durum: Durum,
    aciklama: str = "",
) -> None:
    """Bu barda ne düşünüldüğünü kütüğe yazar. Emir gitmese bile yazılır."""
    conn.execute(
        """
        INSERT INTO sinyaller
            (bar_zamani, tepe, dip, alis_seviyesi, zarar_stop, koruma,
             pozisyon_acik, takipte, aciklama, yazildi_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bar_zamani, _sayi(tepe), _sayi(dip), _sayi(alis_seviyesi),
         _sayi(zarar_stop), _sayi(koruma), int(durum.acik), int(durum.takipte),
         aciklama, simdi_utc()),
    )


# ---------------------------------------------------------------- EMİRLER --

def emir_kimligi(bar_zamani: str, tip: str) -> str:
    """Tekrarsız emir kimliği: aynı bar + aynı tip = aynı kimlik.

    Bağlantı koparsa motor aynı emri aynı kimlikle yeniden dener; broker
    ikincisini reddeder. Böylece çift emir gönderilemez (TD-07).
    """
    temiz = bar_zamani.replace(":", "").replace("-", "").replace("+", "")
    return f"{tip}-{temiz}"


def emir_yaz(
    conn: sqlite3.Connection,
    *,
    client_order_id: str,
    bar_zamani: str,
    tip: str,
    seviye: float,
    adet: int,
    ek_seviye: float = math.nan,
    broker_order_id: str | None = None,
    durum: str = "gonderildi",
) -> None:
    """Gönderilen emri kütüğe yazar.

    `ek_seviye`: alış emrinde, emir dolarsa kurulacak zararına satış seviyesi.
    Emir konurken sabitlenir — dolduğu anda çizgiler kaymış olabilir, ama
    kural alış anındaki dibe göre stop kurmayı söylüyor.
    """
    an = simdi_utc()
    conn.execute(
        """
        INSERT INTO emirler
            (client_order_id, broker_order_id, bar_zamani, tip, seviye,
             ek_seviye, adet, durum, gonderildi_utc, guncellendi_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_order_id) DO UPDATE SET
            broker_order_id=excluded.broker_order_id,
            durum=excluded.durum, guncellendi_utc=excluded.guncellendi_utc
        """,
        (client_order_id, broker_order_id, bar_zamani, tip, float(seviye),
         _sayi(ek_seviye), int(adet), durum, an, an),
    )


def emir_durumu_guncelle(
    conn: sqlite3.Connection, client_order_id: str, yeni_durum: str,
) -> None:
    """Emrin akıbetini günceller: dolu / iptal / red."""
    conn.execute(
        "UPDATE emirler SET durum = ?, guncellendi_utc = ? WHERE client_order_id = ?",
        (yeni_durum, simdi_utc(), client_order_id),
    )


def bekleyen_emirler(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Henüz dolmamış ya da iptal edilmemiş emirler."""
    return conn.execute(
        "SELECT * FROM emirler WHERE durum = 'gonderildi' ORDER BY gonderildi_utc"
    ).fetchall()


# ---------------------------------------------------------- GERÇEKLEŞMELER --

def gerceklesme_yaz(
    conn: sqlite3.Connection,
    *,
    client_order_id: str,
    bar_zamani: str,
    tip: str,
    istenen_seviye: float,
    gerceklesen_fiyat: float,
    adet: int,
) -> None:
    """Dolan emri kaydeder — istenen seviye ile gerçekleşen fiyat yan yana.

    Adım 6'daki karşılaştırma raporunun hammaddesi: backtest bu seviyeyi
    varsayıyordu, gerçekte şu oldu.
    """
    conn.execute(
        """
        INSERT INTO gerceklesmeler
            (client_order_id, bar_zamani, tip, istenen_seviye,
             gerceklesen_fiyat, adet, gerceklesme_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (client_order_id, bar_zamani, tip, float(istenen_seviye),
         float(gerceklesen_fiyat), int(adet), simdi_utc()),
    )
