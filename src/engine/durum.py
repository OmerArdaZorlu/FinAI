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
* `turlar`         — döngünün her turu (kalp atışı). Sağlık kontrolü okur.
* `alarmlar`       — aynı alarmın tekrar tekrar gitmesini önler.
* `komutlar`       — arayüzden gelen /stop, /duraklat kütüğü.
* `uyarilar`       — panelde görünen sorun listesi (koruma bekçisi, alarmlar).

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
                                            -- | 'degisti' (yerinde guncellendi,
                                            -- yerine yeni kimlikli satir geldi)
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

-- Kalp atisi: dongunun her turu, sonucu ne olursa olsun. sinyaller yetmiyor:
-- borsa kapaliyken ve acil durdurmada oraya hic satir yazilmiyor, oysa saglik
-- kontrolunun "motor en son ne zaman CALISTI" bilmesi gerek.
CREATE TABLE IF NOT EXISTS turlar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    baslangic_utc   TEXT NOT NULL,
    bitis_utc       TEXT NOT NULL,
    sonuc           TEXT NOT NULL,          -- 'tamam' | 'hata' | 'durduruldu'
    ozet            TEXT,
    hata            TEXT
);

CREATE INDEX IF NOT EXISTS idx_tur_zaman ON turlar (baslangic_utc);

-- Alarm tekrar korumasi: ayni sorun her saat basi e-posta atmasin.
CREATE TABLE IF NOT EXISTS alarmlar (
    anahtar         TEXT PRIMARY KEY,       -- 'tur_hatasi', 'mutabakat', ...
    son_gonderim    TEXT NOT NULL,
    adet            INTEGER NOT NULL
);

-- Komut kutugu: arayuzden gelen /stop, /duraklat ... Arayuz buraya YAZMAZ;
-- komutu bayrak dosyasiyla iletir, dongu bayragin durumu degisince buraya
-- yazar (veritabanina tek yazar ilkesi).
CREATE TABLE IF NOT EXISTS komutlar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman_utc       TEXT NOT NULL,
    komut           TEXT NOT NULL,
    kaynak          TEXT,
    sonuc           TEXT
);

-- Panelde gorunen sorun listesi. Ayni anahtar kisa surede tekrar gelirse
-- yeni satir acilmaz, tekrar sayaci artar (her saat ayni saglik sorunu
-- tabloyu doldurmasin).
CREATE TABLE IF NOT EXISTS uyarilar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ilk_utc         TEXT NOT NULL,
    son_utc         TEXT NOT NULL,
    seviye          TEXT NOT NULL,          -- 'bilgi' | 'uyari' | 'kotu'
    anahtar         TEXT NOT NULL,
    konu            TEXT NOT NULL,
    mesaj           TEXT,
    tekrar          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_uyari_anahtar ON uyarilar (anahtar, son_utc);
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


def emir_ek_guncelle(
    conn: sqlite3.Connection, client_order_id: str, *, ek_seviye: float, bar_zamani: str,
) -> None:
    """Borsadaki alış emri aynı kaldı ama bar değişti: dolunca kurulacak
    zararına satış seviyesini son barın değerine çeker (backtest dolum barının
    çizgisini kullanır)."""
    conn.execute(
        "UPDATE emirler SET ek_seviye = ?, bar_zamani = ?, guncellendi_utc = ? "
        "WHERE client_order_id = ?",
        (_sayi(ek_seviye), bar_zamani, simdi_utc(), client_order_id),
    )


def emir_var_mi(conn: sqlite3.Connection, client_order_id: str) -> bool:
    """Bu kimlik daha önce kullanıldı mı (hangi durumda olursa olsun)."""
    return conn.execute("SELECT 1 FROM emirler WHERE client_order_id = ?",
                        (client_order_id,)).fetchone() is not None


def bekleyenleri_kapat(conn: sqlite3.Connection, yeni_durum: str) -> None:
    """Henüz akıbeti işlenmemiş tüm emirleri kapatır (acil durdurmada)."""
    conn.execute(
        "UPDATE emirler SET durum = ?, guncellendi_utc = ? WHERE durum = 'gonderildi'",
        (yeni_durum, simdi_utc()),
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


# ------------------------------------------------------------------ TURLAR --

def tur_yaz(
    conn: sqlite3.Connection,
    *,
    baslangic_utc: str,
    bitis_utc: str,
    sonuc: str,
    ozet: str = "",
    hata: str = "",
) -> None:
    """Döngünün bir turunu kalp atışı olarak yazar. Yalnızca eklenir."""
    conn.execute(
        "INSERT INTO turlar (baslangic_utc, bitis_utc, sonuc, ozet, hata) "
        "VALUES (?, ?, ?, ?, ?)",
        (baslangic_utc, bitis_utc, sonuc, ozet, hata),
    )


def son_tur(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """En son yazılan tur; hiç tur yoksa None."""
    return conn.execute(
        "SELECT * FROM turlar ORDER BY id DESC LIMIT 1").fetchone()


def son_turlar(conn: sqlite3.Connection, adet: int = 50) -> list[sqlite3.Row]:
    """En yeni turlar, yeniden eskiye."""
    return conn.execute(
        "SELECT * FROM turlar ORDER BY id DESC LIMIT ?", (int(adet),)).fetchall()


# ---------------------------------------------------------------- ALARMLAR --

def alarm_gonderildi_mi(
    conn: sqlite3.Connection,
    anahtar: str,
    *,
    sessizlik_saat: float,
    simdi: datetime | None = None,
) -> bool:
    """Bu anahtar son `sessizlik_saat` içinde gönderildi mi?"""
    satir = conn.execute(
        "SELECT son_gonderim FROM alarmlar WHERE anahtar = ?", (anahtar,)).fetchone()
    if satir is None:
        return False
    son = datetime.strptime(satir["son_gonderim"], "%Y-%m-%dT%H:%M:%S%z")
    simdi = simdi or datetime.now(timezone.utc)
    return (simdi - son).total_seconds() < sessizlik_saat * 3600


def alarm_isaretle(
    conn: sqlite3.Connection, anahtar: str, *, simdi: datetime | None = None,
) -> None:
    """Anahtarı 'şimdi gönderildi' diye işaretler, sayacı artırır."""
    an = (simdi or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    conn.execute(
        """
        INSERT INTO alarmlar (anahtar, son_gonderim, adet) VALUES (?, ?, 1)
        ON CONFLICT(anahtar) DO UPDATE SET
            son_gonderim = excluded.son_gonderim, adet = alarmlar.adet + 1
        """,
        (anahtar, an),
    )


# ---------------------------------------------------------------- KOMUTLAR --

def komut_yaz(
    conn: sqlite3.Connection,
    *,
    komut: str,
    kaynak: str = "",
    sonuc: str = "",
    zaman_utc: str | None = None,
) -> None:
    """Arayüzden gelen komutu kütüğe yazar (yazan döngüdür, arayüz değil)."""
    conn.execute(
        "INSERT INTO komutlar (zaman_utc, komut, kaynak, sonuc) VALUES (?, ?, ?, ?)",
        (zaman_utc or simdi_utc(), komut, kaynak, sonuc),
    )


# ---------------------------------------------------------------- UYARILAR --

BILGI, UYARI, KOTU = "bilgi", "uyari", "kotu"
UYARI_BIRLESTIRME_SAAT = 6.0


def uyari_yaz(
    conn: sqlite3.Connection,
    *,
    seviye: str,
    anahtar: str,
    konu: str,
    mesaj: str = "",
    simdi: datetime | None = None,
) -> None:
    """Panelin uyarı tablosuna satır ekler.

    Aynı anahtar ve konu son `UYARI_BIRLESTIRME_SAAT` içinde yazıldıysa yeni
    satır açılmaz; o satırın tekrar sayısı ve son zamanı güncellenir.
    """
    an = (simdi or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    son = conn.execute(
        "SELECT id, son_utc, konu FROM uyarilar WHERE anahtar = ? "
        "ORDER BY id DESC LIMIT 1", (anahtar,)).fetchone()
    if son is not None and son["konu"] == konu:
        gecen = (datetime.strptime(an, "%Y-%m-%dT%H:%M:%S%z")
                 - datetime.strptime(son["son_utc"], "%Y-%m-%dT%H:%M:%S%z"))
        if gecen.total_seconds() < UYARI_BIRLESTIRME_SAAT * 3600:
            conn.execute(
                "UPDATE uyarilar SET son_utc = ?, tekrar = tekrar + 1, mesaj = ?, "
                "seviye = ? WHERE id = ?", (an, mesaj, seviye, son["id"]))
            return
    conn.execute(
        "INSERT INTO uyarilar (ilk_utc, son_utc, seviye, anahtar, konu, mesaj) "
        "VALUES (?, ?, ?, ?, ?, ?)", (an, an, seviye, anahtar, konu, mesaj))


def son_uyarilar(conn: sqlite3.Connection, adet: int = 20) -> list[sqlite3.Row]:
    """En yeni uyarılar, yeniden eskiye."""
    return conn.execute(
        "SELECT * FROM uyarilar ORDER BY son_utc DESC, id DESC LIMIT ?",
        (int(adet),)).fetchall()
