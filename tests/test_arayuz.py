"""Arayüz — testler. Ağ yok (FastAPI TestClient, broker çağrısı sahte).

Kritik özellikler:
* Komut göndermek anahtar ister; anahtarsız / yanlış anahtarla 401.
* Anahtar tanımlı değilse dış adresten komut reddedilir.
* /stop onaysız HİÇBİR ŞEY yapmaz; onaylı hali bayrak bırakır.
* Arayüz veritabanına YAZMAZ.
* Backtest katmanı kasa başlangıcında durur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.arayuz import sunucu, veri  # noqa: E402
from src.data.db import connect as veri_baglan, write_bars  # noqa: E402
from src.data.kasa import VAULT_BEGINS  # noqa: E402
from src.engine import durum as D  # noqa: E402
from src.engine import motor as M  # noqa: E402
from src.engine import saglik  # noqa: E402

ANAHTAR = "gizli-anahtar-123"


def _barlar() -> pd.DataFrame:
    """2024-04 → 2024-08 arası saatlik seans barları (kasa sınırını aşar)."""
    gunler = pd.bdate_range("2024-04-01", "2024-08-30", tz="UTC")
    ts = pd.DatetimeIndex([g + pd.Timedelta(hours=h) for g in gunler for h in range(13, 20)])
    rng = np.random.default_rng(1)
    kapanis = 180 + np.cumsum(rng.normal(0, 1, len(ts)))
    return pd.DataFrame({"timestamp": ts, "open": kapanis, "high": kapanis + 1.5,
                         "low": kapanis - 1.5, "close": kapanis, "volume": 1000,
                         "trade_count": 10, "vwap": kapanis})


@pytest.fixture()
def ayarlar(tmp_path):
    a = M.Ayarlar(paper_db=tmp_path / "paper.db", veri_db=tmp_path / "veri.db",
                  dur_dosyasi=tmp_path / "DUR", duraklat_dosyasi=tmp_path / "DURAKLAT",
                  kilit_dosyasi=tmp_path / "dongu.pid")
    with veri_baglan(a.veri_db) as c:
        write_bars(c, _barlar(), symbol="AAPL", timeframe="1Hour", adjustment="all")
    with D.connect(a.paper_db) as c:
        D.sinyal_yaz(c, bar_zamani="2024-08-29T18:00:00+0000", tepe=200.0, dip=180.0,
                     alis_seviyesi=182.0, zarar_stop=140.0, koruma=float("nan"),
                     durum=M.Durum())
        D.tur_yaz(c, baslangic_utc="2024-08-29T19:20:00+0000",
                  bitis_utc="2024-08-29T19:20:05+0000", sonuc="tamam", ozet="AAPL | nakitte")
    veri._onbellek.clear()
    return a


@pytest.fixture()
def istemci(ayarlar, tmp_path):
    ayar = sunucu.ArayuzAyar(motor=ayarlar, anahtar=ANAHTAR,
                             gunluk_dosyasi=tmp_path / "motor.log")
    return TestClient(sunucu.uygulama(ayar))


def komut(istemci, metin, anahtar=ANAHTAR):
    return istemci.post("/api/komut", json={"metin": metin},
                        headers={"X-Arayuz-Anahtari": anahtar} if anahtar is not None else {})


# ------------------------------------------------------------- GÖRÜNTÜLEME --

def test_ana_sayfa_ve_kutuphane_sunuluyor(istemci):
    assert "KABUL-1" in istemci.get("/").text
    r = istemci.get("/static/vendor/lightweight-charts.standalone.production.js")
    assert r.status_code == 200 and "Lightweight Charts" in r.text[:300]


def test_hisseler(istemci):
    (h,) = istemci.get("/api/hisseler").json()
    assert h["sembol"] == "AAPL" and h["motor"] and h["pozisyon"]["acik"] is False


def test_barlar_aralik(istemci):
    son60 = istemci.get("/api/barlar?sembol=AAPL&aralik=60g").json()
    butun = istemci.get("/api/barlar?sembol=AAPL&aralik=arastirma").json()
    assert 0 < len(son60["mumlar"])
    assert butun["son"] < VAULT_BEGINS                     # araştırma aralığı kasada biter
    m = son60["mumlar"][0]
    assert set(m) == {"time", "open", "high", "low", "close"}


def test_grafik_zamani_new_york_duvar_saati():
    """14:00 UTC (yaz) = 10:00 New York; eksende 10:00 görünmeli."""
    t = veri.grafik_zamani(pd.Series(pd.to_datetime(["2024-06-03T14:00:00Z"])))[0]
    assert pd.Timestamp(t, unit="s").hour == 10


def test_canli_katman_sinyali_bir_sonraki_bara_cizer(istemci):
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    noktalar = [p for p in c["cizgiler"]["tepe"] if "value" in p]
    assert {p["value"] for p in noktalar} == {200.0}
    # 18:00 UTC barından sonraki bar 19:00 UTC = 15:00 New York
    assert pd.Timestamp(noktalar[0]["time"], unit="s").hour == 15
    # Tek karar: yalnızca kendi barı boyunca çizilir — ardından boş nokta.
    tepe = c["cizgiler"]["tepe"]
    i = tepe.index(noktalar[0])
    assert len(noktalar) == 1 and "value" not in tepe[i + 1]
    assert all("value" not in p for p in c["cizgiler"]["zarar_stop"])   # pozisyon yok


def _sinyal(ayarlar, bar_zamani, tepe):
    with D.connect(ayarlar.paper_db) as c:
        D.sinyal_yaz(c, bar_zamani=bar_zamani, tepe=tepe, dip=180.0, alis_seviyesi=182.0,
                     zarar_stop=140.0, koruma=float("nan"), durum=M.Durum())


def test_gunun_son_barindaki_karar_ertesi_sabaha_cizilir(istemci, ayarlar):
    """15:00 NY barından sonra 16:00 mumu yok; karar ertesi 09:00'da geçerli.
    Eskiden +1 saatle 16:00'a çiziliyor, grafiğe boş sütun ekliyordu."""
    _sinyal(ayarlar, "2024-08-27T19:00:00+0000", 210.0)       # 15:00 NY
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    ilk = next(p for p in c["cizgiler"]["tepe"] if p.get("value") == 210.0)
    t = pd.Timestamp(ilk["time"], unit="s")
    assert (t.day, t.hour) == (28, 9)


def test_ardisik_olmayan_kararlarda_cizgi_kopar(istemci, ayarlar):
    """Motor 14:00'te ve 17:00'de çalıştı, arada çalışmadı: 14:00'ün seviyesi
    iki saat boyunca sabit görünmemeli."""
    _sinyal(ayarlar, "2024-08-27T14:00:00+0000", 210.0)
    _sinyal(ayarlar, "2024-08-27T17:00:00+0000", 220.0)
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    tepe = c["cizgiler"]["tepe"]
    i = next(k for k, p in enumerate(tepe) if p.get("value") == 210.0)
    saat = [pd.Timestamp(p["time"], unit="s").hour for p in tepe[i:i + 3]]
    assert saat == [11, 12, 14]                                  # NY saati
    assert [p.get("value") for p in tepe[i:i + 3]] == [210.0, None, 220.0]


def test_backtest_kasada_durur(istemci):
    b = istemci.get("/api/katman/backtest?sembol=AAPL&aralik=arastirma").json()
    zamanlar = [p["time"] for p in b["cizgiler"]["tepe"]]
    kasa = int(pd.Timestamp(VAULT_BEGINS).timestamp())   # duvar saati karşılaştırması
    assert zamanlar and max(zamanlar) < kasa
    assert b["ozet"]["son"] < VAULT_BEGINS
    son60 = istemci.get("/api/katman/backtest?sembol=AAPL&aralik=60g").json()
    assert all("value" not in p for p in son60["cizgiler"]["tepe"])   # son 60 gün kasada


def test_ozet(istemci, ayarlar):
    o = istemci.get("/api/ozet").json()
    assert o["son_tur"]["sonuc"] == "tamam" and o["dongu_ayakta"] is False
    ayarlar.duraklat_dosyasi.touch()
    assert istemci.get("/api/ozet").json()["duraklat"] is True


def test_saglik_ucu(istemci, monkeypatch):
    monkeypatch.setattr(saglik, "kontroller", lambda a: [
        saglik.Kontrol("broker", saglik.IYI, "bağlı"),
        saglik.Kontrol("koruyucu stop", saglik.KOTU, "YOK")])
    s = istemci.get("/api/saglik?taze=true").json()
    assert s["saglam"] is False and s["kontroller"][1]["seviye"] == "kotu"


def test_arayuz_veritabanina_yazmaz(istemci, ayarlar):
    ozet = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()   # noqa: E731
    once = (ozet(ayarlar.paper_db), ozet(ayarlar.veri_db))
    for yol in ("/api/hisseler", "/api/ozet", "/api/barlar?sembol=AAPL",
                "/api/katman/canli?sembol=AAPL", "/api/katman/backtest?sembol=AAPL&aralik=arastirma",
                "/api/gunluk"):
        assert istemci.get(yol).status_code == 200, yol
    komut(istemci, "/turlar")
    assert (ozet(ayarlar.paper_db), ozet(ayarlar.veri_db)) == once


def test_salt_okur_baglanti_yazmayi_reddeder(ayarlar):
    import sqlite3
    with veri.salt_okur(ayarlar.paper_db) as c:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM turlar")


# -------------------------------------------------------------- YETKİ --

def test_anahtarsiz_komut_401(istemci, ayarlar):
    assert komut(istemci, "/stop onayla", anahtar=None).status_code == 401
    assert not ayarlar.dur_dosyasi.exists()


def test_yanlis_anahtar_401(istemci, ayarlar):
    assert komut(istemci, "/stop onayla", anahtar="tahmin").status_code == 401
    assert not ayarlar.dur_dosyasi.exists()


def test_anahtar_tanimsizken_dis_adresten_komut_reddedilir(ayarlar, tmp_path):
    ayar = sunucu.ArayuzAyar(motor=ayarlar, anahtar=None, gunluk_dosyasi=tmp_path / "m.log")
    ist = TestClient(sunucu.uygulama(ayar))            # istemci adresi "testclient"
    assert komut(ist, "/duraklat", anahtar=None).status_code == 403
    assert not ayarlar.duraklat_dosyasi.exists()


# ------------------------------------------------------------ KOMUTLAR --

def test_stop_onaysiz_hicbir_sey_yapmaz(istemci, ayarlar):
    r = komut(istemci, "/stop").json()
    assert r["basarili"] is False and "onayla" in r["metin"]
    assert not ayarlar.dur_dosyasi.exists()


def test_stop_onayla_bayrak_birakir(istemci, ayarlar):
    r = komut(istemci, "/stop onayla").json()
    assert r["tehlikeli"] and ayarlar.dur_dosyasi.exists()
    bilgi = json.loads(ayarlar.dur_dosyasi.read_text(encoding="utf-8"))
    assert bilgi["komut"] == "/stop onayla" and bilgi["kaynak"] == "testclient"


def test_sifirla_onay_ister(istemci, ayarlar):
    komut(istemci, "/stop onayla")
    assert komut(istemci, "/sifirla").json()["basarili"] is False
    assert ayarlar.dur_dosyasi.exists()
    komut(istemci, "/sifirla onayla")
    assert not ayarlar.dur_dosyasi.exists()


def test_duraklat_devam(istemci, ayarlar):
    komut(istemci, "/duraklat")
    assert ayarlar.duraklat_dosyasi.exists()
    assert "Zaten" in komut(istemci, "/duraklat").json()["metin"]
    komut(istemci, "/devam")
    assert not ayarlar.duraklat_dosyasi.exists()


def test_bilinmeyen_komut_yardim_gosterir_bayrak_birakmaz(istemci, ayarlar):
    r = komut(istemci, "/sil_hepsini").json()
    assert r["basarili"] is False and "/durum" in r["metin"]
    assert not ayarlar.dur_dosyasi.exists() and not ayarlar.duraklat_dosyasi.exists()


def test_turlar_ve_gunluk(istemci, tmp_path):
    assert "tamam" in komut(istemci, "/turlar").json()["metin"]
    (tmp_path / "motor.log").write_text("satır bir\nsatır iki\n", encoding="utf-8")
    assert komut(istemci, "/gunluk 1").json()["metin"] == "satır iki"


def test_turkce_komut_adlari(istemci):
    assert "Komutlar" in komut(istemci, "/yardım").json()["metin"]



# ---------------------------------------------------------------- UYARILAR --

def _uyari_ekle(ayarlar):
    t0 = dt.datetime(2026, 9, 18, 14, 0, tzinfo=dt.timezone.utc)
    with D.connect(ayarlar.paper_db) as c:
        D.uyari_yaz(c, seviye=D.BILGI, anahtar="taban_konuldu",
                    konu="Alış gerçekleşti — 487 hisseye taban konuldu @ 100.00", simdi=t0)
        for dk in (1, 2):
            D.uyari_yaz(c, seviye=D.KOTU, anahtar="mutabakat",
                        konu="Hisse adedi tutmuyor: broker 1948, kayıt 487",
                        mesaj="Elle incelenmeli.", simdi=t0 + dt.timedelta(minutes=dk))


def test_uyarilar_ucu_en_yeni_once(istemci, ayarlar):
    _uyari_ekle(ayarlar)
    liste = istemci.get("/api/uyarilar").json()
    assert [u["seviye"] for u in liste] == ["kotu", "bilgi"]
    assert liste[0]["tekrar"] == 2 and liste[0]["mesaj"] == "Elle incelenmeli."


def test_uyarilar_tablo_yokken_bos(tmp_path):
    assert veri.son_uyarilar(tmp_path / "yok.db") == []


def test_uyarilar_komutu(istemci, ayarlar):
    assert komut(istemci, "/uyarilar").json()["metin"] == "Hiç uyarı yok."
    _uyari_ekle(ayarlar)
    r = komut(istemci, "/uyarılar").json()
    assert r["basarili"] is False                     # kötü uyarı var
    ilk, ikinci = r["metin"].splitlines()
    assert "KÖTÜ" in ilk and "(×2)" in ilk and "bilgi" in ikinci


def test_panelde_uyari_bolumu_var(istemci):
    assert 'id="uyari-listesi"' in istemci.get("/").text
