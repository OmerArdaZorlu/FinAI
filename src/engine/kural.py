"""Al-sat kurallarının TEK kopyası — hem backtest hem canlı motor burayı çağırır.

Neden burada
------------
Kurallar önce `lab/backtest.py` içindeki bar döngüsünün gövdesinde yaşıyordu.
Motor ikinci bir kopya yazsaydı canlı sistem backtest'ten sessizce ayrışırdı
(TECH_DEBT.md TD-01'in kural hali): bir `>=` `>` olur, bir gecikme kaybolur,
aylar sonra paper sonuçları tuhaf gelince fark edilirdi.

İki soru, iki fonksiyon
-----------------------
Motor ile backtest'in sorduğu soru aynı kuralın iki yüzüdür:

* `emir_seviyeleri()` — **"bir sonraki barda emirlerim nerede dursun?"**
  Motorun asıl kullandığı budur: her bar kapanışında çağırır, çıkan seviyelere
  bekleyen limit/stop emrini koyar.
* `uygula()` — **"bar gerçekleşti, o emirler ne yaptı?"**
  Backtest bunu kullanır. İçeride `emir_seviyeleri()`'ni çağırır, yani
  backtest birebir motorun koyacağı emirleri test eder — uydurma bir seviyeyi
  değil.

Zamanlama sözleşmesi
--------------------
`cizgi`, o barın **kendisi hariç** önceki barlardan hesaplanır
(`lab/backtest.py:cizgiler`, `shift`). Dolayısıyla bar `i`'nin çizgisi bar
`i-1` kapandığında bilinir — motor tam o anda emri koyabilir. Bugünün en
yükseği tepe çizgisine dahil edilseydi çizgi fiyatı kovalardı ve gerçekte
verilemeyecek emirler dolmuş sayılırdı.

Bar içi varsayımlar (hepsi aleyhimize)
--------------------------------------
Bir barın yalnızca açılış/en yüksek/en düşük/kapanışını biliyoruz; içinde
hangisinin önce olduğunu bilmiyoruz. Belirsiz her durumda kötü olan seçilir:

* Aynı barda hem stop hem tepe görüldüyse **önce stop** olmuş sayılır.
* Alış yapılan barda tepeye değse bile satılmaz; stop'a değerse satılır.
* Fiyat seviyenin ötesinde **açıldıysa** (gece boşluğu) işlem açılış fiyatından.
* Açılış zaten stop seviyesinin altındaysa alış yapılmaz.
* **Takip eden stop bir bar gecikmelidir:** bu barın zirvesiyle hesaplanan
  seviye ancak bir SONRAKİ bardan itibaren tetiklenebilir. Aynı barda hem
  zirveyi görüp hem stopa düştüğünü varsaymak kendimize olmayan bir avantaj
  vermek olurdu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

NAN = math.nan

# Eylemler
AL = "AL"
SAT = "SAT"

# Satış sebepleri
SEBEP_STOP = "stop"          # zararına satış — alışta sabitlenen seviye
SEBEP_TAKIP = "takip"        # takip eden stop
SEBEP_TEPE = "tepe"          # tepe çizgisine değince satan eski sürüm
SEBEP_DONEM_SONU = "donem_sonu"


@dataclass(frozen=True, slots=True)
class Kurallar:
    """Sistemin ayarları. Varsayılanlar kullanıcının verdiği kurallardır."""

    n: int                    # çizgi penceresi (bar). Günlükte 20, saatlikte 140
    alim_payi: float = 0.10   # dipten kanal genişliğinin %10'u kadar yukarısı → al
    stop_payi: float = 0.50   # dibin kanal genişliğinin yarısı kadar altı → zararına sat
    maliyet: float = 0.0005   # her alış ve satışta %0.05

    cizgi: str = "donchian"        # "donchian": son n barın en yükseği/en düşüğü
                                   # "bollinger": son n kapanışın ortalaması ± k × sapma
    sapma_katsayisi: float = 2.0   # Bollinger'daki k
    satis: str = "tepe"            # "tepe": tepe çizgisine değince sat
                                   # "takip": tepeye değince satma, takip eden stop'a geç
    takip_payi: float = 0.50       # takip mesafesi: tepeye değildiği andaki genişliğin payı

    def __post_init__(self) -> None:
        if self.cizgi not in ("donchian", "bollinger"):
            raise ValueError(f"cizgi 'donchian' ya da 'bollinger' olmalı, verilen: {self.cizgi}")
        if self.satis not in ("tepe", "takip"):
            raise ValueError(f"satis 'tepe' ya da 'takip' olmalı, verilen: {self.satis}")


@dataclass(frozen=True, slots=True)
class Bar:
    """Tek bir barın fiyatları."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Cizgi:
    """Bu barda geçerli tepe ve dip çizgisi — önceki barlardan hesaplanmış."""

    tepe: float
    dip: float

    @property
    def genislik(self) -> float:
        return self.tepe - self.dip

    @property
    def hazir(self) -> bool:
        """Pencere dolmadıysa çizgi yoktur; o barda hiçbir şey yapılmaz."""
        return not (math.isnan(self.tepe) or math.isnan(self.dip))


@dataclass(frozen=True, slots=True)
class Durum:
    """Pozisyonun kalıcı hali — motor çöküp açılınca veritabanından bu yüklenir.

    `lab/backtest.py:calistir()` içindeki yerel değişkenlerin (`stop`,
    `takipte`, `zirve`, `mesafe`) kalıcı karşılığı. Hisse adedi ve nakit
    burada DEĞİL: onlar kuralın değil, portföyün bilgisi. Kural yalnızca
    "pozisyon açık mı" bilmek zorunda.
    """

    acik: bool = False
    giris_fiyat: float = NAN
    stop: float = NAN          # şu an geçerli koruma seviyesi
    takipte: bool = False      # tepeye değildi mi — takip eden stop devrede mi
    zirve: float = NAN         # takipteyken görülen en yüksek fiyat
    mesafe: float = NAN        # takip mesafesi, tepeye değildiği anda sabitlendi

    @property
    def satis_sebebi(self) -> str:
        """Koruma tetiklenirse bu zararına satış mı, takip eden stop mu."""
        return SEBEP_TAKIP if self.takipte else SEBEP_STOP


@dataclass(frozen=True, slots=True)
class Seviyeler:
    """Bir sonraki barda geçerli emir seviyeleri — motorun emre çevireceği şey.

    Pozisyon yokken `alis` ve `zarar_stop` doludur (`koruma` NaN):
        limit alış emri `alis` seviyesine konur; dolarsa koruma `zarar_stop`
        olarak sabitlenir.

    Pozisyon varken `koruma` doludur (`alis` NaN):
        stop satış emri `koruma` seviyesine konur.

    Hiçbiri yoksa (çizgi hazır değil ya da kanal düz) hepsi NaN'dır — o barda
    emir konmaz.
    """

    alis: float = NAN
    zarar_stop: float = NAN
    koruma: float = NAN

    @property
    def emir_var(self) -> bool:
        return not (math.isnan(self.alis) and math.isnan(self.koruma))


@dataclass(frozen=True, slots=True)
class Olay:
    """Bar içinde gerçekleşen bir alış ya da satış."""

    eylem: str            # AL | SAT
    fiyat: float
    sebep: str = ""       # yalnızca satışta dolu


def emir_seviyeleri(durum: Durum, cizgi: Cizgi, kurallar: Kurallar) -> Seviyeler:
    """Bir sonraki barda emirler nereye konsun.

    Motorun her bar kapanışında çağırdığı fonksiyon. Yan etkisi yoktur.

    Args:
        durum: Pozisyonun bu bar kapanışındaki hali.
        cizgi: BİR SONRAKİ barda geçerli olacak çizgiler (bu bar dahil
            önceki barlardan hesaplanmış).
        kurallar: Sistem ayarları.
    """
    if not cizgi.hazir:
        return Seviyeler()

    if durum.acik:
        return Seviyeler(koruma=durum.stop)

    genislik = cizgi.genislik
    if genislik <= 0:            # düz kanal — alınacak bir aralık yok
        return Seviyeler()

    return Seviyeler(
        alis=cizgi.dip + kurallar.alim_payi * genislik,
        zarar_stop=cizgi.dip - kurallar.stop_payi * genislik,
    )


def uygula(
    durum: Durum,
    bar: Bar,
    cizgi: Cizgi,
    kurallar: Kurallar,
) -> tuple[Durum, list[Olay]]:
    """Bar gerçekleşti — emirler ne yaptı, yeni durum ne.

    Backtest'in bar döngüsünde çağırdığı fonksiyon. İçeride
    `emir_seviyeleri()`'ni kullanır, yani motorun koyacağı emirleri test eder.

    Bir bar iki olay üretebilir: aynı barda alıp stopa düşmek. Bu yüzden
    olaylar liste döner.

    Returns:
        (yeni durum, bu barda gerçekleşen olaylar — sırayla)
    """
    if not cizgi.hazir:
        return durum, []

    if not durum.acik:
        return _pozisyon_yokken(durum, bar, cizgi, kurallar)
    return _pozisyon_varken(durum, bar, cizgi, kurallar)


def _pozisyon_yokken(
    durum: Durum, bar: Bar, cizgi: Cizgi, kurallar: Kurallar,
) -> tuple[Durum, list[Olay]]:
    sev = emir_seviyeleri(durum, cizgi, kurallar)
    if math.isnan(sev.alis):
        return durum, []

    # Bekleyen limit alış emri doldu mu? Barın en düşüğü seviyeye indiyse evet.
    # Açılış zaten stop seviyesinin altındaysa alış yapılmaz — o gün sistem
    # zaten zararda açmış demektir.
    if not (bar.low <= sev.alis and bar.open > sev.zarar_stop):
        return durum, []

    # Gece boşluğu: seviyenin altından açıldıysa limit emri daha iyi fiyattan
    # dolar. min() bunu ifade eder.
    giris = min(bar.open, sev.alis)
    yeni = Durum(acik=True, giris_fiyat=giris, stop=sev.zarar_stop)
    olaylar = [Olay(AL, giris)]

    # Aynı barda stop'a da indiyse çıkarılırız. Takip eden stop bu barda
    # devreye GİRMEZ (alış barında tepeden satış yok), o yüzden sebep hep
    # "stop"tur.
    if bar.low <= yeni.stop:
        olaylar.append(Olay(SAT, yeni.stop, SEBEP_STOP))
        return Durum(), olaylar

    return yeni, olaylar


def takip_guncelle(
    durum: Durum, bar: Bar, cizgi: Cizgi, kurallar: Kurallar,
) -> Durum:
    """Takip eden stop durumunu bu barın verisiyle günceller — SATMAZ.

    Motorun her kapanmış bar için çağırdığı fonksiyon. Canlıda satışı
    broker'daki stop emri yapar; kuralın işi yalnızca seviyenin nereye
    taşınacağını söylemektir. Backtest de satış kontrollerinden sonra aynı
    fonksiyonu çağırır, böylece seviye hesabının tek kopyası olur.

    İki şey yapar:
      1. Fiyat tepe çizgisine değdiyse takip eden stop'u devreye alır ve
         mesafeyi o anki kanal genişliğiyle sabitler.
      2. Takipteyse zirveyi ve stop seviyesini günceller — **yalnızca yukarı**.

    Çıkan seviye BİR SONRAKİ bardan itibaren geçerlidir (modül başındaki
    zamanlama sözleşmesi).
    """
    if not durum.acik or kurallar.satis != "takip" or not cizgi.hazir:
        return durum

    yeni = durum
    if not yeni.takipte and bar.high >= cizgi.tepe:
        # Tepeye değdi: satma, takip eden stop'a geç. Mesafe o anki genişlikle
        # sabitlenir, sonra değişmez.
        yeni = Durum(
            acik=True,
            giris_fiyat=durum.giris_fiyat,
            stop=durum.stop,
            takipte=True,
            mesafe=kurallar.takip_payi * cizgi.genislik,
            zirve=bar.high,
        )

    if yeni.takipte:
        zirve = max(yeni.zirve, bar.high)
        yeni = Durum(
            acik=True,
            giris_fiyat=yeni.giris_fiyat,
            stop=max(yeni.stop, zirve - yeni.mesafe),
            takipte=True,
            zirve=zirve,
            mesafe=yeni.mesafe,
        )

    return yeni


def _pozisyon_varken(
    durum: Durum, bar: Bar, cizgi: Cizgi, kurallar: Kurallar,
) -> tuple[Durum, list[Olay]]:
    # 1) Koruma önce. Aynı barda hem stop hem tepe görüldüyse stop kazanır.
    if bar.open <= durum.stop:
        # Gece boşluğu: stop seviyesinin altından açıldıysa oradan satılır.
        return Durum(), [Olay(SAT, bar.open, durum.satis_sebebi)]
    if bar.low <= durum.stop:
        return Durum(), [Olay(SAT, durum.stop, durum.satis_sebebi)]

    # 2) Tepe çizgisinde satan eski sürüm. Takipteyken tepeye bakılmaz.
    if kurallar.satis == "tepe" and not durum.takipte:
        if bar.open >= cizgi.tepe:
            return Durum(), [Olay(SAT, bar.open, SEBEP_TEPE)]
        if bar.high >= cizgi.tepe:
            return Durum(), [Olay(SAT, cizgi.tepe, SEBEP_TEPE)]

    # 3) Seviye güncellemesi — motorla ortak kod.
    return takip_guncelle(durum, bar, cizgi, kurallar), []
