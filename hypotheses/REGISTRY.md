# Hipotez ve Kabul Kaydı

Bu dosya projenin **hafızasıdır**: ne varsaydık, neyi test ettik, ne çıktı.
ARCHITECTURE.md §7.4'teki deneme sayacı da burasıdır.

**Değişmez kural: hiçbir kayıt silinmez.** Reddedilen hipotezler, başarısız
denemeler ve tüm sonuçlar kalır. Kaç deneme yaptığımızı bilmek, kalan
sonuçların şans olup olmadığını anlamanın tek yolu.

Yeni bir hipotez **test edilmeden önce** buraya yazılır.

## Nasıl okunur

Her maddenin bir etiketi var:

| etiket | anlamı |
|---|---|
| **Genel kabul** | Piyasada yaygın görüş. Bizim verimizle **test edilmedi**. Hangi tipe hangi yöntemin deneneceğine yol gösterir, sonucun yerine geçmez. |
| **Gözlem** | Bizim deneyimizde görüldü. Sadece o sembol ve o dönem için geçerli. |
| **Hipotez** | Test edilecek iddia. Kabul ya da red, önceden yazılan kritere göre verilir. |

Veri: 2016-01 → 2024-06 (araştırma alanı). 2024-07 → 2026-09 arası saklanan
veri (kasa) **hiç açılmadı**.

---

## 1. Varlık tipleri ve genel kabuller

Her sembol eklenirken, sonuçlarına bakılmadan, bir tipe atanır.

| tip | örnek semboller | genel kabul | bizim verimizde | durum |
|---|---|---|---|---|
| Geniş endeks fonu | **SPY**, QQQ, VOO | Uzun vadede yükselir (SPY'ın uzun dönem ortalaması yılda ~%10). Basit al-sat kurallarının maliyetten sonra "al ve bekle"yi geçmesi zordur. | SPY 2016-2024: yılda ~%14, 1 lira → 3.12 | kısmen gözlendi (SPY) |
| Büyük büyüme hissesi | **AAPL**, MSFT, NVDA | Uzun vadede güçlü yükseliş eğilimi. Trendi takip eden yöntemler daha uygun kabul edilir. Bilanço açıklama günlerinde sert sıçrama olur. | AAPL 2016-2024: 1 lira → 8.95 | kısmen gözlendi (AAPL) |
| Tahvil fonu | TLT, IEF | Faize duyarlı: faiz artınca düşer. Uzun yatay dönemler olabilir. | veri yok | test edilmedi |
| Altın | GLD | Uzun yatay dönemler geçirir. Kriz ve enflasyon dönemlerinde yükselme eğilimi. | veri yok | test edilmedi |
| Döngüsel sektör fonu | XLE, XLB | Emtia fiyatlarına bağlı, inişli çıkışlı. Uzun yatay ya da düşüş dönemleri olur. | veri yok | test edilmedi |
| Çok oynak tek hisse | TSLA | Büyük dalgalanma. Kanallar geniş olur, zararına satışlar sık tetiklenir. | veri yok | test edilmedi |

### Stratejiler hakkında genel kabuller

| # | genel kabul | bizim sonuçlarla uyumlu mu |
|---|---|---|
| K-1 | **Range trading** (dipte al, tepede sat) fiyatın **yatay** gittiği piyasalarda işe yarar, güçlü yükselişte ya da düşüşte yaramaz. | Uyumlu. SPY ve AAPL güçlü yükseldi, sistem geride kaldı. Yatay bir varlıkla henüz test edilmedi (H-002). |
| K-2 | **Trend takibi** (takip eden stop, kırılımda alma) güçlü trendli varlıklarda daha iyi çalışır. | Uyumlu. Takip eden stop, AAPL'da sistemi al-tut seviyesine taşıdı. |
| K-3 | Çok sık işlem yapan sistemlerde kazancı **maliyet** yer. | Uyumlu. 1 günlük çizgide 1230 işlem, 1 lira 1.91'den 0.56'ya düştü. |

---

## 2. Veri bölme kuralı: varlık tipine göre

Kullanıcı kararı (2026-09-11). Sadece veriye bakmak bizi yanıltabiliyor. Bu
yüzden model eğitimi ve kural seçimi varlık tipine göre bölünür:

1. **Her sembol bir tipe atanır** (bölüm 1'deki tablo). Atama sembol eklenirken
   yapılır, sonuçlara bakılarak değiştirilmez.
2. **Kurallar ve modeller tip bazında eğitilir ve seçilir.** Bir tipte seçilen
   kural (ör. takip mesafesi) başka bir tipe taşınmaz.
3. **Tip içinde zaman bölmesi aynı kalır:** araştırma 2016-01 → 2024-06, kasa
   2024-07 sonrası ve tek sefer. Eğitim/test yıl yıl ileri yürür: her yıl
   sadece önceki yıllarla eğitilir.
4. **Genel kabuller hangi tipe hangi yöntemin öncelikle deneneceğini
   belirler.** Ama kabul sonucu değiştirmez: her kabul bir hipotez olarak
   yazılır ve test edilir.
5. **Bir kural "tip kuralı" sayılmadan önce o tipten en az 3 sembolde test
   edilir.** Şu an her tipte 1 sembol var, bu yüzden sonuçlar "SPY için" ve
   "AAPL için" diye okunur, "tüm fonlar" ya da "tüm hisseler" diye değil.

---

## 3. Bizim gözlemlerimiz

Hepsi SPY ve AAPL, 2016-01 → 2024-06, maliyet her alış ve satışta %0.05.

| # | gözlem |
|---|---|
| G-1 | "Tepede sat" kuralıyla range trading, **hiçbir ayarda** al-tut'u geçemedi (SPY ve AAPL, günlük ve saatlik, 1 günden 5 aya kadar çizgi süreleri). |
| G-2 | **Ezberleme (overfit) görülmedi.** Sistemin eğitimdeki ve testteki yıllık getirisi birbirine yakın (günlük %5.3 / %3.3, saatlik %3.6 / %6.0). Sorun eğitimde değil, sistem eğitim verisinde bile al-tut'un gerisinde. |
| G-3 | **Aynı riskle bile geride.** Paranın sadece %30'unu SPY'da tutmak 1 lira → 1.45 ve en fazla %11 erime veriyor. Sistem (zamanın %30'unda piyasada) 1.03 ve %31 erime. |
| G-4 | Çizgi kısaldıkça işlem sayısı artıyor, **maliyet kazancı yiyor**. Çizgi uzadıkça sistem zamanın ~%75'inde nakitte kalıyor. |
| G-5 | Yükselişte fiyat tepe çizgisine yapışık gidiyor, dibe hiç inmiyor. "Dipte al" kuralı rallinin tamamını kaçırıyor (grafik: defter bölüm 7). |
| G-6 | **Takip eden stop** sonucu belirgin iyileştirdi (SPY eğitim/test 1.06 → 1.78). Ama iyileşme **piyasada daha uzun kalmaktan** geliyor. Takip mesafesi genişledikçe sistem %90-98 piyasada kalıyor ve al-tut'a dönüşüyor. |
| G-7 | **Düşüşte koruma yok.** 2022'de piyasa %18 düştü, sistemlerin çoğu da o kadar kaybetti. En büyük erime al-tut ile aynı (%35-39). Tek istisna 50 günlük çizgi (2022'de -%0.7), ama aynı sistem 2018'de piyasadan kötü (-%11.7'ye karşı -%5). |
| G-8 | **Dönem uyarısı.** SPY bu dönemde yılda ~%14 yükseldi, uzun dönem ortalamasının (~%10) üstünde. "Sorun seçilen hissede" sonucu AAPL için olduğu kadar SPY için de geçerli olabilir. Yatay seyreden bir varlıkla henüz karşılaştırılmadı (H-002). |
| G-9 | Günlük barlar sadece borsa saatlerini (09:30-16:00) kapsıyor. Saatlik veride gece saatleri atılmalı; atılmazsa kanal çizgilerini hacmi çok düşük gece barları belirliyor. |

---

## 4. Hipotezler

### H-001: Kanal konumu (range trading / mean reversion)

- **Kayıt:** 2026-09 (önceki konuşmada tasarlandı)
- **İddia:** Fiyat son N günün kanalının dibine yakınken ertesi gün getirisi
  ortalamanın üstünde, tepeye yakınken altındadır.
- **Çizgiler:** Donchian kanalı: son N barın en yüksek ve en düşük fiyatı,
  sadece geçmişe bakarak.
- **Kriter (önceden yazıldı):** sıra korelasyonu (rho) negatif,
  `p < 0.05 / 6 = 0.00833` ve `|rho| ≥ 0.05`.
- **Kod:** `lab/h001.py`, `lab/h001_daily.ipynb`, `lab/h001_hourly.ipynb`
- **Durum: REDDEDİLDİ** (günlük ve saatlik). İşaret doğru yönde ama etki
  eşiğin altında, büyük kısmı 2020-2021'den geliyor.

### H-001-B: Kanal arasında al-sat (backtest)

- **Kayıt:** 2026-09-11
- **İddia:** Fiyat son N günün en düşüğüne yaklaşınca alıp, en yükseğine
  değince (ya da dibin epey altına inince) satan sistem, al-tut'tan fazla
  kazandırır.
- **Kod:** `lab/backtest.py`, `lab/h001_backtest.ipynb`
- **Durum: REDDEDİLDİ.** Hiçbir sürüm, tüm dönemde ve eğitim/testte al-tut'u
  geçemedi (sonuçlar bölüm 6'da).

### H-001-C: Bollinger + takip eden stop

- **Kayıt:** 2026-09-11 (kullanıcının seçimi)
- **İddia:** Ortalamayı takip eden bant (Bollinger) ve tepede satmak yerine
  takip eden stop kullanan sistem, al-tut'tan fazla kazandırır.
- **Durum: KARARSIZ.** SPY'da geçemedi. AAPL'da az farkla geçti, ama bunu
  al-tut'a dönüşerek (%90+ piyasada kalarak) ve 8.5 yılda az sayıda işlemle
  yaptı. ~70 ayar denendikten sonra bu kadar küçük bir fark şans olabilir
  (bölüm 5).
- **Güncelleme 2026-09-11:** kullanıcı kararıyla AAPL sürümü **şimdilik kabul
  edildi** → aşağıda KABUL-1. SPY için durum kararsız kalıyor.

### KABUL-1: AAPL, eski çizgi + takip eden stop (şimdilik kabul)

- **Ayrıntılı dosya:** [KABUL-1_AAPL_takip_eden_stop.md](KABUL-1_AAPL_takip_eden_stop.md)
  (hipotez, kod, her yıl seçilen değerler, test yılı işlemleri, hangi
  koşullarda kâr ettirdiği)
- **Karar:** 2026-09-11, kullanıcı. Baseline'ı eğitim/testte geçen tek sistem.
- **Sembol ve tip:** AAPL, büyük büyüme hissesi.
- **Kurallar:**
  - **Çizgiler:** son 20 günün en yüksek ve en düşük fiyatı (günlükte 20 bar,
    saatlikte 140 bar). Sadece önceki barlardan hesaplanır.
  - **Al:** fiyat dipten, iki çizgi arasındaki mesafenin %10'u kadar yukarıya
    inince.
  - **Zararına sat:** alırken belirlenen seviye. Eğitim çoğu yıl dipten 2
    genişlik aşağısını seçti; bazı yıllarda çeyrek genişlik.
  - **Tepede satma:** fiyat tepe çizgisine değince satılmaz, takip eden stop
    devreye girer.
  - **Takip eden stop:** o andan sonra görülen en yüksek fiyattan, tepeye
    değildiği andaki genişliğin **1 katı** kadar düşerse sat. Eğitim her yıl
    1 katı seçti. Seviye sadece yukarı gider.
  - Her alış ve satışta %0.05 maliyet.
- **Sonuç** (eğitim/test 2019 → 2024-06, eşikler her yıl sadece önceki
  yıllardan seçildi, 1 lira →):

  | | sistem | baseline | baseline'ı geçtiği yıl |
  |---|---|---|---|
  | günlük | **5.80** | 5.63 | 6 yılın 4'ü |
  | saatlik | **6.29** | 5.61 | 6 yılın 5'i |

  Aynı eşikler sabit tutularak tüm dönem (2016 → 2024-06):

  | | 1 lira → | baseline | en büyük erime | baseline erime | piyasada | işlem |
  |---|---|---|---|---|---|---|
  | günlük | 10.44 | 8.94 | %38.2 | %38.5 | %90 | 28 |
  | saatlik | 9.90 | 9.13 | %38.3 | %38.7 | %91 | 28 |

  | yıl | günlük | saatlik | baseline |
  |---|---|---|---|
  | 2019 | +80.9% | +106.6% | +88.6% |
  | 2020 | +92.7% | +89.4% | +82.1% |
  | 2021 | +20.3% | +21.1% | +34.5% |
  | 2022 | **-20.8%** | **-21.4%** | -26.5% |
  | 2023 | +53.6% | +49.6% | +48.9% |
  | 2024 (Haz) | +13.8% | +12.9% | +11.4% |

  2022 düşüş yılında piyasadan ~5 puan az kaybetti.
- **Aynı dönemde yakın sonuç veren diğer sürüm:** AAPL günlük Bollinger +
  takip eden stop, eğitim/test 6.10 (6 yılın 3'ü).
- **Kabulün sınırları** (kabul ile birlikte yazıldı):
  - Sadece **AAPL için** geçerli. Bölüm 2 kural 5'e göre "büyük büyüme
    hissesi" tipinin kuralı sayılması için aynı tipten en az 3 sembolde
    (ör. MSFT, NVDA) test edilmeli.
  - Fark küçük (günlükte +%3, saatlikte +%12, 5.5 yılda) ve ~71 denemeden
    sonra geldi (bölüm 5).
  - Sistem zamanın ~%90'ında piyasada. Kazancın çoğu al-tut ile aynı
    kaynaktan geliyor, fark satıp geri alma anlarından. En büyük erime
    baseline ile neredeyse aynı (%38 / %39): düşüşe karşı belirgin koruma yok.
  - 8.5 yılda sadece 28 işlem.
  - Önceden yazılmış bir kabul kriteri yoktu; kabul sonuç görüldükten sonra
    verildi.
  - Saklanan veride (2024-07 sonrası) ve sanal hesapta henüz denenmedi.
- **Kabulü doğrulayacak sonraki adımlar:** aynı tipten 2+ sembolde aynı
  eğitim/test; sonra sanal hesap (ENV-B). Bunlarda baseline'ın altında
  kalırsa kabul geri çekilir ve bu kayıt silinmez, durumu güncellenir.

### H-002: Range trading varlık tipine bağlıdır

- **Kayıt:** 2026-09-11, **test edilmedi**
- **İddia:** Dipte al, tepede sat sistemi uzun vadede güçlü yükselen
  varlıklarda (SPY, AAPL) al-tut'u geçemez, ama yatay seyreden varlık
  tiplerinde (ör. altın, tahvil fonu, döngüsel sektör fonu) geçer.
- **Dayanak:** Genel kabul K-1, gözlemler G-1, G-5, G-8.
- **Test planı:** Her tipten en az 3 sembol indirilir (Alpaca, `scripts/fetch_bars.py`).
  Aynı sistem, aynı dönem, eğitim/test tip bazında. Sistemin tipler
  arasında farklı sonuç vermesi gerekir.
- **Kriter (test öncesi doldurulacak):** —

### H-003: Şirket açıklamaları ikinci bir karar mekanizması olabilir

- **Kayıt:** 2026-09-11 (kullanıcının fikri), **test edilmedi**
- **İddia:** Şirketlerin resmi açıklamaları (SEC EDGAR, KAP'ın ABD karşılığı)
  hisse fiyatının **açıklamadan sonraki 1-2 gün** içindeki hareketi hakkında
  bilgi taşır. İlk dakikalardaki sıçramayı kaçırsak bile hareketin genel
  yönünü yakalayabiliriz. Bu açıklamalardan üretilen sinyal, ikinci bir karar
  mekanizması olarak fiyat sisteminin yanına eklenebilir.
- **Ölçülecek soru:** Açıklamadan sonraki ilk tepkiden sonra fiyat 1-2 gün
  **aynı yönde devam ediyor mu?** Devam ediyorsa ilk dakikaları kaçırmak
  sorun değil; ilk tepkide duruyorsa yakalanacak bir hareket kalmıyor.
- **Kaynak:** SEC EDGAR. Resmi ve ücretsiz. Yeni açıklama akışı ve geçmiş
  arşiv var, kazıma (scraping) yerine resmi uç noktalar kullanılır.
  - **8-K:** önemli olay bildirimi (KAP'taki özel durum açıklaması gibi).
    İçindeki madde numaraları olayın türünü söyler: 2.02 = finansal sonuç,
    5.02 = üst yönetici ayrılığı, 1.01 = önemli anlaşma.
  - **Form 4:** şirket yöneticilerinin kendi hisselerini alıp satması.
  - **10-Q / 10-K:** çeyreklik ve yıllık raporlar.
- **Mimaride yeri:** ARCHITECTURE.md §7.1'deki ikinci model. Hedefi (kısa
  vade) fiyat sisteminden farklı olduğu için ayrı model olur (§7.2), ikisi
  orkestratörde birleşir (§7.3).
- **Tip notu:** EDGAR'a şirketler açıklama yapar. SPY gibi endeks fonlarının
  8-K'sı yoktur, onları makro haberler (faiz kararı, enflasyon verisi)
  etkiler. Bu yüzden H-003 önce "büyük büyüme hissesi" tipinde (AAPL)
  denenir.
- **Bilinen riskler (test öncesi yazıldı):**
  - **Hız:** büyük kurumlar açıklamalara saniyeler içinde tepki veriyor.
    İlk dakikalardaki hareket bizim için kayıp kabul edilir. Denenecek ufuk
    (kullanıcı, 2026-09-11): açıklamadan sonraki **1-2 gün**. Giriş, ilk
    tepkiden sonraki ilk bardan yapılır.
  - **Geçmiş testte sızıntı:** her açıklamanın EDGAR'a **kabul edildiği an**
    (acceptance time) kullanılır, açıklamanın tarihli olduğu gün değil.
    Borsa kapandıktan sonra gelen açıklama ancak ertesi gün işleme girer.
  - **Tek hisse:** tek bir şirketin yılda yayınladığı 8-K sayısı onlarla
    sınırlı (AAPL için henüz sayılmadı). Sonuca güvenmek için birden fazla
    hisse gerekir.
- **Kriter (test öncesi doldurulacak):** —

---

## 5. Deneme sayacı

Tüm döneme bakılarak sonucu görülen ayarlar. Eğitim/test içindeki seçimler
(her yıl 12-36 ayar) buna dahil değil.

| tarih | deney | denenen ayar | sonuç |
|---|---|---|---|
| 2026-09-09 | H-001 ölçüm, günlük (N = 20, 50, 100 gün) | 3 | reddedildi |
| 2026-09-09 | H-001 ölçüm, saatlik (N = 20, 50, 100 gün) | 3 | reddedildi |
| 2026-09-11 | Al-sat, 1 hafta, günlük ve saatlik | 2 | al-tut'un altında |
| 2026-09-11 | Eşik tablosu (3 alım × 4 stop), günlük ve saatlik | 24 | hepsi al-tut'un altında |
| 2026-09-11 | Kısa çizgiler, saatlik (1, 2, 3 gün) | 3 | al-tut'un altında |
| 2026-09-11 | Uzun çizgiler, günlük (10, 20, 50, 100 gün) | 4 | al-tut'un altında |
| 2026-09-11 | 4 sürüm × SPY/AAPL × günlük/saatlik | 16 | SPY altında, AAPL tüm dönemde altında |
| 2026-09-11 | Takip mesafesi tablosu (4 mesafe × 2 çizgi × 2 sembol) | 16 | geniş mesafede al-tut'a dönüşüyor |
| | **Toplam** | **~71** | |

**Bu sayının anlamı (ARCHITECTURE.md §7.4):** tamamen değersiz 50 strateji
denendiğinde, aralarındaki en iyisi şans eseri iyi görünür. ~71 denemeden
sonra al-tut'u küçük farkla geçen bir sonuç, ek kanıt olmadan "çalışıyor"
sayılmaz.

---

## 6. Tüm sonuçlar

Aksi yazmadıkça: SPY, maliyet her alış ve satışta %0.05, "1 lira →" başlangıçtaki
1 liranın dönem sonundaki değeri.

### 6.1 H-001 ölçüm: günlük (`lab/h001_daily.ipynb`)

Baseline: ortalama günlük getiri %0.060, günlerin %51.7'sinde yükseliş.

| N (gün) | rho | p | geçti mi |
|---|---|---|---|
| 20 | -0.041 | 0.067 | hayır |
| 50 | -0.046 | 0.039 | hayır |
| 100 | -0.038 | 0.084 | hayır |

| alt dönem (N=20) | rho |
|---|---|
| 2016-2019 | -0.057 |
| 2020-2021 | -0.117 |
| 2022-2024H1 | +0.011 |

Walk-forward katları (N=20): -0.033, -0.087, **-0.146** (tek anlamlı, 2020-06 → 2021-10), -0.007, -0.017.
Stres: covid çöküşü +0.016, 2022 ayı piyasası -0.023.

### 6.2 H-001 ölçüm: saatlik (`lab/h001_hourly.ipynb`)

Sadece borsa saatleri. Baseline: 7 bar sonrası ortalama getiri %0.060, %52.4 yükseliş.

| N (bar) | rho | p | geçti mi |
|---|---|---|---|
| 140 (20 gün) | -0.032 | 0.144 | hayır |
| 350 (50 gün) | -0.042 | 0.060 | hayır |
| 700 (100 gün) | -0.038 | 0.089 | hayır |

| alt dönem (N=140) | rho |
|---|---|
| 2016-2019 | -0.060 |
| 2020-2021 | -0.093 |
| 2022-2024H1 | +0.021 |

Walk-forward katları: -0.029, -0.080, **-0.130** (2020-06 → 2021-10), +0.010, -0.007.
Stres: covid çöküşü +0.058, 2022 ayı piyasası +0.019.

### 6.3 Al-sat, 1 haftalık çizgi (`lab/h001_backtest.ipynb` bölüm 2-3)

Eşikler: alım = dipten kanal genişliğinin %10'u yukarısı, stop = dipten
genişliğin yarısı aşağısı.

| | günlük | saatlik | al-tut |
|---|---|---|---|
| 1 lira → | 1.03 | 1.11 | 3.12 |
| maliyet olmasa | 1.30 | 1.46 | 3.12 |
| en büyük erime | %31 | %45 | %34 |
| işlem | 237 | 277 | 1 |
| stopla kapanan | 123 | 136 | — |
| piyasada | %30 | %39 | %100 |

Maliyet duyarlılığı (günlük / saatlik): %0 → 1.30 / 1.46, %0.01 → 1.24 / 1.39,
%0.02 → 1.18 / 1.31, %0.05 → 1.03 / 1.11.

### 6.4 Eşik tablosu (bölüm 4)

| | stop 0.25 | stop 0.50 | stop 1.00 | stop yok |
|---|---|---|---|---|
| günlük, alım 0.05 | 0.89 | 1.02 | 1.17 | 1.44 |
| günlük, alım 0.10 | 0.91 | 1.03 | 1.10 | 1.45 |
| günlük, alım 0.20 | 0.86 | 1.08 | 1.17 | 1.57 |
| saatlik, alım 0.05 | 0.81 | 1.11 | 1.05 | 1.40 |
| saatlik, alım 0.10 | 0.89 | 1.11 | 1.19 | 1.43 |
| saatlik, alım 0.20 | 1.08 | 1.28 | 1.29 | 1.49 |

### 6.5 Eğitim/test, 1 haftalık çizgi (bölüm 5)

Her yıl eşikler sadece önceki yıllardan seçildi, o yılda denendi.

| test yılı | günlük sistem | saatlik sistem | al-tut |
|---|---|---|---|
| 2019 | +8.8% | +10.2% | +31.0% |
| 2020 | -6.2% | -3.6% | +18.3% |
| 2021 | +19.8% | +19.6% | +28.5% |
| 2022 | -17.8% | -19.3% | -18.3% |
| 2023 | +3.0% | +8.7% | +26.1% |
| 2024 (Haz) | +5.7% | +9.6% | +15.6% |
| **1 lira →** | **1.09** | **1.22** | **2.37** |

Eğitim her yıl en uzak stop seçeneğini seçti. Yıllık getiri eğitimde / testte:
günlük %5.3 / %3.3, saatlik %3.6 / %6.0.

### 6.6 Kısa çizgiler, saatlik (bölüm 6)

| çizgi | işlem | 1 lira → | maliyet olmasa | eğitim/test | al-tut'u geçtiği yıl |
|---|---|---|---|---|---|
| 1 gün | 1230 | 0.56 | 1.91 | 1.06 | 6'da 1 |
| 2 gün | 676 | 0.73 | 1.43 | 0.96 | hiç |
| 3 gün | 471 | 1.16 | 1.85 | 1.16 | 6'da 1 |
| 5 gün | 277 | 1.11 | 1.46 | 1.22 | hiç |
| al-tut | 1 | 3.12 | 3.12 | 2.37 | — |

### 6.7 Uzun çizgiler, günlük (bölüm 7)

| çizgi | işlem | 1 lira → | maliyet olmasa | eğitim/test | al-tut'u geçtiği yıl |
|---|---|---|---|---|---|
| 5 gün | 237 | 1.03 | 1.30 | 1.09 | 6'da 1 |
| 10 gün | 121 | 1.14 | 1.29 | 1.15 | hiç |
| 20 gün | 61 | 1.21 | 1.29 | 1.06 | hiç |
| 50 gün | 21 | 1.20 | 1.22 | 1.20 | 6'da 1 |
| 100 gün | 8 | 1.13 | 1.14 | 1.23 | 6'da 1 |

Yıl yıl (1 haftalık çizgi, günlük): sistem 9 yılın sadece birinde (2022)
al-tut'u geçti.

| yıl | 5 gün | 10 gün | 20 gün | 50 gün | 100 gün | al-tut |
|---|---|---|---|---|---|---|
| 2016 | +10.7% | +2.3% | +8.7% | +7.7% | 0.0% | +13.0% |
| 2017 | +7.6% | +3.3% | -1.2% | -2.3% | 0.0% | +21.7% |
| 2018 | -11.5% | +6.9% | +2.6% | -11.7% | +0.6% | -5.0% |
| 2019 | +11.8% | +6.3% | +3.6% | +12.8% | +12.7% | +31.1% |
| 2020 | -10.4% | -3.9% | +8.3% | +6.7% | +12.5% | +18.5% |
| 2021 | -1.8% | +11.8% | +5.8% | +4.9% | 0.0% | +28.6% |
| 2022 | -11.3% | -17.0% | -20.1% | -0.7% | -18.5% | -18.2% |
| 2023 | +8.6% | +6.7% | +14.4% | +2.6% | +8.4% | +26.2% |
| 2024 (Haz) | +2.9% | -0.4% | +1.3% | 0.0% | 0.0% | +15.7% |

### 6.8 Bollinger + takip eden stop, SPY ve AAPL (bölüm 8)

Günlükte 20 bar, saatlikte 140 bar. Takip mesafesi varsayılanı: genişliğin yarısı.

| sembol | veri | sürüm | işlem | 1 lira → | en büyük erime | eğitim/test | al-tut'u geçtiği yıl |
|---|---|---|---|---|---|---|---|
| SPY | günlük | eski çizgi + tepede sat | 61 | 1.21 | %30 | 1.06 | hiç |
| SPY | günlük | eski çizgi + takip eden stop | 56 | 1.87 | %31 | 1.81 | 6'da 1 |
| SPY | günlük | Bollinger + tepede sat | 81 | 1.27 | %35 | 1.05 | hiç |
| SPY | günlük | Bollinger + takip eden stop | 75 | 2.20 | %32 | 1.79 | 6'da 2 |
| SPY | saatlik | eski çizgi + tepede sat | 66 | 1.27 | %33 | 1.12 | hiç |
| SPY | saatlik | eski çizgi + takip eden stop | 62 | 1.89 | %35 | 1.81 | 6'da 1 |
| SPY | saatlik | Bollinger + tepede sat | 111 | 1.29 | %35 | 1.23 | hiç |
| SPY | saatlik | Bollinger + takip eden stop | 109 | 1.75 | %36 | 1.72 | 6'da 1 |
| AAPL | günlük | eski çizgi + tepede sat | 52 | 0.80 | %53 | 1.35 | 6'da 1 |
| AAPL | günlük | eski çizgi + takip eden stop | 51 | 1.82 | %35 | 5.80 | 6'da 4 |
| AAPL | günlük | Bollinger + tepede sat | 70 | 0.88 | %42 | 1.48 | 6'da 1 |
| AAPL | günlük | Bollinger + takip eden stop | 68 | 2.13 | %38 | 6.10 | 6'da 3 |
| AAPL | saatlik | eski çizgi + tepede sat | 58 | 1.06 | %46 | 1.26 | 6'da 1 |
| AAPL | saatlik | eski çizgi + takip eden stop | 56 | 3.03 | %36 | 6.29 | 6'da 5 |
| AAPL | saatlik | Bollinger + tepede sat | 98 | 0.96 | %49 | 1.63 | 6'da 1 |
| AAPL | saatlik | Bollinger + takip eden stop | 97 | 1.73 | %42 | 4.86 | 6'da 3 |

Al-tut: SPY tüm dönem 3.12 (erime %34), eğitim/test 2.37. AAPL tüm dönem
8.94 (erime %39), eğitim/test 5.63.

**Davranış listesi** (sürüm ve eşikler her yıl sadece eğitimden seçildi):

| | seçilen sürüm | eğitim/test 1 lira → | al-tut |
|---|---|---|---|
| SPY günlük | Bollinger + takip eden stop (her yıl) | 1.78 | 2.37 |
| SPY saatlik | eski çizgi + takip eden stop (her yıl) | 1.81 | 2.37 |
| AAPL günlük | eski çizgi + takip eden stop (her yıl) | 5.80 | 5.63 |
| AAPL saatlik | eski çizgi + takip eden stop (her yıl) | 6.29 | 5.61 |

Eğitim her yıl en geniş takip mesafesini (1.0) seçti.

**Takip mesafesi ve piyasada kalma** (günlük, eski çizgi, alım 0.10, stop 2.0):

| takip mesafesi | SPY piyasada | SPY 1 lira → | AAPL piyasada | AAPL 1 lira → |
|---|---|---|---|---|
| 0.5 | %67 | 1.95 | %62 | 3.49 |
| 1.0 | %90 | 2.56 | %90 | 10.44 |
| 2.0 | %98 | 3.37 | %98 | 11.22 |
| 4.0 | %99 | 3.36 | %99 | 10.12 |
| al-tut | %100 | 3.12 | %100 | 8.94 |
