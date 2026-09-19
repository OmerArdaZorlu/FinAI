"""Gösterim verisi tazeleme — panelin grafiği için, kararla ilgisi yok.

Kritik: bir seri hata verirse ötekiler denenmeye devam eder ve fonksiyon
patlamaz (turun dışında, turu etkilememeli).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import senkron  # noqa: E402
from src.engine import gosterim as G  # noqa: E402
from src.engine.motor import Ayarlar  # noqa: E402

SIMDI = dt.datetime(2026, 9, 18, 14, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def ayarlar(tmp_path):
    return Ayarlar(veri_db=tmp_path / "veri.db", paper_db=tmp_path / "paper.db")


def test_seriler_motorun_kendi_serisini_istemez(ayarlar):
    """Saatlik AAPL'i motor zaten indiriyor — ikinci kez istenmemeli."""
    assert (ayarlar.sembol, "1Hour") not in G.seriler(ayarlar)
    assert G.seriler(ayarlar) == [("AAPL", "1Min"), ("AAPL", "1Day"),
                                  ("SPY", "1Min"), ("SPY", "1Hour"), ("SPY", "1Day")]
    assert G.seriler(Ayarlar(sembol="SPY")) == [("SPY", "1Min"), ("SPY", "1Day")]


def test_tazele_dogru_serileri_ister(ayarlar, monkeypatch):
    cagrilar = []

    def sahte(semboller, **kw):
        cagrilar.append((semboller[0], kw["timeframe"], kw["bar_dakika"], kw["kesim"]))
        return {semboller[0]: 5}

    monkeypatch.setattr(senkron, "tazele", sahte)
    yazilan = G.tazele(ayarlar, SIMDI)
    assert [(s, tf) for s, tf, _, _ in cagrilar] == G.seriler(ayarlar)
    assert dict(zip([(s, tf) for s, tf, _, _ in cagrilar], [5] * len(cagrilar))) == yazilan
    # Bar süresi doğru verilmeli: yarım bar elemesi buna bakıyor.
    assert {tf: dk for _, tf, dk, _ in cagrilar} == {"1Min": 1, "1Hour": 60, "1Day": 1440}
    # Kesim: SIP gecikmesi kadar geride.
    assert cagrilar[0][3] == SIMDI - dt.timedelta(minutes=ayarlar.veri_gecikmesi_dk)


def test_bir_seri_patlasa_da_otekiler_denenir(ayarlar, monkeypatch):
    def sahte(semboller, **kw):
        if kw["timeframe"] == "1Min":
            raise RuntimeError("Alpaca 403")
        return {semboller[0]: 3}

    monkeypatch.setattr(senkron, "tazele", sahte)
    yazilan = G.tazele(ayarlar, SIMDI)                 # patlamamalı
    assert yazilan[("AAPL", "1Min")] == 0 and yazilan[("SPY", "1Min")] == 0
    assert yazilan[("SPY", "1Day")] == 3
