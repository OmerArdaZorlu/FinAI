"""Motorun günlüğü — dosya + ekran.

Motor saat başı kendi kendine çalışınca ekranda duran bir çıktı kalmıyor.
"Dün 14:20'de ne oldu?" sorusunun tek cevabı bu dosya.

Kararlar
--------
* **Kodlama açıkça UTF-8.** Windows konsolu varsayılan olarak `cp1252`
  kullanıyor ve Türkçe karakterde `UnicodeEncodeError` verip süreci
  öldürüyor. Günlük satırı yüzünden işlem yapan bir sürecin ölmesi kabul
  edilemez; hem dosya hem konsol UTF-8'e zorlanır, konsol yine de
  yazamazsa karakter değiştirilir (`errors="replace"`), patlamaz.
* **Zaman UTC.** `paper.db` ve `market_data.db` içindeki her zaman damgası
  UTC; günlük de öyle olmalı ki satırlar tablolarla yan yana okunabilsin.
* **Boyut sınırlı.** 5 MB × 5 dosya. Aylarca koşan süreç diski doldurmasın.
"""

from __future__ import annotations

import io
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VARSAYILAN_DOSYA = REPO_ROOT / "data" / "gunluk" / "motor.log"
KAYDEDICI_ADI = "motor"

BICIM = "%(asctime)s | %(levelname)-5s | %(message)s"
ZAMAN_BICIMI = "%Y-%m-%dT%H:%M:%SZ"
AZAMI_BOYUT = 5 * 1024 * 1024
YEDEK_SAYISI = 5


class _UtcBicimleyici(logging.Formatter):
    converter = time.gmtime


def _konsol_akisi():
    """stdout'u UTF-8 yazan, yazamadığı karakteri değiştiren bir akışa sarar."""
    akis = sys.stdout
    try:
        akis.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        return akis
    except (AttributeError, io.UnsupportedOperation):
        tampon = getattr(akis, "buffer", None)
        if tampon is None:
            return akis
        return io.TextIOWrapper(tampon, encoding="utf-8", errors="replace",
                                line_buffering=True)


def kur(
    dosya: Path | str | None = VARSAYILAN_DOSYA,
    *,
    seviye: int = logging.INFO,
    konsol: bool = True,
    ad: str = KAYDEDICI_ADI,
) -> logging.Logger:
    """Kaydediciyi kurar ve döndürür (varsayılan: motorunki).

    İki kez çağrılırsa önceki kanallar kapatılıp kaldırılır — aynı satır iki
    kez yazılmaz. `dosya=None` yalnızca konsola yazar. Arayüz kendi dosyasına
    `ad="arayuz"` ile yazar; motorun günlüğüne karışmaz.
    """
    kaydedici = logging.getLogger(ad)
    for kanal in list(kaydedici.handlers):
        kaydedici.removeHandler(kanal)
        kanal.close()

    kaydedici.setLevel(seviye)
    kaydedici.propagate = False
    bicimleyici = _UtcBicimleyici(BICIM, ZAMAN_BICIMI)

    if dosya is not None:
        yol = Path(dosya)
        yol.parent.mkdir(parents=True, exist_ok=True)
        dosya_kanali = RotatingFileHandler(
            yol, maxBytes=AZAMI_BOYUT, backupCount=YEDEK_SAYISI, encoding="utf-8")
        dosya_kanali.setFormatter(bicimleyici)
        kaydedici.addHandler(dosya_kanali)

    if konsol:
        konsol_kanali = logging.StreamHandler(_konsol_akisi())
        konsol_kanali.setFormatter(bicimleyici)
        kaydedici.addHandler(konsol_kanali)

    return kaydedici


def al(ad: str = KAYDEDICI_ADI) -> logging.Logger:
    """Kurulmuş kaydediciyi döndürür (kurulmadıysa sessizdir, hata vermez)."""
    return logging.getLogger(ad)


def son_satirlar(dosya: Path | str = VARSAYILAN_DOSYA, adet: int = 200) -> list[str]:
    """Günlük dosyasının son `adet` satırı. Dosya yoksa boş liste."""
    yol = Path(dosya)
    if not yol.is_file() or adet <= 0:
        return []
    with yol.open("rb") as f:
        f.seek(0, 2)
        boyut = f.tell()
        # Satır başına ~200 bayt varsay; yetmezse baştan oku.
        f.seek(max(0, boyut - adet * 200))
        veri = f.read()
    satirlar = veri.decode("utf-8", errors="replace").splitlines()
    if len(satirlar) < adet and boyut > len(veri):
        satirlar = yol.read_text(encoding="utf-8", errors="replace").splitlines()
    return satirlar[-adet:]
