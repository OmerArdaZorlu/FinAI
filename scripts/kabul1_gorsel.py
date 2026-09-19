#!/usr/bin/env python
"""KABUL-1 belgesindeki işlem anatomisi grafiğini üretir.

Kullanım:
    python scripts/kabul1_gorsel.py

Çıktı: `hypotheses/gorseller/kabul1_islem_anatomisi.png`

Neden ayrı bir script
---------------------
`hypotheses/KABUL-1_AAPL_takip_eden_stop.md` takip eden stopu anlatırken bu
grafiğe gömme yapıyor. Grafiği elle çizip repoya atmak, "her şey yeniden
üretilebilir olsun" kuralını bozardı: veri değişince görselin neye ait olduğu
bilinmez hâle gelir. Bu script tek komutla yeniler.

Hangi işlem çizilir
-------------------
İşlem **alış tarihiyle** sabitlenmiştir, sıra numarasıyla değil. Sıra numarası
kırılgandır: veriye tek bir bar eklenince bütün numaralar kayar ve script
sessizce bambaşka bir işlemi çizer — oysa md'deki açıklama seçilen işlemin
sayılarıyla yazıldı. Tarih bulunamazsa script anlaşılır bir hatayla durur.

Seçilen işlem (2020-11-02 → 2021-01-29) ders örneği olarak seçildi: 60 bar
sürüyor (grafiğe sığacak kadar kısa), ilk 20 barı takip başlamadan geçiyor
(yani "önce ne oluyordu" görünüyor), takip eden stop 13 kez basamak basamak
yükseliyor ve sonunda tetiklenerek kapanıyor.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")          # başsız çalışır; pencere açmaya kalkmasın

import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from lab.backtest import Kurallar, calistir  # noqa: E402
from lab.plots import trade_anatomy_chart  # noqa: E402
from lab.splits import split_research_vault  # noqa: E402
from src.data.load import load_bars  # noqa: E402

# KABUL-1 §3, günlük satır. Motorun kullandığı saatlik eşiklerle aynı paylar.
KURALLAR = Kurallar(
    n=20,
    cizgi="donchian",
    satis="takip",
    alim_payi=0.10,
    stop_payi=2.00,
    takip_payi=1.00,
    maliyet=0.0005,
)

ALIS_TARIHI = "2020-11-02"
CIKTI = REPO_ROOT / "hypotheses" / "gorseller" / "kabul1_islem_anatomisi.png"


class IslemBulunamadi(RuntimeError):
    """Sabitlenen alış tarihinde işlem yok — sessizce başkasını çizmeyelim."""


def islem_sirasi(islemler: pd.DataFrame, alis_tarihi: str) -> int:
    """Alış tarihine karşılık gelen işlemin sıra numarası."""
    gunler = pd.to_datetime(islemler["alis_zamani"]).dt.date
    hedef = pd.Timestamp(alis_tarihi).date()
    eslesen = islemler.index[gunler == hedef]
    if len(eslesen) != 1:
        mevcut = ", ".join(str(g) for g in gunler)
        raise IslemBulunamadi(
            f"{alis_tarihi} tarihinde tam olarak bir alış bekleniyordu, "
            f"{len(eslesen)} bulundu.\n"
            f"  Veri ya da eşikler değişmiş olabilir. Mevcut alış tarihleri:\n"
            f"  {mevcut}"
        )
    return int(eslesen[0])


def uret(cikti: Path = CIKTI, *, alis_tarihi: str = ALIS_TARIHI) -> Path:
    """Grafiği çizer ve diske yazar; yazılan dosyanın yolunu döndürür."""
    gunluk = split_research_vault(load_bars("AAPL", "1Day"), horizon_bars=1).research
    sonuc = calistir(gunluk, KURALLAR)

    sira = islem_sirasi(sonuc.islemler, alis_tarihi)
    islem = sonuc.islemler.iloc[sira]
    print(
        "Çizilen işlem: %s → %s  |  %d bar  |  %s  |  maliyet dahil %+.1f%%"
        % (
            pd.Timestamp(islem["alis_zamani"]).date(),
            pd.Timestamp(islem["satis_zamani"]).date(),
            islem["bar"],
            islem["sebep"],
            100 * islem["getiri_maliyetli"],
        )
    )

    fig = trade_anatomy_chart(gunluk, sonuc, sira, pay=10)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(cikti, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Yazıldı: {cikti.relative_to(REPO_ROOT)}")
    return cikti


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="KABUL-1 belgesindeki işlem anatomisi grafiğini üretir.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--alis-tarihi", default=ALIS_TARIHI,
                   help="Çizilecek işlemin alış tarihi (YYYY-MM-DD)")
    p.add_argument("--cikti", type=Path, default=CIKTI, help="Hedef PNG yolu")
    args = p.parse_args(argv)

    try:
        uret(args.cikti, alis_tarihi=args.alis_tarihi)
    except IslemBulunamadi as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
