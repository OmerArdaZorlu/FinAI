"""Kontrol terminalinin komutları.

Arayüz broker'a emir göndermez ve veritabanına yazmaz. Etkili komutlar
(`/stop`, `/duraklat`) **bayrak dosyası** bırakır; döngü 5 saniye içinde görür,
işler ve `komutlar` tablosuna yazar. `data/DUR` mekanizması zaten motorda
vardı ve testliydi — arayüz aynı kanalı kullanır.

Geri alınamaz komut onay ister: `/flatten` pozisyonu piyasadan kapatır, bu
yüzden `/flatten confirm` yazılmadan hiçbir şey yapmaz.

İsimler ve çıktılar borsa jargonuyla İngilizce; panelin asıl kullanıcısı bir
yapay zekâ ve emir dünyasının ortak dili bu (`flatten`, `halt`, `fill`).
Eski Türkçe adlar takma ad olarak çalışmaya devam eder (`TAKMA_ADLAR`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.engine import gunluk
from src.engine.durum import simdi_utc
from src.engine.motor import Ayarlar

from . import veri

ONAY = ("confirm", "onayla")
SEVIYE_ADI = {"bilgi": "info", "uyari": "WARN", "kotu": "CRIT"}

# Eski Türkçe adlar ve kısayollar → komut.
TAKMA_ADLAR = {
    "/yardim": "/help", "/yardım": "/help", "/?": "/help",
    "/durum": "/status",
    "/turlar": "/runs",
    "/gunluk": "/log", "/günlük": "/log",
    "/uyarilar": "/alerts", "/uyarılar": "/alerts",
    "/duraklat": "/pause",
    "/devam": "/resume",
    "/stop": "/flatten", "/halt": "/flatten",
    "/sifirla": "/unhalt", "/sıfırla": "/unhalt", "/reset": "/unhalt",
}


@dataclass(frozen=True, slots=True)
class Sonuc:
    metin: str
    basarili: bool = True
    tehlikeli: bool = False      # arayüz kırmızı gösterir


YARDIM = """\
Commands:
  /status             health checks (last run, broker, reconciliation, stop...)
  /runs [n]           last n engine runs (default 10)
  /log [n]            last n lines of the engine log (default 30)
  /alerts [n]         last n alerts: stop placed/repaired, partial fill,
                      reconciliation, price gap... (default 10)
  /pause              no new ENTRIES, working buy order canceled. Position is
                      NOT touched, the protective stop stays live.
  /resume             lifts the pause
  /flatten confirm    KILL SWITCH: cancel all orders, close the position AT
                      MARKET. Engine applies it within 5 s.
  /unhalt confirm     lifts the kill switch (engine trades again)
  /help               this list"""


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
    komut = TAKMA_ADLAR.get(komut, komut)
    onayli = args[:1] and args[0].lower() in ONAY
    log.info("komut (%s): %s", kaynak or "?", metin.strip())

    try:
        if komut == "/help":
            return Sonuc(YARDIM)

        if komut == "/status":
            from src.engine import saglik
            sonuclar = saglik.kontroller(ayarlar)
            return Sonuc(saglik.metin_rapor(sonuclar), saglik.saglam_mi(sonuclar))

        if komut == "/runs":
            turlar = veri.son_turlar(ayarlar.paper_db, _sayi(args, 10, 200))
            if not turlar:
                return Sonuc("No runs yet — the engine has never run.", False)
            return Sonuc("\n".join(
                f"{t['baslangic_utc'][:16].replace('T', ' ')}  {t['sonuc']:<10} "
                f"{(t['hata'] or t['ozet'] or '').splitlines()[0] if (t['hata'] or t['ozet']) else ''}"[:160]
                for t in turlar))

        if komut == "/alerts":
            uyarilar = veri.son_uyarilar(ayarlar.paper_db, _sayi(args, 10, 200))
            if not uyarilar:
                return Sonuc("No alerts.")
            return Sonuc("\n".join(
                f"{u['son_utc'][:16].replace('T', ' ')} UTC  "
                f"{SEVIYE_ADI.get(u['seviye'], u['seviye']):<6} {u['konu']}"
                + (f"  (×{u['tekrar']})" if u["tekrar"] > 1 else "")
                for u in uyarilar), not any(u["seviye"] == "kotu" for u in uyarilar))

        if komut == "/log":
            satirlar = gunluk.son_satirlar(gunluk_dosyasi, _sayi(args, 30, 500))
            return Sonuc("\n".join(satirlar) or "Log is empty.")

        if komut == "/pause":
            if ayarlar.duraklat_dosyasi.exists():
                return Sonuc("Already paused.")
            _bayrak_yaz(ayarlar.duraklat_dosyasi, metin.strip(), kaynak)
            return Sonuc("PAUSED. No new entries; the working buy order is canceled on the "
                         "next run. An open position keeps its protective stop.\n"
                         "To lift: /resume", tehlikeli=True)

        if komut == "/resume":
            if not ayarlar.duraklat_dosyasi.exists():
                return Sonuc("Not paused.")
            ayarlar.duraklat_dosyasi.unlink()
            return Sonuc("Pause lifted. The entry order goes back on the next run.")

        if komut == "/flatten":
            if not onayli:
                return Sonuc("⚠ /flatten cancels every order and closes the position AT "
                             "MARKET. It cannot be undone.\n"
                             "To stop new entries only: /pause\n"
                             "If you are sure: /flatten confirm", False, tehlikeli=True)
            if ayarlar.dur_dosyasi.exists():
                return Sonuc("Kill switch already active.", tehlikeli=True)
            _bayrak_yaz(ayarlar.dur_dosyasi, metin.strip(), kaynak)
            log.warning("KILL SWITCH istendi (%s)", kaynak or "?")
            return Sonuc("KILL SWITCH armed. Within 5 s the engine cancels all orders and "
                         "closes the position. Watch it: /status\n"
                         "To restart trading: /unhalt confirm", tehlikeli=True)

        if komut == "/unhalt":
            if not ayarlar.dur_dosyasi.exists():
                return Sonuc("Kill switch is not active.")
            if not onayli:
                return Sonuc("Lifting the kill switch lets the engine trade again on the "
                             "next run.\nIf you are sure: /unhalt confirm",
                             False, tehlikeli=True)
            ayarlar.dur_dosyasi.unlink()
            return Sonuc("Kill switch lifted. The engine runs normally from the next run.")

        return Sonuc(f"Unknown command: {komut}\n\n{YARDIM}", False)
    except Exception as exc:
        log.error("komut hatası (%s): %s", metin, exc)
        return Sonuc(f"Command failed: {exc}", False)
