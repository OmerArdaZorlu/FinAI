"""Veri bölme — araştırma alanı, kilitli kasa, alt dönemler, walk-forward katlar.

ARCHITECTURE.md §7.5'in kod karşılığı ve **tek kaynak**: her hipotez birebir
aynı kesimi kullanmak zorundadır. Sınırlar notebook'lara dağılırsa iki
hipotezin sonucu karşılaştırılamaz hale gelir.

    2016-01-04 ─────────────── 2024-06-30 │purge│ 2024-07-01 ──── 2026-09-04
        ARAŞTIRMA ALANI (~2139 bar, %80)             KASA (~545 bar, %20)
        sınırsız bakılır                             BİR KEZ açılır

Oran klasik 1:4'tür; fark kesimin **kronolojik** olmasıdır. Zaman serisinde
rastgele bölme, modelin Salı'yı öğrenip Pazartesi'yi tahmin etmesi demektir.

Sızıntının tehlikeli yönü **etikettir**, özellik penceresi değil: bir satırın
özelliği geçmişe bakar (sorun yok), ama etiketi K bar ileriden gelir. Sınırın
son K satırının etiketi kasadan geldiği için o satırlar budanır (purge).

Kasada kriz rejimi YOK
----------------------
COVID çöküşü ve 2022 ayı piyasası araştırma alanında kalır; kasa görece sakin
tek bir rejimdir. Yani kasa, stratejinin çöküşte ne yaptığını **söylemez**.
Çözüm sınırı oynatmak değil (sonuca bakarak veri seçmek olur), iki ek kontrol:
`SUBPERIODS` ile alt dönem tutarlılığı, `STRESS_WINDOWS` ile stres raporu.
İkisi de burada, sonuç görülmeden **önce** ilan edilmiştir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd

# --- Sabit sınır. Değiştirmek bilinçli bir karardır ve git'te görünür. ---
RESEARCH_END = "2024-06-30"   # araştırma alanının son günü (dahil)
VAULT_BEGINS = "2024-07-01"   # kasa buradan başlar (dahil)

# Alt dönem tutarlılığı: etki her üçünde de görünmeli. Yalnızca birinde
# varsa o rejime özgüdür, genel bir yasa değildir.
SUBPERIODS: dict[str, tuple[str, str]] = {
    "2016-2019 sakin/yükseliş": ("2016-01-01", "2019-12-31"),
    "2020-2021 covid + toparlanma": ("2020-01-01", "2021-12-31"),
    "2022-2024H1 ayı + faiz şoku": ("2022-01-01", RESEARCH_END),
}

# Stres raporu: seçim kriteri DEĞİL, risk bilgisi. Bu pencerelerde maksimum
# düşüş ne oluyor? Kasa bu soruyu cevaplayamaz, çünkü kriz içermiyor.
STRESS_WINDOWS: dict[str, tuple[str, str]] = {
    "covid çöküşü": ("2020-02-19", "2020-04-30"),
    "2022 ayı piyasası": ("2022-01-03", "2022-10-31"),
}


class SplitError(ValueError):
    """Bölme sözleşmesi ihlal edildiğinde yükseltilir."""


@dataclass(frozen=True)
class Split:
    """Araştırma alanı ve kilitli kasa.

    `research` üzerinde sınırsız çalışılır; `vault` yalnızca nihai birleşik
    sistem için, **bir kez** açılır.
    """

    research: pd.DataFrame
    vault: pd.DataFrame
    purged: int          # etiketi kasaya taşan, budanan satır sayısı
    horizon_bars: int

    def __repr__(self) -> str:  # pragma: no cover - yalnızca gösterim
        def span(d: pd.DataFrame) -> str:
            return f"{d['timestamp'].iloc[0].date()} → {d['timestamp'].iloc[-1].date()}"

        return (
            f"Split(research={len(self.research)} bar [{span(self.research)}], "
            f"vault={len(self.vault)} bar [{span(self.vault)}], "
            f"purged={self.purged}, horizon={self.horizon_bars})"
        )


def split_research_vault(
    df: pd.DataFrame,
    *,
    horizon_bars: int,
    vault_begins: str = VAULT_BEGINS,
) -> Split:
    """Barları araştırma alanı ve kilitli kasa olarak ikiye ayırır (~%80 / %20).

    Args:
        df: Kanonik bar tablosu (`timestamp` UTC tz-aware, artan sıralı).
        horizon_bars: Hedefin (y) kaç bar ileriye baktığı. Araştırma alanının
            son `horizon_bars` satırı budanır — etiketleri kasadan gelir.
        vault_begins: Kasanın başladığı tarih (bu tarih kasaya dahildir).

    Raises:
        SplitError: Sınır veriyi anlamlı biçimde ikiye ayırmıyorsa.
    """
    if horizon_bars < 1:
        raise SplitError(f"horizon_bars >= 1 olmalı, verilen: {horizon_bars}")

    boundary = pd.Timestamp(vault_begins, tz="UTC")
    research_all = df.loc[df["timestamp"] < boundary].reset_index(drop=True)
    vault = df.loc[df["timestamp"] >= boundary].reset_index(drop=True)

    if research_all.empty:
        raise SplitError(f"{vault_begins} öncesinde hiç bar yok — sınır çok erken.")
    if vault.empty:
        raise SplitError(f"{vault_begins} sonrasında hiç bar yok — sınır çok geç.")
    if len(research_all) <= horizon_bars:
        raise SplitError(
            f"Araştırma alanında {len(research_all)} bar var ama purge "
            f"{horizon_bars} bar istiyor — geriye satır kalmıyor."
        )

    return Split(
        research=research_all.iloc[:-horizon_bars].reset_index(drop=True),
        vault=vault,
        purged=horizon_bars,
        horizon_bars=horizon_bars,
    )


def window(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Verilen tarih aralığını döndürür (iki uç da dahil)."""
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return df.loc[(df["timestamp"] >= lo) & (df["timestamp"] < hi)].reset_index(drop=True)


def iter_subperiods(df: pd.DataFrame) -> Iterator[tuple[str, pd.DataFrame]]:
    """Alt dönemleri sırayla verir — etki her rejimde görünüyor mu?"""
    for name, (start, end) in SUBPERIODS.items():
        yield name, window(df, start, end)


def iter_stress_windows(df: pd.DataFrame) -> Iterator[tuple[str, pd.DataFrame]]:
    """Stres pencerelerini sırayla verir — risk raporu için, seçim için değil."""
    for name, (start, end) in STRESS_WINDOWS.items():
        yield name, window(df, start, end)


def purged_walk_forward(
    n_rows: int,
    *,
    horizon_bars: int,
    n_folds: int = 5,
    min_train: int | None = None,
    min_block: int = 10,
) -> Iterator[tuple[range, range]]:
    """Genişleyen pencereli, purge'lü walk-forward katlar üretir.

    Yalnızca **araştırma alanı** üzerinde kullanılır; kasaya asla dokunmaz.
    Klasik k-fold CV'nin zaman serisi karşılığı — veriyi üçe bölüp harcamadan
    doğrulama sağlar.

        kat 1:  [eğitim........]│purge│[test]
        kat 2:  [eğitim..............]│purge│[test]
        kat 3:  [eğitim....................]│purge│[test]

    Eğitim setinin son `horizon_bars` satırı budanır — etiketleri test bloğunun
    içinden gelir. Rastgele karıştırma **yoktur**.

    Args:
        n_rows: Araştırma alanındaki satır sayısı.
        horizon_bars: Etiket ufku — eğitim setinin sonundan bu kadar bar budanır.
        n_folds: Kat sayısı.
        min_train: Kat başına asgari eğitim satırı (varsayılan: bir blok).
        min_block: Blok başına asgari satır. Altına düşülürse hata verilir —
            bir avuç satırlık kat anlamsız sonuç üretir.

    Yields:
        (train_idx, test_idx) — `range` nesneleri, `df.iloc[...]` ile kullanılır.
    """
    if n_folds < 2:
        raise SplitError(f"n_folds >= 2 olmalı, verilen: {n_folds}")
    if horizon_bars < 1:
        raise SplitError(f"horizon_bars >= 1 olmalı, verilen: {horizon_bars}")

    block = n_rows // (n_folds + 1)
    if block < min_block:
        # Bir avuç satırlık kat, sessizce anlamsız sonuç üretir. Hata vermek,
        # gürültüyü ölçüp ona inanmaktan iyidir.
        raise SplitError(
            f"{n_rows} satır {n_folds} kat için çok az: blok {block} bar "
            f"çıkıyor, en az {min_block} gerekiyor."
        )
    # Varsayılan bir blok, ama purge kadar tolerans tanınır: aksi halde
    # ilk kat, eğitim seti purge yüzünden bir tık kısa kaldığı için
    # sessizce düşer ve istenen kat sayısı tutmaz.
    if min_train is None:
        min_train = max(block - horizon_bars, min_block)

    produced = 0
    for fold in range(1, n_folds + 1):
        test_start = block * fold
        test_end = block * (fold + 1) if fold < n_folds else n_rows
        train_end = test_start - horizon_bars     # purge

        if train_end < min_train or test_end <= test_start:
            continue

        produced += 1
        yield range(0, train_end), range(test_start, test_end)

    if produced == 0:
        raise SplitError(
            f"Hiç geçerli kat üretilemedi (n_rows={n_rows}, n_folds={n_folds}, "
            f"horizon_bars={horizon_bars}, min_train={min_train})."
        )
