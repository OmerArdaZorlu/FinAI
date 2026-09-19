"""Panelin GÖSTERDİĞİ serileri tazeler — kararla ilgisi yoktur.

Motor yalnızca kendi çalıştığı seriyi (AAPL saatlik) indirir; karar yolu
budur ve değişmez. Panel ise dakikalık ve günlük grafiği de gösteriyor,
izleme listesindeki öteki sembolleri de. O veriyi buradan indiriyoruz.

Neden döngünün içinde
---------------------
`market_data.db`'ye yazan tek süreç döngü olmalı (AK-4); panel salt-okurdur
ve ağa çıkmaz. Bu yüzden tazeleme, turdan SONRA döngüde çalışır. Karar
yolunun dışındadır: hata verirse yalnızca loglanır, tur sonucunu ve ardışık
hata sayacını etkilemez.

Gecikme
-------
Ücretsiz SIP 15 dakika gecikmeli. Dakikalık grafikteki en yeni mum da bu
yüzden ~16 dakika geridedir (`Ayarlar.veri_gecikmesi_dk`). Motoru
etkilemez: o zaten saatlik ve bir bar geriden çalışır.
"""

from __future__ import annotations

import datetime as dt

from src.data import senkron

from . import gunluk
from .motor import Ayarlar

# Panelin grafikte gösterebildiği seriler.
GOSTERIM_TF = {"1Min": 1, "1Hour": 60, "1Day": 1440}

# Her turda tazelenen seriler. Panelde hangi sembole bakılırsa bakılsın
# 1m / 1H / 1D düğmeleri çalışsın diye izlenen semboller de dakikalık iner
# (sembol başına ~2 milyon bar, depoda ~80 MB). Motorun kendi saatlik serisi
# burada yok: onu `motor.barlari_getir` zaten indiriyor.
def seriler(ayarlar: Ayarlar, izlenenler: tuple[str, ...] = ("SPY",)) -> list[tuple[str, str]]:
    """Tazelenecek (sembol, timeframe) çiftleri — motorun kendi serisi hariç."""
    cikti = [(ayarlar.sembol, "1Min"), (ayarlar.sembol, "1Day")]
    for s in izlenenler:
        if s != ayarlar.sembol:
            cikti += [(s, "1Min"), (s, "1Hour"), (s, "1Day")]
    return cikti


# Depo boşsa bu kadar günden başlanır. Dakikalıkta da tüm geçmiş tutuluyor
# (kullanıcı kararı): sembol başına ~2,5 milyon bar, ~100 MB.
GERIYE_GUN = {"1Min": 4000, "1Hour": 90, "1Day": 3650}


def tazele(ayarlar: Ayarlar, simdi: dt.datetime | None = None,
           izlenenler: tuple[str, ...] = ("SPY",)) -> dict[tuple[str, str], int]:
    """Gösterim serilerini günceller; {(sembol, tf): yazılan bar} döner.

    Bir seri hata verirse loglanır ve ötekilere devam edilir — grafiğin bir
    parçasının eksik kalması turu durdurmaz.
    """
    log = gunluk.al()
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    kesim = simdi - dt.timedelta(minutes=ayarlar.veri_gecikmesi_dk)
    yazilan: dict[tuple[str, str], int] = {}
    for sembol, tf in seriler(ayarlar, izlenenler):
        try:
            sonuc = senkron.tazele(
                [sembol],
                timeframe=tf,
                bar_dakika=GOSTERIM_TF[tf],
                kesim=kesim,
                db_path=ayarlar.veri_db,
                geriye_gun=GERIYE_GUN[tf],
                # Tam yenileme (bölünme düzeltmesi) dakikalıkta YOK: pencere
                # 11 yıl, her gün baştan indirmek milyonlarca barı boşuna
                # çeker. Bölünmeyi saatlik/günlük seri zaten yakalar; olursa
                # dakikalık elle yenilenir (python -m src.engine.gosterim).
                tam_yenileme_saat=None if tf == "1Min" else ayarlar.tam_yenileme_saat,
            )
            yazilan[(sembol, tf)] = int(sonuc.get(sembol, 0))
        except Exception as exc:                      # ağ, 403, disk — hepsi aynı
            log.warning("gösterim verisi tazelenemedi (%s %s): %s", sembol, tf, exc)
            yazilan[(sembol, tf)] = 0
    toplam = sum(yazilan.values())
    if toplam:
        log.info("gösterim verisi: %d yeni bar (%s)", toplam,
                 ", ".join(f"{s} {t}" for (s, t), n in yazilan.items() if n))
    return yazilan


def bosluk_kapat(ayarlar: Ayarlar | None = None, simdi: dt.datetime | None = None) -> None:
    """Elle çalıştırma: python -m src.engine.gosterim

    Dakikalık veride aylarca boşluk varsa (motor onu indirmiyordu) tek
    seferde kapatmak için. Normal işleyişte döngü her turda çağırır.
    """
    ayarlar = ayarlar or Ayarlar()
    for (sembol, tf), n in tazele(ayarlar, simdi).items():
        print(f"{sembol:6} {tf:6} {n:>8,} yeni bar")


if __name__ == "__main__":       # pragma: no cover
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    gunluk.kur()
    bosluk_kapat()
