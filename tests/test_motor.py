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
        self.guncellemeler: list[str] = []
        self.gonderilenler: list[str] = []
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
        self.gonderilenler.append(kimlik)
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

    def emri_guncelle(self, broker_id, *, client_order_id, adet=None, limit=None, stop=None):
        (eski,) = [e for e in self.emirler.values() if e.broker_id == broker_id]
        if not eski.bekliyor:
            raise BrokerError('HTTP 422: {"message":"order is not replaceable"}')
        self.guncellemeler.append(client_order_id)
        self.emirler[eski.client_order_id] = _degistir(eski, durum="replaced")
        seviye = limit if limit is not None else stop if stop is not None else eski.seviye
        yeni = self._kaydet(client_order_id, eski.yon, eski.tip, adet or eski.adet, seviye)
        self.gonderilenler.remove(client_order_id)     # PATCH, yeni emir değil
        return yeni

    def tum_emirleri_iptal(self):
        self.tum_iptal_cagrildi = True
        for kimlik, e in list(self.emirler.items()):
            self.emirler[kimlik] = _degistir(e, durum="canceled")

    # --- test kolaylığı ---
    def doldur(self, kimlik, fiyat):
        e = self.emirler[kimlik]
        self.emirler[kimlik] = _degistir(e, durum="filled", dolan_adet=e.adet,
                                         dolan_ortalama_fiyat=fiyat)

    def kismi_doldur(self, kimlik, adet, fiyat):
        e = self.emirler[kimlik]
        self.emirler[kimlik] = _degistir(e, durum="partially_filled", dolan_adet=adet,
                                         dolan_ortalama_fiyat=fiyat)
        self._pozisyon_adedi += adet

    def bekleyen(self, yon):
        return [e for e in self.emirler.values() if e.bekliyor and e.yon == yon]


def _degistir(emir: Emir, **kw) -> Emir:
    alanlar = {a: getattr(emir, a) for a in Emir.__slots__}
    alanlar.update(kw)
    return Emir(**alanlar)


@pytest.fixture(autouse=True)
def uykusuz(monkeypatch):
    monkeypatch.setattr(M, "bekle", lambda sn: None)


@pytest.fixture()
def ayarlar(tmp_path):
    return M.Ayarlar(sembol="AAPL", kurallar=KURALLAR,
                     paper_db=tmp_path / "paper.db",
                     dur_dosyasi=tmp_path / "DUR",
                     duraklat_dosyasi=tmp_path / "DURAKLAT")


@pytest.fixture()
def sabit_barlar(monkeypatch):
    """Ağa çıkmasın: barları biz veriyoruz."""
    def ayarla(df):
        monkeypatch.setattr(M, "barlari_getir", lambda a, s=None, **kw: df)
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


def test_seviye_ayniysa_bekleyen_emre_hic_dokunulmaz(ayarlar, sabit_barlar):
    """Yeni bar geldi ama seviye aynı: iptal yok, güncelleme yok, yeni emir yok.

    Eskiden her saat iptal + yeniden konuyordu; iptal sürerken yeni emir
    reddedilebildiği için pozisyon korumasız kalabiliyordu (açık 2)."""
    b = SahteBroker()
    tur(ayarlar, b)
    sabit_barlar(barlar(bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    assert b.iptal_edilenler == [] and b.guncellemeler == []
    assert len(b.gonderilenler) == 1
    assert len(b.bekleyen("buy")) == 1


# ----------------------------------------------------------- DURAKLATMA --

def test_duraklatilinca_yeni_alis_emri_konmaz(ayarlar, sabit_barlar):
    ayarlar.duraklat_dosyasi.touch()
    b = SahteBroker()
    sonuc = tur(ayarlar, b)
    assert not sonuc.emir_gonderildi and b.emirler == {}
    assert any("DURAKLATILDI" in s for s in sonuc.satirlar)


def test_duraklatilinca_bekleyen_alis_iptal_edilir(ayarlar, sabit_barlar):
    """Borsada duran alış emri kalırsa duraklatılmış sistem yine alım yapar."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    ayarlar.duraklat_dosyasi.touch()

    tur(ayarlar, b)
    assert b.iptal_edilenler == [kimlik]
    assert not [e for e in b.emirler.values() if e.bekliyor]


def test_duraklatma_pozisyon_acikken_korumayi_kapatmaz(ayarlar, sabit_barlar):
    """Duraklatmak korumayı kapatmamalı: pozisyon varken stop emri aynen konur."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, ALIS)
    b._pozisyon_adedi = 487
    ayarlar.duraklat_dosyasi.touch()

    sonuc = tur(ayarlar, b)
    koruma = [e for e in b.emirler.values() if e.yon == "sell" and e.bekliyor]
    assert sonuc.emir_gonderildi
    assert len(koruma) == 1 and koruma[0].seviye == pytest.approx(ZARAR_STOP)


def test_duraklatma_kalkinca_alis_yeniden_konur(ayarlar, sabit_barlar):
    ayarlar.duraklat_dosyasi.touch()
    b = SahteBroker()
    tur(ayarlar, b)
    ayarlar.duraklat_dosyasi.unlink()

    sonuc = tur(ayarlar, b)
    assert sonuc.emir_gonderildi
    (emir,) = b.emirler.values()
    assert emir.yon == "buy" and emir.seviye == pytest.approx(ALIS)


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


# ----------------------------------------------------- YERİNDE GÜNCELLEME --

def _pozisyon_ac(ayarlar, b, fiyat=ALIS):
    """Alış emri konur, dolar, pozisyon kaydedilir, taban konur."""
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, fiyat)
    b._pozisyon_adedi = 487
    tur(ayarlar, b)
    return kimlik


def _dibi_indir(dip: float = 190.0):
    """Yeni bar; pencerede bir barın dibi `dip`e iner → alış seviyesi değişir."""
    df = barlar(bitis=SONRAKI_BITIS)
    df.loc[df.index[-5], "low"] = dip
    return df


def test_seviye_degisen_alis_yerinde_guncellenir(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    sabit_barlar(_dibi_indir(190.0))                  # genişlik 60: alış 196
    sonuc = tur(ayarlar, b)

    assert b.iptal_edilenler == [] and len(b.guncellemeler) == 1
    (alis,) = b.bekleyen("buy")
    assert alis.seviye == pytest.approx(196.0) and alis.adet == int(100_000 // 196.0)
    assert any("GÜNCELLENDİ" in s for s in sonuc.satirlar)
    with D.connect(ayarlar.paper_db) as c:
        durumlar = [r["durum"] for r in c.execute("SELECT durum FROM emirler ORDER BY rowid")]
        ek = c.execute("SELECT ek_seviye FROM emirler WHERE durum='gonderildi'").fetchone()[0]
    assert durumlar == ["degisti", "gonderildi"]
    assert ek == pytest.approx(190.0 - 2.0 * 60.0)        # yeni dibe göre zararına satış


def test_seviye_ayni_alista_zarar_stop_son_bara_cekilir(ayarlar, sabit_barlar):
    """Emre dokunulmasa da dolunca kurulacak seviye son barın çizgisinden gelir."""
    b = SahteBroker()
    tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        c.execute("UPDATE emirler SET ek_seviye = 1.0")
    sabit_barlar(barlar(bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        ek = c.execute("SELECT ek_seviye FROM emirler").fetchone()[0]
    assert ek == pytest.approx(ZARAR_STOP)


def test_seviye_ayni_taban_her_saat_yeniden_konmaz(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    gonderilen = list(b.gonderilenler)
    sabit_barlar(barlar(bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    assert b.gonderilenler == gonderilen and b.guncellemeler == []
    assert b.iptal_edilenler == []


def test_yukselen_taban_yerinde_guncellenir_iptal_edilmez(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    iptaller = list(b.iptal_edilenler)
    sabit_barlar(barlar(son_high=280.0, bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    assert b.iptal_edilenler == iptaller and len(b.guncellemeler) == 1
    (taban,) = b.bekleyen("sell")
    assert taban.seviye == pytest.approx(230.0) and taban.adet == 487


def test_guncelleme_sirasinda_emir_dolduysa_tur_patlamaz(ayarlar, sabit_barlar, monkeypatch):
    """PATCH 422: emir tam o sırada doldu. Sonraki geçiş broker'dan okur."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler

    def dolmus(broker_id, **kw):
        b.doldur(kimlik, ALIS)
        raise BrokerError('HTTP 422: {"message":"order is not replaceable"}')
    monkeypatch.setattr(b, "emri_guncelle", dolmus)
    sabit_barlar(_dibi_indir(190.0))
    sonuc = tur(ayarlar, b)
    assert not sonuc.durduruldu
    assert any("değiştirilemedi" in s for s in sonuc.satirlar)

    b._pozisyon_adedi = 487                           # sonraki geçiş dolumu işler
    sonuc = M.koruma_turu(ayarlar, broker=b)
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert pozisyon.acik and adet == 487
    assert [e.adet for e in b.bekleyen("sell")] == [487]


def test_iptal_ile_dolum_yarisinda_dolum_kaybolmaz(ayarlar, sabit_barlar):
    """Pozisyon açıldı, eski alış iptal edilirken aslında dolmuştu: kayıt
    'iptal' yazıp dolumu yutmamalı — akıbet broker'dan okunur."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    ayarlar.duraklat_dosyasi.touch()
    tur(ayarlar, b)                                   # iptal istendi
    b.emirler[kimlik] = _degistir(b.emirler[kimlik], durum="filled", dolan_adet=487,
                                  dolan_ortalama_fiyat=ALIS)
    b._pozisyon_adedi = 487
    ayarlar.duraklat_dosyasi.unlink()
    sonuc = tur(ayarlar, b)
    assert not sonuc.durduruldu, sonuc
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert pozisyon.acik and adet == 487


# ------------------------------------------------------------ KISMİ DOLUM --

def test_kismen_dolup_iptal_edilen_alis_dolan_adetle_acilir(ayarlar, sabit_barlar):
    """Açık 1: 487'nin 100'ü doldu, kalanı iptal edildi → pozisyon 100 adet."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.kismi_doldur(kimlik, 100, 204.9)
    b.emri_iptal(b.emirler[kimlik].broker_id)          # gün sonu düştü

    sonuc = tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
        g = c.execute("SELECT adet FROM gerceklesmeler").fetchone()
    assert not sonuc.durduruldu, sonuc                  # mutabakat tutuyor
    assert pozisyon.acik and adet == 100 and g["adet"] == 100
    assert pozisyon.stop == pytest.approx(ZARAR_STOP)
    (taban,) = b.bekleyen("sell")
    assert taban.adet == 100
    assert [u.anahtar for u in sonuc.uyarilar] == ["kismi_dolum"]


def test_tur_aninda_kismen_dolmus_alisin_kalani_iptal_edilir(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.kismi_doldur(kimlik, 100, 204.9)                 # emir hâlâ canlı

    sonuc = tur(ayarlar, b)
    assert kimlik in b.iptal_edilenler
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert not sonuc.durduruldu and pozisyon.acik and adet == 100
    assert [e.adet for e in b.bekleyen("sell")] == [100]
    assert b.bekleyen("buy") == []


def test_kismi_satis_pozisyonu_kucultur(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    (taban,) = b.bekleyen("sell")
    b.emirler[taban.client_order_id] = _degistir(
        taban, durum="canceled", dolan_adet=87, dolan_ortalama_fiyat=100.0)
    b._pozisyon_adedi = 400
    sonuc = tur(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert pozisyon.acik and adet == 400 and not sonuc.durduruldu
    assert [e.adet for e in b.bekleyen("sell")] == [400]


def test_acil_durdurmadan_sonra_eski_kismi_dolum_isleme_alinmaz(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.kismi_doldur(kimlik, 100, 204.9)
    ayarlar.dur_dosyasi.write_text("dur", encoding="utf-8")
    tur(ayarlar, b)                                    # pozisyon piyasadan kapandı
    b._pozisyon_adedi = 0
    ayarlar.dur_dosyasi.unlink()

    sonuc = tur(ayarlar, b)
    assert not sonuc.durduruldu, sonuc
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert not pozisyon.acik and adet == 0


# --------------------------------------------------------- KORUMA BEKÇİSİ --

def bekci(ayarlar, broker, **kw):
    return M.koruma_turu(ayarlar, broker=broker, **kw)


class SaymaliBroker(SahteBroker):
    """Broker'a kaç kez gidildiğini sayar."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.cagri = 0

    def borsa_saati(self):
        self.cagri += 1
        return super().borsa_saati()

    def pozisyon(self, sembol):
        self.cagri += 1
        return super().pozisyon(sembol)

    def bekleyen_emirler(self, sembol=None):
        self.cagri += 1
        return super().bekleyen_emirler(sembol)

    def emir_sorgula(self, kimlik):
        self.cagri += 1
        return super().emir_sorgula(kimlik)


def test_bekci_bostayken_brokera_hic_gitmez(ayarlar):
    b = SaymaliBroker()
    sonuc = bekci(ayarlar, b)
    assert b.cagri == 0 and "boşta" in sonuc.ozet


def test_bekci_dur_varken_hicbir_sey_yapmaz(ayarlar, sabit_barlar):
    b = SaymaliBroker()
    tur(ayarlar, b)
    ayarlar.dur_dosyasi.write_text("dur", encoding="utf-8")
    b.cagri = 0
    sonuc = bekci(ayarlar, b)
    assert b.cagri == 0 and "DUR" in sonuc.ozet


def test_bekci_borsa_kapaliyken_emre_dokunmaz(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, ALIS)
    b._pozisyon_adedi = 487
    b._acik = False
    bekci(ayarlar, b)
    assert b.bekleyen("sell") == []


def test_bekci_dolumdan_hemen_sonra_taban_koyar(ayarlar, sabit_barlar):
    """Açık 3: alış 13:45'te doldu — taban 14:20'yi değil, bir dakikayı bekler."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.doldur(kimlik, 204.5)
    b._pozisyon_adedi = 487

    sonuc = bekci(ayarlar, b)
    (taban,) = b.bekleyen("sell")
    assert taban.tip == "stop" and taban.adet == 487
    assert taban.seviye == pytest.approx(ZARAR_STOP)
    assert [(u.seviye, u.anahtar) for u in sonuc.uyarilar] == [(D.BILGI, "taban_konuldu")]
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert pozisyon.acik and adet == 487

    # Sonraki saatlik tur aynı tabanı görür, dokunmaz.
    gonderilen = list(b.gonderilenler)
    sabit_barlar(barlar(bitis=SONRAKI_BITIS))
    tur(ayarlar, b)
    assert b.gonderilenler == gonderilen and b.guncellemeler == []


def test_bekci_kismi_dolumda_kalani_iptal_edip_dolan_kadar_taban_koyar(ayarlar, sabit_barlar):
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.kismi_doldur(kimlik, 100, 204.9)

    sonuc = bekci(ayarlar, b)
    assert kimlik in b.iptal_edilenler and b.bekleyen("buy") == []
    (taban,) = b.bekleyen("sell")
    assert taban.adet == 100 and taban.seviye == pytest.approx(ZARAR_STOP)
    assert {u.anahtar for u in sonuc.uyarilar} == {"kismi_dolum", "taban_konuldu"}


def test_bekci_iptal_bitmezse_uyarir_taban_koymaz(ayarlar, sabit_barlar, monkeypatch):
    """İptal 10 sn'de bitmedi: kalan alış hâlâ açık, satış emri wash trade
    riski taşır — bekle, bir dakika sonra tekrar bak."""
    b = SahteBroker()
    tur(ayarlar, b)
    (kimlik,) = b.emirler
    b.kismi_doldur(kimlik, 100, 204.9)

    def yavas_iptal(broker_id):
        b.emirler[kimlik] = _degistir(b.emirler[kimlik], durum="pending_cancel")
    monkeypatch.setattr(b, "emri_iptal", yavas_iptal)
    sonuc = bekci(ayarlar, b)
    assert "kismi_iptal_bitmedi" in [u.anahtar for u in sonuc.uyarilar]
    assert b.bekleyen("sell") == []


def test_bekci_pozisyon_varken_taban_yoksa_koyar_ve_uyarir(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    (taban,) = b.bekleyen("sell")
    b.emirler[taban.client_order_id] = _degistir(taban, durum="rejected")

    sonuc = bekci(ayarlar, b)
    (yeni,) = b.bekleyen("sell")
    assert yeni.adet == 487 and yeni.seviye == pytest.approx(ZARAR_STOP)
    assert [(u.seviye, u.anahtar) for u in sonuc.uyarilar] == [(D.UYARI, "taban_yoktu")]


def test_bekci_taban_adedi_yanlissa_yerinde_duzeltir(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    (taban,) = b.bekleyen("sell")
    b.emirler[taban.client_order_id] = _degistir(taban, adet=300)
    iptaller = list(b.iptal_edilenler)

    sonuc = bekci(ayarlar, b)
    assert len(b.guncellemeler) == 1 and b.iptal_edilenler == iptaller
    (yeni,) = b.bekleyen("sell")
    assert yeni.adet == 487
    assert [u.anahtar for u in sonuc.uyarilar] == ["taban_duzeltildi"]


def test_bekci_taban_yerindeyse_hic_emir_gondermez(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    gonderilen = list(b.gonderilenler)
    sonuc = bekci(ayarlar, b)
    assert b.gonderilenler == gonderilen and b.guncellemeler == []
    assert sonuc.uyarilar == [] and "yerinde" in sonuc.ozet


def test_bekci_mutabakat_bozuksa_emre_dokunmaz(ayarlar, sabit_barlar):
    """Bölünme: broker 4 katı hisse gösteriyor. Eski seviyeye taban koymak
    hisseleri anında sattırabilirdi — dokunma, haber ver."""
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    b._pozisyon_adedi = 487 * 4
    gonderilen = list(b.gonderilenler)
    sonuc = bekci(ayarlar, b)
    assert b.gonderilenler == gonderilen and b.guncellemeler == []
    assert sonuc.durduruldu and [u.seviye for u in sonuc.uyarilar] == [D.KOTU]


def test_bekci_satis_dolunca_pozisyonu_kapatir(ayarlar, sabit_barlar):
    b = SahteBroker()
    _pozisyon_ac(ayarlar, b)
    (taban,) = b.bekleyen("sell")
    b.doldur(taban.client_order_id, 99.5)
    b._pozisyon_adedi = 0
    sonuc = bekci(ayarlar, b)
    with D.connect(ayarlar.paper_db) as c:
        pozisyon, adet, _ = D.durum_yukle(c)
    assert not pozisyon.acik and adet == 0 and "pozisyon yok" in sonuc.ozet


# ---------------------------------------------------------- FİYAT SIÇRAMASI --

def test_bolunme_sicramasinda_emir_gonderilmez(ayarlar, sabit_barlar):
    """4'e bölünme: son 10 bar dörtte bir fiyatta. Kanal 50–250 olur, alış
    seviyesi 70 çıkar ve piyasa 57'deyken anında dolardı."""
    df = barlar()
    for k in ("open", "high", "low", "close"):
        df.loc[df.index[-10:], k] = df.loc[df.index[-10:], k] / 4
    sabit_barlar(df)
    b = SahteBroker()
    sonuc = tur(ayarlar, b)
    assert sonuc.durduruldu and b.emirler == {}
    assert "sıçrama" in sonuc.ozet
    assert [u.anahtar for u in sonuc.uyarilar] == ["fiyat_sicramasi"]


def test_sicramada_depo_bastan_indirilir_duzelirse_devam(ayarlar, monkeypatch):
    """Bölünme: artımlı depo karışık, tam yenileme düzeltilmiş fiyatı getirir."""
    karisik = barlar()
    for k in ("open", "high", "low", "close"):
        karisik.loc[karisik.index[-10:], k] = karisik.loc[karisik.index[-10:], k] / 4
    istekler = []

    def getir(a, s=None, *, tam_yenile=False):
        istekler.append(tam_yenile)
        return barlar() if tam_yenile else karisik
    monkeypatch.setattr(M, "barlari_getir", getir)

    sonuc = tur(ayarlar, SahteBroker())
    assert istekler == [False, True]
    assert not sonuc.durduruldu and sonuc.emir_gonderildi


def test_esigin_altindaki_sicramada_emir_normal(ayarlar, sabit_barlar):
    df = barlar()
    df.loc[df.index[-3], "open"] = 230.0 * 1.2          # %20: eşiğin altında
    sabit_barlar(df)
    sonuc = tur(ayarlar, SahteBroker())
    assert not sonuc.durduruldu and sonuc.emir_gonderildi
