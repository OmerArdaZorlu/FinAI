"""Karsilastirma raporu testleri — paper kosusunun asil ciktisi.

Kayma isaretinin dogru olmasi kritik: alista pahaliya almak da satista ucuza
satmak da aleyhimizedir, ikisi de POZITIF kayma olarak raporlanmali.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import durum as D  # noqa: E402
from src.engine import rapor as R  # noqa: E402

AL_BAR = "2026-09-15T14:00:00+0000"
SAT_BAR = "2026-11-02T15:00:00+0000"


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "paper.db"


def gercekles(conn, kimlik, bar, tip, istenen, olan, adet=100):
    D.gerceklesme_yaz(conn, client_order_id=kimlik, bar_zamani=bar, tip=tip,
                      istenen_seviye=istenen, gerceklesen_fiyat=olan, adet=adet)


def test_bos_veritabaninda_rapor_patlamaz(db):
    with D.connect(db) as c:
        metin = R.metin_rapor(c)
    assert "Henüz dolan emir yok" in metin


def test_alista_pahaliya_almak_pozitif_kayma(db):
    with D.connect(db) as c:
        gercekles(c, "a", AL_BAR, "limit_al", 205.0, 205.41)   # %0.2 pahali
        g = R.gerceklesmeler(c)
    assert g["kayma_yuzde"].iloc[0] == pytest.approx(0.2, abs=0.01)


def test_satista_ucuza_satmak_da_pozitif_kayma(db):
    with D.connect(db) as c:
        gercekles(c, "s", SAT_BAR, "stop_sat", 230.0, 229.54)  # %0.2 ucuz
        g = R.gerceklesmeler(c)
    assert g["kayma_yuzde"].iloc[0] == pytest.approx(0.2, abs=0.01)


def test_lehimize_gerceklesme_negatif_kayma(db):
    """Limit emri daha iyi fiyattan dolarsa backtest kotumserdi."""
    with D.connect(db) as c:
        gercekles(c, "a", AL_BAR, "limit_al", 205.0, 204.0)
        g = R.gerceklesmeler(c)
    assert g["kayma_yuzde"].iloc[0] < 0


def test_al_sat_ciftleri_islem_olarak_eslesir(db):
    with D.connect(db) as c:
        gercekles(c, "a1", AL_BAR, "limit_al", 205.0, 205.0, adet=487)
        gercekles(c, "s1", SAT_BAR, "stop_sat", 230.0, 230.0, adet=487)
        i = R.islemler(c)
    assert len(i) == 1
    assert i["getiri_yuzde"].iloc[0] == pytest.approx((230 / 205 - 1) * 100)
    assert i["kazanc"].iloc[0] == pytest.approx((230 - 205) * 487)


def test_acik_pozisyon_islem_sayilmaz(db):
    """Alis var, satis yok — henuz kapanmis islem yok."""
    with D.connect(db) as c:
        gercekles(c, "a1", AL_BAR, "limit_al", 205.0, 205.0)
        assert R.islemler(c).empty
        assert "Kapanmış işlem yok" in R.metin_rapor(c)


def test_rapor_iptal_edilen_emirleri_de_sayar(db):
    with D.connect(db) as c:
        gercekles(c, "a1", AL_BAR, "limit_al", 205.0, 205.0)
        D.emir_yaz(c, client_order_id="a1", bar_zamani=AL_BAR, tip="limit_al",
                   seviye=205.0, adet=100, durum="dolu")
        for i in range(3):
            D.emir_yaz(c, client_order_id=f"x{i}", bar_zamani=AL_BAR,
                       tip="limit_al", seviye=204.0, adet=100, durum="iptal")
        ozet = R.emir_ozeti(c).set_index("durum")["adet"]
    assert ozet["dolu"] == 1 and ozet["iptal"] == 3
