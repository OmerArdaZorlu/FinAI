# HANDOFF — 2026-09-20 (üçüncü oturum sonu)

Yeni oturum için durum özeti. Kalıcı kurallar `CLAUDE.md`'de; önce onu, sonra
bunu, sonra `docs/TECH_DEBT.md`'yi oku.

## Kullanıcıyla çalışma

- Sade Türkçe, jargonsuz, kısa. Soru sorulunca cevap ver, kod yazmaya başlama.
- **Anlatım dersi:** tablo/terim işe yaramıyor. İşe yarayan: önce temel (Alpaca'da
  ne duruyor, ne gönderiyoruz), sonra **tek işlemin saat saat zaman çizelgesi**,
  sonra her madde o çizelgeye bağlanarak 2-3 cümle.
- **Panelin asıl kullanıcısı bir yapay zekâ** — Alpaca'nın kendi ekranının yerine
  geçiyor. Arayüz kararlarında ölçüt: "bir yapay zekâ bunu okuyup karar verebilir
  mi". Bu yüzden arayüz terimleri ve terminal komutları İngilizce borsa jargonu.

## Sistem (kısaca)

KABUL-1: AAPL saatlik, Donchian 140 bar. Alış `dip + 0.10×genişlik`, zarar
stopu `dip − 2.00×genişlik`, tepeye değince takip eden stop
`zirve − 1.00×genişlik`. Tek pozisyon, tam hisse, Alpaca **paper**.

## Şu ana kadar yapılanlar (HEPSİ UNCOMMITTED — commit'i kullanıcı yapar)

### Motor ve koruma (önceki oturum)

Dört koruma açığı kapandı: kısmi dolum, tabanın her saat iptal+yeniden
konması, dolumla taban arası boşluk, bölünmenin depoyu bozması. Çözümler
sırasıyla: bitmiş emirde `filled_qty` ile gerçek dolum, **PATCH** ile yerinde
güncelleme (`broker.emri_guncelle`), **dakikada bir koruma bekçisi**
(`motor.koruma_turu`), günlük tam yenileme + >%25 sıçrama kilidi.
Uyarı tablosu (`paper.db → uyarilar`) her müdahaleyi kaydediyor.

**Plandan sapma:** bölünme eşiği "kanal > fiyatın %50'si" değil "iki bar arası
sıçrama > %25" — ölçüm: kanal mart 2020'de %42, en büyük sıçrama %13,6.

### Panel (bu oturum)

- **Ekrana göre yükleme:** açılışta görünen sürenin 2 katı iner; geriye
  sürükleyince bir parça daha. Yıl parçaları ve arkada toplu indirme kalktı.
- **Canlı çizgiler kesintisiz:** motorun çalışmadığı barlarda tepe/dip/alış
  aynı kural fonksiyonlarıyla bar verisinden hesaplanıyor
  (`veri._surekli_cizgiler`); motorun çalıştığı barda motorun değeri geçerli.
- **Alpaca düzeni:** sağda Watchlist (varlık sınıfı gruplu: Stocks, ETFs,
  Commodities, Crypto, Options, Other — `src/arayuz/varlik.py`), grafiğin
  altında Positions ve Orders tabloları (Alpaca'dan salt-okur, 10 sn
  önbellekli; ulaşılamazsa panel çalışmaya devam eder).
- **Bar aralığı:** 1m · 1H · 1D. Kural çizgileri yalnızca 1H'de görünür.
- **Göstergeler** (`static/gosterge.js`): SMA, EMA, Bollinger fiyatın üstüne;
  Volume, RSI, MACD, AO altta ayrı panellerde, ana grafikle eşleşerek kayar.
- **Terminal komutları İngilizce:** `/status`, `/runs`, `/log`, `/alerts`,
  `/pause`, `/resume`, `/flatten confirm`, `/unhalt confirm`, `/help`.
  Eski Türkçe adlar ve "onayla" takma ad olarak çalışıyor.
- **Sürüm kontrolü:** `ARAYUZ_SURUMU` (şu an 5) sayfa ile sunucu arasında
  uyuşmazsa panel "sunucu eski, yeniden başlat" diyor. İki kez eski sunucu
  yüzünden zaman kaybedildi; kod değişince paneli yeniden başlat.

### Veri

- `src/engine/gosterim.py`: panelin gösterdiği seriler (motor sembolü 1Min +
  1Day, izlenenler 1Min + 1Hour + 1Day) her turdan **sonra** tazelenir. Karar
  yolunun dışında, hatası turu etkilemez. Dakikalıkta günlük tam yenileme
  KAPALI (11 yıllık pencere her gün inmesin diye).
- AAPL dakikalık 2016 → 2026-09-18 tamamlandı (1,93 milyon bar). SPY dakikalık
  **inmedi** (DNS hatası), bir dahaki sefere. Depo 315 MB.
- Kullanıcı kararı: dakikalık veri budanmıyor, tamamı saklanıyor.

## Bilinen bulgu — 09:00 saatlik mumu (REGISTRY §6.11)

Depodaki 09:00 saatlik barı seans öncesini (09:00–09:29) içeriyor. Düzeltilince
(`session.acilis_mumu_duzelt`, 1Min barlardan yeniden kuruluyor) sabit eşik
9.9004 → 9.70, eğitimli 6.29 → 6.12. KABUL-1 kararı değişmiyor. **Motor hâlâ
düzeltilmemiş barla çalışıyor** — düzeltmenin canlıya alınıp alınmayacağı
karar bekliyor.

## Doğrulama durumu

297 test yeşil · parite 9.9004 / 28, parmak izi `d1e6ef7289d0e7f5` ·
panel headless Chrome'da DevTools ile tıklanarak denendi (aralık geçişleri,
yedi gösterge, tablolar), konsolda hata yok.

## SIRADAKİ İŞ — canlı UI testi (borsa 16:30 TR'de açılır)

1. `.env`: `ARAYUZ_ANAHTARI`, isteğe bağlı `SMTP_*`, `ALARM_ALICI`.
2. `python -m src.engine.dongu` + `python -m src.arayuz`.
3. İlk tur 16:20 TR (13:20 UTC) sonrası: panelde alış seviyesi, `/status`'ta
   alış emri bekliyor, Orders tablosunda görünüyor.
4. Alış dolunca **1 dakika içinde**: Alerts'te "N hisseye taban konuldu",
   `/status` → koruyucu stop borsada, Positions tablosunda pozisyon.
5. Kısmi dolumda: Alerts'te "bir kısmı gerçekleşti", pozisyon adedi = broker adedi.
6. Sonraki turlar: seviye değişmediyse iptal/yeni emir yok; takip stop yükselince
   "GÜNCELLENDİ".
7. `/pause` → bekleyen alış iptal; `/resume`.
8. Pozisyon açıkken `/flatten confirm` → 5 sn içinde kapanır, sonra `/unhalt confirm`.

**Canlıda ilk kez görülecek:** PATCH'in Alpaca'daki gerçek davranışı, kısmi
dolumda iptal süresi, wash trade reddi.

## Açık kararlar (hâlâ verilmedi)

Kasa (2024-07 →) açılsın mı · 09:00 düzeltmesi motora girsin mi · paper koşusu
bitiş kriteri · eşik yenileme kuralı · REGISTRY borcu (~6 deney kaydedilmedi,
sayaç güncel değil — TD-14) · TD-09 kalanı (günlük zarar / maruziyet /
emir-oranı limitleri) · tüm dönemde al-tut farkının neden kapandığının ölçümü.
