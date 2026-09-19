"""Sağlık kontrolleri — testler. Ağ yok: broker sahte.

En kritik iki kontrol: motor en son ne zaman çalıştı, ve pozisyon varken
koruyucu stop borsada duruyor mu.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import connect as veri_baglan, write_bars  # noqa: E402
from src.engine import durum as D  # noqa: E402
from src.engine import motor as M  # noqa: E402
from src.engine import saglik as S  # noqa: E402
from src.engine.broker import BorsaSaati, Emir, Pozisyon  # noqa: E402
from src.engine.kural import Durum  # noqa: E402

UTC = dt.timezone.utc
SIMDI = dt.datetime(2026, 9, 18, 15, 30, tzinfo=UTC)       # 11:30 New York, borsa açık


def _iso(an):
    return an.strftime("%Y-%m-%dT%H:%M:%S+0000")


class SahteBroker:
    def __init__(self, *, acik=True, pozisyon=0, emirler=(), hata=None):
        self.acik, self.poz, self.emirler, self.hata = acik, pozisyon, list(emirler), hata

    def borsa_saati(self):
        if self.hata:
            raise self.hata
        return BorsaSaati(self.acik, "", "2026-09-19T09:30:00-04:00", "")

    def pozisyon(self, sembol):
        return Pozisyon(sembol, self.poz, 300.0, 310.0) if self.poz else None

    def bekleyen_emirler(self, sembol=None):
        return self.emirler


def emir(yon, adet, seviye):
    return Emir(broker_id="b1", client_order_id=f"{yon}-1", sembol="AAPL", yon=yon,
                tip="limit" if yon == "buy" else "stop", adet=adet, seviye=seviye,
                durum="new", dolan_adet=0, dolan_ortalama_fiyat=float("nan"))


@pytest.fixture()
def ayarlar(tmp_path):
    a = M.Ayarlar(paper_db=tmp_path / "paper.db", veri_db=tmp_path / "veri.db",
                  dur_dosyasi=tmp_path / "DUR", duraklat_dosyasi=tmp_path / "DURAKLAT",
                  kilit_dosyasi=tmp_path / "dongu.pid")
    # Sağlıklı başlangıç: taze tur, taze kilit, taze veri.
    with D.connect(a.paper_db) as c:
        D.tur_yaz(c, baslangic_utc=_iso(SIMDI - dt.timedelta(minutes=10)),
                  bitis_utc=_iso(SIMDI - dt.timedelta(minutes=9)), sonuc="tamam",
                  ozet="AAPL | nakitte")
    a.kilit_dosyasi.write_text("1234", encoding="utf-8")
    os.utime(a.kilit_dosyasi, (SIMDI.timestamp(), SIMDI.timestamp()))
    ts = pd.date_range(SIMDI - dt.timedelta(hours=3), periods=2, freq="1h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "open": 300.0, "high": 301.0, "low": 299.0,
                       "close": 300.0, "volume": 1, "trade_count": 1, "vwap": 300.0})
    with veri_baglan(a.veri_db) as c:
        write_bars(c, df, symbol="AAPL", timeframe="1Hour", adjustment="all")
    return a


def kontrol(ayarlar, broker, simdi=SIMDI):
    return {k.ad: k for k in S.kontroller(ayarlar, broker=broker, simdi=simdi)}


def test_saglikli_sistem(ayarlar):
    b = SahteBroker(emirler=[emir("buy", 322, 309.95)])
    sonuc = S.kontroller(ayarlar, broker=b, simdi=SIMDI)
    assert S.saglam_mi(sonuc), S.metin_rapor(sonuc)
    assert all(k.seviye == S.IYI for k in sonuc), S.metin_rapor(sonuc)


def test_hic_tur_yoksa_kotu(tmp_path, ayarlar):
    ayarlar = M.Ayarlar(**{**{f: getattr(ayarlar, f) for f in M.Ayarlar.__slots__},
                           "paper_db": tmp_path / "bos.db"})
    k = kontrol(ayarlar, SahteBroker(emirler=[emir("buy", 1, 1)]))
    assert k["son tur"].seviye == S.KOTU


def test_son_tur_eskiyse_kotu(ayarlar):
    k = kontrol(ayarlar, SahteBroker(emirler=[emir("buy", 1, 1)]),
                simdi=SIMDI + dt.timedelta(hours=2))
    assert k["son tur"].seviye == S.KOTU


def test_son_tur_hataysa_kotu(ayarlar):
    with D.connect(ayarlar.paper_db) as c:
        D.tur_yaz(c, baslangic_utc=_iso(SIMDI), bitis_utc=_iso(SIMDI), sonuc="hata",
                  hata="ConnectionError: ağ yok")
    k = kontrol(ayarlar, SahteBroker(emirler=[emir("buy", 1, 1)]))
    assert k["son tur sonucu"].seviye == S.KOTU and "ağ yok" in k["son tur sonucu"].mesaj


def test_kilit_yoksa_ya_da_bayatsa_kotu(ayarlar):
    b = SahteBroker(emirler=[emir("buy", 1, 1)])
    assert kontrol(ayarlar, b, simdi=SIMDI + dt.timedelta(minutes=5))["döngü süreci"].seviye == S.KOTU
    ayarlar.kilit_dosyasi.unlink()
    assert kontrol(ayarlar, b)["döngü süreci"].seviye == S.KOTU


def test_broker_ulasilamazsa_kotu_ama_patlamaz(ayarlar):
    k = kontrol(ayarlar, SahteBroker(hata=ConnectionError("ağ yok")))
    assert k["broker"].seviye == S.KOTU
    assert k["koruyucu stop"].seviye == S.KOTU


def test_mutabakat_bozuksa_kotu(ayarlar):
    """Broker'da pozisyon var, kayıtta yok."""
    k = kontrol(ayarlar, SahteBroker(pozisyon=322, emirler=[emir("sell", 322, 248.0)]))
    assert k["mutabakat"].seviye == S.KOTU


def _pozisyon_kaydet(ayarlar, adet=322):
    with D.connect(ayarlar.paper_db) as c:
        D.durum_kaydet(c, Durum(acik=True, giris_fiyat=309.9, stop=248.6),
                       adet=adet, son_islenen_bar=None)


def test_pozisyon_varken_koruyucu_stop_yoksa_kotu(ayarlar):
    _pozisyon_kaydet(ayarlar)
    k = kontrol(ayarlar, SahteBroker(pozisyon=322))
    assert k["mutabakat"].seviye == S.IYI
    assert k["koruyucu stop"].seviye == S.KOTU and "KORUMASIZ" in k["koruyucu stop"].mesaj


def test_pozisyon_varken_koruyucu_stop_yerindeyse_iyi(ayarlar):
    _pozisyon_kaydet(ayarlar)
    k = kontrol(ayarlar, SahteBroker(pozisyon=322, emirler=[emir("sell", 322, 248.6)]))
    assert k["koruyucu stop"].seviye == S.IYI


def test_bekleyen_alis_yoksa_yalnizca_uyari(ayarlar):
    """Sabah 9:30–10:20 arası doğal olarak olur; alarm atmamalı."""
    sonuc = S.kontroller(ayarlar, broker=SahteBroker(), simdi=SIMDI)
    k = {x.ad: x for x in sonuc}
    assert k["alış emri"].seviye == S.UYARI
    assert S.saglam_mi(sonuc)


def test_bayat_veri_yalnizca_borsa_acikken_kotu(ayarlar):
    ileri = SIMDI + dt.timedelta(hours=6)
    b_acik = SahteBroker(emirler=[emir("buy", 1, 1)])
    assert kontrol(ayarlar, b_acik, simdi=ileri)["veri tazeliği"].seviye == S.KOTU
    b_kapali = SahteBroker(acik=False)
    assert kontrol(ayarlar, b_kapali, simdi=ileri)["veri tazeliği"].seviye == S.IYI


def test_dur_kotu_duraklat_uyari(ayarlar):
    ayarlar.dur_dosyasi.touch()
    ayarlar.duraklat_dosyasi.touch()
    k = kontrol(ayarlar, SahteBroker())
    assert k["acil durdurma"].seviye == S.KOTU
    assert k["duraklatma"].seviye == S.UYARI
    assert "alış emri" not in k           # duraklatılmışken alış beklenmez


def test_metin_rapor_sonuc_satiri(ayarlar):
    ayarlar.dur_dosyasi.touch()
    metin = S.metin_rapor(S.kontroller(ayarlar, broker=SahteBroker(), simdi=SIMDI))
    assert "SORUN VAR" in metin and "✗" in metin
