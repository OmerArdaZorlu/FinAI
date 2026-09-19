"""Kontrol terminalinin komutları.

Arayüz broker'a emir göndermez ve veritabanına yazmaz. Etkili komutlar
(`/stop`, `/duraklat`) **bayrak dosyası** bırakır; döngü 5 saniye içinde görür,
işler ve `komutlar` tablosuna yazar. `data/DUR` mekanizması zaten motorda
vardı ve testliydi — arayüz aynı kanalı kullanır.

Geri alınamaz komut onay ister: `/stop` pozisyonu piyasadan kapatır, bu yüzden
`/stop onayla` yazılmadan hiçbir şey yapmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.engine import gunluk
from src.engine.durum import simdi_utc
from src.engine.motor import Ayarlar

from . import veri

ONAY = "onayla"
SEVIYE_ADI = {"bilgi": "bilgi", "uyari": "UYARI", "kotu": "KÖTÜ"}


@dataclass(frozen=True, slots=True)
class Sonuc:
    metin: str
    basarili: bool = True
    tehlikeli: bool = False      # arayüz kırmızı gösterir


YARDIM = """\
Komutlar:
  /durum              sağlık kontrolleri (son tur, broker, mutabakat, stop...)
  /turlar [n]         son n tur (varsayılan 10)
  /gunluk [n]         motor günlüğünün son n satırı (varsayılan 30)
  /uyarilar [n]       son n uyarı: taban konuldu/düzeltildi, kısmi dolum,
                      mutabakat, fiyat sıçraması... (varsayılan 10)
  /duraklat           yeni ALIM yok, bekleyen alış iptal. Pozisyona DOKUNMAZ,
                      koruyucu stop çalışmaya devam eder.
  /devam              duraklatmayı kaldırır
  /stop onayla        ACİL DURDURMA: tüm emirler iptal, pozisyon PİYASADAN
                      KAPATILIR. Döngü 5 sn içinde uygular.
  /sifirla onayla     acil durdurmayı kaldırır (motor yeniden işlem yapar)
  /yardim             bu liste"""


def _bayrak_yaz(yol: Path, metin: str, kaynak: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps({"komut": metin, "kaynak": kaynak, "zaman": simdi_utc()},
                              ensure_ascii=False), encoding="utf-8")


def _sayi(args: list[str], varsayilan: int, azami: int) -> int:
    try:
        return max(1, min(azami, int(args[0]))) if args else varsayilan
    except ValueError:
        return varsayilan


def calistir(metin: str, ayarlar: Ayarlar, *, kaynak: str = "",
             gunluk_dosyasi: Path = gunluk.VARSAYILAN_DOSYA) -> Sonuc:
    """Komutu çalıştırır. İstisna yükseltmez; her sonuç bir metindir."""
    log = gunluk.al("arayuz")
    parcalar = metin.strip().split()
    if not parcalar:
        return Sonuc("", True)
    komut, args = parcalar[0].lower(), parcalar[1:]
    if not komut.startswith("/"):
        komut = "/" + komut
    log.info("komut (%s): %s", kaynak or "?", metin.strip())

    try:
        if komut in ("/yardim", "/yardım", "/help", "/?"):
            return Sonuc(YARDIM)

        if komut == "/durum":
            from src.engine import saglik
            sonuclar = saglik.kontroller(ayarlar)
            return Sonuc(saglik.metin_rapor(sonuclar), saglik.saglam_mi(sonuclar))

        if komut == "/turlar":
            turlar = veri.son_turlar(ayarlar.paper_db, _sayi(args, 10, 200))
            if not turlar:
                return Sonuc("Hiç tur yok — döngü hiç çalışmamış.", False)
            return Sonuc("\n".join(
                f"{t['baslangic_utc'][:16].replace('T', ' ')}  {t['sonuc']:<10} "
                f"{(t['hata'] or t['ozet'] or '').splitlines()[0] if (t['hata'] or t['ozet']) else ''}"[:160]
                for t in turlar))

        if komut in ("/uyarilar", "/uyarılar"):
            uyarilar = veri.son_uyarilar(ayarlar.paper_db, _sayi(args, 10, 200))
            if not uyarilar:
                return Sonuc("Hiç uyarı yok.")
            return Sonuc("\n".join(
                f"{u['son_utc'][:16].replace('T', ' ')} UTC  "
                f"{SEVIYE_ADI.get(u['seviye'], u['seviye']):<6} {u['konu']}"
                + (f"  (×{u['tekrar']})" if u["tekrar"] > 1 else "")
                for u in uyarilar), not any(u["seviye"] == "kotu" for u in uyarilar))

        if komut == "/gunluk":
            satirlar = gunluk.son_satirlar(gunluk_dosyasi, _sayi(args, 30, 500))
            return Sonuc("\n".join(satirlar) or "Günlük boş.")

        if komut == "/duraklat":
            if ayarlar.duraklat_dosyasi.exists():
                return Sonuc("Zaten duraklatılmış.")
            _bayrak_yaz(ayarlar.duraklat_dosyasi, metin.strip(), kaynak)
            return Sonuc("DURAKLATILDI. Yeni alım yapılmayacak, bekleyen alış emri bir "
                         "sonraki turda iptal edilecek. Pozisyon varsa koruma sürüyor.\n"
                         "Geri almak için: /devam", tehlikeli=True)

        if komut == "/devam":
            if not ayarlar.duraklat_dosyasi.exists():
                return Sonuc("Duraklatma yok zaten.")
            ayarlar.duraklat_dosyasi.unlink()
            return Sonuc("Duraklatma kaldırıldı. Bir sonraki turda alış emri yeniden konur.")

        if komut == "/stop":
            if args[:1] != [ONAY]:
                return Sonuc("⚠ /stop tüm emirleri iptal eder ve pozisyonu PİYASA FİYATINDAN "
                             "KAPATIR. Geri alınamaz.\n"
                             "Yalnızca yeni alımı durdurmak istiyorsan: /duraklat\n"
                             "Emin isen yaz: /stop onayla", False, tehlikeli=True)
            if ayarlar.dur_dosyasi.exists():
                return Sonuc("Acil durdurma zaten etkin.", tehlikeli=True)
            _bayrak_yaz(ayarlar.dur_dosyasi, metin.strip(), kaynak)
            log.warning("ACİL DURDURMA istendi (%s)", kaynak or "?")
            return Sonuc("ACİL DURDURMA bayrağı kondu. Döngü 5 saniye içinde emirleri iptal "
                         "edip pozisyonu kapatacak. Durumu izle: /durum\n"
                         "Yeniden başlatmak için: /sifirla onayla", tehlikeli=True)

        if komut == "/sifirla":
            if not ayarlar.dur_dosyasi.exists():
                return Sonuc("Acil durdurma yok zaten.")
            if args[:1] != [ONAY]:
                return Sonuc("Acil durdurma kaldırılırsa motor bir sonraki turda yeniden "
                             "işlem yapmaya başlar.\nEmin isen yaz: /sifirla onayla",
                             False, tehlikeli=True)
            ayarlar.dur_dosyasi.unlink()
            return Sonuc("Acil durdurma kaldırıldı. Motor bir sonraki turda normal çalışır.")

        return Sonuc(f"Bilinmeyen komut: {komut}\n\n{YARDIM}", False)
    except Exception as exc:
        log.error("komut hatası (%s): %s", metin, exc)
        return Sonuc(f"Komut çalışmadı: {exc}", False)
