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
5. **Fiyat sıçraması:** son 140 barda iki bar arası %25'ten büyük sıçrama
   varsa emir yok (hisse bölünmesi, bozuk veri).

Koruma bekçisi — `koruma_turu`
------------------------------
Saatlik tur emri koyup çıkar; arada olanları görmez. Alış 13:45'te dolarsa
taban emri ancak 14:20 turunda konurdu. Döngü, borsa açıkken **dakikada
bir** `koruma_turu`'nu çağırır: dolan emirleri kayda işler, kısmen dolan
alışın kalanını iptal eder ve "elimdeki hisse kadar taban emri borsada
duruyor mu?" diye bakar; durmuyorsa koyar, adedi yanlışsa düzeltir. Bar
çekmez, seviye hesaplamaz — seviye her zaman saatlik turun kaydettiğidir.

Kısmi gerçekleşme
-----------------
Alpaca alış emrinin bir kısmını doldurup kalanını bekletebilir (paper hesap
bunu emirlerin ~%10'unda bilerek yapar). Kural: kısmen dolmuş alış görülünce
kalanı iptal edilir, emir bitene kadar beklenir ve **dolan adet** pozisyon
olarak işlenir. Kalan alış açıkken satış emri koymak Alpaca'da "wash trade"
diye reddedilebildiği için önce iptal, sonra taban.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.data import senkron
from src.data.alpaca import AlpacaError
from src.data.db import DEFAULT_DB_PATH, connect, read_bars
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
    veri_db: Path = DEFAULT_DB_PATH   # barların ortak deposu (araştırmayla aynı)
    dur_dosyasi: Path = REPO_ROOT / "data" / "DUR"
    duraklat_dosyasi: Path = REPO_ROOT / "data" / "DURAKLAT"   # yeni alım yok, koruma sürer
    kilit_dosyasi: Path = REPO_ROOT / "data" / "dongu.pid"      # döngü ayakta mı / tek örnek
    bayat_bar_siniri: int = 3        # en yeni tam bar bu kadar bardan eskiyse bayat
    # İki bar arası bundan büyük fiyat sıçraması varsa emir yok. Ölçüm
    # (2026-09-19, araştırma dönemi 2016-01 → 2024-06): en büyük sıçrama %13,6
    # (2020-03-16). 2'ye bölünme %50, 4'e bölünme %75 sıçrama yapar.
    sicrama_esigi: float = 0.25
    # Depo bu kadar saatte bir baştan indirilir: bölünmeden önce inmiş barlar
    # düzeltilmiş fiyatla yenilenir (senkron.py). Günde bir kez.
    tam_yenileme_saat: float = 20.0


# Kısmen dolmuş alışın kalanı iptal edilince emrin bitmesi bu kadar beklenir.
KISMI_BEKLEME_SN = 10.0
KISMI_ARALIK_SN = 0.5
bekle = time.sleep           # testler sahte uykuyla değiştirir


@dataclass(frozen=True, slots=True)
class Uyari:
    """Panelin uyarı tablosuna gidecek bir olay. Döngü kaydeder / e-postalar."""

    seviye: str          # D.BILGI | D.UYARI | D.KOTU
    anahtar: str
    konu: str
    mesaj: str = ""


@dataclass
class TurSonucu:
    """Bir turun özeti — log ve test için."""

    ozet: str
    satirlar: list[str] = field(default_factory=list)
    emir_gonderildi: bool = False
    durduruldu: bool = False
    uyarilar: list[Uyari] = field(default_factory=list)

    def yaz(self, satir: str) -> None:
        self.satirlar.append(satir)

    def uyar(self, seviye: str, anahtar: str, konu: str, mesaj: str = "") -> None:
        self.uyarilar.append(Uyari(seviye, anahtar, konu, mesaj))
        self.yaz(f"[{seviye}] {konu}")

    def __str__(self) -> str:
        return "\n".join([self.ozet, *(f"  {s}" for s in self.satirlar)])


# --------------------------------------------------------------- VERİ --

def barlari_getir(
    ayarlar: Ayarlar, simdi: dt.datetime | None = None, *, tam_yenile: bool = False,
) -> pd.DataFrame:
    """Seans filtresinden geçmiş, **yalnızca tamamlanmış** barlar.

    Veri artık doğrudan API'den değil **depodan** gelir. Motor önce depoyu
    tazeler (`senkron.tazele` yalnızca eksiği indirir), sonra okur. Bu, her
    turda 60 günü baştan indirmeyi bitirir: 4 HTTP isteği yerine 1.

    Kararın değişmemesi için iki filtre aynı yerde duruyor:

    * `regular_hours` — seans dışı barlar elenir (09:30–16:00 ET).
    * `biter <= kesim` — `kesim`den sonra kapanan barlar elenir.

    İkinci filtre, `senkron` yarım bar yazmadığı hâlde burada da gerekli:
    `market_data.db` araştırma tarafıyla ORTAK. Araştırma bugüne kadar bar
    indirmiş olabilir, yani depoda `kesim`den yeni barlar bulunabilir. Motor
    onları okursa "bir bar geriden" rejimi bozulur — henüz görmememiz gereken
    fiyatı görmüş oluruz.

    `tam_yenile=True` pencerenin tamamını hemen baştan indirir (sıçrama
    görülünce); aksi halde günde bir kez (`Ayarlar.tam_yenileme_saat`).
    """
    simdi = simdi or dt.datetime.now(dt.timezone.utc)
    kesim = simdi - dt.timedelta(minutes=ayarlar.veri_gecikmesi_dk)
    baslangic = kesim - dt.timedelta(days=ayarlar.gecmis_gun)

    try:
        senkron.tazele(
            [ayarlar.sembol],
            timeframe=ayarlar.timeframe,
            bar_dakika=ayarlar.bar_dakika,
            kesim=kesim,
            db_path=ayarlar.veri_db,
            geriye_gun=ayarlar.gecmis_gun,
            tam_yenileme_saat=0.0 if tam_yenile else ayarlar.tam_yenileme_saat,
        )
    except AlpacaError as exc:
        if "403" in str(exc):
            raise AlpacaError(
                "Alpaca 403 döndü. Anahtarlar yanlış OLMAYABİLİR: ücretsiz planda\n"
                "  SIP verisi 15 dakika gecikmelidir ve sorgu bitişi şimdiye çok\n"
                f"  yakınsa 403 gelir. Şu anki gecikme payı: {ayarlar.veri_gecikmesi_dk} dk."
            ) from exc
        raise

    with connect(ayarlar.veri_db) as conn:
        ham = read_bars(
            conn, ayarlar.sembol,
            timeframe=ayarlar.timeframe,
            start=baslangic.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

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

        # 3) Bekleyen emirlerin akıbeti (dolan varsa duruma işlenir). Kısmen
        #    dolmuş alışın kalanı önce iptal edilir ki dolan adet kesinleşsin.
        _kismi_alislari_sonlandir(conn, broker, sonuc, kuru)
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

        # 6b) FİYAT SIÇRAMASI — hisse bölünmesi ya da bozuk veri. Depoda eski
        #     (bölünme öncesi) ve yeni fiyatlar yan yana durursa kanal saçma
        #     genişler, alış seviyesi piyasanın üstüne çıkıp anında dolar.
        sicrama = _sicrama(barlar, ayarlar)
        if sicrama:
            # Önce depoyu baştan indir: bölünmeyse düzeltilmiş fiyatlar gelir.
            sonuc.yaz(f"sıçrama görüldü ({sicrama}) — depo baştan indiriliyor")
            barlar = barlari_getir(ayarlar, simdi, tam_yenile=True)
            sicrama = _sicrama(barlar, ayarlar) if len(barlar) > ayarlar.kurallar.n else ""
            if not sicrama:
                sonuc.yaz("tam yenilemeden sonra sıçrama kalmadı — devam")
                son_bar_zamani = _iso(barlar["timestamp"].iloc[-1])
        if sicrama:
            sonuc.ozet = f"Fiyat verisinde anormal sıçrama: {sicrama}. Emir gönderilmedi."
            D.sinyal_yaz(conn, bar_zamani=son_bar_zamani, tepe=math.nan,
                         dip=math.nan, alis_seviyesi=math.nan,
                         zarar_stop=math.nan, koruma=math.nan,
                         durum=pozisyon_durumu, aciklama=f"sıçrama: {sicrama}")
            sonuc.uyar(D.KOTU, "fiyat_sicramasi",
                       "Fiyatlarda anormal sıçrama — alış yapılmadı",
                       f"{sicrama}.\nHisse bölünmesi olabilir. Depo günde bir kez "
                       "baştan indiriliyor; düzelmezse scripts/fetch_bars.py ile tüm "
                       "geçmişi yeniden indir.")
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


# ------------------------------------------------------ KORUMA BEKÇİSİ --

def koruma_turu(
    ayarlar: Ayarlar | None = None,
    *,
    broker: Broker | None = None,
    kuru: bool = False,
) -> TurSonucu:
    """Dakikalık hafif tur: elimdeki hisse kadar taban emri borsada mı?

    Saatlik turun aksine bar çekmez, seviye hesaplamaz; taban seviyesi
    kayıttaki (saatlik turun hesapladığı) seviyedir. Boştayken — pozisyon da
    bekleyen alış da yokken — broker'a hiç gitmez.
    """
    ayarlar = ayarlar or Ayarlar()
    sonuc = TurSonucu(ozet="")

    with D.connect(ayarlar.paper_db) as conn:
        if ayarlar.dur_dosyasi.exists():
            sonuc.ozet = "DUR bayrağı var — koruma turu atlandı (acil tur işi)"
            return sonuc

        pozisyon_durumu, adet, son_islenen = D.durum_yukle(conn)
        bekleyen_alis = any(r["tip"] == LIMIT_AL for r in D.bekleyen_emirler(conn))
        if not pozisyon_durumu.acik and not bekleyen_alis:
            sonuc.ozet = "boşta — pozisyon ve bekleyen alış yok"
            return sonuc

        broker = broker or Broker()
        if not broker.borsa_saati().acik:
            sonuc.ozet = "borsa kapalı"
            return sonuc

        onceden_acik = pozisyon_durumu.acik
        _kismi_alislari_sonlandir(conn, broker, sonuc, kuru)
        pozisyon_durumu, adet = _emirleri_isle(conn, broker, pozisyon_durumu, adet, sonuc)
        D.durum_kaydet(conn, pozisyon_durumu, adet=adet, son_islenen_bar=son_islenen)

        if not pozisyon_durumu.acik:
            sonuc.ozet = "pozisyon yok" + (" — alış bekliyor" if bekleyen_alis else "")
            return sonuc

        gercek = broker.pozisyon(ayarlar.sembol)
        gercek_adet = gercek.adet if gercek else 0
        if gercek_adet != adet:
            # Kayıt ile broker ayrıştı (bölünme, elle işlem ...). Yanlış adede
            # ya da bölünme öncesi seviyeye taban koymak zarar verebilir:
            # dokunma, haber ver. Saatlik tur da mutabakatta duracak.
            sonuc.ozet = f"MUTABAKAT BOZUK — broker'da {gercek_adet}, kayıtta {adet} adet"
            sonuc.uyar(D.KOTU, "mutabakat",
                       f"Hisse adedi tutmuyor: broker {gercek_adet}, kayıt {adet}",
                       "Koruma bekçisi emirlere dokunmadı. Elle incelenmeli.")
            sonuc.durduruldu = True
            return sonuc

        _tabani_sagla(conn, broker, ayarlar, pozisyon_durumu, adet,
                      son_islenen or D.simdi_utc(), sonuc, kuru,
                      yeni_pozisyon=not onceden_acik)
        if not sonuc.ozet:
            sonuc.ozet = "taban yerinde: %d adet @ %.2f" % (adet, pozisyon_durumu.stop)
        return sonuc


def _tabani_sagla(
    conn: sqlite3.Connection,
    broker: Broker,
    ayarlar: Ayarlar,
    pozisyon_durumu: Durum,
    adet: int,
    bar_zamani: str,
    sonuc: TurSonucu,
    kuru: bool,
    *,
    yeni_pozisyon: bool,
) -> None:
    """Borsada `adet` hisselik, kayıttaki seviyede tek bir taban emri olsun."""
    seviye = pozisyon_durumu.stop
    if math.isnan(seviye):
        sonuc.uyar(D.KOTU, "taban_seviyesi_yok", "Taban seviyesi bilinmiyor — emir konamadı",
                   "Kayıtta pozisyon açık ama stop seviyesi boş.")
        return

    stoplar = [e for e in broker.bekleyen_emirler(ayarlar.sembol)
               if e.yon == "sell" and e.tip == "stop"]
    mevcut = stoplar[0] if stoplar else None
    for fazla in stoplar[1:]:
        if not kuru:
            broker.emri_iptal(fazla.broker_id)
        sonuc.yaz(f"fazla taban emri iptal: {fazla.client_order_id}")

    if mevcut is not None and _ayni_emir(mevcut, adet, seviye):
        return

    kimlik = _yeni_kimlik(conn, D.emir_kimligi(bar_zamani, STOP_SAT) + "-K")
    if kuru:
        sonuc.yaz("[kuru] taban %s: %d adet @ %.2f" % (
            "düzeltilecekti" if mevcut else "konacaktı", adet, seviye))
        return

    try:
        if mevcut is not None:
            if mevcut.kismi:
                return               # tetiklenmiş, satılıyor — dokunma
            emir = broker.emri_guncelle(mevcut.broker_id, client_order_id=kimlik,
                                        adet=adet, stop=seviye)
        else:
            emir = broker.stop_sat(ayarlar.sembol, adet, seviye, kimlik)
    except BrokerError as exc:
        if mevcut is not None and "422" in str(exc):
            sonuc.yaz(f"taban şu an değiştirilemedi, bir dakika sonra yeniden: {exc}")
            return
        raise

    if mevcut is not None:
        D.emir_durumu_guncelle(conn, mevcut.client_order_id, "degisti")
    D.emir_yaz(conn, client_order_id=kimlik, bar_zamani=bar_zamani, tip=STOP_SAT,
               seviye=seviye, adet=adet, broker_order_id=emir.broker_id)
    sonuc.emir_gonderildi = True

    if mevcut is not None:
        sonuc.uyar(D.UYARI, "taban_duzeltildi",
                   "Taban emri düzeltildi: %d hisse @ %.2f → %d hisse @ %.2f" % (
                       mevcut.adet, mevcut.seviye, adet, seviye),
                   "Borsadaki taban emri elimizdeki hisseyle ya da kayıttaki seviyeyle "
                   "uyuşmuyordu; yerinde güncellendi.")
    elif yeni_pozisyon:
        sonuc.uyar(D.BILGI, "taban_konuldu",
                   "Alış gerçekleşti — %d hisseye taban konuldu @ %.2f" % (adet, seviye))
    else:
        sonuc.uyar(D.UYARI, "taban_yoktu",
                   "Taban emri yoktu! %d hisseye yeniden konuldu @ %.2f" % (adet, seviye),
                   "Pozisyon açıkken borsada taban emri bulunamadı (reddedilmiş, elle "
                   "iptal edilmiş ya da süresi dolmuş olabilir).")


# ------------------------------------------------------------ PARÇALAR --

def _emirleri_isle(
    conn: sqlite3.Connection,
    broker: Broker,
    pozisyon_durumu: Durum,
    adet: int,
    sonuc: TurSonucu,
) -> tuple[Durum, int]:
    """Bekleyen emirlerin broker'daki son halini alır, dolanları duruma işler.

    Yalnızca **bitmiş** emirler işlenir (`Emir.son_halde`); canlı emrin dolan
    adedi henüz kesin değildir. Bitmiş emirde `dolan_adet > 0` ise o kadar
    hisse gerçekten alınmış/satılmıştır — emir iptal edilmiş olsa bile.
    """
    for satir in D.bekleyen_emirler(conn):
        emir = broker.emir_sorgula(satir["client_order_id"])
        if emir is None or not emir.son_halde:
            continue

        dolan = emir.dolan_adet
        if dolan <= 0:
            D.emir_durumu_guncelle(conn, emir.client_order_id,
                                   "degisti" if emir.durum == "replaced" else "iptal")
            sonuc.yaz(f"emir düştü ({emir.durum}): {emir.client_order_id}")
            continue

        D.emir_durumu_guncelle(conn, emir.client_order_id, "dolu")
        D.gerceklesme_yaz(
            conn,
            client_order_id=emir.client_order_id,
            bar_zamani=satir["bar_zamani"],
            tip=satir["tip"],
            istenen_seviye=float(satir["seviye"]),
            gerceklesen_fiyat=emir.dolan_ortalama_fiyat,
            adet=dolan,
        )
        fark = (emir.dolan_ortalama_fiyat / float(satir["seviye"]) - 1) * 100
        kismi = dolan < emir.adet
        sonuc.yaz("DOLDU %s: istenen %.2f → gerçekleşen %.2f (%%%+.3f)%s" % (
            satir["tip"], satir["seviye"], emir.dolan_ortalama_fiyat, fark,
            f" — KISMİ: {dolan}/{emir.adet} adet" if kismi else ""))
        if kismi:
            yon = "Alış" if satir["tip"] == LIMIT_AL else "Satış"
            sonuc.uyar(D.UYARI, "kismi_dolum",
                       f"{yon} emrinin bir kısmı gerçekleşti: {dolan}/{emir.adet} hisse",
                       f"Emir {emir.client_order_id} '{emir.durum}' olarak bitti. "
                       f"Gerçekleşen {dolan} hisse kayda işlendi.")

        if satir["tip"] == LIMIT_AL:
            if pozisyon_durumu.acik:
                adet += dolan        # aynı pozisyona ek dolum — koruma ilkinden
            else:
                # Zararına satış seviyesi emir konurken sabitlenmişti.
                pozisyon_durumu = Durum(
                    acik=True,
                    giris_fiyat=emir.dolan_ortalama_fiyat,
                    stop=float(satir["ek_seviye"]),
                )
                adet = dolan
        else:
            kalan = adet - dolan
            if kalan > 0:
                adet = kalan         # satış kısmen oldu, pozisyon küçüldü
            else:
                pozisyon_durumu = Durum()
                adet = 0

    return pozisyon_durumu, adet


def _son_hali_bekle(broker: Broker, client_order_id: str):
    """İptal istenen emrin bitmesini kısa aralıklarla bekler. Son hali döner."""
    emir = broker.emir_sorgula(client_order_id)
    beklenen = 0.0
    while emir is not None and not emir.son_halde and beklenen < KISMI_BEKLEME_SN:
        bekle(KISMI_ARALIK_SN)
        beklenen += KISMI_ARALIK_SN
        emir = broker.emir_sorgula(client_order_id)
    return emir


def _kismi_alislari_sonlandir(
    conn: sqlite3.Connection, broker: Broker, sonuc: TurSonucu, kuru: bool,
) -> None:
    """Kısmen dolmuş alış emrinin kalanını iptal eder, emrin bitmesini bekler.

    Sonra `_emirleri_isle` dolan adedi kesin olarak işler. Kalan alış açıkken
    taban (satış) emri koymak wash trade diye reddedilebilir; önce iptal.
    """
    for satir in D.bekleyen_emirler(conn):
        if satir["tip"] != LIMIT_AL:
            continue
        emir = broker.emir_sorgula(satir["client_order_id"])
        if emir is None or not emir.kismi:
            continue
        if kuru:
            sonuc.yaz(f"[kuru] kısmen dolmuş alışın kalanı iptal edilecekti "
                      f"({emir.dolan_adet}/{emir.adet})")
            continue
        sonuc.yaz(f"alış kısmen doldu ({emir.dolan_adet}/{emir.adet}) — kalan iptal ediliyor")
        broker.emri_iptal(emir.broker_id)
        son = _son_hali_bekle(broker, emir.client_order_id)
        if son is None or not son.son_halde:
            sonuc.uyar(D.UYARI, "kismi_iptal_bitmedi",
                       "Kısmen dolan alışın iptali bitmedi — bir sonraki geçişte bakılacak",
                       f"Emir {emir.client_order_id}, {KISMI_BEKLEME_SN:.0f} sn sonra "
                       f"hâlâ '{son.durum if son else '?'}'.")


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


def _sicrama(barlar: pd.DataFrame, ayarlar: Ayarlar) -> str:
    """Çizgiyi kuran barlarda iki bar arası anormal sıçrama var mı. Varsa açıklama."""
    son = barlar.iloc[-(ayarlar.kurallar.n + 1):].reset_index(drop=True)
    oran = (son["open"] / son["close"].shift(1) - 1).abs()
    if oran.isna().all() or oran.max() <= ayarlar.sicrama_esigi:
        return ""
    i = int(oran.idxmax())
    return "%s barında önceki kapanış %.2f → açılış %.2f (%%%.0f)" % (
        _ny(son["timestamp"].iloc[i]), son["close"].iloc[i - 1], son["open"].iloc[i],
        oran.iloc[i] * 100)


def _ayni_emir(emir, adet: int, seviye: float) -> bool:
    """Borsadaki emir istenenle aynı mı (fiyat kuruş hassasiyetinde)."""
    return emir.adet == adet and round(emir.seviye, 2) == round(seviye, 2)


def _yeni_kimlik(conn: sqlite3.Connection, temel: str) -> str:
    """Tekrarsız kimlik. `temel` daha önce kullanılmadıysa kendisi; kullanıldıysa
    zaman eki alır (Alpaca, değiştirilmiş emirler dahil kimliği bir kez kabul eder)."""
    if not D.emir_var_mi(conn, temel):
        return temel
    return f"{temel}-{dt.datetime.now(dt.timezone.utc):%y%m%d%H%M%S}"


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
    # DURAKLATMA yalnızca nakitteyken etkilidir: yeni alım yok, borsada bekleyen
    # alış emri de iptal (yoksa duraklatılmış sistem yine de alım yapardı).
    # Pozisyon açıkken aşağıdaki akış aynen çalışır — koruma sürer.
    if not pozisyon_durumu.acik and ayarlar.duraklat_dosyasi.exists():
        _alislari_iptal(conn, broker, ayarlar, sonuc, kuru)
        return

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

    bekleyenler = broker.bekleyen_emirler(ayarlar.sembol)
    yon, broker_tipi = ("buy", "limit") if tip == LIMIT_AL else ("sell", "stop")
    ayni = [e for e in bekleyenler if e.yon == yon and e.tip == broker_tipi]
    mevcut = ayni[0] if ayni else None
    fazlalar = [e for e in bekleyenler if e is not mevcut]

    # Başka tipte kalan emirler (ör. pozisyon açıldı, eski alış duruyor) iptal.
    # Kayıttaki satır "gonderildi" kalır: akıbeti `_emirleri_isle`'de broker'dan
    # okunur — iptal ile dolum yarışırsa dolum kaybolmasın.
    for eski in fazlalar:
        if kuru:
            sonuc.yaz(f"[kuru] iptal edilecekti: {eski.client_order_id}")
            continue
        broker.emri_iptal(eski.broker_id)
        sonuc.yaz(f"iptal: {eski.client_order_id}")

    # Doğru emir zaten borsada duruyorsa DOKUNMA. Her saat iptal + yeniden
    # koymak, iptal sürerken yeni emrin "yetersiz adet" ile reddedilip
    # pozisyonun korumasız kalmasına yol açıyordu.
    if mevcut is not None and _ayni_emir(mevcut, emir_adedi, seviye):
        sonuc.yaz("emir zaten yerinde: %s %d adet @ %.2f" % (tip, mevcut.adet, mevcut.seviye))
        if tip == LIMIT_AL and not kuru:
            D.emir_ek_guncelle(conn, mevcut.client_order_id, ek_seviye=ek,
                               bar_zamani=bar_zamani)
        return
    if mevcut is not None and mevcut.kismi:
        sonuc.yaz(f"emir kısmen dolmakta, dokunulmadı: {mevcut.client_order_id}")
        return

    kimlik = _yeni_kimlik(conn, D.emir_kimligi(bar_zamani, tip))
    eylem = "güncellenecekti" if mevcut is not None else "gönderilecekti"
    ek_metin = f" (dolarsa stop {ek:.2f})" if not math.isnan(ek) else ""
    if kuru:
        sonuc.yaz("[kuru] %s: %s %d adet @ %.2f%s" % (
            eylem, tip, emir_adedi, seviye, ek_metin))
        return

    try:
        if mevcut is not None:
            emir = broker.emri_guncelle(
                mevcut.broker_id, client_order_id=kimlik, adet=emir_adedi,
                **({"limit": seviye} if tip == LIMIT_AL else {"stop": seviye}))
        elif tip == LIMIT_AL:
            emir = broker.limit_al(ayarlar.sembol, emir_adedi, seviye, kimlik)
        else:
            emir = broker.stop_sat(ayarlar.sembol, emir_adedi, seviye, kimlik)
    except BrokerError as exc:
        if "must be unique" in str(exc):
            sonuc.yaz(f"aynı kimlikli emir zaten var, tekrar gönderilmedi: {kimlik}")
            return
        if mevcut is not None and "422" in str(exc):
            # Emir tam o sırada doldu ya da zaten değiştiriliyor. Bir sonraki
            # geçiş (en geç 1 dk, koruma bekçisi) broker'dan son hali okur.
            sonuc.yaz(f"emir şu an değiştirilemedi, sonraki geçişte bakılacak: {exc}")
            return
        raise

    if mevcut is not None:
        D.emir_durumu_guncelle(conn, mevcut.client_order_id, "degisti")
    D.emir_yaz(conn, client_order_id=kimlik, bar_zamani=bar_zamani, tip=tip,
               seviye=seviye, ek_seviye=ek, adet=emir_adedi,
               broker_order_id=emir.broker_id)
    sonuc.emir_gonderildi = True
    if mevcut is not None:
        sonuc.yaz("GÜNCELLENDİ: %s %d adet @ %.2f → %d adet @ %.2f%s" % (
            tip, mevcut.adet, mevcut.seviye, emir_adedi, seviye, ek_metin))
    else:
        sonuc.yaz("EMİR: %s %d adet @ %.2f%s" % (tip, emir_adedi, seviye, ek_metin))


def _alislari_iptal(
    conn: sqlite3.Connection,
    broker: Broker,
    ayarlar: Ayarlar,
    sonuc: TurSonucu,
    kuru: bool,
) -> None:
    """Duraklatmada: borsada bekleyen ALIŞ emirlerini iptal eder, satışlara dokunmaz."""
    alislar = [e for e in broker.bekleyen_emirler(ayarlar.sembol) if e.yon == "buy"]
    for emir in alislar:
        if kuru:
            sonuc.yaz(f"[kuru] duraklatma: iptal edilecekti {emir.client_order_id}")
            continue
        broker.emri_iptal(emir.broker_id)       # akıbeti _emirleri_isle okur
        sonuc.yaz(f"duraklatma: bekleyen alış iptal edildi {emir.client_order_id}")
    sonuc.yaz("DURAKLATILDI — yeni alış emri konmadı (%s var)"
              % ayarlar.duraklat_dosyasi.name)


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
    D.bekleyenleri_kapat(conn, "iptal")   # durum sıfırlanıyor; eski dolumlar işlenmez
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
