"""Varlık sınıfı — panelin izleme listesi ve tablolarındaki kategori."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.arayuz import varlik as V  # noqa: E402


@pytest.mark.parametrize("sembol, alpaca, beklenen", [
    ("AAPL", None, V.STOCKS),
    ("aapl", "us_equity", V.STOCKS),
    ("SPY", None, V.ETFS),
    ("TLT", "us_equity", V.ETFS),          # Alpaca fonu da hisse sayar
    ("GLD", "us_equity", V.COMMODITIES),
    ("BTC/USD", None, V.CRYPTO),
    ("ETHUSD", "crypto", V.CRYPTO),
    ("AAPL240621C00200000", None, V.OPTIONS),
    ("XYZ", "us_option", V.OPTIONS),
    ("ABC", "yeni_sinif", V.OTHER),
])
def test_sinif(sembol, alpaca, beklenen):
    assert V.sinif(sembol, alpaca) == beklenen


def test_tablolar_cakismaz():
    assert not V.ETF & V.EMTIA
