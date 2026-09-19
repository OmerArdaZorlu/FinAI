"""Parite kontrolü — karar mantığı değişmedi mi?

    python scripts/parite.py          # fark varsa çıkış kodu 1

Motor ya da kural koduna dokunan her değişiklikten sonra çalıştırılır. İki
sabit sonucu yeniden üretir:

1. **Backtest** — araştırma dönemi (kasa hariç), KABUL-1 kuralları:
   1 lira → 9.9004, 28 işlem.
2. **Motor parmak izi** — `barlari_getir` sabit bir saatte (2026-09-17 14:00
   UTC) hangi barları görüyor: bar sayısı, çizgiler, seviyeler ve barların
   md5'i. Motorun "bir bar geriden" rejimi, seans filtresi ya da yarım bar
   elemesi bozulursa burada görünür.

Ağa çıkmaz: `senkron.tazele` devre dışı bırakılır, barlar depodan okunur.
Depo sonradan yeniden indirildiyse (ör. bölünme düzeltmesi) parmak izi
değişebilir — o zaman önce veriye bak, sonra koda.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.splits import split_research_vault  # noqa: E402
from src.data import senkron  # noqa: E402
from src.data.load import load_bars  # noqa: E402
from src.data.session import regular_hours  # noqa: E402
from src.engine import motor as M  # noqa: E402
from src.engine.kural import Durum, emir_seviyeleri  # noqa: E402
from src.engine.tekrar import calistir  # noqa: E402

BEKLENEN_BAKIYE = 9.9004
BEKLENEN_ISLEM = 28
PARMAK_IZI_SAATI = dt.datetime(2026, 9, 17, 14, 0, tzinfo=dt.timezone.utc)
BEKLENEN_PARMAK_IZI = {
    "bar": 294,
    "tepe": 336.22,
    "dip": 307.01,
    "alis": 309.931,
    "zarar_stop": 248.59,
    "md5": "d1e6ef7289d0e7f5",
}


def backtest() -> tuple[float, int]:
    df = split_research_vault(regular_hours(load_bars("AAPL", "1Hour")), horizon_bars=1).research
    sonuc = calistir(df.reset_index(drop=True), M.KURALLAR_KABUL1)
    return round(float(sonuc.bakiye.iloc[-1]), 4), len(sonuc.islemler)


def parmak_izi() -> dict:
    senkron.tazele = lambda *a, **k: {}          # ağa çıkma, depodan oku
    ayarlar = M.Ayarlar()
    barlar = M.barlari_getir(ayarlar, simdi=PARMAK_IZI_SAATI)
    cizgi = M.cizgi_hesapla(barlar, ayarlar.kurallar.n)
    sev = emir_seviyeleri(Durum(), cizgi, ayarlar.kurallar)
    ham = barlar[["timestamp", "open", "high", "low", "close"]].to_csv(index=False)
    return {
        "bar": len(barlar),
        "tepe": round(cizgi.tepe, 2),
        "dip": round(cizgi.dip, 2),
        "alis": round(sev.alis, 3),
        "zarar_stop": round(sev.zarar_stop, 2),
        "md5": hashlib.md5(ham.encode()).hexdigest()[:16],
    }


def main() -> int:
    tamam = True

    bakiye, islem = backtest()
    ok = (bakiye, islem) == (BEKLENEN_BAKIYE, BEKLENEN_ISLEM)
    tamam &= ok
    print(f"{'✓' if ok else '✗'} backtest      {bakiye:.4f} / {islem} işlem "
          f"(beklenen {BEKLENEN_BAKIYE:.4f} / {BEKLENEN_ISLEM})")

    iz = parmak_izi()
    for ad, beklenen in BEKLENEN_PARMAK_IZI.items():
        ok = iz[ad] == beklenen
        tamam &= ok
        print(f"{'✓' if ok else '✗'} parmak izi   {ad:<11} {iz[ad]}"
              + ("" if ok else f"  (beklenen {beklenen})"))

    print("PARİTE TAMAM" if tamam else "PARİTE BOZUK — karar mantığı değişmiş olabilir")
    return 0 if tamam else 1


if __name__ == "__main__":
    raise SystemExit(main())
