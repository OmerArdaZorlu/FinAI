"""Saatlik motor — bir tur: veri → karar → emir → kayıt.

Nasıl çalışır
-------------
Sürekli açık kalan bir servis değil; her saat başı **bir kez** çalışıp çıkan
bir program. Çökerse bir sonraki tur temiz başlar, durumu diskten okur. Zaten
bir işi vardır: bekleyen emirleri güncellemek.

    python -m src.engine.motor            # gerçek tur (paper hesaba emir gider)
    python -m src.engine.motor --kuru     # hiçbir emir göndermez, sadece anlatır

Zamanlama — neden "bir bar geriden"
-----------------------------------
Ücretsiz Alpaca planında SIP verisi 15 dakika gecikmelidir; sorgunun bitişi
şimdiye çok yakınsa API **403** döner. Dolayısıyla saat 12:00'de kapanan
11:00–12:00 barını göremeyiz; elimizdeki en yeni TAM bar 10:00–11:00'dir.

    12:00'de emri koyarken kullandığımız veri  : 10:00–11:00 barına kadar
    backtest'in aynı anda kullandığı veri      : 11:00–12:00 barına kadar

Yani çizgiler bir bar eskidir. Ölçüldü: sabit eşikle 8.5 yılda 1 lira 9.90
yerine 9.46, işlem sayısı aynı (28), erime aynı. Barların %80'inde seviye
zaten birebir aynı çıkıyor, çünkü 140 barlık kanal ancak yeni bir uç gelince
değişiyor.

Emirler bekler, motor beklemez
------------------------------
Motor fiyatı izlemez. Her tur, bir sonraki bar için **bekleyen** emri borsaya
bırakır ve çıkar. Emir orada durduğu için biz uyurken de dolar; veri
gecikmesi gerçekleşmeyi etkilemez. Koruma emri `gtc`'dir, gece de yaşar.

Güvenlik katmanları (hepsi emir göndermeden önce)
-------------------------------------------------
1. **Acil durdurma:** `data/DUR` dosyası varsa her şeyi kapat, dur (TD-09).
2. **Mutabakat:** broker'daki gerçek pozisyon kayıtla uyuşmuyorsa dur (TD-06).
3. **Bayat veri:** en yeni tam bar olması gerekenden eskiyse emir yok (TD-08).
4. **Tekrarsız emir kimliği:** aynı bar + aynı tip = aynı kimlik; broker
   ikincisini reddeder (TD-07).
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.data.alpaca import AlpacaError, fetch_bars
from src.data.session import EXCHANGE_TZ, regular_hours

from . import durum as D
from .broker import LIMIT_AL, STOP_SAT, Broker, BrokerError
from .kural import Bar, Cizgi, Durum, Kurallar, emir_seviyeleri, takip_guncelle

REPO_ROOT = Path(__file__).resolve().parents[2]

# KABUL-1'de saatlik için seçilen eşikler (hypotheses/KABUL-1_*.md §3).
# Motor bunları DEĞİŞTİRMEZ; eşik yenileme bilinçli bir karar olarak açıktır.
KURALLAR_KABUL1 = Kurallar(
    n=140,                # 20 işlem günü × 7 saatlik bar
    cizgi="donchian",
    satis="takip",
    alim_payi=0.10,
    stop_payi=2.00,
    takip_payi=1.00,
    maliyet=0.0005,
)


@dataclass(frozen=True, slots=True)
class Ayarlar:
    sembol: str = "AAPL"
    timeframe: str = "1Hour"
    bar_dakika: int = 60
    kurallar: Kurallar = KURALLAR_KABUL1
    veri_gecikmesi_dk: int = 16      # SIP 15 dk gecikmeli; 1 dk emniyet payı
    gecmis_gun: int = 60             # 140 seans barı için fazlasıyla yeter
    paper_db: Path = D.DEFAULT_PAPER_DB_PATH
    dur_dosyasi: Path = REPO_ROOT / "data" / "DUR"
    bayat_bar_siniri: int = 3        # en yeni tam bar bu kadar bardan eskiyse bayat


@dataclass
class TurSonucu:
    """Bir turun özeti — log ve test için."""

    ozet: str
    satirlar: list[str] = field(default_factory=list)
    emir_gonderildi: bool = False
    durduruldu: bool = False

    def yaz(self, satir: str) -> None:
        self.satirlar.append(satir)

    def __str__(self) -> str:
        return "\n".join([self.ozet, *(f"  {s}" for s in self.satirlar)])


# --------------------------------------------------------------- VERİ --

def barlari_getir(ayarlar: Ayarlar, simdi: dt.datetime | None = None) -> pd.DataFrame:
    """Seans filtresinden geçmiş, **yalnızca tamamlanmış** barlar.

    Alpaca yarım bar da döndürür: 12:04'te sorulursa 11:00 barını verir, ama o
    bar 12:00'de kapanacaktır. Yarım barla çizgi hesaplamak, henüz olmamış bir
    zirveyi görmüş gibi davranmak olurdu — bu yüzden atılır.
    """
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    kesim = simdi - dt.timedelta(minutes=ayarlar.veri_gecikmesi_dk)
    baslangic = kesim - dt.timedelta(days=ayarlar.gecmis_gun)

    try:
        ham = fetch_bars(
            ayarlar.sembol,
            start=baslangic.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=kesim.strftime("%Y-%m-%dT%H:%M:%SZ"),
            timeframe=ayarlar.timeframe,
            verbose=False,
        )
    except AlpacaError as exc:
        if "403" in str(exc):
            raise AlpacaError(
                "Alpaca 403 döndü. Anahtarlar yanlış OLMAYABİLİR: ücretsiz planda\n"
                "  SIP verisi 15 dakika gecikmelidir ve sorgu bitişi şimdiye çok\n"
                f"  yakınsa 403 gelir. Şu anki gecikme payı: {ayarlar.veri_gecikmesi_dk} dk."
            ) from exc
        raise

    seans = regular_hours(ham)
    # Barlar BAŞLANGIÇ saatiyle etiketli: 11:00 barı 12:00'de kapanır.
    biter = seans["timestamp"] + pd.Timedelta(minutes=ayarlar.bar_dakika)
    return seans.loc[biter <= kesim].reset_index(drop=True)


def cizgi_hesapla(barlar: pd.DataFrame, n: int, *, son_haric: int = 0) -> Cizgi:
    """Son `n` barın en yükseği ve en düşüğü.

    Args:
        son_haric: Sondan kaç bar dışlansın. `0` → çizgi bu barlara kadar
            olanı özetler (bir sonraki barın emri için). `1` → son barın
            kendisi hariç (o barı `takip_guncelle`'ye verirken kullanılır;
            backtest'teki `shift(1)`'in aynısı).
    """
    kullanilacak = barlar.iloc[: len(barlar) - son_haric] if son_haric else barlar
    if len(kullanilacak) < n:
        return Cizgi(math.nan, math.nan)
    son_n = kullanilacak.iloc[-n:]
    return Cizgi(tepe=float(son_n["high"].max()), dip=float(son_n["low"].min()))


# ------------------------------------------------------------- BİR TUR --

def bir_tur(
    ayarlar: Ayarlar | None = None,
    *,
    broker: Broker | None = None,
    kuru: bool = False,
    simdi: dt.datetime | None = None,
) -> TurSonucu:
    """Motorun tek turu. `kuru=True` ise hiçbir emir gönderilmez."""
    ayarlar = ayarlar or Ayarlar()
    broker = broker or Broker()
    sonuc = TurSonucu(ozet="")

    with D.connect(ayarlar.paper_db) as conn:
        # 1) ACİL DURDURMA — her şeyden önce.
        if ayarlar.dur_dosyasi.exists():
            return _acil_durdur(conn, ayarlar, broker, sonuc, kuru)

        # 2) Borsa açık mı? Tatil ve yarım gün bilgisi broker'dan gelir.
        saat = broker.borsa_saati()
        if not saat.acik:
            sonuc.ozet = "Borsa kapalı — bir sonraki açılış: " + saat.sonraki_acilis
            return sonuc

        pozisyon_durumu, adet, son_islenen = D.durum_yukle(conn)

        # 3) Bekleyen emirlerin akıbeti (dolan varsa duruma işlenir).
        pozisyon_durumu, adet = _emirleri_isle(
            conn, broker, pozisyon_durumu, adet, sonuc)

        # 4) MUTABAKAT — broker gerçeği ile kaydımız uyuşuyor mu?
        if not _mutabakat(broker, ayarlar, pozisyon_durumu, adet, sonuc):
            D.durum_kaydet(conn, pozisyon_durumu, adet=adet,
                           son_islenen_bar=son_islenen)
            sonuc.durduruldu = True
            return sonuc

        # 5) Veri.
        barlar = barlari_getir(ayarlar, simdi)
        if len(barlar) < ayarlar.kurallar.n + 1:
            sonuc.ozet = (f"Yetersiz bar: {len(barlar)} var, "
                          f"{ayarlar.kurallar.n + 1} gerekli. Emir yok.")
            return sonuc

        son_bar_zamani = _iso(barlar["timestamp"].iloc[-1])

        # 6) BAYAT VERİ kontrolü.
        bayat = _bayat_mi(barlar, ayarlar, simdi)
        if bayat:
            sonuc.ozet = f"Bayat veri: {bayat}. Emir gönderilmedi."
            D.sinyal_yaz(conn, bar_zamani=son_bar_zamani, tepe=math.nan,
                         dip=math.nan, alis_seviyesi=math.nan,
                         zarar_stop=math.nan, koruma=math.nan,
                         durum=pozisyon_durumu, aciklama=f"bayat veri: {bayat}")
            sonuc.durduruldu = True
            return sonuc

        # 7) Son tam barı henüz işlemediysek takip eden stop'u güncelle.
        #    Çizgi, o barın KENDİSİ hariç öncekilerden — backtest'teki shift(1).
        if son_islenen != son_bar_zamani and pozisyon_durumu.acik:
            son = barlar.iloc[-1]
            onceki_durum = pozisyon_durumu
            pozisyon_durumu = takip_guncelle(
                pozisyon_durumu,
                Bar(float(son["open"]), float(son["high"]),
                    float(son["low"]), float(son["close"])),
                cizgi_hesapla(barlar, ayarlar.kurallar.n, son_haric=1),
                ayarlar.kurallar,
            )
            if pozisyon_durumu != onceki_durum:
                sonuc.yaz("takip eden stop güncellendi: %.2f → %.2f%s" % (
                    onceki_durum.stop, pozisyon_durumu.stop,
                    " (takip DEVREYE GİRDİ)"
                    if pozisyon_durumu.takipte and not onceki_durum.takipte else ""))

        # 8) Bir sonraki bar için emir seviyeleri.
        cizgi = cizgi_hesapla(barlar, ayarlar.kurallar.n)
        seviyeler = emir_seviyeleri(pozisyon_durumu, cizgi, ayarlar.kurallar)

        D.sinyal_yaz(conn, bar_zamani=son_bar_zamani, tepe=cizgi.tepe,
                     dip=cizgi.dip, alis_seviyesi=seviyeler.alis,
                     zarar_stop=seviyeler.zarar_stop, koruma=seviyeler.koruma,
                     durum=pozisyon_durumu,
                     aciklama="kuru çalışma" if kuru else "")

        # 9) Emirleri koy.
        _emirleri_koy(conn, broker, ayarlar, pozisyon_durumu, adet,
                      seviyeler, son_bar_zamani, sonuc, kuru,
                      nakit=broker.hesap().nakit)

        D.durum_kaydet(conn, pozisyon_durumu, adet=adet,
                       son_islenen_bar=son_bar_zamani)

        sonuc.ozet = "%s | son tam bar %s | %s | tepe %.2f dip %.2f" % (
            ayarlar.sembol,
            _ny(barlar["timestamp"].iloc[-1]),
            "POZİSYON %d adet, stop %.2f%s" % (
                adet, pozisyon_durumu.stop,
                " (takipte)" if pozisyon_durumu.takipte else "")
            if pozisyon_durumu.acik else "nakitte",
            cizgi.tepe, cizgi.dip,
        )
        return sonuc


# ------------------------------------------------------------ PARÇALAR --

def _emirleri_isle(
    conn: sqlite3.Connection,
    broker: Broker,
    pozisyon_durumu: Durum,
    adet: int,
    sonuc: TurSonucu,
) -> tuple[Durum, int]:
    """Bekleyen emirlerin broker'daki son halini alır, dolanları duruma işler."""
    for satir in D.bekleyen_emirler(conn):
        emir = broker.emir_sorgula(satir["client_order_id"])
        if emir is None:
            continue
        if emir.bekliyor:
            continue

        D.emir_durumu_guncelle(conn, emir.client_order_id,
                               "dolu" if emir.dolu else "iptal")
        if not emir.dolu:
            sonuc.yaz(f"emir düştü ({emir.durum}): {emir.client_order_id}")
            continue

        D.gerceklesme_yaz(
            conn,
            client_order_id=emir.client_order_id,
            bar_zamani=satir["bar_zamani"],
            tip=satir["tip"],
            istenen_seviye=float(satir["seviye"]),
            gerceklesen_fiyat=emir.dolan_ortalama_fiyat,
            adet=emir.dolan_adet,
        )
        fark = (emir.dolan_ortalama_fiyat / float(satir["seviye"]) - 1) * 100
        sonuc.yaz("DOLDU %s: istenen %.2f → gerçekleşen %.2f (%%%+.3f)" % (
            satir["tip"], satir["seviye"], emir.dolan_ortalama_fiyat, fark))

        if satir["tip"] == LIMIT_AL:
            # Zararına satış seviyesi emir konurken sabitlenmişti.
            pozisyon_durumu = Durum(
                acik=True,
                giris_fiyat=emir.dolan_ortalama_fiyat,
                stop=float(satir["ek_seviye"]),
            )
            adet = emir.dolan_adet
        else:
            pozisyon_durumu = Durum()
            adet = 0

    return pozisyon_durumu, adet


def _mutabakat(
    broker: Broker,
    ayarlar: Ayarlar,
    pozisyon_durumu: Durum,
    adet: int,
    sonuc: TurSonucu,
) -> bool:
    """Broker'daki gerçek pozisyon kaydımızla uyuşuyor mu (TD-06).

    Uyuşmuyorsa motor **işlem açmaz**. Kendi kaydına göre davranmak, gerçekte
    olmayan bir pozisyonu korumaya çalışmak ya da korumasız bir pozisyonu
    görmezden gelmek demektir.
    """
    gercek = broker.pozisyon(ayarlar.sembol)
    gercek_adet = gercek.adet if gercek else 0
    kayitli_adet = adet if pozisyon_durumu.acik else 0

    if gercek_adet == kayitli_adet:
        return True

    sonuc.ozet = (
        "MUTABAKAT BOZUK — motor durdu.\n"
        f"  broker'da {gercek_adet} adet, kayıtta {kayitli_adet} adet.\n"
        "  Elle incelenmeli: pozisyon ve kayıt eşitlenmeden tur atılmaz."
    )
    return False


def _bayat_mi(
    barlar: pd.DataFrame, ayarlar: Ayarlar, simdi: dt.datetime | None,
) -> str:
    """En yeni tam bar makul bir yaşta mı (TD-08). Bayatsa sebebi döner."""
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    son = barlar["timestamp"].iloc[-1].to_pydatetime()
    yas_dk = (simdi - son).total_seconds() / 60
    sinir = ayarlar.bar_dakika * (ayarlar.bayat_bar_siniri + 1) + ayarlar.veri_gecikmesi_dk
    if yas_dk > sinir:
        return (f"en yeni tam bar {yas_dk:.0f} dakika önce "
                f"({_ny(barlar['timestamp'].iloc[-1])}), sınır {sinir:.0f} dk")
    return ""


def _emirleri_koy(
    conn: sqlite3.Connection,
    broker: Broker,
    ayarlar: Ayarlar,
    pozisyon_durumu: Durum,
    adet: int,
    seviyeler,
    bar_zamani: str,
    sonuc: TurSonucu,
    kuru: bool,
    nakit: float,
) -> None:
    """Hesaplanan seviyeleri borsadaki bekleyen emirlere çevirir."""
    if not seviyeler.emir_var:
        sonuc.yaz("emir seviyesi yok (çizgi hazır değil ya da kanal düz)")
        return

    if pozisyon_durumu.acik:
        tip, seviye, emir_adedi, ek = STOP_SAT, seviyeler.koruma, adet, math.nan
        if emir_adedi <= 0:
            sonuc.yaz("pozisyon açık ama adet 0 — emir konmadı")
            return
    else:
        tip, seviye, ek = LIMIT_AL, seviyeler.alis, seviyeler.zarar_stop
        emir_adedi = int(nakit // seviye)          # TAM hisse
        if emir_adedi <= 0:
            sonuc.yaz(f"nakit {nakit:.2f} bir hisseye yetmiyor ({seviye:.2f})")
            return

    kimlik = D.emir_kimligi(bar_zamani, tip)
    bekleyenler = broker.bekleyen_emirler(ayarlar.sembol)

    # Bu bar için doğru emir zaten borsada duruyorsa DOKUNMA. Motor aynı bar
    # içinde ikinci kez çalışırsa (yeniden deneme, çökme sonrası açılış) eski
    # emri iptal edip yerine aynı kimlikle yenisini koyamaz — kimlik tekrarsız
    # olduğu için broker reddeder ve ortada emirsiz kalırdık.
    mevcut = next((e for e in bekleyenler if e.client_order_id == kimlik), None)
    if mevcut is not None:
        sonuc.yaz("emir zaten yerinde: %s %d adet @ %.2f" % (
            tip, mevcut.adet, mevcut.seviye))
        return

    # Başka barlardan kalan emirler iptal — seviye her bar değişebilir.
    for eski in bekleyenler:
        if kuru:
            sonuc.yaz(f"[kuru] iptal edilecekti: {eski.client_order_id}")
            continue
        broker.emri_iptal(eski.broker_id)
        D.emir_durumu_guncelle(conn, eski.client_order_id, "iptal")

    if kuru:
        sonuc.yaz("[kuru] gönderilecekti: %s %d adet @ %.2f%s" % (
            tip, emir_adedi, seviye,
            f" (dolarsa stop {ek:.2f})" if not math.isnan(ek) else ""))
        return

    try:
        if tip == LIMIT_AL:
            emir = broker.limit_al(ayarlar.sembol, emir_adedi, seviye, kimlik)
        else:
            emir = broker.stop_sat(ayarlar.sembol, emir_adedi, seviye, kimlik)
    except BrokerError as exc:
        if "must be unique" in str(exc):
            sonuc.yaz(f"aynı kimlikli emir zaten var, tekrar gönderilmedi: {kimlik}")
            return
        raise

    D.emir_yaz(conn, client_order_id=kimlik, bar_zamani=bar_zamani, tip=tip,
               seviye=seviye, ek_seviye=ek, adet=emir_adedi,
               broker_order_id=emir.broker_id)
    sonuc.emir_gonderildi = True
    sonuc.yaz("EMİR: %s %d adet @ %.2f%s" % (
        tip, emir_adedi, seviye,
        f" (dolarsa stop {ek:.2f})" if not math.isnan(ek) else ""))


def _acil_durdur(
    conn: sqlite3.Connection,
    ayarlar: Ayarlar,
    broker: Broker,
    sonuc: TurSonucu,
    kuru: bool,
) -> TurSonucu:
    """`data/DUR` dosyası görüldü: emirleri iptal et, pozisyonu kapat, dur (TD-09)."""
    sonuc.ozet = f"ACİL DURDURMA — {ayarlar.dur_dosyasi} dosyası var."
    sonuc.durduruldu = True
    if kuru:
        sonuc.yaz("[kuru] emirler iptal edilip pozisyon kapatılacaktı")
        return sonuc

    broker.tum_emirleri_iptal()
    sonuc.yaz("bekleyen emirler iptal edildi")

    pozisyon = broker.pozisyon(ayarlar.sembol)
    if pozisyon and pozisyon.adet > 0:
        kimlik = "ACIL-" + D.simdi_utc().replace(":", "").replace("-", "")
        broker.piyasadan_sat(ayarlar.sembol, pozisyon.adet, kimlik)
        sonuc.yaz(f"pozisyon piyasadan kapatıldı: {pozisyon.adet} adet")
    else:
        sonuc.yaz("açık pozisyon yok")

    D.durum_kaydet(conn, Durum(), adet=0, son_islenen_bar=None)
    sonuc.yaz("durum sıfırlandı — motor duruyor. Devam için DUR dosyasını silin.")
    return sonuc


# -------------------------------------------------------------- YARDIM --

def _iso(zaman) -> str:
    return pd.Timestamp(zaman).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S+0000")


def _ny(zaman) -> str:
    return pd.Timestamp(zaman).tz_convert(EXCHANGE_TZ).strftime("%Y-%m-%d %H:%M %Z")


def main() -> int:
    cozumleyici = argparse.ArgumentParser(
        description="Saatlik alım satım motoru — bir tur (Alpaca paper).")
    cozumleyici.add_argument("--kuru", action="store_true",
                            help="hiçbir emir gönderme, sadece ne yapacağını yaz")
    cozumleyici.add_argument("--sembol", default="AAPL")
    args = cozumleyici.parse_args()

    sonuc = bir_tur(Ayarlar(sembol=args.sembol), kuru=args.kuru)
    print(sonuc)
    return 1 if sonuc.durduruldu else 0


if __name__ == "__main__":
    raise SystemExit(main())
