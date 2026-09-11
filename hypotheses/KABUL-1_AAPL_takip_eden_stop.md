# KABUL-1: AAPL, eski çizgi + takip eden stop

> **Durum:** ✅ şimdilik kabul (kullanıcı kararı, 2026-09-11)
> **Ana kayıt:** [REGISTRY.md](REGISTRY.md) → H-001-C ve KABUL-1
> **Defter:** [lab/KABUL-1_AAPL_takip_eden_stop.ipynb](../lab/KABUL-1_AAPL_takip_eden_stop.ipynb) — adım adım, grafikli; diğer hipotezler için şablon
> **Veri:** AAPL, 2016-01 → 2024-06. 2024-07 sonrası saklanan veri açılmadı.

---

## 1. Hipotez

**AAPL'da fiyat son 20 günün en düşük seviyesine yaklaşınca alıp, tepeye
değince hemen satmak yerine takip eden stopla çıkan sistem, hisseyi alıp
beklemekten (baseline) fazla kazandırır.**

Nereden geldi:
1. H-001 / H-001-B: "dipte al, tepede sat" sistemi hiçbir ayarda baseline'ı
   geçemedi. Sebep: tepede satınca yükselişin geri kalanı kaçıyordu.
2. Kullanıcının önerisi: tepeye gelince satma, takip eden stop kullan.
3. SPY ve AAPL'da 4 sürüm denendi. Eğitim, AAPL için her yıl bu sürümü seçti.

---

## 2. Sistem, tek cümle

Fiyat son 20 günün dibine yaklaşınca al; tepeye değince satma, o andan
sonraki en yüksek fiyattan bir kanal genişliği kadar düşünce sat; fiyat
dibin çok altına inerse zararına sat.

---

## 3. Kurallar ve seçilen değerler

### Çizgiler

| | değer |
|---|---|
| Tepe çizgisi | son 20 işlem gününün **en yüksek** fiyatı |
| Dip çizgisi | son 20 işlem gününün **en düşük** fiyatı |
| Geriye bakış | günlükte 20 bar, saatlikte 140 bar (20 gün × 7 saat) |
| O anki bar | **dahil değil**, sadece öncekiler |
| Güncelleme | günlükte her gün borsa açılmadan önce, saatlikte her saat başı |
| Nasıl kayar | her güncellemede en eski bar çıkar, en yeni bar girer. Çizgi ancak yeni bir zirve/dip gelince ya da eski zirve/dip pencereden çıkınca değişir, bu yüzden basamak basamak hareket eder. |
| Saatlik veri | sadece borsa saatleri (09:30-16:00 New York); gece saatleri atılır |

### Al-sat seviyeleri

**Genişlik** = tepe çizgisi − dip çizgisi.

| seviye | formül | seçilen değer | ne zaman değişir |
|---|---|---|---|
| **Al** | dip + `alim_payi` × genişlik | `alim_payi = 0.10` (her yıl) | her güncellemede |
| **Zararına sat** | alış anındaki dip − `stop_payi` × genişlik | `stop_payi = 2.0` (çoğu yıl), bazı yıllarda `0.25` (tablo aşağıda) | alışta sabitlenir |
| **Takip eden stop** | fiyat tepeye değdikten sonra görülen en yüksek − `takip_payi` × (değdiği andaki genişlik) | `takip_payi = 1.0` (her yıl) | her güncellemede, sadece yukarı |
| **Maliyet** | her alışta ve her satışta | %0.05 | — |

**Örnek:** tepe 200, dip 180, genişlik 20.
- 182'de al (180 + 20 × 0.10). Zararına satış seviyesi 140 (180 − 20 × 2).
- Fiyat 200'e değer: satma, takip eden stop 180'e kurulur (200 − 20).
- Fiyat 230'a çıkar: stop 210'a yükselir.
- Fiyat 210'a iner: **sat**.

### Bar içi varsayımlar (hepsi aleyhimize)

- Aynı barda hem stop hem tepe görüldüyse önce stop olmuş sayılır.
- Alış yapılan barda satış yok (stop hariç).
- Takip eden stop, tepeye değilen bardan **sonraki** bardan itibaren geçerli.
- Fiyat seviyenin ötesinde açıldıysa (gece boşluğu) işlem açılış fiyatından.
- Açılış zaten zararına satış seviyesinin altındaysa alış yapılmaz.
- Her alışta paranın tamamı kullanılır, kaldıraç yok, nakitte faiz yok.

### Her yıl eğitimde seçilen değerler

Eğitimde her yıl 36 kombinasyon denendi: alım {0.05, 0.10, 0.20} × zararına
satış {0.25, 0.5, 1.0, 2.0} × takip {0.25, 0.5, 1.0}. Eğitim döneminde en çok
kazandıran seçildi.

| test yılı | eğitim | günlük: alım / stop / takip | saatlik: alım / stop / takip |
|---|---|---|---|
| 2019 | 2016-2018 | 0.10 / **0.25** / 1.0 | 0.10 / 2.0 / 1.0 |
| 2020 | 2016-2019 | 0.10 / 2.0 / 1.0 | 0.10 / 2.0 / 1.0 |
| 2021 | 2016-2020 | 0.10 / 2.0 / 1.0 | 0.10 / **0.25** / 1.0 |
| 2022 | 2016-2021 | 0.10 / 2.0 / 1.0 | 0.10 / **0.25** / 1.0 |
| 2023 | 2016-2022 | 0.10 / 2.0 / 1.0 | 0.10 / **0.25** / 1.0 |
| 2024 (Haz) | 2016-2023 | 0.10 / 2.0 / 1.0 | 0.10 / 2.0 / 1.0 |

Takip mesafesi her yıl denenen **en geniş** seçenek (1.0) oldu. Daha geniş
değerler denenmedi.

---

## 4. Kod

| ne | nerede |
|---|---|
| Kurallar, al-sat döngüsü | `lab/backtest.py` → `Kurallar`, `calistir()` |
| Çizgiler | `lab/backtest.py` → `cizgiler()` (son n barın en yükseği/en düşüğü, `shift(1)`) |
| Eğitim/test | `lab/backtest.py` → `egitim_test(..., sabit={"cizgi": "donchian", "satis": "takip"})` |
| Saatlik seans filtresi | `lab/session.py` → `regular_hours()` |
| Araştırma / kasa bölmesi | `lab/splits.py` → `split_research_vault()` |
| Defter | `lab/KABUL-1_AAPL_takip_eden_stop.ipynb` (adım adım), `lab/DENEY_GUNLUGU.ipynb` adım 7-8 |

Tekrar çalıştırmak için:

```python
from src.data.load import load_bars
from lab.session import regular_hours
from lab.splits import split_research_vault
from lab.backtest import Kurallar, calistir, egitim_test

gunluk  = split_research_vault(load_bars('AAPL', '1Day'), horizon_bars=1).research
saatlik = split_research_vault(regular_hours(load_bars('AAPL', '1Hour')), horizon_bars=1).research

# eğitim/test: her yıl eşikler önceki yıllardan seçilir
et = egitim_test(gunluk, n=20, test_yillari=range(2019, 2025),
                 sabit={'cizgi': 'donchian', 'satis': 'takip'})
et['testte'].add(1).prod()        # → 5.80

# tek bir sabit ayarla
k = Kurallar(n=20, cizgi='donchian', satis='takip',
             alim_payi=0.10, stop_payi=2.0, takip_payi=1.0, maliyet=0.0005)
sonuc = calistir(gunluk, k)
```

---

## 5. Test yöntemi

- **Test dönemi:** 2019-01 → 2024-06, **5.5 yıl**, 6 ayrı test yılı.
- Her test yılı için eşikler **sadece o yıldan önceki** yıllara bakılarak
  seçildi (eğitim 3 yıldan 8 yıla kadar büyüyor). Test yılına bakılmadı.
- Test yılının başında çizgilerin hazır olması için önceki 20 günün fiyatı
  kullanıldı (geçmiş veri, sızıntı değil). İşlem sadece test yılının içinde.
- **Yöntemden gelen bir etki:** her test yılı ayrı çalıştırıldığı için yıl
  sonunda elde hisse varsa satılıyor, yeni yıl boş başlıyor. Gerçek bir
  sistemde bu satışlar olmaz. Fazladan maliyet ve yıl başı yükselişlerini
  kaçırma ihtimali getirir; etkisi küçük ama sonuç tam olarak bu değildir.

---

## 6. Sonuçlar (sadece test yılları)

### Toplam: 2019 başında 1 lira, 2024 Haziran'da

| | sistem | baseline | baseline'ı geçtiği yıl | işlem | yılda | piyasada |
|---|---|---|---|---|---|---|
| günlük | **5.80** | 5.63 | 6 yılın 4'ü | 22 | ~4 | %84 |
| saatlik | **6.29** | 5.61 | 6 yılın 5'i | 38 | ~7 | %88 |

**Ek bilgiler (2026-09-11, defterden, günlük):**

| | değer |
|---|---|
| Baseline, kesintisiz (test başında al, sonunda sat; tek maliyet) | **5.66**. Yukarıdaki 5.63, her yıl ayrı alış-satış maliyeti düşüldüğü için biraz düşük. |
| En büyük erime, test yılları | sistem **%27.6**, baseline %31.4 |
| İşlemler | 22 işlemin 9'u kazançlı, 13'ü zararlı; işlem başına ortalama +%10.7. Zararlar küçük, kazançlar büyük. |

### Yıl yıl

| yıl | günlük | saatlik | baseline | günlük işlem | saatlik işlem |
|---|---|---|---|---|---|
| 2019 | +80.9% ✗ | +106.6% ✓ | +88.6% | 5 | 3 |
| 2020 | +92.7% ✓ | +89.4% ✓ | +82.1% | 4 | 4 |
| 2021 | +20.3% ✗ | +21.1% ✗ | +34.5% | 3 | 7 |
| 2022 | -20.8% ✓ | -21.4% ✓ | -26.5% | 4 | 15 |
| 2023 | +53.6% ✓ | +49.6% ✓ | +48.9% | 4 | 7 |
| 2024 (Haz) | +13.8% ✓ | +12.9% ✓ | +11.4% | 2 | 2 |

### İşlemler

| test yılı | günlük: ort. tutma (işlem günü) | günlük: satış sebebi | saatlik: ort. tutma | saatlik: satış sebebi |
|---|---|---|---|---|
| 2019 | 41 | 3 stop, 1 takip, 1 yıl sonu | 84 | 2 takip, 1 yıl sonu |
| 2020 | 54 | 2 takip, 1 stop, 1 yıl sonu | 54 | 2 takip, 1 stop, 1 yıl sonu |
| 2021 | 50 | 3 takip | 21 | 4 stop, 3 takip |
| 2022 | 60 | 3 takip, 1 yıl sonu | 16 | **11 stop**, 3 takip, 1 yıl sonu |
| 2023 | 61 | 3 takip, 1 yıl sonu | 35 | 3 takip, 3 stop, 1 yıl sonu |
| 2024 (Haz) | 56 | 1 takip, 1 yıl sonu | 56 | 1 takip, 1 yıl sonu |

---

## 7. Hangi koşullarda kâr ettirdi

Aşağıdakiler 6 test yılının sonuçlarından çıkan **gözlem ve yorumlardır**.
6 yıl az bir örnek; bunlar kanıt değil, sonraki testlerde kontrol edilecek
beklentilerdir.

**Baseline'ı geçtiği durumlar**

- **Sert düşüş ve toparlanma olan yıllar (2020).** Fiyat düşerken takip
  eden stop hisseyi düşüşün bir kısmında sattırıyor, sistem fiyat 20 günün
  dibine yaklaşınca yeniden alıyor. Düşüşün bir kısmı kaçırılıp dipten
  yeniden girildiğinde baseline geçiliyor.
- **Düşüş yılı (2022).** Piyasa %26.5 kaybederken sistem ~%21 kaybetti.
  Takip eden stop her büyük düşüşün bir kısmından kaçırdı. Koruma tam değil,
  düşüşün çoğu yine yaşandı.
**Baseline'a yakın kaldığı durumlar**

- **Uzun, kesintisiz yükselişler.** Takip mesafesi geniş (1 kanal genişliği)
  olduğu için küçük geri çekilmelerde satmıyor; hisse ortalama 2-3 ay
  tutuluyor ve yükselişin büyük kısmı yakalanıyor. Burada baseline'ı
  geçmiyor, ama çok geride de kalmıyor. Eski "tepede sat" sistemi tam bu
  durumda kaybediyordu.

**Geride kaldığı durumlar**

- **Düzenli yükseliş, orta derinlikte geri çekilmeler (2021).** Geri çekilme
  takip eden stopu tetikleyecek kadar derin ama fiyat 20 günün dibine inecek
  kadar derin değilse sistem satıp nakitte bekliyor. Yeniden alış ancak
  fiyat dibe yaklaşınca geliyor, bu arada yükseliş kaçıyor.
- **Zararına satış seviyesi yakın seçildiğinde (0.25).** 2019 günlükte 5
  işlemin 3'ü, 2022 saatlikte 15 işlemin 11'i zararına satışla kapandı.
  Yakın stop, AAPL'ın normal dalgalanmasında sık tetikleniyor. Uzak stop
  (2.0) seçilen yıllarda zararına satış neredeyse hiç olmadı.

**Genel olarak:** sistem zamanın ~%85-90'ında piyasada. Kazancın büyük kısmı
AAPL'ın kendi yükselişinden geliyor. Baseline'dan fark, büyük düşüşlerin bir
kısmından kaçıp dipten yeniden girmekten geliyor.

---

## 8. Kabulün sınırları

- **Sadece AAPL için.** "Büyük büyüme hissesi" tipinin kuralı sayılması için
  aynı tipten en az 3 hissede test edilmeli (REGISTRY bölüm 2, kural 5).
- **Fark küçük:** günlükte 1 lira başına 17 kuruş, saatlikte 68 kuruş (5.5
  yılda). ~71 denemeden sonra geldi.
- **Önceden yazılmış bir kabul kriteri yoktu;** kabul sonuç görüldükten sonra
  verildi.
- **Düşüşe karşı koruma sınırlı:** tüm dönemde en büyük erime baseline ile
  neredeyse aynı (%38 / %39).
- **Az işlem:** test yıllarında günlükte 22, saatlikte 38 işlem.
- **Takip mesafesi sınırda:** eğitim her yıl denenen en geniş değeri seçti.
  Daha geniş değerlerde sistem giderek al-tut'a dönüşüyor (REGISTRY 6.8).
- Saklanan veride (2024-07 sonrası) ve sanal hesapta henüz denenmedi.

### Denenip reddedilen değişiklikler

- **Zararına satış dip çizgisinde (2026-09-11):** dibin altında değil, dip
  çizgisine değince sat. Test yıllarında 1 lira günlük 3.56 (son hali 5.80),
  saatlik 5.39 (son hali 6.29). İşlem 22 → 90, çoğu küçük zararla kapandı;
  erime %35. Ayrıntı: REGISTRY 6.9. KABUL-1 değişmedi.

### Başka veride denemeler

- **Dakikalık veri (2026-09-12):** aynı sistem, kararlar her dakika. Test
  yıllarında 1 lira 6.32 (saatlik 6.29, günlük 5.80, dakikalık baseline 5.57).
  22 işlem, 6 yılın 5'inde baseline'ı geçti, erime %30.8 (baseline %35.0).
  Saatlikle neredeyse aynı, belirgin kazanç yok. Ayrıntı: REGISTRY 6.10,
  defter adım 8b.

---

## 9. Sonraki adımlar

1. Aynı tipten 2+ hissede (ör. MSFT, NVDA) aynı eğitim/test. Veri indirilmesi
   gerekiyor (`scripts/fetch_bars.py`).
2. Yıl sonu satışlarını kaldıran, yıllar arasında pozisyonu taşıyan bir
   eğitim/test (bölüm 5'teki etkiyi ölçmek için).
3. Sanal hesap (ENV-B), alım satım motoru gerektirir (`docs/ALIM_SATIM_MOTORU.md`).

Bunlardan birinde baseline'ın altında kalırsa kabul geri çekilir. Bu dosya
silinmez, durumu güncellenir.
