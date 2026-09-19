"""Sistem sağlam mı? — tek komutla durum raporu.

    python -m src.engine.saglik          # çıkış kodu: 0 sağlam, 1 sorun var

Neden var
---------
Motor sürekli ekranda duran bir program değil: saat başı bir tur atıp
uyuyor. "Motor çalışıyor" ile "üç gün önce ölüp sustu" dışarıdan aynı görünür.
Bu modül motorun geride bıraktığı izlere (`paper.db`) ve broker'a bakıp
tek ekranda söyler.

Kontroller BURADA bir kez yazılır; `alarm.py` ve arayüzün `/durum` komutu
aynı fonksiyonu çağırır.

Üç seviye
---------
* `iyi`   — sorun yok.
* `uyari` — dikkat, ama doğal olarak da olabilir (ör. sabah 9:30–10:20 arası
            bekleyen alış emri yoktur; önceki gün `day` emri süresi doldu,
            ilk tur 10:20'de). Çıkış kodunu bozmaz, alarm atmaz.
* `kotu`  — müdahale gerekir. Çıkış kodu 1.
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

from src.data.db import connect as veri_baglan
from src.data.senkron import son_bar_zamani

from . import durum as D
from .broker import Broker
from .motor import Ayarlar

IYI, UYARI, KOTU = "iyi", "uyari", "kotu"

# Döngü her saatin :20'sinde tur atar; bir tur kaçarsa bile 70 dakika yeter.
AZAMI_TUR_ARALIGI_DK = 70
# Döngü uyurken kilit dosyasını tazeler; bundan eskiyse süreç ölmüş sayılır.
AZAMI_KILIT_YASI_SN = 120


@dataclass(frozen=True, slots=True)
class Kontrol:
    ad: str
    seviye: str          # IYI | UYARI | KOTU
    mesaj: str

    @property
    def saglam(self) -> bool:
        return self.seviye != KOTU


def _utc(metin: str) -> dt.datetime:
    return dt.datetime.strptime(metin, "%Y-%m-%dT%H:%M:%S%z")


def _dakika(fark: dt.timedelta) -> str:
    dk = int(fark.total_seconds() // 60)
    return f"{dk} dk" if dk < 120 else f"{dk // 60} sa {dk % 60} dk"


# ------------------------------------------------------------ KONTROLLER --

def _son_tur(conn, simdi: dt.datetime) -> list[Kontrol]:
    tur = D.son_tur(conn)
    if tur is None:
        return [Kontrol("son tur", KOTU, "hiç tur yok — döngü hiç çalışmamış"),
                Kontrol("son tur sonucu", UYARI, "—")]
    yas = simdi - _utc(tur["baslangic_utc"])
    zaman = Kontrol(
        "son tur",
        IYI if yas <= dt.timedelta(minutes=AZAMI_TUR_ARALIGI_DK) else KOTU,
        f"{tur['baslangic_utc'][:16].replace('T', ' ')} UTC ({_dakika(yas)} önce)",
    )
    if tur["sonuc"] == "hata":
        sonuc = Kontrol("son tur sonucu", KOTU, f"HATA: {tur['hata'] or tur['ozet']}")
    else:
        sonuc = Kontrol("son tur sonucu", IYI, f"{tur['sonuc']} — {tur['ozet'] or ''}"[:160])
    return [zaman, sonuc]


def _kilit(ayarlar: Ayarlar, simdi: dt.datetime) -> Kontrol:
    yol = ayarlar.kilit_dosyasi
    if not yol.exists():
        return Kontrol("döngü süreci", KOTU, "çalışmıyor (kilit dosyası yok)")
    yas = simdi.timestamp() - yol.stat().st_mtime
    if yas > AZAMI_KILIT_YASI_SN:
        return Kontrol("döngü süreci", KOTU,
                       f"yanıt vermiyor — kilit {int(yas)} sn önce tazelendi")
    pid = yol.read_text(encoding="utf-8").strip() or "?"
    return Kontrol("döngü süreci", IYI, f"ayakta (pid {pid})")


def _bayraklar(ayarlar: Ayarlar) -> list[Kontrol]:
    sonuc = []
    if ayarlar.dur_dosyasi.exists():
        sonuc.append(Kontrol("acil durdurma", KOTU,
                             f"{ayarlar.dur_dosyasi.name} VAR — motor işlem yapmıyor"))
    else:
        sonuc.append(Kontrol("acil durdurma", IYI, "yok"))
    if ayarlar.duraklat_dosyasi.exists():
        sonuc.append(Kontrol("duraklatma", UYARI,
                             "DURAKLATILDI — yeni alım yok, koruma sürüyor"))
    else:
        sonuc.append(Kontrol("duraklatma", IYI, "yok"))
    return sonuc


def _veri(ayarlar: Ayarlar, simdi: dt.datetime, borsa_acik: bool | None) -> Kontrol:
    if not Path(ayarlar.veri_db).is_file():
        return Kontrol("veri tazeliği", KOTU, f"{ayarlar.veri_db} yok")
    with veri_baglan(ayarlar.veri_db) as c:
        son = son_bar_zamani(c, ayarlar.sembol, timeframe=ayarlar.timeframe)
    if son is None:
        return Kontrol("veri tazeliği", KOTU, "depoda hiç bar yok")
    yas = simdi - son
    mesaj = f"son bar {son:%Y-%m-%d %H:%M} UTC ({_dakika(yas)} önce)"
    # Borsa kapalıyken veri doğal olarak eskir; yalnızca açıkken değerlendir.
    sinir = dt.timedelta(minutes=ayarlar.bar_dakika * (ayarlar.bayat_bar_siniri + 1)
                         + ayarlar.veri_gecikmesi_dk)
    if borsa_acik and yas > sinir:
        return Kontrol("veri tazeliği", KOTU, f"BAYAT — {mesaj}")
    return Kontrol("veri tazeliği", IYI, mesaj)


def _broker_kontrolleri(conn, ayarlar: Ayarlar, broker: Broker) -> tuple[list[Kontrol], bool | None]:
    """Broker'a bağlanıp mutabakat ve emirlere bakar. Borsa açık mı döner."""
    try:
        saat = broker.borsa_saati()
    except Exception as exc:       # ağ, anahtar, HTTP — hepsi aynı sonuç
        mesaj = f"bağlanılamadı: {exc}"[:200]
        return ([Kontrol("broker", KOTU, mesaj),
                 Kontrol("mutabakat", KOTU, "bakılamadı"),
                 Kontrol("koruyucu stop", KOTU, "bakılamadı")], None)

    kontroller = [Kontrol("broker", IYI,
                          "bağlı — borsa " + ("AÇIK" if saat.acik else
                                              f"kapalı, açılış {saat.sonraki_acilis[:16]}"))]

    durum, adet, _ = D.durum_yukle(conn)
    kayitli = adet if durum.acik else 0
    try:
        gercek_poz = broker.pozisyon(ayarlar.sembol)
        bekleyen = broker.bekleyen_emirler(ayarlar.sembol)
    except Exception as exc:
        return (kontroller + [Kontrol("mutabakat", KOTU, f"bakılamadı: {exc}"[:200]),
                              Kontrol("koruyucu stop", KOTU, "bakılamadı")], saat.acik)
    gercek = gercek_poz.adet if gercek_poz else 0

    if gercek == kayitli:
        kontroller.append(Kontrol("mutabakat", IYI,
                                  f"{ayarlar.sembol}: {gercek} adet, kayıt ile aynı"))
    else:
        kontroller.append(Kontrol("mutabakat", KOTU,
                                  f"BOZUK — broker {gercek}, kayıt {kayitli} adet"))

    satislar = [e for e in bekleyen if e.yon == "sell"]
    alislar = [e for e in bekleyen if e.yon == "buy"]
    if gercek > 0:
        koruyan = [e for e in satislar if e.adet >= gercek]
        if koruyan:
            e = koruyan[0]
            kontroller.append(Kontrol("koruyucu stop", IYI,
                                      f"borsada: {e.adet} adet @ {e.seviye:.2f}"))
        else:
            kontroller.append(Kontrol("koruyucu stop", KOTU,
                                      f"YOK — {gercek} adet pozisyon KORUMASIZ"))
    else:
        kontroller.append(Kontrol("koruyucu stop", IYI, "pozisyon yok, gerekmiyor"))
        if saat.acik and not ayarlar.duraklat_dosyasi.exists():
            if alislar:
                e = alislar[0]
                kontroller.append(Kontrol("alış emri", IYI,
                                          f"bekliyor: {e.adet} adet @ {e.seviye:.2f}"))
            else:
                kontroller.append(Kontrol("alış emri", UYARI,
                                          "borsa açık ama bekleyen alış emri yok"))
    return kontroller, saat.acik


def kontroller(
    ayarlar: Ayarlar | None = None,
    *,
    broker: Broker | None = None,
    simdi: dt.datetime | None = None,
) -> list[Kontrol]:
    """Bütün kontrolleri çalıştırır. İstisna yükseltmez — her sorun bir satır olur."""
    ayarlar = ayarlar or Ayarlar()
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    sonuc: list[Kontrol] = []

    try:
        broker = broker or Broker()
    except Exception as exc:
        broker = None
        broker_hatasi = f"kurulamadı: {exc}"[:200]

    with D.connect(ayarlar.paper_db) as conn:
        sonuc += _son_tur(conn, simdi)
        sonuc.append(_kilit(ayarlar, simdi))
        if broker is None:
            sonuc += [Kontrol("broker", KOTU, broker_hatasi),
                      Kontrol("mutabakat", KOTU, "bakılamadı"),
                      Kontrol("koruyucu stop", KOTU, "bakılamadı")]
            borsa_acik = None
        else:
            b_kontroller, borsa_acik = _broker_kontrolleri(conn, ayarlar, broker)
            sonuc += b_kontroller
    try:
        sonuc.append(_veri(ayarlar, simdi, borsa_acik))
    except Exception as exc:
        sonuc.append(Kontrol("veri tazeliği", KOTU, f"okunamadı: {exc}"[:200]))
    sonuc += _bayraklar(ayarlar)
    return sonuc


def saglam_mi(sonuclar: list[Kontrol]) -> bool:
    return all(k.saglam for k in sonuclar)


ISARET = {IYI: "✓", UYARI: "!", KOTU: "✗"}


def metin_rapor(sonuclar: list[Kontrol]) -> str:
    genislik = max(len(k.ad) for k in sonuclar)
    satirlar = [f"  {ISARET[k.seviye]} {k.ad:<{genislik}}  {k.mesaj}" for k in sonuclar]
    kotu = [k for k in sonuclar if k.seviye == KOTU]
    uyari = [k for k in sonuclar if k.seviye == UYARI]
    if kotu:
        son = f"SONUÇ: SORUN VAR ({len(kotu)})"
    elif uyari:
        son = f"SONUÇ: sağlam, {len(uyari)} uyarı"
    else:
        son = "SONUÇ: sağlam"
    return "\n".join(satirlar + ["", son])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sonuclar = kontroller()
    print(metin_rapor(sonuclar))
    return 0 if saglam_mi(sonuclar) else 1


if __name__ == "__main__":
    raise SystemExit(main())
