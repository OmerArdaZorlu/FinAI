"""Bölme sözleşmesi testleri — kasa sızıntısı ve purge doğruluğu."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.splits import (  # noqa: E402
    RESEARCH_END,
    STRESS_WINDOWS,
    SUBPERIODS,
    VAULT_BEGINS,
    SplitError,
    iter_stress_windows,
    iter_subperiods,
    purged_walk_forward,
    split_research_vault,
    window,
)


def make_bars(start: str = "2016-01-04", n: int = 2684) -> pd.DataFrame:
    ts = pd.bdate_range(start, periods=n, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close": range(n)})


# --------------------------------------------------- ARAŞTIRMA / KASA --

def test_boundary_splits_at_the_declared_date():
    split = split_research_vault(make_bars(), horizon_bars=1)
    boundary = pd.Timestamp(VAULT_BEGINS, tz="UTC")
    assert split.research["timestamp"].max() < boundary
    assert split.vault["timestamp"].min() >= boundary


def test_research_and_vault_never_overlap():
    split = split_research_vault(make_bars(), horizon_bars=5)
    assert set(split.research["timestamp"]).isdisjoint(set(split.vault["timestamp"]))


def test_purge_removes_exactly_horizon_rows():
    """Etiketi kasaya taşan son K satır atılmalı — ne eksik ne fazla."""
    bars = make_bars()
    boundary = pd.Timestamp(VAULT_BEGINS, tz="UTC")
    untouched = int((bars["timestamp"] < boundary).sum())

    for k in (1, 5, 20):
        split = split_research_vault(bars, horizon_bars=k)
        assert len(split.research) == untouched - k
        assert split.purged == k


def test_purge_gap_is_real():
    """Purge sonrası araştırmanın son barı ile kasanın ilki arasında K bar olmalı."""
    bars = make_bars()
    k = 10
    split = split_research_vault(bars, horizon_bars=k)
    last_research = split.research["timestamp"].iloc[-1]
    gap = bars.loc[
        (bars["timestamp"] > last_research)
        & (bars["timestamp"] < split.vault["timestamp"].iloc[0])
    ]
    assert len(gap) == k


def test_split_ratio_is_roughly_one_to_four():
    split = split_research_vault(make_bars(), horizon_bars=1)
    total = len(split.research) + len(split.vault) + split.purged
    ratio = len(split.vault) / total
    assert 0.15 < ratio < 0.25, f"kasa oranı beklenenden uzak: {ratio:.2%}"


def test_rejects_bad_horizon():
    with pytest.raises(SplitError):
        split_research_vault(make_bars(), horizon_bars=0)


def test_rejects_boundary_outside_data():
    with pytest.raises(SplitError, match="çok geç"):
        split_research_vault(make_bars(), horizon_bars=1, vault_begins="2099-01-01")
    with pytest.raises(SplitError, match="çok erken"):
        split_research_vault(make_bars(), horizon_bars=1, vault_begins="1990-01-01")


# ------------------------------------------------- ALT DÖNEM / STRES --

def test_subperiods_cover_research_without_gaps_or_overlap():
    bars = make_bars()
    seen: set[pd.Timestamp] = set()
    for _, part in iter_subperiods(bars):
        stamps = set(part["timestamp"])
        assert seen.isdisjoint(stamps), "alt dönemler örtüşüyor"
        seen |= stamps

    research = bars.loc[bars["timestamp"] <= pd.Timestamp(RESEARCH_END, tz="UTC")]
    assert seen == set(research["timestamp"]), "alt dönemler araştırma alanını tam kapsamıyor"


def test_subperiods_never_touch_the_vault():
    bars = make_bars()
    boundary = pd.Timestamp(VAULT_BEGINS, tz="UTC")
    for name, part in iter_subperiods(bars):
        assert (part["timestamp"] < boundary).all(), f"{name} kasaya taşıyor"


def test_stress_windows_are_inside_research():
    bars = make_bars()
    boundary = pd.Timestamp(VAULT_BEGINS, tz="UTC")
    for name, part in iter_stress_windows(bars):
        assert len(part) > 0, f"{name} boş"
        assert (part["timestamp"] < boundary).all(), f"{name} kasaya taşıyor"


def test_window_bounds_are_inclusive():
    bars = make_bars()
    got = window(bars, "2020-03-02", "2020-03-06")
    assert [str(t.date()) for t in got["timestamp"]] == [
        "2020-03-02", "2020-03-03", "2020-03-04", "2020-03-05", "2020-03-06",
    ]


# ------------------------------------------------------ WALK-FORWARD --

def test_walk_forward_train_always_precedes_test():
    for train, test in purged_walk_forward(1000, horizon_bars=1, n_folds=5):
        assert max(train) < min(test), "eğitim testin içine giriyor"


def test_walk_forward_gap_equals_horizon():
    k = 7
    for train, test in purged_walk_forward(1000, horizon_bars=k, n_folds=5):
        assert min(test) - max(train) - 1 == k


def test_walk_forward_train_window_expands():
    sizes = [len(train) for train, _ in purged_walk_forward(1000, horizon_bars=1)]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)


def test_walk_forward_covers_tail():
    folds = list(purged_walk_forward(1000, horizon_bars=1, n_folds=5))
    assert max(folds[-1][1]) == 999, "son blok verinin sonuna kadar gitmeli"


def test_walk_forward_rejects_too_little_data():
    with pytest.raises(SplitError):
        list(purged_walk_forward(10, horizon_bars=1, n_folds=5))
    with pytest.raises(SplitError):
        list(purged_walk_forward(1000, horizon_bars=1, n_folds=1))
