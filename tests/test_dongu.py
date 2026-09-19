"""Döngü — testler. Saat sahte: testler gerçekten beklemez.

Kritik özellikler:
* Her saatin :20'sinde tur; gün ve yaz saati sınırında kaymaz.
* Üst üste 3 hatada durur, arada başarı olursa sayaç sıfırlanır.
* Her tur kalp atışı yazar (hata olsa bile).
* İkinci döngü kilide takılır.
* DUR bayrağı uyku sırasında belirirse acil tur saat başını beklemez.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import alarm  # noqa: E402
from src.engine import dongu as DG  # noqa: E402
from src.engine import durum as D  # noqa: E402
from src.engine import motor as M  # noqa: E402

UTC = dt.timezone.utc


class Saat:
    def __init__(self, an):
        self.an = an
        self.olaylar = {}          # zaman -> fonksiyon (uyku sırasında tetiklenir)

    def simdi(self):
        return self.an

    def uyu(self, sn):
        onceki = self.an
        self.an = self.an + dt.timedelta(seconds=sn)
        for zaman, fn in list(self.olaylar.items()):
            if onceki < zaman <= self.an:
                fn()
                del self.olaylar[zaman]


class SahteTur:
    def __init__(self, saat, hatalar=()):
        self.saat = saat
        self.hatalar = list(hatalar)       # sırayla: True = bu tur hata versin
        self.zamanlar = []

    def __call__(self, ayarlar, kuru=False):
        self.zamanlar.append(self.saat.simdi())
        if self.hatalar and self.hatalar.pop(0):
            raise ConnectionError("ağ yok")
        return M.TurSonucu(ozet="AAPL | nakitte")


@pytest.fixture()
def ayarlar(tmp_path):
    return M.Ayarlar(paper_db=tmp_path / "paper.db", veri_db=tmp_path / "veri.db",
                     dur_dosyasi=tmp_path / "DUR", duraklat_dosyasi=tmp_path / "DURAKLAT",
                     kilit_dosyasi=tmp_path / "dongu.pid")


@pytest.fixture(autouse=True)
def alarm_kaydedici(monkeypatch):
    giden = []
    monkeypatch.setattr(alarm, "gonder", lambda konu, govde, **kw: giden.append(
        (kw.get("anahtar"), konu)) or True)
    return giden


def calistir(ayarlar, saat, tur, **kw):
    kw.setdefault("koruma_fn", None)          # bekçi ayrı testlerde
    kw.setdefault("gosterim_fn", None)        # gösterim verisi ağa çıkar, ayrı testlerde
    return DG.dongu(ayarlar, tur_fn=tur, simdi_fn=saat.simdi, uyu_fn=saat.uyu,
                    bildir=kw.pop("bildir", False), sinyal_yakala=False, **kw)


def turlar(ayarlar):
    with D.connect(ayarlar.paper_db) as c:
        return c.execute("SELECT * FROM turlar ORDER BY id").fetchall()


# ------------------------------------------------------------ TETİK ZAMANI --

@pytest.mark.parametrize("simdi, beklenen", [
    ("2026-09-18 14:05", "2026-09-18 14:20"),
    ("2026-09-18 14:20", "2026-09-18 15:20"),     # tam tetik anı: bir sonraki
    ("2026-09-18 14:19:59", "2026-09-18 14:20"),
    ("2026-09-18 23:30", "2026-09-19 00:20"),     # gün sınırı
    ("2026-12-31 23:59", "2027-01-01 00:20"),     # yıl sınırı
    ("2026-11-01 05:40", "2026-11-01 06:20"),     # New York yaz saati bitişi (UTC kaymaz)
    ("2026-03-08 06:25", "2026-03-08 07:20"),     # New York yaz saati başlangıcı
])
def test_sonraki_tetik(simdi, beklenen):
    an = dt.datetime.fromisoformat(simdi).replace(tzinfo=UTC)
    assert DG.sonraki_tetik(an) == dt.datetime.fromisoformat(beklenen).replace(tzinfo=UTC)


def test_turlar_her_saatin_20sinde(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    tur = SahteTur(saat)
    assert calistir(ayarlar, saat, tur, azami_tur=3) == 0
    assert [t.strftime("%H:%M") for t in tur.zamanlar] == ["14:05", "14:20", "15:20"]


def test_gosterim_verisi_tur_sonrasi_tazelenir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    cagri = []
    calistir(ayarlar, saat, SahteTur(saat), azami_tur=2,
             gosterim_fn=lambda a: cagri.append(a.sembol))
    assert cagri == ["AAPL", "AAPL"]


def test_gosterim_hatasi_turu_etkilemez(ayarlar):
    """Grafik verisi inemezse işlem durmaz: tur 'tamam' kalır, sayaç artmaz."""
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))

    def patla(_ayarlar):
        raise RuntimeError("Alpaca 403")

    assert calistir(ayarlar, saat, SahteTur(saat), azami_tur=4, gosterim_fn=patla) == 0
    assert [t["sonuc"] for t in turlar(ayarlar)] == ["tamam"] * 4


# -------------------------------------------------------------- HATA TAVRI --

def test_uc_ardisik_hatada_durur(ayarlar, alarm_kaydedici):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    tur = SahteTur(saat, hatalar=[True, True, True, False])
    assert calistir(ayarlar, saat, tur, bildir=True, azami_tur=10) == 1
    assert len(tur.zamanlar) == 3
    assert [t["sonuc"] for t in turlar(ayarlar)] == ["hata"] * 3
    anahtarlar = [a for a, _ in alarm_kaydedici]
    assert anahtarlar.count("tur_hatasi") == 3 and "ucuncu_hata" in anahtarlar


def test_durunca_dur_dosyasi_olusturulmaz(ayarlar):
    """Ağ hatası pozisyonu kapattırmamalı."""
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    calistir(ayarlar, saat, SahteTur(saat, hatalar=[True] * 3), azami_tur=10)
    assert not ayarlar.dur_dosyasi.exists()


def test_basari_sayaci_sifirlar(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    tur = SahteTur(saat, hatalar=[True, True, False, True, True, False])
    assert calistir(ayarlar, saat, tur, azami_tur=6) == 0
    assert len(tur.zamanlar) == 6


def test_her_tur_kalp_atisi_yazar(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    calistir(ayarlar, saat, SahteTur(saat, hatalar=[False, True, False]), azami_tur=3)
    t = turlar(ayarlar)
    assert [x["sonuc"] for x in t] == ["tamam", "hata", "tamam"]
    assert "ağ yok" in t[1]["hata"]


def test_durdurulan_tur_kaydedilir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))

    def tur(ayarlar, kuru=False):
        s = M.TurSonucu(ozet="MUTABAKAT BOZUK — motor durdu.")
        s.durduruldu = True
        return s

    calistir(ayarlar, saat, tur, azami_tur=1)
    assert turlar(ayarlar)[0]["sonuc"] == "durduruldu"


# ------------------------------------------------------------------- KİLİT --

def test_taze_kilit_varsa_ikinci_dongu_baslamaz(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    ayarlar.kilit_dosyasi.write_text("999", encoding="utf-8")
    os.utime(ayarlar.kilit_dosyasi, (saat.an.timestamp(), saat.an.timestamp()))
    tur = SahteTur(saat)
    assert calistir(ayarlar, saat, tur, azami_tur=1) == 2
    assert tur.zamanlar == []
    assert ayarlar.kilit_dosyasi.read_text(encoding="utf-8") == "999"   # dokunulmadı


def test_bayat_kilit_devralinir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    ayarlar.kilit_dosyasi.write_text("999", encoding="utf-8")
    eski = saat.an.timestamp() - 3600
    os.utime(ayarlar.kilit_dosyasi, (eski, eski))
    assert calistir(ayarlar, saat, SahteTur(saat), azami_tur=1) == 0


def test_kapaninca_kilit_birakilir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    calistir(ayarlar, saat, SahteTur(saat), azami_tur=2)
    assert not ayarlar.kilit_dosyasi.exists()


# --------------------------------------------------------------- BAYRAKLAR --

def test_dur_uykuda_belirince_acil_tur_hemen(ayarlar, alarm_kaydedici):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    bayrak_ani = dt.datetime(2026, 9, 18, 14, 30, tzinfo=UTC)
    saat.olaylar[bayrak_ani] = lambda: ayarlar.dur_dosyasi.write_text(
        '{"komut": "/stop onayla", "kaynak": "192.168.1.5"}', encoding="utf-8")
    tur = SahteTur(saat)
    calistir(ayarlar, saat, tur, azami_tur=3)

    ikinci_uc = tur.zamanlar[2]
    assert bayrak_ani <= ikinci_uc < bayrak_ani + dt.timedelta(seconds=DG.DILIM_SN + 1)
    with D.connect(ayarlar.paper_db) as c:
        k = c.execute("SELECT * FROM komutlar").fetchone()
    assert k["komut"] == "/stop onayla" and k["kaynak"] == "192.168.1.5"
    assert any(a.startswith("komut_DUR") for a, _ in alarm_kaydedici)


def test_acilista_var_olan_bayrak_acil_tur_tetiklemez(ayarlar):
    """Bayrak zaten varsa her uyku diliminde tekrar tekrar acil tur atılmamalı."""
    ayarlar.dur_dosyasi.touch()
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    tur = SahteTur(saat)
    calistir(ayarlar, saat, tur, azami_tur=2)
    assert [t.strftime("%H:%M") for t in tur.zamanlar] == ["14:05", "14:20"]


def test_duraklat_kaldirilinca_kutuge_yazilir(ayarlar):
    ayarlar.duraklat_dosyasi.touch()
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    saat.olaylar[dt.datetime(2026, 9, 18, 14, 10, tzinfo=UTC)] = ayarlar.duraklat_dosyasi.unlink
    calistir(ayarlar, saat, SahteTur(saat), azami_tur=2)
    with D.connect(ayarlar.paper_db) as c:
        k = c.execute("SELECT * FROM komutlar").fetchone()
    assert k["sonuc"] == "DURAKLAT kaldırıldı"


# ---------------------------------------------------------- KORUMA BEKÇİSİ --

class SahteKoruma:
    def __init__(self, saat, hata=False, uyarilar=()):
        self.saat, self.hata, self.uyarilar = saat, hata, list(uyarilar)
        self.zamanlar = []

    def __call__(self, ayarlar, kuru=False):
        self.zamanlar.append(self.saat.simdi())
        if self.hata:
            raise ConnectionError("broker yok")
        s = M.TurSonucu(ozet="taban yerinde")
        for u in self.uyarilar:
            s.uyar(*u)
        self.uyarilar = []
        return s


def test_bekci_uykuda_dakikada_bir_calisir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    bekci = SahteKoruma(saat)
    calistir(ayarlar, saat, SahteTur(saat), azami_tur=2, koruma_fn=bekci)
    araliklar = {(b - a).total_seconds() for a, b in zip(bekci.zamanlar, bekci.zamanlar[1:])}
    assert 14 <= len(bekci.zamanlar) <= 15           # 14:05 → 14:20 arası
    assert araliklar == {60.0}


def test_bekci_hatasi_donguyu_durdurmaz(ayarlar, alarm_kaydedici):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    tur = SahteTur(saat)
    assert calistir(ayarlar, saat, tur, azami_tur=3, bildir=True,
                    koruma_fn=SahteKoruma(saat, hata=True)) == 0
    assert len(tur.zamanlar) == 3                    # saatlik turlar aksamadı
    assert "koruma_hatasi" in [a for a, _ in alarm_kaydedici]
    assert [t["sonuc"] for t in turlar(ayarlar)] == ["tamam"] * 3


def test_bekci_uyarilari_tabloya_yazilir(ayarlar, alarm_kaydedici):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    bekci = SahteKoruma(saat, uyarilar=[(D.BILGI, "taban_konuldu", "taban konuldu"),
                                        (D.UYARI, "taban_yoktu", "taban yoktu!")])
    calistir(ayarlar, saat, SahteTur(saat), azami_tur=2, bildir=True, koruma_fn=bekci)
    with D.connect(ayarlar.paper_db) as c:
        yazilan = [r["anahtar"] for r in D.son_uyarilar(c)]
    assert yazilan == ["taban_konuldu"]              # bilgi doğrudan tabloya
    assert "taban_yoktu" in [a for a, _ in alarm_kaydedici]   # sorun alarm yoluyla


def test_bekci_kapatilabilir(ayarlar):
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    assert calistir(ayarlar, saat, SahteTur(saat), azami_tur=2, koruma_fn=None) == 0


def test_gercek_bekci_bostayken_sorunsuz_doner(ayarlar):
    """Varsayılan koruma_turu: kayıtta pozisyon yok → broker'a gitmeden döner."""
    saat = Saat(dt.datetime(2026, 9, 18, 14, 5, tzinfo=UTC))
    assert calistir(ayarlar, saat, SahteTur(saat), azami_tur=2,
                    koruma_fn=M.koruma_turu) == 0
