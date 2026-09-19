"""Artımlı bar tazeleme — testler. Ağ erişimi gerektirmez.

`fetch_bars` monkeypatch'lenir ve hangi parametrelerle çağrıldığı kaydedilir;
asıl iddia orada görünür: **istek 60 günden değil, depodaki son bardan
başlamalı.**

Bir de sessiz bozulmaya karşı iki bekçi var: yarım bar depoya yazılmamalı, ve
"yeni bar yok" bir hata sayılmamalı.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import senkron  # noqa: E402
from src.data.alpaca import AlpacaError, BosVeriError  # noqa: E402
from src.data.db import connect, read_bars, write_bars  # noqa: E402

UTC = dt.timezone.utc
KESIM = dt.datetime(2026, 9, 17, 16, 0, tzinfo=UTC)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "market_data.db"


def barlar(baslangic: str, adet: int, *, saat: int = 1, fiyat: float = 100.0) -> pd.DataFrame:
    """Sentetik bar tablosu — kanonik şemada, saatlik."""
    ts = pd.date_range(baslangic, periods=adet, freq=f"{saat}h", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": fiyat, "high": fiyat + 1, "low": fiyat - 1, "close": fiyat,
        "volume": 1000, "trade_count": 10, "vwap": fiyat,
    })


class SahteCekici:
    """fetch_bars yerine geçer; çağrıları kaydeder, hazır tablo döndürür."""

    def __init__(self, sonuc: pd.DataFrame | Exception):
        self.sonuc = sonuc
        self.cagrilar: list[dict] = []

    def __call__(self, symbol, *, start, end, timeframe, adjustment="all", **kw):
        self.cagrilar.append({
            "symbol": symbol, "start": start, "end": end,
            "timeframe": timeframe, "adjustment": adjustment,
        })
        if isinstance(self.sonuc, Exception):
            raise self.sonuc
        return self.sonuc.copy()


def kur(monkeypatch, sonuc) -> SahteCekici:
    sahte = SahteCekici(sonuc)
    monkeypatch.setattr(senkron, "fetch_bars", sahte)
    return sahte


def tazele(db, **kw):
    varsayilan = dict(timeframe="1Hour", bar_dakika=60, kesim=KESIM, db_path=db)
    return senkron.tazele(["AAPL"], **{**varsayilan, **kw})


# ------------------------------------------------------- soğuk başlangıç --

def test_bos_depoda_geriye_gun_kadar_gecmis_istenir(db, monkeypatch):
    sahte = kur(monkeypatch, barlar("2026-09-16 13:00", 5))

    tazele(db, geriye_gun=90)

    istek = sahte.cagrilar[0]
    beklenen = (KESIM - dt.timedelta(days=90)).strftime(senkron.ZAMAN_BICIMI)
    assert istek["start"] == beklenen
    assert istek["end"] == KESIM.strftime(senkron.ZAMAN_BICIMI)


def test_bos_depoda_gelen_barlar_yazilir(db, monkeypatch):
    kur(monkeypatch, barlar("2026-09-16 13:00", 5))

    assert tazele(db) == {"AAPL": 5}

    with connect(db) as c:
        assert len(read_bars(c, "AAPL", timeframe="1Hour")) == 5


# -------------------------------------------------------------- artımlı --

def test_depoda_bar_varsa_istek_son_bardan_baslar(db, monkeypatch):
    """Planın asıl iddiası: 60 günden değil, kaldığımız yerden."""
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 2),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")
    # depodaki son bar: 14:00

    sahte = kur(monkeypatch, barlar("2026-09-17 14:00", 2))
    tazele(db, geriye_gun=90)

    assert sahte.cagrilar[0]["start"] == "2026-09-17T14:00:00Z"


def test_son_bar_dahil_isteniyor_ki_yarim_kayit_duzelsin(db, monkeypatch):
    """Son kayıtlı bar eksik değerlerle durabilir; UPSERT onu tazelesin diye
    istek o bardan (dahil) başlar."""
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 2, fiyat=100.0),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")

    kur(monkeypatch, barlar("2026-09-17 14:00", 1, fiyat=250.0))
    tazele(db)

    with connect(db) as c:
        df = read_bars(c, "AAPL", timeframe="1Hour")
    assert len(df) == 2                          # yeni satır eklenmedi
    assert df["close"].iloc[-1] == 250.0         # eski değer güncellendi


def test_iki_kez_calistirmak_bar_sayisini_artirmaz(db, monkeypatch):
    kur(monkeypatch, barlar("2026-09-16 13:00", 5))
    tazele(db)
    tazele(db)

    with connect(db) as c:
        assert len(read_bars(c, "AAPL", timeframe="1Hour")) == 5


# ------------------------------------------------------------ yarım bar --

def test_kesimden_sonra_kapanan_bar_yazilmaz(db, monkeypatch):
    """16:00 barı 17:00'de kapanır; kesim 16:00 olduğu için depoya girmemeli."""
    kur(monkeypatch, barlar("2026-09-17 13:00", 4))   # 13,14,15,16

    assert tazele(db) == {"AAPL": 3}

    with connect(db) as c:
        df = read_bars(c, "AAPL", timeframe="1Hour")
    assert df["timestamp"].max() == pd.Timestamp("2026-09-17 15:00", tz="UTC")


def test_gelen_barlarin_hepsi_yarimsa_hic_yazilmaz(db, monkeypatch):
    """write_bars boş tabloda ValidationError yükseltir — oraya hiç gitmemeli."""
    kur(monkeypatch, barlar("2026-09-17 16:00", 1))

    assert tazele(db) == {"AAPL": 0}

    with connect(db) as c:
        assert read_bars(c, "AAPL", timeframe="1Hour").empty


# ----------------------------------------------------------- yeni bar yok --

def test_kapanacak_yeni_bar_yoksa_aga_hic_cikilmaz(db, monkeypatch):
    """Depodaki son bar 15:00 (16:00'da kapanır). Bir sonraki bar 17:00'de
    kapanacak, kesim 16:00 — yani istenecek bir şey yok."""
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 3),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")

    sahte = kur(monkeypatch, barlar("2026-09-17 16:00", 1))

    assert tazele(db) == {"AAPL": 0}
    assert sahte.cagrilar == []          # tek HTTP isteği bile atılmadı


def test_bos_veri_hatasi_yutulur(db, monkeypatch):
    """Hafta sonu / tatil: istek gider, bar dönmez. Bu hata değil."""
    kur(monkeypatch, BosVeriError("aralıkta hiç bar dönmedi"))

    assert tazele(db) == {"AAPL": 0}


def test_gercek_alpaca_hatasi_yutulmaz(db, monkeypatch):
    """Yetkilendirme, ağ, HTTP 4xx/5xx — bunlar yukarı çıkmalı. Yutulursa
    motor bozuk veriyle sessizce karar verir."""
    kur(monkeypatch, AlpacaError("Kimlik doğrulama reddedildi (HTTP 403)"))

    with pytest.raises(AlpacaError, match="403"):
        tazele(db)


# ------------------------------------------------------------- işaretçi --

def test_son_bar_zamani_seri_yoksa_none(db):
    with connect(db) as c:
        assert senkron.son_bar_zamani(c, "AAPL", timeframe="1Hour") is None


def test_son_bar_zamani_diger_serilerden_etkilenmez(db):
    """Aynı sembolün günlük serisi daha yeniyse saatlik işaretçiyi kaydırmamalı."""
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 2),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")
        write_bars(c, barlar("2026-09-20 00:00", 1, saat=24),
                   symbol="AAPL", timeframe="1Day", adjustment="all")
        write_bars(c, barlar("2026-09-25 13:00", 1),
                   symbol="MSFT", timeframe="1Hour", adjustment="all")

        son = senkron.son_bar_zamani(c, "AAPL", timeframe="1Hour")

    assert son == dt.datetime(2026, 9, 17, 14, 0, tzinfo=UTC)


# ------------------------------------------------------------ çok sembol --

def test_semboller_ayri_ayri_islenir(db, monkeypatch):
    sahte = kur(monkeypatch, barlar("2026-09-16 13:00", 3))

    sonuc = senkron.tazele(
        ["AAPL", "MSFT"],
        timeframe="1Hour", bar_dakika=60, kesim=KESIM, db_path=db,
    )

    assert sonuc == {"AAPL": 3, "MSFT": 3}
    assert [c["symbol"] for c in sahte.cagrilar] == ["AAPL", "MSFT"]


# --------------------------------------------------------------- künye --

def test_indirme_kunyeye_yazilir(db, monkeypatch):
    kur(monkeypatch, barlar("2026-09-16 13:00", 5))
    tazele(db)

    with connect(db) as c:
        kayit = c.execute(
            "SELECT symbol, rows_written, source FROM ingest_log"
        ).fetchall()

    assert kayit == [("AAPL", 5, "senkron.tazele")]


# ------------------------------------------------- günlük tam yenileme --

def _depoda_bar_var(db):
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 2),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")


def test_tam_yenileme_hic_yapilmadiysa_pencerenin_tamami_istenir(db, monkeypatch):
    """Bölünme: eski barlar düzeltilmiş fiyatla yeniden insin diye."""
    _depoda_bar_var(db)
    sahte = kur(monkeypatch, barlar("2026-09-17 14:00", 2))
    tazele(db, geriye_gun=60, tam_yenileme_saat=20)

    beklenen = (KESIM - dt.timedelta(days=60)).strftime(senkron.ZAMAN_BICIMI)
    assert sahte.cagrilar[0]["start"] == beklenen
    with connect(db) as c:
        (kaynak,) = c.execute("SELECT source FROM ingest_log").fetchone()
    assert kaynak == "senkron.tam"


def test_tam_yenilemeden_sonra_20_saat_artimli_devam(db, monkeypatch):
    _depoda_bar_var(db)
    sahte = kur(monkeypatch, barlar("2026-09-17 14:00", 2))
    tazele(db, geriye_gun=60, tam_yenileme_saat=20)
    tazele(db, geriye_gun=60, tam_yenileme_saat=20,
           kesim=KESIM + dt.timedelta(hours=3))
    assert sahte.cagrilar[1]["start"] == "2026-09-17T15:00:00Z"   # son bardan

    tazele(db, geriye_gun=60, tam_yenileme_saat=20,
           kesim=KESIM + dt.timedelta(hours=21))
    beklenen = (KESIM + dt.timedelta(hours=21) - dt.timedelta(days=60)).strftime(
        senkron.ZAMAN_BICIMI)
    assert sahte.cagrilar[2]["start"] == beklenen


def test_tam_yenileme_eski_fiyati_duzeltir(db, monkeypatch):
    """4'e bölünme sonrası Alpaca eski barı düzeltilmiş fiyatla verir; UPSERT ezer."""
    with connect(db) as c:
        write_bars(c, barlar("2026-09-17 13:00", 2, fiyat=320.0),
                   symbol="AAPL", timeframe="1Hour", adjustment="all")
    kur(monkeypatch, barlar("2026-09-17 13:00", 2, fiyat=80.0))
    tazele(db, tam_yenileme_saat=0)
    with connect(db) as c:
        df = read_bars(c, "AAPL", timeframe="1Hour")
    assert df["close"].tolist() == [80.0, 80.0]


def test_tam_yenileme_istenmezse_eski_davranis(db, monkeypatch):
    _depoda_bar_var(db)
    sahte = kur(monkeypatch, barlar("2026-09-17 14:00", 2))
    tazele(db, geriye_gun=60)
    assert sahte.cagrilar[0]["start"] == "2026-09-17T14:00:00Z"
