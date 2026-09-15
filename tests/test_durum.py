"""Motor durumunun kalici hafizasi — testler. Ag erisimi gerektirmez.

Kritik ozellik: motor cokup acilinca takip eden stop kaldigi yerden devam
etmeli. Zirve ve stop diske yazilmazsa koruma seviyesi kaybolur (TD-06).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import durum as D  # noqa: E402
from src.engine.kural import Durum  # noqa: E402

BAR = "2026-09-15T14:00:00+0000"


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "paper.db"


def test_hic_kayit_yokken_bos_durum_doner(db):
    with D.connect(db) as c:
        durum, adet, son_bar = D.durum_yukle(c)
    assert not durum.acik and adet == 0 and son_bar is None


def test_takipteki_pozisyon_yeniden_baslatmadan_sonra_aynen_gelir(db):
    """Motor coktu, acildi: zirve ve stop kaldigi yerden devam etmeli."""
    onceki = Durum(acik=True, giris_fiyat=205.0, stop=230.0,
                   takipte=True, zirve=280.0, mesafe=50.0)
    with D.connect(db) as c:
        D.durum_kaydet(c, onceki, adet=434, son_islenen_bar=BAR)

    with D.connect(db) as c:          # ayri baglanti = ayri surec gibi
        sonraki, adet, son_bar = D.durum_yukle(c)

    assert sonraki == onceki
    assert sonraki.stop == 230.0 and sonraki.zirve == 280.0
    assert adet == 434 and son_bar == BAR


def test_bos_durumdaki_nan_alanlar_null_olarak_gidip_nan_donerler(db):
    with D.connect(db) as c:
        D.durum_kaydet(c, Durum(), adet=0, son_islenen_bar=None)
    with D.connect(db) as c:
        durum, _, _ = D.durum_yukle(c)
    assert not durum.acik
    assert math.isnan(durum.stop) and math.isnan(durum.zirve)


def test_durum_tek_satir_kalir_uzerine_yazilir(db):
    with D.connect(db) as c:
        D.durum_kaydet(c, Durum(), adet=0, son_islenen_bar=None)
        D.durum_kaydet(c, Durum(acik=True, stop=100.0), adet=5, son_islenen_bar=BAR)
        assert c.execute("SELECT COUNT(*) FROM motor_durumu").fetchone()[0] == 1
        durum, adet, _ = D.durum_yukle(c)
    assert durum.acik and adet == 5


def test_ayni_kimlikli_emir_iki_satir_olusturmaz(db):
    """Cift emir korumasinin veritabani ayagi (TD-07)."""
    kimlik = D.emir_kimligi(BAR, "limit_al")
    with D.connect(db) as c:
        for _ in range(3):
            D.emir_yaz(c, client_order_id=kimlik, bar_zamani=BAR,
                       tip="limit_al", seviye=205.0, adet=434)
        assert c.execute("SELECT COUNT(*) FROM emirler").fetchone()[0] == 1
        assert len(D.bekleyen_emirler(c)) == 1


def test_emir_kimligi_bar_ve_tip_basina_tekrarsiz():
    assert D.emir_kimligi(BAR, "limit_al") != D.emir_kimligi(BAR, "stop_sat")
    assert D.emir_kimligi(BAR, "limit_al") != D.emir_kimligi(
        "2026-09-15T15:00:00+0000", "limit_al")
    assert D.emir_kimligi(BAR, "limit_al") == D.emir_kimligi(BAR, "limit_al")


def test_dolan_emir_bekleyenlerden_cikar(db):
    kimlik = D.emir_kimligi(BAR, "limit_al")
    with D.connect(db) as c:
        D.emir_yaz(c, client_order_id=kimlik, bar_zamani=BAR,
                   tip="limit_al", seviye=205.0, adet=434)
        D.emir_durumu_guncelle(c, kimlik, "dolu")
        assert D.bekleyen_emirler(c) == []


def test_gerceklesme_istenen_ve_olan_fiyati_yan_yana_tutar(db):
    """Paper kosusunun asil ciktisi: backtest 205 diyordu, gercekte 204.87 oldu."""
    kimlik = D.emir_kimligi(BAR, "limit_al")
    with D.connect(db) as c:
        D.gerceklesme_yaz(c, client_order_id=kimlik, bar_zamani=BAR,
                          tip="limit_al", istenen_seviye=205.0,
                          gerceklesen_fiyat=204.87, adet=434)
        satir = c.execute(
            "SELECT istenen_seviye, gerceklesen_fiyat FROM gerceklesmeler"
        ).fetchone()
    assert satir["istenen_seviye"] == pytest.approx(205.0)
    assert satir["gerceklesen_fiyat"] == pytest.approx(204.87)


def test_sinyal_emir_gitmese_bile_yazilir(db):
    with D.connect(db) as c:
        D.sinyal_yaz(c, bar_zamani=BAR, tepe=250.0, dip=200.0,
                     alis_seviyesi=205.0, zarar_stop=100.0, koruma=math.nan,
                     durum=Durum(), aciklama="borsa kapali")
        satir = c.execute("SELECT * FROM sinyaller").fetchone()
    assert satir["aciklama"] == "borsa kapali"
    assert satir["koruma"] is None          # NaN -> NULL
    assert satir["alis_seviyesi"] == pytest.approx(205.0)


def test_arastirma_veritabanina_dokunulmaz():
    """Paper veritabani ayri dosya olmali (ENVIRONMENTS.md §5)."""
    from src.data.db import DEFAULT_DB_PATH
    assert D.DEFAULT_PAPER_DB_PATH != DEFAULT_DB_PATH
    assert D.DEFAULT_PAPER_DB_PATH.name == "paper.db"
