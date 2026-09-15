"""Motor turu testleri — sahte broker, ağ erişimi yok.

Buradaki senaryolar ENV-B'nin varlık sebebi olan tatbikatların otomatik hali
(ENVIRONMENTS.md §3): mutabakat, bayat veri, acil durdurma, çift emir.
Gerçek tatbikat paper hesapta elle de yapılır; bu testler o güne kadar
bozulmadığını garanti eder.

Sayılar `test_kural.py` ile aynı: tepe 250 · dip 200 · genişlik 50
    alış 205 · zararına satış 100 · takip mesafesi 50
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import durum as D  # noqa: E402
from src.engine import motor as M  # noqa: E402
from src.engine.broker import (  # noqa: E402
    LIMIT_AL,
    STOP_SAT,
    BorsaSaati,
    BrokerError,
    Emir,
    Pozisyon,
)
from src.engine.kural import Durum, Kurallar  # noqa: E402

KURALLAR = Kurallar(n=20, cizgi="donchian", satis="takip",
                    alim_payi=0.10, stop_payi=2.0, takip_payi=1.0)
ALIS = 205.0
ZARAR_STOP = 100.0


# ------------------------------------------------------------ YARDIMCILAR --

def barlar(adet: int = 40, *, son_high: float = 240.0,
           bitis: dt.datetime | None = None) -> pd.DataFrame:
    """Tepesi 250, dibi 200 olan yapay seans barları.

    Son bar DIŞINDAKİ her bar 250'ye değip 200'e iner, böylece pencere nereye
    kayarsa kaysın çizgiler tepe=250 / dip=200 çıkar ve seviyeler elle
    hesaplanabilir. Son bar kanalın içinde kalır (varsayılan zirve 240), yani
    takip eden stop kendiliğinden devreye girmez — `son_high` ile tetiklenir.
    """
    bitis = bitis or dt.datetime(2026, 9, 15, 15, 0, tzinfo=dt.timezone.utc)
    ts = [bitis - dt.timedelta(hours=adet - 1 - i) for i in range(adet)]
    satirlar = []
    for i in range(adet):
        if i == adet - 1:
            o, h, lo, c = 230.0, son_high, 225.0, 232.0   # son bar
        else:
            o, h, lo, c = 230.0, 250.0, 200.0, 230.0      # kanalı kuran barlar
        satirlar.append({"timestamp": ts[i], "open": o, "high": h,
                         "low": lo, "close": c})
    df = pd.DataFrame(satirlar)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


class SahteBroker:
    """Testlerde gerçek broker yerine geçer. Emirleri hafızada tutar."""

    def __init__(self, *, acik=True, nakit=100_000.0, pozisyon_adedi=0):
        self._acik = acik
        self._nakit = nakit
        self._pozisyon_adedi = pozisyon_adedi
        self.emirler: dict[str, Emir] = {}
        self.iptal_edilenler: list[str] = []
        self.piyasa_satislari: list[int] = []
        self.tum_iptal_cagrildi = False
        self._sayac = 0

    # --- okuma ---
    def borsa_saati(self):
        return BorsaSaati(acik=self._acik, su_an="", sonraki_acilis="2026-09-16T09:30:00-04:00",
                          sonraki_kapanis="")

    def hesap(self):
        from src.engine.broker import Hesap
        return Hesap(nakit=self._nakit, ozkaynak=self._nakit, alim_gucu=self._nakit,
                     islem_engelli=False, hesap_engelli=False)

    def pozisyon(self, sembol):
        if self._pozisyon_adedi <= 0:
            return None
        return Pozisyon(sembol=sembol, adet=self._pozisyon_adedi,
                        ortalama_maliyet=ALIS, guncel_fiyat=230.0)

    def bekleyen_emirler(self, sembol=None):
        return [e for e in self.emirler.values() if e.bekliyor]

    def emir_sorgula(self, client_order_id):
        return self.emirler.get(client_order_id)

    # --- emir ---
    def _kaydet(self, kimlik, yon, tip, adet, seviye, durum="new"):
        if kimlik in self.emirler:
            raise BrokerError('HTTP 422: {"message":"client_order_id must be unique"}')
        self._sayac += 1
        emir = Emir(broker_id=f"b{self._sayac}", client_order_id=kimlik,
                    sembol="AAPL", yon=yon, tip=tip, adet=adet, seviye=seviye,
                    durum=durum, dolan_adet=0, dolan_ortalama_fiyat=float("nan"))
        self.emirler[kimlik] = emir
        return emir

    def limit_al(self, sembol, adet, seviye, kimlik):
        return self._kaydet(kimlik, "buy", "limit", adet, seviye)

    def stop_sat(self, sembol, adet, seviye, kimlik):
        return self._kaydet(kimlik, "sell", "stop", adet, seviye)

    def piyasadan_sat(self, sembol, adet, kimlik):
        self.piyasa_satislari.append(adet)
        return self._kaydet(kimlik, "sell", "market", adet, float("nan"), durum="filled")

    def emri_iptal(self, broker_id):
        for kimlik, e in list(self.emirler.items()):
            if e.broker_id == broker_id:
                self.iptal_edilenler.append(kimlik)
                self.emirler[kimlik] = _degistir(e, durum="canceled")

    def tum_emirleri_iptal(self):
        self.tum_iptal_cagrildi = True
        for kimlik, e in list(self.emirler.items()):
            self.emirler[kimlik] = _degistir(e, durum="canceled")

    # --- test kolaylığı ---
    def doldur(self, kimlik, fiyat):
        e = self.emirler[kimlik]
        self.emirler[kimlik] = _degistir(e, durum="filled", dolan_adet=e.adet,
                                         dolan_ortalama_fiyat=fiyat)


def _degistir(emir: Emir, **kw) -> Emir:
    alanlar = {a: getattr(emir, a) for a in Emir.__slots__}
    alanlar.update(kw)
    return Emir(**alanlar)


@pytest.fixture()
def ayarlar(tmp_path):
    return M.Ayarlar(sembol="AAPL", kurallar=KURALLAR,
                     paper_db=tmp_path / "paper.db",
                     dur_dosyasi=tmp_path / "DUR")


@pytest.fixture()
def sabit_barlar(monkeypatch):
    """Ağa çıkmasın: barları biz veriyoruz."""
    def ayarla(df):
        monkeypatch.setattr(M, "barlari_getir", lambda a, s=None: df)
    ayarla(barlar())
    return ayarla


SIMDI = dt.datetime(2026, 9, 15, 15, 30, tzinfo=dt.timezone.utc)
SONRAKI_BITIS = dt.datetime(2026, 9, 15, 16, 0, tzinfo=dt.timezone.utc)


def tur(ayarlar, broker, **kw):
    return M.bir_tur(ayarlar, broker=broker, simdi=SIMDI, **kw)


# --------------------------------------------------------------- KAPALI --

def test_borsa_kapaliyken_emir_gonderilmez(ayarlar, sabit_barlar):
    b = SahteBroker(acik=False)
    sonuc = tur(ayarlar, b)
    assert not sonuc.emir_gonderildi and b.emirler == {}
    assert "kapalı" in sonuc.ozet.lower()


# ------------------------------------------------------------ ALIŞ EMRİ --

def test_nakitteyken_dogru_seviyeye_tam_hisse_limit_alis_konur(ayarlar, sabit_barlar):
    b = SahteBroker(nakit=100_000.0)
    sonuc = tur(ayarlar, b)

    assert sonuc.emir_gonderildi
    (emir,) = b.emirler.values()
    assert emir.yon == "buy" and emir.tip == "limit"
    assert emir.seviye == pytest.approx(ALIS)
    assert emir.adet == int(100_000 // ALIS) == 487      # TAM hisse, kesirli değil


def test_nakit_bir_hisseye_yetmiyorsa_emir_yok(ayarlar, sabit_barlar):
    b = SahteBroker(nakit=100.0)
    sonuc = tur(ayarlar, b)
    assert not sonuc.emir_gonderildi and b.emirler == {}
    assert any("yetmiyor" in s for s in sonuc.satirlar)


def test_alis_emrine_zararina_satis_seviyesi_ilistirilir(ayarlar, sabit_barlar):
    """Stop alışta sabitlenir; emir dolunca çizgiler kaymış olsa bile bu kullanılır."""
    b = SahteBroker()
    tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        satir = c.execute("SELECT * FROM emirler").fetchone()
    assert satir["tip"] == LIMIT_AL
    assert satir["ek_seviye"] == pytest.approx(ZARAR_STOP)


# ---------------------------------------------------------- DOLAN EMİR --

def test_dolan_alis_duruma_islenir_ve_stop_ek_seviyeden_kurulur(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, 204.50)              # seviyeden biraz iyi doldu

    sonuc = tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
        g = c.execute("SELECT * FROM gerceklesmeler").fetchone()

    assert pozisyon.acik and adet == 487
    assert pozisyon.giris_fiyat == pytest.approx(204.50)
    assert pozisyon.stop == pytest.approx(ZARAR_STOP)
    # Paper koşusunun asıl çıktısı: istenen vs gerçekleşen
    assert g["istenen_seviye"] == pytest.approx(ALIS)
    assert g["gerceklesen_fiyat"] == pytest.approx(204.50)
    assert any("DOLDU" in s for s in sonuc.satirlar)


def test_pozisyon_varken_koruma_emri_konur(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, ALIS)
    b._pozisyon_adedi = 487

    sonuc = tur(ayarlar, b)
    assert sonuc.emir_gonderildi
    koruma = [e for e in b.emirler.values() if e.yon == "sell" and e.bekliyor]
    assert len(koruma) == 1 and koruma[0].tip == "stop"
    assert koruma[0].seviye == pytest.approx(ZARAR_STOP)
    assert koruma[0].adet == 487


def test_tepeye_deginca_takip_devreye_girer_ve_stop_yukselir(ayarlar, sabit_barlar):
    """Fiyat 280'i görür: stop 100'den 230'a (280 − 50) çıkmalı."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, ALIS)
    b._pozisyon_adedi = 487
    tur(ayarlar, b)                                   # pozisyon kuruldu

    sabit_barlar(barlar(son_high=280.0, bitis=SONRAKI_BITIS))  # YENI bar: zirve 280
    sonuc = tur(ayarlar, b)

    with D.connect(ayarlar.paper_db) as c:
        pozisyon, _, _ = D.durum_yukle(c)
    assert pozisyon.takipte
    assert pozisyon.stop == pytest.approx(230.0)
    assert any("takip" in s.lower() for s in sonuc.satirlar)


# ------------------------------------------------------------ TATBİKATLAR --

def test_mutabakat_bozuksa_motor_durur_ve_emir_gondermez(ayarlar, sabit_barlar):
    """Broker'da pozisyon var ama kayıtta yok — dokunma, dur (TD-06)."""
    b = SahteBroker(pozisyon_adedi=100)
    sonuc = tur(ayarlar, b)
    assert sonuc.durduruldu and not sonuc.emir_gonderildi
    assert b.emirler == {}
    assert "MUTABAKAT BOZUK" in sonuc.ozet


def test_yeniden_baslatmada_durum_diskten_geri_gelir(ayarlar, sabit_barlar):
    """Motor çöktü: takip eden stop seviyesi kaybolmamalı (TD-06)."""
    with D.connect(ayarlar.paper_db) as c:
        D.durum_kaydet(c, Durum(acik=True, giris_fiyat=ALIS, stop=230.0,
                                takipte=True, zirve=280.0, mesafe=50.0),
                       adet=487, son_islenen_bar=None)

    b = SahteBroker(pozisyon_adedi=487)               # broker da aynı fikirde
    tur(ayarlar, b)

    koruma = [e for e in b.emirler.values() if e.yon == "sell"]
    assert len(koruma) == 1
    assert koruma[0].seviye == pytest.approx(230.0)   # 100'den değil, 230'dan korur


def test_bayat_veride_emir_gonderilmez(ayarlar, sabit_barlar):
    """Son tam bar çok eski — veri akışı kesilmiş olabilir (TD-08)."""
    eski = barlar(bitis=dt.datetime(2026, 9, 10, 15, 0, tzinfo=dt.timezone.utc))
    sabit_barlar(eski)
    b = SahteBroker()
    sonuc = tur(ayarlar, b)
    assert sonuc.durduruldu and not sonuc.emir_gonderildi and b.emirler == {}
    assert "Bayat veri" in sonuc.ozet


def test_yetersiz_barda_emir_gonderilmez(ayarlar, sabit_barlar):
    sabit_barlar(barlar(adet=5))                      # n=20 için az
    b = SahteBroker()
    sonuc = tur(ayarlar, b)
    assert not sonuc.emir_gonderildi and b.emirler == {}
    assert "Yetersiz bar" in sonuc.ozet


def test_acil_durdurma_emirleri_iptal_edip_pozisyonu_kapatir(ayarlar, sabit_barlar):
    """DUR dosyası (TD-09)."""
    b = SahteBroker(pozisyon_adedi=487)
    ayarlar.dur_dosyasi.write_text("dur", encoding="utf-8")

    sonuc = tur(ayarlar, b)

    assert sonuc.durduruldu
    assert b.tum_iptal_cagrildi
    assert b.piyasa_satislari == [487]
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert not pozisyon.acik and adet == 0


def test_acil_durdurma_borsa_saatinden_once_bakilir(ayarlar, sabit_barlar):
    """Borsa kapalı olsa bile DUR dosyası işler."""
    b = SahteBroker(acik=False, pozisyon_adedi=10)
    ayarlar.dur_dosyasi.write_text("dur", encoding="utf-8")
    sonuc = tur(ayarlar, b)
    assert sonuc.durduruldu and b.tum_iptal_cagrildi


def test_kuru_calismada_hicbir_emir_gitmez(ayarlar, sabit_barlar):
    b = SahteBroker()
    sonuc = tur(ayarlar, b, kuru=True)
    assert b.emirler == {} and not sonuc.emir_gonderildi
    assert any("[kuru]" in s for s in sonuc.satirlar)


def test_her_turda_eski_bekleyen_emir_iptal_edilir(ayarlar, sabit_barlar):
    """Seviye her bar değişebilir; eski emir ortada kalmamalı."""
    b = SahteBroker()
    tur(ayarlar, b)
    sabit_barlar(barlar(bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    assert len(b.iptal_edilenler) == 1
    assert len([e for e in b.emirler.values() if e.bekliyor]) == 1


# ------------------------------------------------------------- ÇİZGİLER --

def test_cizgi_son_haric_backtestteki_shift_ile_ayni():
    df = barlar(adet=25, son_high=280.0)     # son barin zirvesi kanalin uzerinde
    # Emir seviyeleri son bari DA sayar: motor bir sonraki bar icin hesaplar.
    assert M.cizgi_hesapla(df, 20).tepe == pytest.approx(280.0)
    # takip_guncelle'ye verilen cizgi son bari saymaz (backtest'teki shift(1)):
    # yoksa fiyat her yeni zirvede "tepeye degmis" sayilir, cizgi fiyati kovalar.
    assert M.cizgi_hesapla(df, 20, son_haric=1).tepe == pytest.approx(250.0)


def test_pencere_dolmadan_cizgi_uretilmez():
    cizgi = M.cizgi_hesapla(barlar(adet=5), 20)
    assert not cizgi.hazir
