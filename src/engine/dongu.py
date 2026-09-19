"""Motoru kendi kendine çalıştıran döngü.

    python -m src.engine.dongu            # gerçek emirlerle (Alpaca PAPER)
    python -m src.engine.dongu --kuru     # emir göndermeden, sadece anlatır

İşletim sistemine bağımlı değil
-------------------------------
cron, Görev Zamanlayıcı, systemd timer kullanılmaz — sistem nerede
çalışacaksa (dizüstü, AWS, konteyner) aynı komutla çalışsın diye. Döngü kendi
içinde saati izler.

Ne zaman tur atar
-----------------
Açılışta bir kez, sonra **her saatin :20'sinde** (UTC). Bar hh:00'da kapanır;
ücretsiz SIP 15 dakika gecikmeli ve motor `kesim = şimdi − 16 dk` kullanıyor.
hh:20'de kesim hh:04 olur, yani hh:00'da kapanan bar tamdır. 4 dakika pay.

Arada, **dakikada bir** koruma bekçisi (`motor.koruma_turu`) çalışır:
"elimdeki hisse kadar taban emri borsada mı?" Boştayken broker'a hiç
gitmez, borsa kapalıyken tek istekle çıkar. Hata verirse loglanır ve alarm
gider; döngüyü durdurmaz, hata sayacına da girmez.

Döngü **borsa takvimini bilmez.** `bir_tur` ilk iş olarak broker'a borsa açık
mı diye soruyor ve kapalıysa ucuza çıkıyor. Tatil, yarım gün, yaz saati
bilgisi tek yerde kalsın diye takvim buraya kopyalanmadı.

Hata tavrı
----------
Tur hata verirse: loglanır, alarm gider, döngü **devam eder** (tek bir ağ
kopması sistemi öldürmesin). **Üst üste 3 hata** olursa döngü durur ve yüksek
öncelikli alarm gider — kalıcı bir bozuklukta körü körüne devam etmesin.
`data/DUR` OLUŞTURULMAZ: o dosya pozisyonu piyasadan kapatır, geçici ağ hatası
için fazla sert. Borsadaki `gtc` koruyucu stop yerinde kalır.

Bayraklar (arayüzden gelen komutlar)
------------------------------------
Döngü uyurken 5 saniyede bir uyanır ve `data/DUR` / `data/DURAKLAT`
dosyalarına bakar. `DUR` belirirse acil tur **hemen** çalışır — bir saat
sonraki turu beklemez. Bayrağın belirmesi/kalkması `komutlar` tablosuna
yazılır (veritabanına tek yazar döngüdür, arayüz değil).

Tek örnek
---------
`data/dongu.pid` kilit dosyası. Döngü uyurken onu düzenli tazeler; tazeyse
ikinci bir döngü başlamayı reddeder. Kilit bayatsa (süreç ölmüş) devralınır.
Süreç yoklaması bilerek pid ile yapılmıyor: Windows'ta `os.kill(pid, 0)`
süreci yoklamaz, **öldürür**.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import alarm, gosterim, gunluk, saglik
from . import durum as D
from .motor import Ayarlar, TurSonucu, bir_tur, koruma_turu

DILIM_SN = 5.0
KORUMA_ARALIK_SN = 60.0
KILIT_BAYAT_SN = saglik.AZAMI_KILIT_YASI_SN


# ------------------------------------------------------------------ SAAT --

def sonraki_tetik(simdi: dt.datetime, dakika: int = 20) -> dt.datetime:
    """`simdi`den KESİN SONRA gelen ilk hh:`dakika` (UTC)."""
    simdi = simdi.astimezone(dt.timezone.utc)
    aday = simdi.replace(minute=dakika, second=0, microsecond=0)
    if aday <= simdi:
        aday += dt.timedelta(hours=1)
    return aday


def _iso(an: dt.datetime) -> str:
    return an.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


# ----------------------------------------------------------------- KİLİT --

class KilitAlinamadi(RuntimeError):
    """Başka bir döngü zaten çalışıyor."""


class Kilit:
    """`data/dongu.pid` — tek örnek garantisi ve 'ayaktayım' işareti."""

    def __init__(self, yol: Path, *, simdi: Callable[[], float] = time.time):
        self.yol = Path(yol)
        self._simdi = simdi
        self._bizim = False

    def al(self) -> None:
        if self.yol.exists():
            yas = self._simdi() - self.yol.stat().st_mtime
            if yas < KILIT_BAYAT_SN:
                sahip = self.yol.read_text(encoding="utf-8").strip() or "?"
                raise KilitAlinamadi(
                    f"başka bir döngü çalışıyor (pid {sahip}, kilit {int(yas)} sn önce "
                    f"tazelendi): {self.yol}")
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        self.yol.write_text(str(os.getpid()), encoding="utf-8")
        self._bizim = True

    def tazele(self) -> None:
        if self._bizim:
            an = self._simdi()
            os.utime(self.yol, (an, an))

    def birak(self) -> None:
        if self._bizim and self.yol.exists():
            try:
                if self.yol.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    self.yol.unlink()
            except OSError:
                pass
        self._bizim = False


# -------------------------------------------------------------- BAYRAKLAR --

def _bayrak_bilgisi(yol: Path) -> dict:
    """Arayüzün bayrağa yazdığı JSON (komut, kaynak, zaman). Bozuksa boş."""
    try:
        return json.loads(yol.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}


@dataclass
class _BayrakIzleyici:
    """DUR / DURAKLAT dosyalarının belirmesini ve kalkmasını fark eder."""

    ayarlar: Ayarlar
    paper_db: Path
    onceki: dict[str, bool] = field(default_factory=dict)

    def bak(self) -> bool:
        """Değişiklikleri kütüğe yazar. DUR YENİ belirdiyse True (acil tur gerek)."""
        log = gunluk.al()
        acil = False
        for ad, yol in (("DUR", self.ayarlar.dur_dosyasi),
                        ("DURAKLAT", self.ayarlar.duraklat_dosyasi)):
            var = yol.exists()
            if ad not in self.onceki:            # ilk bakış: yalnızca durumu öğren
                self.onceki[ad] = var
                if var:
                    log.warning("%s bayrağı açılışta mevcut", ad)
                continue
            if var == self.onceki[ad]:
                continue
            self.onceki[ad] = var
            bilgi = _bayrak_bilgisi(yol) if var else {}
            olay = f"{ad} {'kondu' if var else 'kaldırıldı'}"
            kaynak = str(bilgi.get("kaynak", ""))
            log.warning("BAYRAK: %s (kaynak: %s)", olay, kaynak or "bilinmiyor")
            with D.connect(self.paper_db) as conn:
                D.komut_yaz(conn, komut=bilgi.get("komut", olay), kaynak=kaynak,
                            sonuc=olay)
            if var:
                alarm.gonder(
                    f"KOMUT: {olay}",
                    f"{olay}\nkaynak: {kaynak or 'bilinmiyor'}\n"
                    f"komut: {bilgi.get('komut', '-')}\nzaman: {D.simdi_utc()}",
                    anahtar=f"komut_{ad}_{D.simdi_utc()}",
                    sessizlik_saat=alarm.HER_ZAMAN, paper_db=self.paper_db,
                    kayit=False)
            if ad == "DUR" and var:
                acil = True
        return acil


# ------------------------------------------------------------------ DÖNGÜ --

TurFn = Callable[..., TurSonucu]


def _uyarilari_isle(ayarlar: Ayarlar, ts: TurSonucu, bildir: bool) -> None:
    """Turun uyarılarını panelin tablosuna yazar; sorunları e-postalar. Asla patlamaz."""
    log = gunluk.al()
    for u in ts.uyarilar:
        try:
            if bildir and u.seviye != D.BILGI:
                alarm.gonder(u.konu[:120], u.mesaj or u.konu, anahtar=u.anahtar,
                             seviye=u.seviye, paper_db=ayarlar.paper_db)
            else:
                with D.connect(ayarlar.paper_db) as conn:
                    D.uyari_yaz(conn, seviye=u.seviye, anahtar=u.anahtar,
                                konu=u.konu, mesaj=u.mesaj)
        except Exception as exc:
            log.error("uyarı işlenemedi (%s): %s", u.anahtar, exc)


def _koruma(ayarlar: Ayarlar, kuru: bool, koruma_fn: TurFn, bildir: bool) -> None:
    """Koruma bekçisinin bir geçişi. Asla patlamaz — döngü sürmeli."""
    log = gunluk.al()
    try:
        ts = koruma_fn(ayarlar, kuru=kuru)
    except Exception as exc:
        log.error("KORUMA HATASI: %s\n%s", exc, traceback.format_exc())
        if bildir:
            alarm.gonder(f"KORUMA HATASI: {exc}"[:120], traceback.format_exc(),
                         anahtar="koruma_hatasi", paper_db=ayarlar.paper_db)
        return
    if ts.satirlar or ts.durduruldu:        # yalnızca bir şey olduysa log
        (log.warning if ts.uyarilar else log.info)("koruma: %s", ts)
    _uyarilari_isle(ayarlar, ts, bildir)


def _tur(ayarlar: Ayarlar, kuru: bool, tur_fn: TurFn,
         simdi_fn: Callable[[], dt.datetime], bildir: bool = False) -> tuple[str, str]:
    """Tek tur: çalıştırır, kalp atışını yazar. (sonuc, özet) döner; istisnayı yukarı atar."""
    log = gunluk.al()
    baslangic = simdi_fn()
    try:
        ts = tur_fn(ayarlar, kuru=kuru)
    except Exception as exc:
        hata = f"{type(exc).__name__}: {exc}"
        with D.connect(ayarlar.paper_db) as conn:
            D.tur_yaz(conn, baslangic_utc=_iso(baslangic), bitis_utc=_iso(simdi_fn()),
                      sonuc="hata", ozet="", hata=hata[:2000])
        log.error("TUR HATASI: %s\n%s", hata, traceback.format_exc())
        raise

    sonuc = "durduruldu" if ts.durduruldu else "tamam"
    ozet = ts.ozet.splitlines()[0] if ts.ozet else ""
    with D.connect(ayarlar.paper_db) as conn:
        D.tur_yaz(conn, baslangic_utc=_iso(baslangic), bitis_utc=_iso(simdi_fn()),
                  sonuc=sonuc, ozet=str(ts)[:2000])
    (log.warning if ts.durduruldu else log.info)("tur %s: %s", sonuc, ts)
    _uyarilari_isle(ayarlar, ts, bildir)
    return sonuc, ozet


def _bildirimler(ayarlar: Ayarlar, sonuc: str, ozet: str) -> None:
    """Tur sonrası: sağlık alarmı, işlem bildirimi, günlük özet. Asla patlamaz."""
    log = gunluk.al()
    try:
        if sonuc == "durduruldu":
            alarm.gonder(f"MOTOR DURDU: {ozet}"[:120], ozet,
                         anahtar="tur_durdu", paper_db=ayarlar.paper_db)
        kontroller = saglik.kontroller(ayarlar)
        alarm.saglik_bildir(kontroller, paper_db=ayarlar.paper_db)
        alarm.islemleri_bildir(ayarlar.paper_db)
        alarm.gunluk_ozet_gonder(ayarlar.paper_db,
                                 ek_metin=saglik.metin_rapor(kontroller))
    except Exception as exc:
        log.error("bildirimler çalışmadı: %s", exc)


def _gosterim(ayarlar: Ayarlar, gosterim_fn: Callable[[Ayarlar], object] | None) -> None:
    """Panelin gösterdiği seriler (dakikalık, günlük, izlenen semboller).

    Karar yolunun dışında: hatası loglanır, turu ve ardışık hata sayacını
    etkilemez. Grafiğin eksik kalması işlem durdurmaz.
    """
    if gosterim_fn is None:
        return
    try:
        gosterim_fn(ayarlar)
    except Exception as exc:
        gunluk.al().error("gösterim verisi tazelenemedi: %s", exc)


def dongu(
    ayarlar: Ayarlar | None = None,
    *,
    kuru: bool = False,
    tetik_dakika: int = 20,
    azami_ardisik_hata: int = 3,
    tur_fn: TurFn = bir_tur,
    gosterim_fn: Callable[[Ayarlar], object] | None = gosterim.tazele,
    koruma_fn: TurFn | None = koruma_turu,
    koruma_aralik_sn: float = KORUMA_ARALIK_SN,
    simdi_fn: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
    uyu_fn: Callable[[float], None] = time.sleep,
    bildir: bool = True,
    sinyal_yakala: bool = True,
    azami_tur: int | None = None,
) -> int:
    """Döngüyü çalıştırır. Çıkış kodu: 0 düzgün kapandı, 1 ardışık hata, 2 kilit.

    `azami_tur` yalnızca testler için: o kadar turdan sonra düzgünce çıkar.
    `koruma_fn=None` koruma bekçisini kapatır (yalnızca testler).
    """
    ayarlar = ayarlar or Ayarlar()
    log = gunluk.al()
    kilit = Kilit(ayarlar.kilit_dosyasi, simdi=lambda: simdi_fn().timestamp())
    try:
        kilit.al()
    except KilitAlinamadi as exc:
        log.error("%s", exc)
        return 2

    durdur = {"istendi": False}

    def _isaret(signum, _frame):
        log.warning("kapanma isteği (sinyal %s) — o anki tur bitince çıkılacak", signum)
        durdur["istendi"] = True

    if sinyal_yakala:
        for ad in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, ad):
                try:
                    signal.signal(getattr(signal, ad), _isaret)
                except (ValueError, OSError):
                    pass       # ana iş parçacığında değilse

    izleyici = _BayrakIzleyici(ayarlar, Path(ayarlar.paper_db))
    izleyici.bak()
    ardisik = 0
    tur_sayisi = 0
    log.info("döngü başladı — %s, %s, tetik her saatin :%02d'si (UTC)",
             ayarlar.sembol, "KURU" if kuru else "gerçek emir (paper)", tetik_dakika)

    try:
        while not durdur["istendi"]:
            # ---- tur
            try:
                sonuc, ozet = _tur(ayarlar, kuru, tur_fn, simdi_fn, bildir)
                ardisik = 0
                if bildir:
                    _bildirimler(ayarlar, sonuc, ozet)
                _gosterim(ayarlar, gosterim_fn)
            except Exception as exc:
                ardisik += 1
                if bildir:
                    alarm.gonder(f"TUR HATASI ({ardisik}/{azami_ardisik_hata}): {exc}"[:120],
                                 traceback.format_exc(), anahtar="tur_hatasi",
                                 paper_db=ayarlar.paper_db)
                if ardisik >= azami_ardisik_hata:
                    mesaj = (f"{ardisik} tur üst üste hata verdi — DÖNGÜ DURDU. "
                             "Yeni emir gönderilmeyecek. Borsadaki koruyucu stop yerinde; "
                             "data/DUR oluşturulmadı. Sorun giderilince döngüyü yeniden başlat.")
                    log.critical(mesaj)
                    if bildir:
                        alarm.gonder("DÖNGÜ DURDU — üst üste hata", mesaj,
                                     anahtar="ucuncu_hata", sessizlik_saat=0,
                                     paper_db=ayarlar.paper_db)
                    return 1

            tur_sayisi += 1
            if azami_tur is not None and tur_sayisi >= azami_tur:
                break

            # ---- uyku (kısa dilimler: bayrak, kapanma isteği, saat kayması)
            hedef = sonraki_tetik(simdi_fn(), tetik_dakika)
            log.info("sonraki tur %s UTC", hedef.strftime("%Y-%m-%d %H:%M"))
            son_koruma = simdi_fn()
            while not durdur["istendi"]:
                try:
                    kilit.tazele()
                    acil = izleyici.bak()
                except Exception as exc:       # disk/DB kilidi — uykuyu bozmasın
                    log.error("bayrak/kilit kontrolü başarısız: %s", exc)
                    acil = False
                if acil:
                    log.warning("DUR bayrağı göründü — acil tur hemen çalışıyor")
                    break
                if (koruma_fn is not None
                        and (simdi_fn() - son_koruma).total_seconds() >= koruma_aralik_sn):
                    son_koruma = simdi_fn()
                    _koruma(ayarlar, kuru, koruma_fn, bildir)
                kalan = (hedef - simdi_fn()).total_seconds()
                if kalan <= 0:
                    break
                uyu_fn(min(DILIM_SN, kalan))
    finally:
        kilit.birak()
        log.info("döngü kapandı")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Motoru saat başı kendi kendine çalıştırır.")
    p.add_argument("--kuru", action="store_true", help="hiçbir emir gönderme")
    p.add_argument("--sembol", default="AAPL")
    p.add_argument("--tetik-dakika", type=int, default=20,
                   help="her saatin kaçıncı dakikasında tur atılsın (UTC)")
    args = p.parse_args(argv)
    gunluk.kur()
    return dongu(Ayarlar(sembol=args.sembol), kuru=args.kuru,
                 tetik_dakika=args.tetik_dakika)


if __name__ == "__main__":
    raise SystemExit(main())
