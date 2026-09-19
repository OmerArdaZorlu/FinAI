"""Arayüz — testler. Ağ yok (FastAPI TestClient, broker çağrısı sahte).

Kritik özellikler:
* Komut göndermek anahtar ister; anahtarsız / yanlış anahtarla 401.
* Anahtar tanımlı değilse dış adresten komut reddedilir.
* /flatten onaysız HİÇBİR ŞEY yapmaz; onaylı hali bayrak bırakır.
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


def _gunluk_barlar() -> pd.DataFrame:
    """Günlük barlar: damga 00:00 New York (= 04:00/05:00 UTC), seans dışı görünür."""
    gunler = pd.bdate_range("2024-04-01", "2024-08-30", tz="UTC") + pd.Timedelta(hours=4)
    kapanis = 180 + np.arange(len(gunler)) * 0.1
    return pd.DataFrame({"timestamp": gunler, "open": kapanis, "high": kapanis + 2,
                         "low": kapanis - 2, "close": kapanis, "volume": 5000,
                         "trade_count": 50, "vwap": kapanis})


def _dakikalik_barlar() -> pd.DataFrame:
    """Tek günün seans dakikaları (09:30–15:59 NY = 13:30–19:59 UTC)."""
    ts = pd.date_range("2024-08-30T13:30:00Z", "2024-08-30T19:59:00Z", freq="1min")
    kapanis = 200 + np.arange(len(ts)) * 0.01
    return pd.DataFrame({"timestamp": ts, "open": kapanis, "high": kapanis + 0.2,
                         "low": kapanis - 0.2, "close": kapanis, "volume": 10,
                         "trade_count": 1, "vwap": kapanis})


@pytest.fixture()
def ayarlar(tmp_path):
    a = M.Ayarlar(paper_db=tmp_path / "paper.db", veri_db=tmp_path / "veri.db",
                  dur_dosyasi=tmp_path / "DUR", duraklat_dosyasi=tmp_path / "DURAKLAT",
                  kilit_dosyasi=tmp_path / "dongu.pid")
    with veri_baglan(a.veri_db) as c:
        write_bars(c, _barlar(), symbol="AAPL", timeframe="1Hour", adjustment="all")
        write_bars(c, _gunluk_barlar(), symbol="AAPL", timeframe="1Day", adjustment="all")
        write_bars(c, _dakikalik_barlar(), symbol="AAPL", timeframe="1Min", adjustment="all")
    with D.connect(a.paper_db) as c:
        D.sinyal_yaz(c, bar_zamani="2024-08-29T18:00:00+0000", tepe=200.0, dip=180.0,
                     alis_seviyesi=182.0, zarar_stop=140.0, koruma=float("nan"),
                     durum=M.Durum())
        D.tur_yaz(c, baslangic_utc="2024-08-29T19:20:00+0000",
                  bitis_utc="2024-08-29T19:20:05+0000", sonuc="tamam", ozet="AAPL | nakitte")
    veri._onbellek.clear()
    return a


class SahteBroker:
    """Alpaca'nın ham JSON'unu döndürür; kaç kez çağrıldığını sayar."""

    def __init__(self):
        self.cagri = 0
        self.hata: Exception | None = None

    def _say(self):
        self.cagri += 1
        if self.hata:
            raise self.hata

    def pozisyonlar(self):
        self._say()
        return [{"symbol": "AAPL", "asset_class": "us_equity", "side": "long", "qty": "326",
                 "avg_entry_price": "306.27", "current_price": "320.5", "market_value": "104483",
                 "unrealized_pl": "4638.98", "unrealized_plpc": "0.04646"},
                {"symbol": "BTC/USD", "asset_class": "crypto", "side": "long", "qty": "0.5",
                 "avg_entry_price": "60000", "current_price": "58000", "market_value": "29000",
                 "unrealized_pl": "-1000", "unrealized_plpc": "-0.0333"}]

    def emir_gecmisi(self, durum="all", adet=200):
        self._say()
        return [{"symbol": "AAPL", "asset_class": "us_equity", "type": "limit", "limit_price": "306.27",
                 "stop_price": None, "side": "buy", "qty": "326", "filled_qty": "0",
                 "filled_avg_price": None, "status": "canceled",
                 "submitted_at": "2026-09-15T16:12:46Z", "client_order_id": "limit_al-X"}]


@pytest.fixture()
def sahte_broker():
    return SahteBroker()


@pytest.fixture()
def istemci(ayarlar, tmp_path, sahte_broker):
    ayar = sunucu.ArayuzAyar(motor=ayarlar, anahtar=ANAHTAR,
                             gunluk_dosyasi=tmp_path / "motor.log",
                             broker_fn=lambda: sahte_broker)
    return TestClient(sunucu.uygulama(ayar))


def komut(istemci, metin, anahtar=ANAHTAR):
    return istemci.post("/api/komut", json={"metin": metin},
                        headers={"X-Arayuz-Anahtari": anahtar} if anahtar is not None else {})


# ------------------------------------------------------------- GÖRÜNTÜLEME --

def test_ana_sayfa_ve_kutuphane_sunuluyor(istemci):
    assert "KABUL-1" in istemci.get("/").text
    r = istemci.get("/static/vendor/lightweight-charts.standalone.production.js")
    assert r.status_code == 200 and "Lightweight Charts" in r.text[:300]


def test_izleme(istemci):
    (h,) = istemci.get("/api/izleme").json()
    assert h["sembol"] == "AAPL" and h["motor"] and h["sinif"] == "Stocks"
    df = _barlar()
    gun = df["timestamp"].dt.tz_convert("America/New_York").dt.date
    onceki = df["close"][gun < gun.iloc[-1]].iloc[-1]
    assert h["fiyat"] == pytest.approx(df["close"].iloc[-1], abs=1e-3)
    assert h["degisim"] == pytest.approx((df["close"].iloc[-1] / onceki - 1) * 100, abs=1e-3)


def test_pozisyonlar_alpacadan(istemci):
    p = istemci.get("/api/pozisyonlar").json()
    assert p["hata"] is None
    aapl, btc = p["satirlar"]
    assert (aapl["sembol"], aapl["sinif"], aapl["yon"], aapl["adet"]) == ("AAPL", "Stocks", "Long", 326)
    assert aapl["kz"] == pytest.approx(4638.98) and aapl["kz_yuzde"] == pytest.approx(4.65)
    assert btc["sinif"] == "Crypto" and btc["kz"] < 0


def test_emirler_alpacadan(istemci):
    (e,) = istemci.get("/api/emirler").json()["satirlar"]
    assert (e["sembol"], e["tip"], e["limit"], e["yon"], e["durum"]) == ("AAPL", "limit", 306.27, "buy", "canceled")
    assert e["dolan"] == 0 and e["dolan_fiyat"] is None


def test_broker_tablolari_onbellekli(istemci, sahte_broker):
    istemci.get("/api/emirler")
    istemci.get("/api/emirler")
    assert sahte_broker.cagri == 1


def test_alpacaya_ulasilamazsa_panel_calisir(istemci, sahte_broker):
    sahte_broker.hata = RuntimeError("ağ hatası: bağlantı reddedildi")
    r = istemci.get("/api/pozisyonlar")
    assert r.status_code == 200
    assert r.json() == {"satirlar": [], "hata": "ağ hatası: bağlantı reddedildi"}


def test_kapsam(istemci):
    k = istemci.get("/api/kapsam?sembol=AAPL").json()
    b = istemci.get("/api/barlar?sembol=AAPL").json()
    assert (k["ilk"], k["son"]) == (b["time"][0], b["time"][-1])
    assert k["kasa"] == int(pd.Timestamp(VAULT_BEGINS).timestamp())
    assert k["son_iso"].startswith("2024-08-30")


def test_barlar_pencere_sutunlu(istemci):
    tum = istemci.get("/api/barlar?sembol=AAPL").json()
    assert len({len(tum[k]) for k in ("time", "open", "high", "low", "close")}) == 1
    assert len(tum["time"]) == len(_barlar()) and tum["time"] == sorted(tum["time"])
    bas, bit = tum["time"][100], tum["time"][200]
    b = istemci.get(f"/api/barlar?sembol=AAPL&bas={bas}&bit={bit}").json()
    assert b["time"] == tum["time"][100:200]                  # bas dahil, bit hariç


def test_ardisik_pencereler_delik_ve_cift_birakmaz(istemci):
    """Panel sola doğru [a,b) + [b,c) ister; birleşim [a,c) ile aynı olmalı."""
    tum = istemci.get("/api/barlar?sembol=AAPL").json()["time"]
    a, b = tum[50], tum[300] + 1800                           # b bir bar zamanına denk gelmese de
    sol = istemci.get(f"/api/barlar?sembol=AAPL&bas={a}&bit={b}").json()["time"]
    sag = istemci.get(f"/api/barlar?sembol=AAPL&bas={b}").json()["time"]
    assert sol + sag == tum[50:]


def test_yapilandirma_surum(istemci):
    from src.arayuz import sunucu as S
    y = istemci.get("/api/yapilandirma").json()
    assert y["surum"] == S.ARAYUZ_SURUMU
    assert y["siniflar"][:4] == ["Stocks", "ETFs", "Commodities", "Crypto"]
    assert y["araliklar"] == ["1Min", "1Hour", "1Day"]


def test_gunluk_barlar_seans_filtresinden_gecmez(istemci):
    """Günlük barın damgası 00:00 NY; seans filtresi uygulanırsa hepsi elenir."""
    g = istemci.get("/api/barlar?sembol=AAPL&tf=1Day").json()
    assert len(g["time"]) == len(_gunluk_barlar()) and g["tf"] == "1Day"
    assert pd.Timestamp(g["time"][0], unit="s").hour == 0          # NY duvar saati


def test_dakikalik_pencere_sqlden_okunur(istemci):
    tam = istemci.get("/api/barlar?sembol=AAPL&tf=1Min").json()
    assert len(tam["time"]) == len(_dakikalik_barlar())
    bas, bit = tam["time"][60], tam["time"][120]
    d = istemci.get(f"/api/barlar?sembol=AAPL&tf=1Min&bas={bas}&bit={bit}").json()
    assert d["time"] == tam["time"][60:120]
    # Dakikalık önbelleğe alınmaz — tablo hiç okunmadan sınırlar bulunmalı
    k = istemci.get("/api/kapsam?sembol=AAPL&tf=1Min").json()
    assert (k["ilk"], k["son"]) == (tam["time"][0], tam["time"][-1])
    assert k["araliklar"] == ["1Min", "1Hour", "1Day"]


def test_mumlarda_hacim_var(istemci):
    b = istemci.get("/api/barlar?sembol=AAPL").json()
    assert len(b["volume"]) == len(b["time"]) and b["volume"][0] == 1000


def test_bilinmeyen_bar_araligi_400(istemci):
    assert istemci.get("/api/barlar?sembol=AAPL&tf=5Min").status_code == 400
    assert istemci.get("/api/kapsam?sembol=AAPL&tf=haftalik").status_code == 400


def test_grafik_zamani_new_york_duvar_saati():
    """14:00 UTC (yaz) = 10:00 New York; eksende 10:00 görünmeli."""
    t = veri.grafik_zamani(pd.Series(pd.to_datetime(["2024-06-03T14:00:00Z"])))[0]
    assert pd.Timestamp(t, unit="s").hour == 10


def test_canli_katman_sinyali_bir_sonraki_bara_cizer(istemci):
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    noktalar = [p for p in c["cizgiler"]["tepe"] if p.get("value") == 200.0]
    assert len(noktalar) == 1
    # 18:00 UTC barından sonraki bar 19:00 UTC = 15:00 New York
    assert pd.Timestamp(noktalar[0]["time"], unit="s").hour == 15
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


def _seviye_beklenen(sira: int) -> tuple[float, float, float]:
    """sira'ncı seans barında geçerli tepe / dip / alış — elle, önceki 140 bar."""
    df = _barlar()
    w = df.iloc[sira - M.KURALLAR_KABUL1.n:sira]
    tepe, dip = w["high"].max(), w["low"].min()
    return tepe, dip, dip + M.KURALLAR_KABUL1.alim_payi * (tepe - dip)


def test_motor_calismayan_barlarda_cizgi_hesaplanir(istemci, ayarlar):
    """Motor 14:00'te ve 17:00'de çalıştı, arada çalışmadı: aradaki barlarda
    tepe / dip / alış bar verisinden hesaplanır, çizgi kopmaz."""
    _sinyal(ayarlar, "2024-08-27T14:00:00+0000", 210.0)
    _sinyal(ayarlar, "2024-08-27T17:00:00+0000", 220.0)
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    tepe = c["cizgiler"]["tepe"]
    i = next(k for k, p in enumerate(tepe) if p.get("value") == 210.0)
    saat = [pd.Timestamp(p["time"], unit="s").hour for p in tepe[i:i + 4]]
    assert saat == [11, 12, 13, 14]                              # NY saati, her bar
    assert tepe[i + 3]["value"] == 220.0                         # motorun değeri
    assert all("value" in p for p in tepe[i:])                   # sona kadar kopmaz

    # Aradaki 12:00 NY barı (16:00 UTC) elle hesapla aynı
    df = _barlar()
    sira = int(df["timestamp"].searchsorted(pd.Timestamp("2024-08-27T16:00:00Z")))
    beklenen = _seviye_beklenen(sira)
    for ad, b in zip(("tepe", "dip", "alis"), beklenen):
        assert c["cizgiler"][ad][i + 1]["value"] == pytest.approx(b, abs=1e-3)


def test_pozisyon_varken_stop_sonraki_karara_kadar_surer(istemci, ayarlar):
    with D.connect(ayarlar.paper_db) as conn:
        D.sinyal_yaz(conn, bar_zamani="2024-08-27T14:00:00+0000", tepe=210.0, dip=180.0,
                     alis_seviyesi=float("nan"), zarar_stop=float("nan"), koruma=150.0,
                     durum=M.Durum(acik=True, giris_fiyat=185.0, stop=150.0))
    c = istemci.get("/api/katman/canli?sembol=AAPL&aralik=60g").json()
    zs = c["cizgiler"]["zarar_stop"]
    i = next(k for k, p in enumerate(zs) if p.get("value") == 150.0)
    # Sonraki karar (fikstürdeki 29 Ağustos, pozisyonsuz) gelene kadar 150'de
    t_sonraki = veri.grafik_zamani(pd.Series(pd.to_datetime(["2024-08-29T19:00:00Z"])))[0]
    arada = [p for p in zs[i:] if p["time"] < t_sonraki]
    assert len(arada) > 5 and all(p.get("value") == 150.0 for p in arada)
    assert all("value" not in p for p in zs if p["time"] >= t_sonraki)
    alis = c["cizgiler"]["alis"]
    assert all("value" not in p for p in alis if p["time"] < t_sonraki and p["time"] >= zs[i]["time"])


def test_backtest_kasada_durur(istemci):
    b = istemci.get("/api/katman/backtest?sembol=AAPL").json()
    zamanlar = b["cizgiler"]["tepe"]["time"]
    kasa = int(pd.Timestamp(VAULT_BEGINS).timestamp())   # duvar saati karşılaştırması
    assert zamanlar and max(zamanlar) < kasa
    assert len(b["cizgiler"]["tepe"]["value"]) == len(zamanlar)
    assert b["ozet"]["son"] < VAULT_BEGINS
    sonrasi = istemci.get(f"/api/katman/backtest?sembol=AAPL&bas={kasa}").json()
    assert sonrasi["cizgiler"]["tepe"]["time"] == []


def test_backtest_pencereleri_birlesince_tami(istemci):
    tam = istemci.get("/api/katman/backtest?sembol=AAPL").json()
    t = tam["cizgiler"]["dip"]["time"]
    orta = t[len(t) // 2]
    sol = istemci.get(f"/api/katman/backtest?sembol=AAPL&bit={orta}").json()
    sag = istemci.get(f"/api/katman/backtest?sembol=AAPL&bas={orta}").json()
    for ad in ("dip", "zarar_stop"):
        assert sol["cizgiler"][ad]["time"] + sag["cizgiler"][ad]["time"] == tam["cizgiler"][ad]["time"]
        assert sol["cizgiler"][ad]["value"] + sag["cizgiler"][ad]["value"] == tam["cizgiler"][ad]["value"]
    assert sol["islemler"] + sag["islemler"] == tam["islemler"]


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
    for yol in ("/api/izleme", "/api/pozisyonlar", "/api/emirler", "/api/ozet", "/api/barlar?sembol=AAPL",
                "/api/katman/canli?sembol=AAPL", "/api/katman/backtest?sembol=AAPL",
                "/api/kapsam?sembol=AAPL", "/api/barlar?sembol=AAPL&bas=0&bit=9999999999",
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

def test_flatten_onaysiz_hicbir_sey_yapmaz(istemci, ayarlar):
    r = komut(istemci, "/flatten").json()
    assert r["basarili"] is False and "confirm" in r["metin"]
    assert not ayarlar.dur_dosyasi.exists()


def test_flatten_confirm_bayrak_birakir(istemci, ayarlar):
    r = komut(istemci, "/flatten confirm").json()
    assert r["tehlikeli"] and ayarlar.dur_dosyasi.exists()
    bilgi = json.loads(ayarlar.dur_dosyasi.read_text(encoding="utf-8"))
    assert bilgi["komut"] == "/flatten confirm" and bilgi["kaynak"] == "testclient"


def test_unhalt_onay_ister(istemci, ayarlar):
    komut(istemci, "/flatten confirm")
    assert komut(istemci, "/unhalt").json()["basarili"] is False
    assert ayarlar.dur_dosyasi.exists()
    komut(istemci, "/unhalt confirm")
    assert not ayarlar.dur_dosyasi.exists()


def test_pause_resume(istemci, ayarlar):
    komut(istemci, "/pause")
    assert ayarlar.duraklat_dosyasi.exists()
    assert "Already paused" in komut(istemci, "/pause").json()["metin"]
    komut(istemci, "/resume")
    assert not ayarlar.duraklat_dosyasi.exists()


def test_bilinmeyen_komut_yardim_gosterir_bayrak_birakmaz(istemci, ayarlar):
    r = komut(istemci, "/sil_hepsini").json()
    assert r["basarili"] is False and "/status" in r["metin"]
    assert not ayarlar.dur_dosyasi.exists() and not ayarlar.duraklat_dosyasi.exists()


def test_runs_ve_log(istemci, tmp_path):
    assert "tamam" in komut(istemci, "/runs").json()["metin"]
    (tmp_path / "motor.log").write_text("satır bir\nsatır iki\n", encoding="utf-8")
    assert komut(istemci, "/log 1").json()["metin"] == "satır iki"


def test_eski_turkce_adlar_takma_ad_olarak_calisir(istemci, ayarlar):
    """Kas hafızası bozulmasın: eski adlar yeni komuta yönlenir."""
    assert "Commands" in komut(istemci, "/yardım").json()["metin"]
    assert "tamam" in komut(istemci, "/turlar").json()["metin"]
    komut(istemci, "/stop onayla")                       # eski ad + eski onay sözcüğü
    assert ayarlar.dur_dosyasi.exists()
    komut(istemci, "/sifirla onayla")
    assert not ayarlar.dur_dosyasi.exists()



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


def test_alerts_komutu(istemci, ayarlar):
    assert komut(istemci, "/alerts").json()["metin"] == "No alerts."
    _uyari_ekle(ayarlar)
    r = komut(istemci, "/uyarılar").json()             # eski ad da çalışır
    assert r["basarili"] is False                     # kötü uyarı var
    ilk, ikinci = r["metin"].splitlines()
    assert "CRIT" in ilk and "(×2)" in ilk and "info" in ikinci


def test_panelde_uyari_bolumu_var(istemci):
    assert 'id="uyari-listesi"' in istemci.get("/").text


# ------------------------------------------------------- EKLEMELİ YÜKLEME --

def test_ozet_isaretleri_degisince_degisir(istemci, ayarlar):
    ilk = istemci.get("/api/ozet?sembol=AAPL").json()["isaretler"]
    assert ilk["son_bar"] == "2024-08-30T19:00:00+0000" and ilk["tam_yenileme"] is None
    assert istemci.get("/api/ozet?sembol=AAPL").json()["isaretler"] == ilk   # değişiklik yok

    _sinyal(ayarlar, "2024-08-30T13:00:00+0000", 205.0)
    yeni_bar = _barlar().iloc[[-1]].assign(timestamp=pd.Timestamp("2024-09-03 13:00", tz="UTC"))
    with veri_baglan(ayarlar.veri_db) as c:
        write_bars(c, yeni_bar, symbol="AAPL", timeframe="1Hour", adjustment="all")
        c.execute("INSERT INTO ingest_log (symbol, timeframe, adjustment, feed, requested_start, "
                  "requested_end, actual_start, actual_end, rows_fetched, rows_written, source, "
                  "fetched_at_utc) VALUES ('AAPL','1Hour','all','sip','a','b','c','d',1,1,"
                  "'senkron.tam','e')")
    son = istemci.get("/api/ozet?sembol=AAPL").json()["isaretler"]
    assert son["son_bar"] == "2024-09-03T13:00:00+0000"
    assert son["son_sinyal"] == ilk["son_sinyal"] + 1
    assert son["tam_yenileme"] is not None


def test_barlar_sonra_yalnizca_yenileri_verir_ve_birlesince_ayni(istemci):
    tam = istemci.get("/api/barlar?sembol=AAPL").json()
    kesim = tam["time"][-10]
    yeni = istemci.get(f"/api/barlar?sembol=AAPL&sonra={kesim}").json()
    assert len(yeni["time"]) == 9 and all(t > kesim for t in yeni["time"])
    for k in ("time", "open", "close"):
        assert [v for t, v in zip(tam["time"], tam[k]) if t <= kesim] + yeni[k] == tam[k]


def test_bar_tablosu_onbellekten_dosya_degisince_yeniden(ayarlar, monkeypatch):
    okuma = []
    gercek = veri._barlari_oku
    monkeypatch.setattr(veri, "_barlari_oku",
                        lambda y, s, tf: okuma.append(1) or gercek(y, s, tf))
    veri._bar_onbellek.clear()
    veri._seans_barlari(ayarlar.veri_db, "AAPL")
    veri._seans_barlari(ayarlar.veri_db, "AAPL")
    assert len(okuma) == 1
    import os, time
    t = time.time() + 5
    os.utime(ayarlar.veri_db, (t, t))
    veri._seans_barlari(ayarlar.veri_db, "AAPL")
    assert len(okuma) == 2
    veri._seans_barlari(ayarlar.veri_db, "AAPL", "1Day")       # aralık başına ayrı tablo
    assert len(okuma) == 3


def test_izleme_indeksle_dogru(ayarlar):
    with veri_baglan(ayarlar.veri_db) as c:
        write_bars(c, _barlar().iloc[:20], symbol="MSFT", timeframe="1Hour", adjustment="all")
        write_bars(c, _barlar().iloc[:5].assign(timestamp=pd.date_range(
            "2025-01-02", periods=5, freq="D", tz="UTC")), symbol="SPY", timeframe="1Day",
            adjustment="all")
    h = veri.izleme(ayarlar.veri_db, "AAPL")
    assert [x["sembol"] for x in h] == ["AAPL", "MSFT"]          # SPY'nin saatliği yok
    assert h[0]["son_bar"] == "2024-08-30T19:00:00+0000"
    assert h[1]["son_bar"] == _barlar()["timestamp"].iloc[19].strftime("%Y-%m-%dT%H:%M:%S+0000")


def test_buyuk_yanit_sikistirilir(istemci):
    r = istemci.get("/api/barlar?sembol=AAPL",
                    headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
