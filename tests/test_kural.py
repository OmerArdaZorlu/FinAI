"""Al-sat kurallarının testleri — canlıya çıkacak kod burası.

Her senaryo elle hesaplanmıştır. Sayılar bilerek yuvarlak seçildi:

    tepe 250 · dip 200 · genişlik 50
    alim_payi 0.10 → alış seviyesi  200 + 0.10 × 50 = 205
    stop_payi 2.00 → zararına satış 200 − 2.00 × 50 = 100
    takip_payi 1.0 → takip mesafesi        1.0 × 50 =  50

Ağ erişimi ya da veri dosyası gerektirmez.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.kural import (  # noqa: E402
    AL,
    SAT,
    SEBEP_STOP,
    SEBEP_TAKIP,
    SEBEP_TEPE,
    Bar,
    Cizgi,
    Durum,
    Kurallar,
    emir_seviyeleri,
    uygula,
)

CIZGI = Cizgi(tepe=250.0, dip=200.0)
ALIS_SEVIYESI = 205.0
ZARAR_STOP = 100.0
MESAFE = 50.0

TAKIP = Kurallar(n=140, cizgi="donchian", satis="takip",
                 alim_payi=0.10, stop_payi=2.0, takip_payi=1.0)
TEPEDE_SAT = Kurallar(n=140, cizgi="donchian", satis="tepe",
                      alim_payi=0.10, stop_payi=2.0)

BOS = Durum()


def acik(stop: float = ZARAR_STOP, **kw) -> Durum:
    """Açık pozisyon durumu kısayolu."""
    return Durum(acik=True, giris_fiyat=ALIS_SEVIYESI, stop=stop, **kw)


# ------------------------------------------------------------- SEVİYELER --

def test_pozisyon_yokken_seviyeler_elle_hesaplananla_ayni():
    sev = emir_seviyeleri(BOS, CIZGI, TAKIP)
    assert sev.alis == pytest.approx(ALIS_SEVIYESI)
    assert sev.zarar_stop == pytest.approx(ZARAR_STOP)
    assert math.isnan(sev.koruma)        # pozisyon yok, koruma emri de yok
    assert sev.emir_var


def test_pozisyon_varken_yalnizca_koruma_emri_var():
    sev = emir_seviyeleri(acik(stop=230.0), CIZGI, TAKIP)
    assert sev.koruma == pytest.approx(230.0)
    assert math.isnan(sev.alis)          # elde hisse varken alış emri konmaz


def test_cizgi_hazir_degilse_emir_konmaz():
    """Isınma döneminde pencere dolmamıştır — hiçbir emir verilmez."""
    sev = emir_seviyeleri(BOS, Cizgi(tepe=math.nan, dip=math.nan), TAKIP)
    assert not sev.emir_var


def test_duz_kanalda_emir_konmaz():
    """tepe == dip: alınacak bir aralık yok, sıfıra bölme de yok."""
    assert not emir_seviyeleri(BOS, Cizgi(250.0, 250.0), TAKIP).emir_var


# ------------------------------------------------------------------ ALIŞ --

def test_fiyat_alis_seviyesine_inince_alinir():
    durum, olaylar = uygula(BOS, Bar(210.0, 212.0, 203.0, 208.0), CIZGI, TAKIP)
    assert [o.eylem for o in olaylar] == [AL]
    assert olaylar[0].fiyat == pytest.approx(ALIS_SEVIYESI)
    assert durum.acik and durum.stop == pytest.approx(ZARAR_STOP)
    assert not durum.takipte


def test_seviyeye_inmeyen_barda_alinmaz():
    """En düşük 206 — bekleyen limit emri 205'te, dolmadı."""
    durum, olaylar = uygula(BOS, Bar(210.0, 212.0, 206.0, 208.0), CIZGI, TAKIP)
    assert olaylar == [] and not durum.acik


def test_gece_boslugu_seviyenin_altindan_acilirsa_acilistan_alinir():
    """Limit emri daha iyi fiyattan dolar: 190 < 205."""
    _, olaylar = uygula(BOS, Bar(190.0, 195.0, 188.0, 192.0), CIZGI, TAKIP)
    assert olaylar[0].fiyat == pytest.approx(190.0)


def test_acilis_stop_seviyesinin_altindaysa_alinmaz():
    """Sistem zaten zararda açmış — o barda pozisyona girilmez."""
    durum, olaylar = uygula(BOS, Bar(95.0, 99.0, 90.0, 97.0), CIZGI, TAKIP)
    assert olaylar == [] and not durum.acik


def test_ayni_barda_alinip_stopa_dusulebilir():
    """En düşük hem 205'in hem 100'ün altında: önce alınır, sonra stop olur."""
    durum, olaylar = uygula(BOS, Bar(210.0, 212.0, 99.0, 105.0), CIZGI, TAKIP)
    assert [(o.eylem, o.sebep) for o in olaylar] == [(AL, ""), (SAT, SEBEP_STOP)]
    assert olaylar[1].fiyat == pytest.approx(ZARAR_STOP)
    assert not durum.acik


def test_alis_barinda_tepeye_deginse_bile_takip_baslamaz():
    """Alış barında satış yok (stop hariç); takip eden stop da devreye girmez."""
    durum, _ = uygula(BOS, Bar(210.0, 260.0, 203.0, 255.0), CIZGI, TAKIP)
    assert durum.acik and not durum.takipte
    assert durum.stop == pytest.approx(ZARAR_STOP)


# ------------------------------------------------- TAKİP EDEN STOP (satis="takip") --

def test_tepeye_deginca_satilmaz_takip_devreye_girer():
    durum, olaylar = uygula(acik(), Bar(240.0, 280.0, 238.0, 275.0), CIZGI, TAKIP)
    assert olaylar == []                       # tepede SATILMAZ
    assert durum.takipte
    assert durum.mesafe == pytest.approx(MESAFE)
    assert durum.zirve == pytest.approx(280.0)
    assert durum.stop == pytest.approx(230.0)  # 280 − 50


def test_takip_stopu_degdigi_barda_tetiklenmez():
    """Bar içinde zirvenin mi dibin mi önce geldiğini bilmiyoruz.

    Bu barda zirve 280 görülüp stop 230'a çıkıyor, ama barın en düşüğü 240.
    Yeni seviye ancak BİR SONRAKİ bardan itibaren tetiklenebilir.
    """
    durum, olaylar = uygula(acik(), Bar(240.0, 280.0, 240.0, 275.0), CIZGI, TAKIP)
    assert olaylar == [] and durum.stop == pytest.approx(230.0)

    # Sonraki bar 230'un altına iniyor — şimdi satılır.
    _, olaylar = uygula(durum, Bar(235.0, 236.0, 229.0, 231.0), CIZGI, TAKIP)
    assert [(o.eylem, o.sebep) for o in olaylar] == [(SAT, SEBEP_TAKIP)]
    assert olaylar[0].fiyat == pytest.approx(230.0)


def test_takip_seviyesi_yalnizca_yukari_gider():
    takipte = Durum(acik=True, giris_fiyat=ALIS_SEVIYESI, stop=230.0,
                    takipte=True, zirve=280.0, mesafe=MESAFE)
    # Daha alçak bir zirve: seviye düşmez.
    durum, _ = uygula(takipte, Bar(250.0, 260.0, 245.0, 255.0), CIZGI, TAKIP)
    assert durum.zirve == pytest.approx(280.0)
    assert durum.stop == pytest.approx(230.0)

    # Yeni zirve: seviye yükselir.
    durum, _ = uygula(durum, Bar(255.0, 300.0, 252.0, 295.0), CIZGI, TAKIP)
    assert durum.zirve == pytest.approx(300.0)
    assert durum.stop == pytest.approx(250.0)


def test_takipteyken_tepe_cizgisine_bakilmaz():
    """Takip başladıktan sonra tepeye tekrar değmek bir şey değiştirmez."""
    takipte = Durum(acik=True, giris_fiyat=ALIS_SEVIYESI, stop=230.0,
                    takipte=True, zirve=280.0, mesafe=MESAFE)
    _, olaylar = uygula(takipte, Bar(255.0, 260.0, 252.0, 258.0), CIZGI, TAKIP)
    assert olaylar == []


# --------------------------------------------------------- KORUMA / STOP --

def test_zararina_satis_sebebi_stop_takipteyken_takip():
    bar = Bar(105.0, 106.0, 99.0, 101.0)
    _, olaylar = uygula(acik(), bar, CIZGI, TAKIP)
    assert olaylar[0].sebep == SEBEP_STOP

    takipte = Durum(acik=True, giris_fiyat=ALIS_SEVIYESI, stop=ZARAR_STOP,
                    takipte=True, zirve=150.0, mesafe=MESAFE)
    _, olaylar = uygula(takipte, bar, CIZGI, TAKIP)
    assert olaylar[0].sebep == SEBEP_TAKIP


def test_gece_boslugu_stopun_altindan_acilirsa_acilistan_satilir():
    """Stop 100'deyken 80'den açıldıysa 100'den değil 80'den satılır."""
    _, olaylar = uygula(acik(), Bar(80.0, 85.0, 78.0, 82.0), CIZGI, TAKIP)
    assert olaylar[0].fiyat == pytest.approx(80.0)


def test_ayni_barda_hem_stop_hem_tepe_gorulduyse_stop_kazanir():
    """Belirsizlikte aleyhimize olan seçilir."""
    _, olaylar = uygula(acik(), Bar(240.0, 280.0, 99.0, 275.0), CIZGI, TAKIP)
    assert [(o.eylem, o.sebep) for o in olaylar] == [(SAT, SEBEP_STOP)]


# ------------------------------------------------- ESKİ SÜRÜM (satis="tepe") --

def test_tepede_sat_surumu_tepe_cizgisinden_satar():
    _, olaylar = uygula(acik(), Bar(240.0, 260.0, 238.0, 255.0), CIZGI, TEPEDE_SAT)
    assert [(o.eylem, o.sebep) for o in olaylar] == [(SAT, SEBEP_TEPE)]
    assert olaylar[0].fiyat == pytest.approx(250.0)


def test_tepede_sat_surumu_tepenin_ustunde_acilirsa_acilistan_satar():
    _, olaylar = uygula(acik(), Bar(255.0, 260.0, 253.0, 258.0), CIZGI, TEPEDE_SAT)
    assert olaylar[0].fiyat == pytest.approx(255.0)


# ---------------------------------------------------------------- AYARLAR --

def test_gecersiz_ayar_reddedilir():
    with pytest.raises(ValueError, match="cizgi"):
        Kurallar(n=20, cizgi="kanal")
    with pytest.raises(ValueError, match="satis"):
        Kurallar(n=20, satis="ortalama")


def test_durum_degistirilemez_uygula_yeni_nesne_dondurur():
    """Durum frozen — motor yanlışlıkla geçmişi değiştiremez."""
    onceki = acik()
    sonraki, _ = uygula(onceki, Bar(240.0, 280.0, 238.0, 275.0), CIZGI, TAKIP)
    assert onceki.takipte is False        # girdi olduğu gibi duruyor
    assert sonraki is not onceki
