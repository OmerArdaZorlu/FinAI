"""Alarm (e-posta) — testler. Ağ yok: gönderici sahte.

Kritik iki özellik:
* Aynı sorun sessizlik penceresinde tekrar e-posta atmaz.
* SMTP patlarsa istisna yukarı ÇIKMAZ — alarm gönderememek işlemi durdurmamalı.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import alarm  # noqa: E402
from src.engine import durum as D  # noqa: E402

UTC = dt.timezone.utc
AYAR = alarm.SmtpAyar("smtp.ornek", 587, "gonderen@ornek", "sifre", "alici@ornek")


class SahteGonderici:
    def __init__(self, hata: Exception | None = None):
        self.giden = []
        self.hata = hata

    def __call__(self, ileti, ayar):
        if self.hata:
            raise self.hata
        self.giden.append(ileti)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "paper.db"


def gonder(db, gonderici, **kw):
    varsayilan = dict(anahtar="test", paper_db=db, ayar=AYAR, gonderici=gonderici)
    return alarm.gonder("konu", "gövde", **{**varsayilan, **kw})


def test_gonderilir_ve_konu_onekli(db):
    g = SahteGonderici()
    assert gonder(db, g)
    (ileti,) = g.giden
    assert ileti["Subject"].startswith(alarm.KONU_ONEKI)
    assert ileti["To"] == "alici@ornek"


def test_ayni_anahtar_sessizlikte_tekrar_gitmez(db):
    g = SahteGonderici()
    simdi = dt.datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    assert gonder(db, g, simdi=simdi)
    assert not gonder(db, g, simdi=simdi + dt.timedelta(hours=5))
    assert len(g.giden) == 1


def test_sessizlik_dolunca_yeniden_gider(db):
    g = SahteGonderici()
    simdi = dt.datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    gonder(db, g, simdi=simdi)
    assert gonder(db, g, simdi=simdi + dt.timedelta(hours=6, minutes=1))
    assert len(g.giden) == 2


def test_farkli_anahtar_birbirini_susturmaz(db):
    g = SahteGonderici()
    assert gonder(db, g, anahtar="a")
    assert gonder(db, g, anahtar="b")


def test_smtp_patlarsa_istisna_cikmaz_ve_isaretlenmez(db):
    """Gönderilemeyen alarm 'gönderildi' sayılmamalı — bir sonraki denemede gitsin."""
    assert not gonder(db, SahteGonderici(hata=OSError("bağlantı reddedildi")))
    g = SahteGonderici()
    assert gonder(db, g)


def test_ayar_yoksa_sessizce_devre_disi(db, monkeypatch):
    monkeypatch.setattr(alarm, "ayar_oku", lambda *a, **k: None)
    g = SahteGonderici()
    assert not alarm.gonder("k", "g", anahtar="x", paper_db=db, gonderici=g)
    assert g.giden == []


def test_ayar_oku_eksik_alanda_none(tmp_path, monkeypatch):
    for k in ("SMTP_SUNUCU", "SMTP_PORT", "SMTP_KULLANICI", "SMTP_SIFRE", "ALARM_ALICI"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("SMTP_SUNUCU=smtp.x\nSMTP_PORT=587\n", encoding="utf-8")
    assert alarm.ayar_oku(env) is None


def test_ayar_oku_tam(tmp_path, monkeypatch):
    for k in ("SMTP_SUNUCU", "SMTP_PORT", "SMTP_KULLANICI", "SMTP_SIFRE", "ALARM_ALICI"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("SMTP_SUNUCU=smtp.x\nSMTP_PORT=465\nSMTP_KULLANICI=a@x\n"
                   "SMTP_SIFRE=s\nALARM_ALICI=b@x\n", encoding="utf-8")
    ayar = alarm.ayar_oku(env)
    assert ayar == alarm.SmtpAyar("smtp.x", 465, "a@x", "s", "b@x")


# ------------------------------------------------------------ bildirimler --

def _gerceklesme(db, kimlik, tip="limit_al"):
    with D.connect(db) as c:
        D.gerceklesme_yaz(c, client_order_id=kimlik, bar_zamani="2026-09-18T14:00:00+0000",
                          tip=tip, istenen_seviye=309.93, gerceklesen_fiyat=309.90, adet=322)


def test_her_islem_bir_kez_bildirilir(db):
    g = SahteGonderici()
    _gerceklesme(db, "limit_al-1")
    assert alarm.islemleri_bildir(db, ayar=AYAR, gonderici=g) == 1
    assert alarm.islemleri_bildir(db, ayar=AYAR, gonderici=g) == 0
    _gerceklesme(db, "stop_sat-2", tip="stop_sat")
    assert alarm.islemleri_bildir(db, ayar=AYAR, gonderici=g) == 1
    assert [i["Subject"].split()[2] for i in g.giden] == ["ALIŞ", "SATIŞ"]


def test_gunluk_ozet_kapanistan_once_gitmez(db):
    g = SahteGonderici()
    oglen_ny = dt.datetime(2026, 9, 18, 16, 0, tzinfo=UTC)      # 12:00 New York
    assert not alarm.gunluk_ozet_gonder(db, simdi=oglen_ny, ayar=AYAR, gonderici=g)
    assert g.giden == []


def test_gunluk_ozet_gunde_bir_kez(db):
    g = SahteGonderici()
    aksam = dt.datetime(2026, 9, 18, 20, 30, tzinfo=UTC)        # 16:30 New York
    assert alarm.gunluk_ozet_gonder(db, simdi=aksam, ayar=AYAR, gonderici=g)
    assert not alarm.gunluk_ozet_gonder(db, simdi=aksam + dt.timedelta(hours=2),
                                        ayar=AYAR, gonderici=g)
    ertesi = aksam + dt.timedelta(days=1)
    assert alarm.gunluk_ozet_gonder(db, simdi=ertesi, ayar=AYAR, gonderici=g)
    assert len(g.giden) == 2
    assert "Gelmediği gün" in g.giden[0].get_content()


def test_saglik_bildir_yalnizca_kotuler(db):
    from src.engine.saglik import IYI, KOTU, UYARI, Kontrol
    g = SahteGonderici()
    sonuclar = [Kontrol("a", IYI, "tamam"), Kontrol("b", UYARI, "dikkat"),
                Kontrol("c", KOTU, "bozuk")]
    assert alarm.saglik_bildir(sonuclar, paper_db=db, ayar=AYAR, gonderici=g) == 1
    assert "c" in g.giden[0]["Subject"]


# -------------------------------------------------------------- uyarı tablosu --

def _uyarilar(db):
    with D.connect(db) as c:
        return [dict(r) for r in D.son_uyarilar(c)]


def test_sorun_alarmi_eposta_ayarsizken_de_tabloya_yazilir(db, monkeypatch):
    monkeypatch.setattr(alarm, "ayar_oku", lambda *a, **k: None)
    alarm.gonder("MOTOR DURDU", "ayrıntı", anahtar="tur_durdu", paper_db=db)
    (u,) = _uyarilar(db)
    assert u["konu"] == "MOTOR DURDU" and u["seviye"] == D.KOTU and u["mesaj"] == "ayrıntı"


def test_susturulan_alarm_da_tabloya_yazilir(db):
    g = SahteGonderici()
    simdi = dt.datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    gonder(db, g, simdi=simdi)
    gonder(db, g, simdi=simdi + dt.timedelta(hours=1))        # e-posta susturuldu
    (u,) = _uyarilar(db)
    assert len(g.giden) == 1 and u["tekrar"] == 2


def test_islem_bildirimi_ve_gunluk_ozet_tabloya_yazilmaz(db):
    g = SahteGonderici()
    _gerceklesme(db, "limit_al-1")
    alarm.islemleri_bildir(db, ayar=AYAR, gonderici=g)
    alarm.gunluk_ozet_gonder(db, simdi=dt.datetime(2026, 9, 18, 21, 0, tzinfo=UTC),
                             ayar=AYAR, gonderici=g)
    assert len(g.giden) == 2 and _uyarilar(db) == []


def test_tablo_yazilamasa_da_alarm_patlamaz(tmp_path):
    klasor_db = tmp_path / "klasor"
    klasor_db.mkdir()                                # dosya değil klasör: açılamaz
    assert gonder(klasor_db, SahteGonderici()) is False
