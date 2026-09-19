"""E-posta bildirimi — bir şey bozulunca, işlem olunca, günde bir özet.

İki kural hepsinin üstünde
--------------------------
1. **Asla istisna yükseltmez.** Alarm gönderememek işlem yapmayı durdurmamalı.
   SMTP hatası loglanır, `False` döner, döngü devam eder.
2. **Aynı şeyi tekrar tekrar göndermez.** Kalıcı bir bozukluk saat başı
   e-posta yağdırırsa alarmlar okunmaz hale gelir — tam da önemli olduğu anda.
   Her alarmın bir `anahtar`ı var; aynı anahtar `sessizlik_saat` içinde ikinci
   kez gitmez (`paper.db` → `alarmlar`).

Günlük özetin asıl işlevi
-------------------------
Özet her gün gelir. **Gelmediği gün sistem ölmüş demektir.** Alarm sistemi
"bozulunca haber ver" üzerine kuruluysa, alarm sisteminin kendisinin ölmesi
sessizlikle aynı görünür; düzenli gelen özet bu kör noktayı kapatır.

Ayarlar (`.env`)
----------------
    SMTP_SUNUCU=smtp.gmail.com
    SMTP_PORT=587
    SMTP_KULLANICI=...@gmail.com
    SMTP_SIFRE=...            # Gmail: normal parola ÇALIŞMAZ, "uygulama parolası"
    ALARM_ALICI=...@...

Eksikse alarm sessizce devre dışı kalır (yalnızca log) — paper koşusu e-posta
kurulmadan da başlayabilsin.
"""

from __future__ import annotations

import datetime as dt
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from src.data.alpaca import load_dotenv

from . import durum as D
from . import gunluk

REPO_ROOT = Path(__file__).resolve().parents[2]
BORSA_TZ = ZoneInfo("America/New_York")
KONU_ONEKI = "[KABUL-1 paper]"

# Özetin gönderileceği en erken saat (borsa saatiyle). Kapanış 16:00;
# son tur 15:20'de, 16:20 turu borsa kapalı olduğu için ucuza çıkar.
OZET_SAATI = dt.time(16, 20)

HER_ZAMAN = 24 * 365 * 10      # "bir kez gönder" için sessizlik: fiilen sonsuz


@dataclass(frozen=True, slots=True)
class SmtpAyar:
    sunucu: str
    port: int
    kullanici: str
    sifre: str
    alici: str


Gonderici = Callable[[EmailMessage, SmtpAyar], None]


def ayar_oku(dotenv_yolu: Path | str = REPO_ROOT / ".env") -> SmtpAyar | None:
    """`.env`'den SMTP ayarlarını okur; biri eksikse None."""
    load_dotenv(dotenv_yolu)
    alanlar = {k: os.environ.get(k, "").strip() for k in (
        "SMTP_SUNUCU", "SMTP_PORT", "SMTP_KULLANICI", "SMTP_SIFRE", "ALARM_ALICI")}
    if not all(alanlar.values()):
        return None
    try:
        port = int(alanlar["SMTP_PORT"])
    except ValueError:
        return None
    return SmtpAyar(alanlar["SMTP_SUNUCU"], port, alanlar["SMTP_KULLANICI"],
                    alanlar["SMTP_SIFRE"], alanlar["ALARM_ALICI"])


def _smtp_gonder(ileti: EmailMessage, ayar: SmtpAyar) -> None:
    """Gerçek gönderim. 465 → SSL, diğerleri → STARTTLS."""
    if ayar.port == 465:
        with smtplib.SMTP_SSL(ayar.sunucu, ayar.port, timeout=20) as s:
            s.login(ayar.kullanici, ayar.sifre)
            s.send_message(ileti)
    else:
        with smtplib.SMTP(ayar.sunucu, ayar.port, timeout=20) as s:
            s.starttls()
            s.login(ayar.kullanici, ayar.sifre)
            s.send_message(ileti)


def gonder(
    konu: str,
    govde: str,
    *,
    anahtar: str,
    sessizlik_saat: float = 6.0,
    paper_db: Path | str = D.DEFAULT_PAPER_DB_PATH,
    ayar: SmtpAyar | None = None,
    gonderici: Gonderici | None = None,
    simdi: dt.datetime | None = None,
    seviye: str = D.KOTU,
    kayit: bool = True,
) -> bool:
    """E-posta gönderir; gönderildiyse True. **Asla istisna yükseltmez.**

    Aynı `anahtar` son `sessizlik_saat` içinde gönderildiyse gönderilmez.

    `kayit=True` (sorun alarmları) ise olay panelin uyarı tablosuna da yazılır
    — e-posta ayarlı olmasa ve susturulmuş olsa bile. İşlem bildirimi ve
    günlük özet sorun değildir, `kayit=False` ile çağrılır.
    """
    log = gunluk.al()
    if kayit:
        try:
            with D.connect(paper_db) as conn:
                D.uyari_yaz(conn, seviye=seviye, anahtar=anahtar, konu=konu,
                            mesaj=govde[:2000], simdi=simdi)
        except Exception as exc:
            log.error("uyarı kaydedilemedi (%s): %s — %s", anahtar, konu, exc)
    try:
        ayar = ayar or ayar_oku()
        if ayar is None:
            log.info("alarm (e-posta ayarlı değil, yalnızca log): %s", konu)
            return False

        with D.connect(paper_db) as conn:
            if D.alarm_gonderildi_mi(conn, anahtar, sessizlik_saat=sessizlik_saat,
                                     simdi=simdi):
                log.info("alarm susturuldu (%s, son %.0f saat içinde gitti): %s",
                         anahtar, sessizlik_saat, konu)
                return False

        ileti = EmailMessage()
        ileti["Subject"] = f"{KONU_ONEKI} {konu}"
        ileti["From"] = ayar.kullanici
        ileti["To"] = ayar.alici
        ileti.set_content(govde, charset="utf-8")
        (gonderici or _smtp_gonder)(ileti, ayar)

        with D.connect(paper_db) as conn:
            D.alarm_isaretle(conn, anahtar, simdi=simdi)
        log.info("alarm gönderildi (%s): %s", anahtar, konu)
        return True
    except Exception as exc:          # SMTP, ağ, disk — hiçbiri döngüyü öldürmemeli
        log.error("alarm GÖNDERİLEMEDİ (%s): %s — %s", anahtar, konu, exc)
        return False


# ---------------------------------------------------- HAZIR BİLDİRİMLER --

def saglik_bildir(sonuclar, **kw) -> int:
    """Kötü çıkan her sağlık kontrolü için ayrı anahtarla alarm. Gidenlerin sayısı."""
    from .saglik import KOTU, metin_rapor
    kotuler = [k for k in sonuclar if k.seviye == KOTU]
    rapor = metin_rapor(sonuclar)
    giden = 0
    for k in kotuler:
        giden += gonder(f"SORUN: {k.ad} — {k.mesaj}"[:120], rapor,
                        anahtar=f"saglik_{k.ad}", **kw)
    return giden


def islemleri_bildir(paper_db: Path | str = D.DEFAULT_PAPER_DB_PATH, **kw) -> int:
    """Dolan her emir için bir kez e-posta. Gidenlerin sayısı."""
    with D.connect(paper_db) as conn:
        satirlar = conn.execute(
            "SELECT * FROM gerceklesmeler ORDER BY id").fetchall()
    giden = 0
    for g in satirlar:
        yon = "ALIŞ" if g["tip"] == "limit_al" else "SATIŞ"
        konu = "%s %d adet @ %.2f" % (yon, g["adet"], g["gerceklesen_fiyat"])
        govde = (f"{yon} gerçekleşti\n\n"
                 f"  adet        : {g['adet']}\n"
                 f"  istenen     : {g['istenen_seviye']:.2f}\n"
                 f"  gerçekleşen : {g['gerceklesen_fiyat']:.2f}\n"
                 f"  zaman (UTC) : {g['gerceklesme_utc']}\n"
                 f"  emir        : {g['client_order_id']}\n")
        giden += gonder(konu, govde, anahtar=f"islem_{g['client_order_id']}",
                        sessizlik_saat=HER_ZAMAN, paper_db=paper_db, kayit=False, **kw)
    return giden


def ozet_zamani_mi(simdi: dt.datetime) -> str | None:
    """Kapanıştan sonraysa günün tarihini (borsa saatiyle) döner, değilse None."""
    yerel = simdi.astimezone(BORSA_TZ)
    return yerel.date().isoformat() if yerel.time() >= OZET_SAATI else None


def gunluk_ozet_gonder(
    paper_db: Path | str = D.DEFAULT_PAPER_DB_PATH,
    *,
    ek_metin: str = "",
    simdi: dt.datetime | None = None,
    **kw,
) -> bool:
    """Kapanıştan sonra, günde bir kez özet. Zamanı değilse hiçbir şey yapmaz."""
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    gun = ozet_zamani_mi(simdi)
    if gun is None:
        return False

    from .rapor import metin_rapor
    with D.connect(paper_db) as conn:
        bugun = conn.execute(
            "SELECT sonuc, COUNT(*) AS n FROM turlar WHERE baslangic_utc >= ? "
            "GROUP BY sonuc", ((simdi - dt.timedelta(hours=24)).strftime(
                "%Y-%m-%dT%H:%M:%S+0000"),)).fetchall()
        rapor = metin_rapor(conn)
    tur_ozeti = ", ".join(f"{r['sonuc']} {r['n']}" for r in bugun) or "hiç tur yok"
    govde = (f"Günlük özet — {gun}\n\n"
             f"Son 24 saatte turlar: {tur_ozeti}\n\n"
             f"{ek_metin}\n\n{rapor}\n\n"
             "Bu e-posta her gün gelir. Gelmediği gün sistem çalışmıyor demektir.")
    return gonder(f"Günlük özet {gun}", govde, anahtar=f"gunluk_ozet_{gun}",
                  sessizlik_saat=HER_ZAMAN, paper_db=paper_db, simdi=simdi,
                  kayit=False, **kw)
