"""Destek-direnç aralığında al-sat — geçmiş veride deneme (backtest).

Kurallar burada DEĞİL
---------------------
Al-sat kurallarının tek kopyası `src/engine/kural.py`'dedir; canlı motor da
aynı fonksiyonu çağırır (TECH_DEBT.md TD-01). Bu dosya kalan işi yapar:
çizgileri hesaplar, barları sırayla o fonksiyona verir, para/hisse muhasebesini
tutar ve eğitim/test düzenini kurar. Kuralı değiştirmek isteyen `kural.py`'ye
gider — burada değiştirilirse canlı sistem backtest'ten ayrışır.

Sistem
------
* **Tepe çizgisi (direnç):** son N barın en yüksek fiyatı.
* **Dip çizgisi (destek):** son N barın en düşük fiyatı.
* **Al:** fiyat dip çizgisine yaklaşınca — dipten, kanal genişliğinin
  `alim_payi` kadar yukarısına kadar inerse.
* **Sat:** fiyat tepe çizgisine değince, tam çizgide.
* **Zararına sat (stop):** fiyat, alırken beklenen dibin çok altına inerse.
  "Çok altı" = alış anındaki dip çizgisinin, kanal genişliğinin `stop_payi`
  kadar aşağısı. Stop seviyesi alışta sabitlenir, sonra değişmez.

Örnek (`alim_payi=0.10`, `stop_payi=0.50`): tepe 510, dip 500, genişlik 10.
    alış seviyesi 501 · satış seviyesi 510 (her bar güncellenir) · stop 495

Seçenekler (2026-09-11 eklendi, varsayılan eski sistem)
-------------------------------------------------------
* `cizgi="bollinger"`: çizgiler son n kapanışın ortalamasının k sapma
  üstünden ve altından geçer. Fiyat yükselince bant da yükselir.
* `satis="takip"`: tepeye değince satılmaz, **takip eden stop** devreye
  girer. O andan sonra görülen en yüksek fiyattan `takip_payi` × genişlik
  kadar düşerse satılır. Seviye yalnızca yukarı gider.
  Örnek: genişlik 10, `takip_payi=0.50` → mesafe 5. Fiyat 510'a değer
  (satış 505), 520'ye çıkar (satış 515), 514'e iner → 515'ten satılır.

Sızıntı kuralı
--------------
Çizgiler **yalnızca önceki barlardan** hesaplanır (bugünkü bar hariç).
Bugünün en yükseği tepe çizgisine dahil edilseydi, fiyat her yeni zirvede
"tepeye değmiş" sayılırdı — çizgi fiyatı kovalar, gerçekte verilemeyecek
emirler dolar. `lab/h001.py`'deki kanal konumu bugünü de sayar; o bir
ölçümdür, emir seviyesi değildir. Burada fark bilerek yapıldı.

Bar içi varsayımlar (hepsi aleyhimize)
--------------------------------------
Bir barın yalnızca açılış/en yüksek/en düşük/kapanışını biliyoruz, bar
içinde hangisinin önce olduğunu bilmiyoruz. Belirsiz her durumda kötü olan
seçilir:

* Aynı barda hem stop hem tepe görüldüyse **önce stop** olmuş sayılır.
* Alış yapılan barda tepeye değse bile satılmaz; stop'a değerse satılır.
* Fiyat seviyenin ötesinde **açıldıysa** (gece boşluğu) işlem açılış
  fiyatından yapılır. Stop 495'teyken sabah 480'den açılırsa 480'den satılır.
* Açılış zaten stop seviyesinin altındaysa alış yapılmaz.

Diğer varsayımlar
-----------------
* Her alışta paranın tamamı kullanılır, borç (kaldıraç) yok.
* Pozisyon yokken para faiz getirmez.
* Maliyet her alışta ve her satışta ayrı ayrı `maliyet` oranında ödenir
  (spread + kayma). Sonuç maliyetli **ve** maliyetsiz raporlanır
  (TECH_DEBT.md TD-11).
* Dönem sonunda açık pozisyon son kapanıştan kapatılır.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.engine.kural import (
    AL,
    SEBEP_DONEM_SONU,
    Bar,
    Cizgi,
    Durum,
    Kurallar,
    emir_seviyeleri,
    uygula,
)

__all__ = [
    "Kurallar", "Sonuc", "cizgiler", "bollinger_cizgiler", "calistir",
    "en_buyuk_dusus", "ozet", "egitim_test", "egitim_test_detay",
    "zincirle", "al_tut",
]


@dataclass(frozen=True)
class Sonuc:
    """Denemenin çıktısı."""

    islemler: pd.DataFrame    # her al-sat bir satır
    bakiye: pd.Series         # her bar sonunda paranın değeri (1.0 = başlangıç)
    cizgiler: pd.DataFrame    # timestamp, tepe, dip — grafikte çizmek için
    kurallar: Kurallar
    # Her bar sonunda geçerli seviyeler (2026-09-11 eklendi):
    #   alis_seviyesi — pozisyon yokken o barda alış seviyesi
    #   koruma        — pozisyon varken bir sonraki barda geçerli satış seviyesi
    #                   (zararına satış ya da takip eden stop)
    #   takipte       — takip eden stop devrede mi
    seviyeler: pd.DataFrame | None = None


def cizgiler(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Tepe ve dip çizgisi — yalnızca ÖNCEKİ `n` bardan (bugün hariç)."""
    if n < 2:
        raise ValueError(f"n >= 2 olmalı, verilen: {n}")
    return pd.DataFrame({
        "timestamp": df["timestamp"],
        "tepe": df["high"].rolling(n).max().shift(1),
        "dip": df["low"].rolling(n).min().shift(1),
    })


def bollinger_cizgiler(df: pd.DataFrame, n: int, k: float = 2.0) -> pd.DataFrame:
    """Ortalamayı takip eden bant — yalnızca ÖNCEKİ `n` kapanıştan (bugün hariç).

        orta = son n kapanışın ortalaması
        tepe = orta + k × sapma      dip = orta − k × sapma

    Fiyat yükselince ortalama da yükselir, dip çizgisi fiyatın arkasından
    yukarı gelir. Donchian'da ise dip, fiyat ne kadar yükselirse yükselsin
    n bar boyunca eski en düşük seviyede kalır.
    """
    if n < 2:
        raise ValueError(f"n >= 2 olmalı, verilen: {n}")
    orta = df["close"].rolling(n).mean().shift(1)
    sapma = df["close"].rolling(n).std().shift(1)
    return pd.DataFrame({
        "timestamp": df["timestamp"],
        "tepe": orta + k * sapma,
        "dip": orta - k * sapma,
        "orta": orta,
    })


def calistir(df: pd.DataFrame, kurallar: Kurallar) -> Sonuc:
    """Sistemi bar bar uygular.

    Args:
        df: Kanonik bar tablosu (`timestamp`, `open`, `high`, `low`, `close`),
            zamana göre sıralı.
        kurallar: Sistem ayarları.
    """
    k = kurallar
    if k.cizgi == "donchian":
        lines = cizgiler(df, k.n)
    else:
        lines = bollinger_cizgiler(df, k.n, k.sapma_katsayisi)
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    tepe = lines["tepe"].to_numpy(float)
    dip = lines["dip"].to_numpy(float)
    ts = df["timestamp"].to_numpy()

    nakit = 1.0
    adet = 0.0                 # elimizdeki hisse (kesirli)
    durum = Durum()            # kuralın gördüğü pozisyon hali
    giris_i = -1
    giris_fiyat = np.nan
    islemler: list[dict] = []
    bakiye = np.empty(len(df))
    alis_kayit = np.full(len(df), np.nan)
    koruma_kayit = np.full(len(df), np.nan)
    takip_kayit = np.zeros(len(df), dtype=bool)

    def kaydet_satis(i: int, fiyat: float, sebep: str) -> None:
        """Kapanan işlemi deftere yazar. Para muhasebesi çağıranda."""
        islemler.append({
            "alis_zamani": ts[giris_i], "alis": giris_fiyat,
            "satis_zamani": ts[i], "satis": fiyat, "sebep": sebep,
            "bar": i - giris_i,
            "getiri": fiyat / giris_fiyat - 1,
            "getiri_maliyetli": (fiyat * (1 - k.maliyet))
                                / (giris_fiyat * (1 + k.maliyet)) - 1,
        })

    for i in range(len(df)):
        if np.isnan(tepe[i]):          # çizgiler henüz oluşmadı
            bakiye[i] = nakit
            continue

        cizgi = Cizgi(tepe[i], dip[i])
        bar = Bar(o[i], h[i], lo[i], c[i])

        # Motorun bu bar için koyacağı emirler — grafikte göstermek için kaydet.
        if not durum.acik:
            alis_kayit[i] = emir_seviyeleri(durum, cizgi, k).alis

        durum, olaylar = uygula(durum, bar, cizgi, k)

        for olay in olaylar:
            if olay.eylem == AL:
                giris_i = i
                giris_fiyat = olay.fiyat
                adet = nakit / (olay.fiyat * (1 + k.maliyet))
                nakit = 0.0
            else:
                nakit = adet * olay.fiyat * (1 - k.maliyet)
                kaydet_satis(i, olay.fiyat, olay.sebep)
                adet = 0.0

        # Açık pozisyon, o anki kapanıştan satılsaydı ne ederdi
        bakiye[i] = nakit + adet * c[i] * (1 - k.maliyet)
        if adet:
            koruma_kayit[i] = durum.stop
            takip_kayit[i] = durum.takipte

    if adet:
        nakit = adet * c[-1] * (1 - k.maliyet)
        kaydet_satis(len(df) - 1, c[-1], SEBEP_DONEM_SONU)
        adet = 0.0
        durum = Durum()
        bakiye[-1] = nakit

    return Sonuc(
        islemler=pd.DataFrame(islemler),
        bakiye=pd.Series(bakiye, index=pd.DatetimeIndex(ts), name="bakiye"),
        cizgiler=lines,
        kurallar=k,
        seviyeler=pd.DataFrame({
            "timestamp": df["timestamp"].to_numpy(),
            "alis_seviyesi": alis_kayit,
            "koruma": koruma_kayit,
            "takipte": takip_kayit,
        }, index=df.index),
    )


def en_buyuk_dusus(bakiye: pd.Series) -> float:
    """Zirveden sonraki en büyük kayıp. -0.25 = paranın %25'i bir ara eridi."""
    return float((bakiye / bakiye.cummax() - 1).min())


def ozet(df: pd.DataFrame, sonuc: Sonuc, bar_per_yil: float) -> pd.DataFrame:
    """Sistemi 'başta al, sonda sat' ile yan yana koyar.

    Args:
        bar_per_yil: Günlükte 252, saatlikte 252 × 7.
    """
    yil = len(df) / bar_per_yil
    tr = sonuc.islemler
    m = sonuc.kurallar.maliyet
    # Al-tut da bir alış ve bir satış maliyeti öder — adil kıyas için
    al_tut = df["close"] / df["close"].iloc[0] * (1 - m) / (1 + m)
    al_tut.index = sonuc.bakiye.index

    def yillik(toplam: float) -> float:
        return (1 + toplam) ** (1 / yil) - 1

    sistem_toplam = float(sonuc.bakiye.iloc[-1] - 1)
    maliyetsiz = float(np.prod(1 + tr["getiri"]) - 1) if len(tr) else 0.0
    al_tut_toplam = float(al_tut.iloc[-1] - 1)
    piyasada = tr["bar"].sum() / len(df) if len(tr) else 0.0

    satirlar = {
        "toplam getiri": (sistem_toplam, al_tut_toplam),
        "toplam getiri (maliyetsiz)": (maliyetsiz, al_tut_toplam),
        "yıllık getiri": (yillik(sistem_toplam), yillik(al_tut_toplam)),
        "en büyük düşüş": (en_buyuk_dusus(sonuc.bakiye), en_buyuk_dusus(al_tut)),
        "piyasada kalma süresi": (piyasada, 1.0),
        "işlem sayısı": (len(tr), 1),
        "kazanan işlem oranı": (float((tr["getiri_maliyetli"] > 0).mean()) if len(tr) else np.nan, np.nan),
        "ortalama işlem getirisi": (float(tr["getiri_maliyetli"].mean()) if len(tr) else np.nan, np.nan),
        "tepede satılan": ((tr["sebep"] == "tepe").sum() if len(tr) else 0, np.nan),
        "stopla satılan": ((tr["sebep"] == "stop").sum() if len(tr) else 0, np.nan),
        "takip eden stopla satılan": ((tr["sebep"] == "takip").sum() if len(tr) else 0, np.nan),
    }
    return pd.DataFrame(satirlar, index=["sistem", "başta al, sonda sat"]).T


# ------------------------------------------------------- EĞİTİM / TEST --

ALIM_SECENEKLERI = (0.05, 0.10, 0.20)
STOP_SECENEKLERI = (0.25, 0.50, 1.00, 2.00)
TAKIP_SECENEKLERI = (0.25, 0.50, 1.00)   # yalnızca satis="takip" iken denenir


def egitim_test(
    df: pd.DataFrame,
    n: int,
    test_yillari: range,
    *,
    maliyet: float = 0.0005,
    varsayilan: tuple[float, float] = (0.10, 0.50),
    sabit: dict | None = None,
) -> pd.DataFrame:
    """Eşikleri geçmişte seç, hiç bakılmamış bir sonraki yılda dene.

    Her test yılı için:
      1. **Eğitim:** o yıldan ÖNCEKİ tüm veride eşik kombinasyonları denenir
         (`ALIM_SECENEKLERI` × `STOP_SECENEKLERI`, takip eden stop'ta ayrıca
         × `TAKIP_SECENEKLERI`), en çok kazandıran seçilir.
      2. **Test:** seçilen eşikler o yılda uygulanır. Eşik seçerken bu yıla
         hiç bakılmadı.

    Test yılının başında çizgilerin hazır olması için önceki `n` bar da
    verilir. Bu geçmiş fiyattır, sızıntı değildir; işlem yalnızca test
    yılının içinde açılır.

    Args:
        sabit: Denenmeyen, sabit tutulan ayarlar. Ör.
            `{"cizgi": "bollinger", "satis": "takip"}`. Verilmezse eski sistem.

    Returns:
        Yıl başına bir satır: seçilen eşikler, eğitimdeki ve testteki getiri,
        varsayılan eşiklerle testteki getiri, aynı yılda başta al sonda sat.
    """
    tablo, _, _ = _egitim_test(df, n, test_yillari, maliyet=maliyet,
                               varsayilan=varsayilan, sabit=sabit)
    return tablo


def egitim_test_detay(
    df: pd.DataFrame,
    n: int,
    test_yillari: range,
    *,
    maliyet: float = 0.0005,
    varsayilan: tuple[float, float] = (0.10, 0.50),
    sabit: dict | None = None,
) -> tuple[pd.DataFrame, dict[int, Sonuc], dict[int, pd.DataFrame]]:
    """`egitim_test` ile aynı hesap, ayrıntılarıyla birlikte.

    Returns:
        (tablo, yil_sonuclari, egitim_skorlari)
        * `tablo`: `egitim_test`'in döndürdüğü tablonun aynısı.
        * `yil_sonuclari`: her test yılının `Sonuc`'u (seçilen eşiklerle).
        * `egitim_skorlari`: her test yılı için eğitimde denenen tüm
          kombinasyonlar ve getirileri (satır başına bir kombinasyon).
    """
    return _egitim_test(df, n, test_yillari, maliyet=maliyet,
                        varsayilan=varsayilan, sabit=sabit, detay=True)


def _egitim_test(df, n, test_yillari, *, maliyet, varsayilan, sabit, detay=False):
    sabit = dict(sabit or {})
    izgara = [{"alim_payi": a, "stop_payi": s}
              for a in ALIM_SECENEKLERI for s in STOP_SECENEKLERI]
    if sabit.get("satis") == "takip":
        izgara = [{**p, "takip_payi": t} for p in izgara for t in TAKIP_SECENEKLERI]

    ts = df["timestamp"]
    close = df["close"].to_numpy(float)
    rows, yil_sonuclari, egitim_skorlari = [], {}, {}
    for yil in test_yillari:
        bas = int(np.searchsorted(ts, pd.Timestamp(f"{yil}-01-01", tz="UTC")))
        son = int(np.searchsorted(ts, pd.Timestamp(f"{yil + 1}-01-01", tz="UTC")))
        if bas <= n or son <= bas:
            raise ValueError(f"{yil} için yeterli veri yok.")
        egitim, test = df.iloc[:bas], df.iloc[bas - n:son]

        def calis(veri: pd.DataFrame, ayar: dict) -> Sonuc:
            return calistir(veri, Kurallar(n=n, maliyet=maliyet, **sabit, **ayar))

        def getiri(veri: pd.DataFrame, ayar: dict) -> float:
            return float(calis(veri, ayar).bakiye.iloc[-1] - 1)

        skor = [getiri(egitim, p) for p in izgara]
        j = int(np.argmax(skor))          # eşitlikte ilk sıradaki — eski davranışla aynı
        secilen = izgara[j]
        test_sonuc = calis(test, secilen)
        satir = {
            "test_yili": yil,
            "secilen_alim": secilen["alim_payi"],
            "secilen_stop": secilen["stop_payi"],
        }
        if "takip_payi" in secilen:
            satir["secilen_takip"] = secilen["takip_payi"]
        satir.update({
            "egitimde": skor[j],
            "testte": float(test_sonuc.bakiye.iloc[-1] - 1),
            "varsayilan_esiklerle": getiri(
                test, {"alim_payi": varsayilan[0], "stop_payi": varsayilan[1]}),
            "basta_al_sonda_sat": close[son - 1] / close[bas - 1]
                                  * (1 - maliyet) / (1 + maliyet) - 1,
        })
        rows.append(satir)
        if detay:
            yil_sonuclari[yil] = test_sonuc
            egitim_skorlari[yil] = pd.DataFrame(
                [{**p, "egitim_getirisi": s} for p, s in zip(izgara, skor)])
    return pd.DataFrame(rows), yil_sonuclari, egitim_skorlari


def zincirle(yil_sonuclari: dict[int, Sonuc], n: int) -> pd.Series:
    """Test yıllarının bakiye eğrilerini arka arkaya bağlar: 1 lira nasıl büyüdü.

    Her test yılının başındaki `n` ısınma barı (işlem açılmayan, önceki
    yıldan gelen fiyatlar) atılır; her yıl bir öncekinin bittiği değerden
    devam eder. Son değer, `egitim_test` tablosundaki `testte` getirilerinin
    çarpımına eşittir.
    """
    parcalar, carpan = [], 1.0
    for yil in sorted(yil_sonuclari):
        eq = yil_sonuclari[yil].bakiye.iloc[n:]
        parcalar.append(eq * carpan)
        carpan *= float(eq.iloc[-1])
    return pd.concat(parcalar).rename("bakiye")


def al_tut(df: pd.DataFrame, bas: str, son: str | None = None,
           maliyet: float = 0.0005) -> pd.Series:
    """Baseline: `bas` tarihinden önceki son kapanışta al, hiç dokunma.

    1 liranın her bar sonundaki değeri. Bir alış ve bir satış maliyeti düşülür.
    """
    ts = df["timestamp"]
    i0 = int(np.searchsorted(ts, pd.Timestamp(bas, tz="UTC")))
    i1 = len(df) if son is None else int(np.searchsorted(ts, pd.Timestamp(son, tz="UTC")))
    if i0 < 1:
        raise ValueError(f"{bas} öncesinde kapanış yok.")
    c = df["close"].iloc[i0:i1].to_numpy(float) / float(df["close"].iloc[i0 - 1])
    return pd.Series(c * (1 - maliyet) / (1 + maliyet),
                     index=pd.DatetimeIndex(ts.iloc[i0:i1].to_numpy()), name="baseline")
