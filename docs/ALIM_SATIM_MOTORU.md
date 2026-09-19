# Alım Satım Motoru — Not

> **Durum:** 🟡 NOT — kenara alındı, henüz kod yok (2026-09-11)
> **İlgili:** [ARCHITECTURE.md](ARCHITECTURE.md) (bugünkü sistem) · [ARCHITECTURE_TASARIM.md](ARCHITECTURE_TASARIM.md) §2, §3, §7, §8, §11 (tasarım) · [TECH_DEBT.md](TECH_DEBT.md) · [ENVIRONMENTS.md](ENVIRONMENTS.md) · [hypotheses/REGISTRY.md](../hypotheses/REGISTRY.md)

**Motor** = karar mekanizmalarından gelen sinyali alıp borsaya emir olarak
gönderen, açık pozisyonları ve stopları takip eden, her şeyi kaydeden parça.
Hipotez ve backtest araştırma tarafıdır; motor, onların canlıda çalıştığı yerdir.

---

## 1. Şu an ne var

| parça | durum | nerede |
|---|---|---|
| Geçmiş bar indirme (Alpaca) ve saklama (SQLite) | ✅ var | `src/data/`, `scripts/fetch_bars.py` |
| Seans filtresi (gece saatlerini atma, yaz/kış saati) | ✅ var | `lab/session.py` |
| Al-sat kurallarının geçmiş veride simülasyonu | ✅ var, **sadece araştırma** | `lab/backtest.py` |
| Canlı veri akışı | ⬜ yok | tasarımda `src/data/stream.py` diye geçiyor, dosya yok |
| Özellik hesabı (`features.py`), eğitim (`train.py`), model | ⬜ yok | hiçbir hipotez henüz geçmedi |
| Orkestratör, risk, emir, pozisyon takibi | ⬜ yok | sadece tasarımda |

Yani **motorun hiçbir parçası yazılmadı.** `lab/backtest.py` motorun ne
yapacağını geçmiş veride taklit ediyor, ama borsaya bağlanmıyor.

---

## 2. Tasarımda ne yazıyor (ARCHITECTURE_TASARIM.md)

```text
 Alpaca canlı veri ──► son 100 bar (RAM) ──► features.py ──► model(ler)
                                                                 │
                                                                 ▼
                     SQLite kayıt ◄── emir (Alpaca) ◄── risk ◄── orkestratör
```

| adım | tasarımdaki hali |
|---|---|
| Çalışma ortamı | QuantConnect LEAN motoru, Docker içinde, AWS EC2 |
| Veri | Alpaca WebSocket, AAPL + SPY, aynı zaman damgasında hizalanır |
| Karar | XGBoost model(ler)i, her biri −1 ile +1 arası sinyal üretir |
| Birleştirme | Orkestratör: sinyallerin ağırlıklı ortalaması, eşiği geçerse AL/SAT, yoksa BEKLE (§7.3) |
| Risk | İşlem başına kasanın %1'i, takip eden stop |
| Emir | Alpaca REST, piyasa ya da limit emri |
| Kayıt | SQLite: barlar, sinyaller, emirler, gerçekleşmeler, durum |
| Ortamlar | ENV-A araştırma → ENV-B sanal hesap (paper) → ENV-C gerçek para; aralarında kontrol kapıları G1, G2 |

**Eksik:** §8 "Risk Yönetimi" bölümü başlık olarak var ama içi hiç yazılmamış
(pozisyon boyutu formülü, günlük zarar limiti, takip eden stop ayarları...).

---

## 3. Motoru etkileyen verilmemiş kararlar (TECH_DEBT.md "Açık Kararlar")

| # | karar | motora etkisi |
|---|---|---|
| AK-1 | Günlük mü, saatlik mi? | Günlükte motor günde bir kez birkaç saniye çalışır, veri ücretsiz, PDT sorunu yok. Saatlikte sürekli çalışır, anlık veri ayda $99, günde çok işlem PDT sınırına takılır. |
| AK-2 | Alpaca mı, IBKR mı? | Emir gönderme kodu, kesirli hissede stop kurulabilmesi, para transfer maliyeti. |
| AK-3 | Hangi veri kaynağı? | Ücretsiz planda son 15 dakika gecikmeli. Saatlik sistemde her sinyal 15 dakika geç kalır. |
| AK-4 | Tek konteyner mi, birden fazla mı? | SQLite'a tek yazar olmalı; pozisyon durumunun tek sahibi olmalı. |

---

## 4. Motor için gerekenler

Her madde ilgili teknik borç numarasıyla. Hepsi ⬜ açık.

| # | parça | ne yapar | neden gerekli | ilgili |
|---|---|---|---|---|
| M-1 | **Canlı veri girişi** | Borsa açıkken yeni barları alır, son N barı tutar | Çizgiler ve sinyaller buna göre hesaplanır | AK-3 |
| M-2 | **Bayat veri koruması** | Veri akışı durursa işlem açmaz, alarm verir | Eski fiyatla işlem açmamak için | TD-08 |
| M-3 | **Karar fonksiyonu** | Kuralları uygular (al / sat / bekle) | — | TD-01 |
| M-4 | **Açıklama girişi (EDGAR)** | Yeni şirket açıklamalarını alır, kabul saatiyle kaydeder | İkinci karar mekanizması | H-003 |
| M-5 | **Orkestratör** | Fiyat sistemi ve açıklama sisteminin sinyallerini tek karara indirir | İki mekanizma çelişirse ne yapılacağı | §7.3, TD-20 |
| M-6 | **Tip bazında ayar** | Her sembolün tipine göre kural setini seçer | REGISTRY §2: kurallar tipe göre | REGISTRY |
| M-7 | **Risk** | Pozisyon büyüklüğü, günlük zarar limiti, toplam risk sınırı | Tek işlemin ya da kötü bir günün kasayı eritmemesi | §8, TD-09 |
| M-8 | **Emir yöneticisi** | Limit/stop emirleri gönderir, her emre tekrar edilemeyen bir kimlik verir, bağlantı koparsa aynı kimlikle yeniden dener | Aynı emrin iki kez gitmemesi | TD-07 |
| M-9 | **Pozisyon ve stop takibi** | Açık pozisyonları, zararına satış ve takip eden stop seviyelerini her bar kontrol eder | Kesirli hissede broker stop tutamıyor, stop bizim süreçte durmak zorunda | TD-19 |
| M-10 | **Yeniden başlama ve mutabakat** | Motor çöküp açılınca broker'dan gerçek pozisyonu çeker, kendi kaydıyla karşılaştırır | Çökünce stop koruması da ölür; açılışta her şey yeniden kurulmalı | TD-06 |
| M-11 | **Acil durdurma** | Tek bir bayrakla tüm pozisyonları kapatıp durur | Model bozulursa ya da bir hata olursa | TD-09 |
| M-12 | **PDT sayacı** | Aynı gün al-sat sayısını tutar, sınıra yaklaşınca yeni gün içi işlem açmaz | $25.000 altı hesapta 5 günde 3'ten fazla gün içi işlem 90 gün kısıtlama getirir | TD-04 |
| M-13 | **Kayıt** | Her sinyal, emir, gerçekleşme ve durum SQLite'a yazılır | Denetim, hata ayıklama, paper karşılaştırması | §3.4 |
| M-14 | **Paper karşılaştırma raporu** | Sanal hesaptaki gerçekleşme fiyatlarını backtest'in varsaydıklarıyla karşılaştırır | Backtest'in ne kadar iyimser olduğunu ölçmek | TD-10, TD-11 |
| M-15 | **Anahtar yönetimi** | API anahtarları kodda değil, ortamda durur | Sızıntı | TD-05 |

---

## 5. Deneylerimizden motora çıkan notlar

1. **Backtest ile motor aynı karar kodunu kullanmalı (M-3).** Şu an kurallar
   `lab/backtest.py` içindeki döngünün içinde. Motor yazılırken bu kurallar
   tek bir fonksiyona taşınmalı: "şu an elimde ne var, bu barda fiyat ne
   yaptı, çizgiler nerede → ne yapılmalı". Backtest de motor da bu fonksiyonu
   çağırır. İki ayrı kopya olursa canlı sistem backtest'ten farklı davranır
   (TD-01'in aynısı, bu sefer kurallar için).
2. **Backtest limit emirlerinin dolduğunu varsayıyor.** Fiyat seviyeye değince
   alış yapılmış sayılıyor. Gerçekte değmek emrin dolması demek değil. Motor
   limit emri kullanmalı ve sanal hesapta kaç emrin gerçekten dolduğu
   ölçülmeli (M-14).
3. **Takip eden stop bizim süreçte duruyor (M-9, M-10).** Kesirli hissede
   Alpaca'da koruyucu emir kurulamıyor. Motor çökerse takip eden stop da
   çalışmaz. Yeniden başlarken en yüksek fiyat ve stop seviyesi kayıttan
   geri yüklenmeli.
4. **Gece boşlukları.** Fiyat seviyenin ötesinde açılırsa işlem açılış
   fiyatından yapılır (backtest'teki varsayım). Motor da açılışta önce stop
   kontrolü yapmalı.
5. **Açıklamalar her saatte gelebilir (M-4).** Borsa kapalıyken gelen 8-K
   ertesi açılışa kadar bekletilir. Motorun fiyat barlarından bağımsız bir
   olay kuyruğu olmalı.
6. **Tip bazında ayar (M-6).** Sembol eklenirken tipi yazılır; motor kural
   setini tipe göre seçer. Bir sembolün tipi motor çalışırken değişmez.

---

## 6. Ne zaman yazılır

- **Gerçek para (ENV-C):** en az bir hipotez G1 kapısını geçmeden olmaz.
  Şu an geçen yok (REGISTRY: H-001 ve H-001-B reddedildi, H-001-C kararsız).
- **Sanal hesap (ENV-B) iskeleti daha önce yazılabilir.** Tesisatı (veri →
  karar → emir → kayıt → yeniden başlama) mevcut sistemle, sanal parayla
  denemek, strateji bulununca zaman kazandırır. Önerilen başlangıç: günlük
  bar (ücretsiz veri, PDT yok), tek konteyner, M-1, M-3, M-8, M-9, M-10,
  M-13 önce.
