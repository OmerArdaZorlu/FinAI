# Örnek: Ev Fiyatı Tahmini

> **Amaç:** Makine öğrenmesi sürecinin tamamını, borsa bilgisi gerektirmeyen bir örnek üzerinden anlatmak.
> Sunum ve ekip içi anlatım için hazırlandı.
> **Not:** Aşağıdaki bütün sayılar gerçek — 600 ilanlık sentetik bir veri setiyle XGBoost çalıştırılarak üretildi.

---

## İçindekiler

1. [Problem](#1-problem)
2. [Ham veri](#2-ham-veri)
3. [Ham veri neden yetmez](#3-ham-veri-neden-yetmez)
4. [Özellik mühendisliği](#4-özellik-mühendisliği)
5. [En tehlikeli hata: sızıntı](#5-en-tehlikeli-hata-sızıntı-leakage)
6. [Veri bölme](#6-veri-bölme)
7. [XGBoost nasıl öğreniyor](#7-xgboost-nasıl-öğreniyor)
8. [Hangi özellik işe yaradı](#8-hangi-özellik-işe-yaradı)
9. [Model gerçekten işe yarıyor mu](#9-model-gerçekten-işe-yarıyor-mu)
10. [Örnek tahminler](#10-örnek-tahminler)
11. [Borsa sistemine eşleme](#11-borsa-sistemimize-eşleme)

---

## 1. Problem

Bir evin fiyatını, özelliklerine bakarak tahmin et.

---

## 2. Ham veri

Elimizde 600 ilan var:

| semt | m² | oda | bina_yaşı | kat | metro_km | **fiyat** |
|---|---|---|---|---|---|---|
| Ümraniye | 167 | 4 | 14 | 0 | 3.76 | 6.820.000 |
| Esenyurt | 186 | 5 | 24 | 3 | 0.22 | 4.190.000 |
| Esenyurt | 202 | 6 | 16 | 4 | 3.41 | 4.250.000 |
| Kadıköy | 172 | 4 | 14 | 4 | 2.36 | 8.380.000 |
| Beşiktaş | 69 | 2 | 35 | 7 | 1.30 | 3.510.000 |
| Esenyurt | 107 | 3 | 14 | 12 | 0.43 | 2.240.000 |

Son sütun **cevap** — modelin öğrenmesi gereken şey. Diğerleri **ipucu**.

---

## 3. Ham veri neden yetmez

**"4 oda" tek başına ne söyler?**

- 200 m² 4 oda → geniş, ferah
- 90 m² 4 oda → sıkışık

Aynı sayı, farklı anlam. Modele ham hâliyle verirsen bu farkı göremez.

**Çözüm: türetilmiş özellik.**

```
oda_başına_m² = m² ÷ oda
```

Artık 50 ve 22.5 gibi anlamlı sayılar var.

---

## 4. Özellik mühendisliği

| Yeni özellik | Nasıl hesaplandı | Neden |
|---|---|---|
| `oda_başına_m²` | m² ÷ oda | Oda sayısı tek başına yanıltıcı |
| `yeni_mi` | bina_yaşı ≤ 5 → 1, değilse 0 | Alıcı için 3 yaş ile 5 yaş fark etmez, 5 ile 30 eder |
| `metro_yakın` | metro_km ≤ 1.0 → 1, değilse 0 | Yürüme mesafesi bir eşik meselesi |
| `semt_kod` | Metin → sayı | Model metin okuyamaz |

Dönüşüm sonrası tablo:

| m² | oda | bina_yaşı | kat | metro_km | oda_başına_m² | yeni_mi | metro_yakın | semt_kod | fiyat |
|---|---|---|---|---|---|---|---|---|---|
| 167 | 4 | 14 | 0 | 3.76 | 41.8 | 0 | 0 | 2 | 6.820.000 |
| 186 | 5 | 24 | 3 | 0.22 | 37.2 | 0 | 1 | 3 | 4.190.000 |
| 202 | 6 | 16 | 4 | 3.41 | 33.7 | 0 | 0 | 3 | 4.250.000 |
| 172 | 4 | 14 | 4 | 2.36 | 43.0 | 0 | 0 | 0 | 8.380.000 |
| 69 | 2 | 35 | 7 | 1.30 | 34.5 | 0 | 0 | 1 | 3.510.000 |
| 107 | 3 | 14 | 12 | 0.43 | 35.7 | 0 | 1 | 3 | 2.240.000 |

Fiyat sütunu duruyor ama o **cevap**, ipucu değil. Modele ayrı veriliyor.

---

## 5. En tehlikeli hata: sızıntı (leakage)

Şu özelliği eklediğini düşün:

```
m²_başına_fiyat = fiyat ÷ m²
```

Model mükemmel sonuç verir. Hata neredeyse sıfır. Herkes sevinir.

**Ama işe yaramaz.** Çünkü yeni bir ev geldiğinde `fiyat`'ı bilmiyorsun — zaten onu tahmin etmeye çalışıyorsun. O özelliği hesaplayamazsın bile.

Aynı tuzağın daha sinsi hâli: **"ilan kaç günde satıldı"**. Geçmiş veride var, tahmin anında yok. Ve pahalı evler geç satıldığı için fiyatla ilişkili — model buna yapışır.

> **Kural:** Bir özelliği, **tahmin anında elinde olmayan** hiçbir bilgiden türetme.

Sızıntının en kötü yanı: hiçbir test hata vermez. Sistem çalışır, sonuçlar harika görünür, sadece gerçek hayatta işe yaramaz.

---

## 6. Veri bölme

600 ilanın 450'siyle model **öğrenir**. Kalan 150'sini **hiç görmez** — sınav bunlar.

Neden: modelin daha önce gördüğü bir evde doğru bilmesi hiçbir şey ifade etmez. Ezberlemiş de olabilir.

---

## 7. XGBoost nasıl öğreniyor

### 7.1 Tek ağaç

Model önce tek bir soru arar. Bütün özelliklerde bütün eşikleri deneyip **en iyi ayıranı** bulur:

```
semt_kod < 2 ?                          ← seçilen soru
│
├── evet  (Kadıköy / Beşiktaş)
│     └── m² < 138 ?
│           ├── evet  → +207.763
│           └── hayır → +2.113.025
│
└── hayır (Ümraniye / Esenyurt)
      └── m² < 126 ?
            ├── evet  → −1.307.056
            └── hayır → −345.724
```

Okunuşu: *"Pahalı semtte ve 138 m²'den büyükse, ortalamanın 2.1 milyon üstü."*

Tek ağaç kaba. Test hatası **%59**.

### 7.2 Sonra 300 ağaç

Her yeni ağaç, önceki ağaçların **yanıldığı yerleri** düzeltmek için kurulur. Katkısının sadece **%5'i** eklenir — küçük adımlarla ilerlesin, aşırıya kaçmasın diye.

| Ağaç sayısı | Eğitim hatası | Test hatası |
|---|---|---|
| 1 | %57.1 | %59.3 |
| 3 | %52.1 | %54.4 |
| 10 | %39.6 | %41.8 |
| 30 | %19.8 | %22.9 |
| 100 | %5.6 | %9.8 |
| 300 | %3.1 | **%9.2** |

**Dikkat edilecek yer:** 100'den 300'e giderken eğitim hatası %5.6 → %3.1 düştü, ama test hatası neredeyse aynı kaldı (%9.8 → %9.2).

Model artık öğrenmiyor, **ezberliyor.**

Bu tablo "ne zaman durmalı" sorusunun cevabı: iki sütun ayrışmaya başladığı yerde.

---

## 8. Hangi özellik işe yaradı

```
semt_kod        ████████████████████████████████████████
m²              ██████████
oda             ████████
bina_yaşı       ██
yeni_mi         █
metro_km        █
oda_başına_m²   █
kat             ·
metro_yakın     ·
```

**Okunuşu:** Fiyatı en çok semt belirliyor, sonra büyüklük. Kat neredeyse hiç fark etmiyor.

Bu tablo aynı zamanda bir **hipotez karnesi**: "kat önemlidir" diye düşünmüştük, veri hayır diyor. Ve `metro_yakın` özelliğini boşuna türetmişiz — `metro_km` zaten aynı bilgiyi taşıyor.

---

## 9. Model gerçekten işe yarıyor mu

Tek başına "%9.2 hata" hiçbir şey ifade etmez. Karşılaştırmak gerekir:

| Yöntem | Hata |
|---|---|
| Hep ortalama fiyatı söyle | %61.6 |
| Sadece m² × ortalama m² fiyatı | %40.8 |
| **XGBoost** | **%9.2** |

En basit kuralı (m² × birim fiyat) **dörde katlayarak** yenmiş. İşe yarıyor.

Eğer model %38 çıksaydı, %40.8'lik basit kuralın yanında değersiz olurdu — ne kadar karmaşık olursa olsun.

> **Kural:** Her modelin bir baseline'ı olmalı. Baseline'ı yenemiyorsa model yoktur.

---

## 10. Örnek tahminler

Modelin hiç görmediği evler:

| semt | m² | oda | yaş | Gerçek | Tahmin | Sapma |
|---|---|---|---|---|---|---|
| Ümraniye | 112 | 3 | 14 | 4.050.000 | 3.396.000 | −16.1% |
| Ümraniye | 179 | 4 | 2 | 7.680.000 | 6.965.000 | −9.3% |
| Esenyurt | 133 | 4 | 29 | 2.610.000 | 3.240.000 | **+24.1%** |
| Ümraniye | 90 | 2 | 8 | 3.010.000 | 2.841.000 | −5.6% |
| Ümraniye | 132 | 3 | 28 | 4.030.000 | 4.307.000 | +6.9% |
| Beşiktaş | 91 | 3 | 27 | 4.870.000 | 5.240.000 | +7.6% |

Üçüncü satır: model bazen ciddi yanılıyor.

**Ortalama %9 hata, her tahminde %9 hata demek değil.** Bazıları %5, bazıları %24. Bir sistem kurarken tek tek tahminlere değil, dağılıma bakmak gerekir.

---

## 11. Borsa sistemimize eşleme

Adımlar birebir aynı, sadece isimler değişiyor:

| Ev fiyatı örneği | Borsa sistemi |
|---|---|
| Bir ilan | Bir gün |
| m², oda, semt | Getiri, hacim oranı, volatilite |
| `oda_başına_m²` türetmek | `hacim ÷ 20 günlük ortalama hacim` türetmek |
| Fiyat (tahmin edilen) | Yarın yükselecek mi (tahmin edilen) |
| "Kaç günde satıldı" sızıntısı | "Yarının fiyatı" sızıntısı |
| 150 evi sınava ayırmak | Son dönemi sınava ayırmak |
| Semt en önemli çıktı | Hangi özellik? — henüz bilmiyoruz |
| m² × birim fiyat baseline'ı | "Hep yükselir" baseline'ı |
| Ortalama %9 hata | Doğru bilme oranı %5x |

---

## 12. Tek fark — ve çok önemli

**Ev fiyatlarında veriyi rastgele bölebilirsin.** 3 numaralı ev ile 500 numaralı ev arasında zaman ilişkisi yok.

**Borsada bölemezsin.** Zamanı karıştırırsan model geleceği görmüş olur: Mart ayı verisiyle eğitip Şubat'ta test edersen, Şubat'ta ne olacağını zaten öğrenmiştir.

Bu yüzden borsada:

- Hep **geçmişle eğitip geleceği** test ediyoruz
- Eğitim ile test arasına **boşluk** koyuyoruz (hesaplar geriye baktığı için sınır aşılmasın)

```
EV FİYATI                    BORSA
─────────                    ─────
┌───────────────┐            ┌──────────────┐  ┌─┐  ┌──────┐
│ rastgele karıştır, böl │   │   eğitim     │  │▓│  │ test │
└───────────────┘            └──────────────┘  └─┘  └──────┘
   sırası önemsiz              geçmiş        boşluk  gelecek
```

---

## Özet — süreç tek bakışta

```
  ham veri
      │
      ▼  anlamlı sayılara çevir  (özellik mühendisliği)
  özellik tablosu
      │
      ▼  cevabı ekle  (hedef)
  özellik + cevap
      │
      ▼  ayır  (eğitim / sınav)
  eğitim seti          sınav seti
      │                     │
      ▼  öğren              │
   300 ağaç ───────────────►│  tahmin et
      │                     │
      ▼                     ▼
  hangi özellik      baseline ile karşılaştır
  işe yaradı              │
                          ▼
                 işe yarıyor mu? ──hayır──► özellikleri değiştir, baştan
                          │
                          └─evet─► kullan
```
