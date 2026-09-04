# Teknik Borç (Tech Debt) Kayıt Defteri

> Mimari incelemesinde tespit edilen, **kapatılmadan üretime çıkılmaması gereken** açık maddeler.
> Her madde: sabit ID · önem · hangi ortamda çözülür · sahip · tanım-of-done.
> **Kural:** Bir madde ancak DoD'sindeki tüm kutular işaretlenince `✅ Kapalı` olur. Kısmen yapılan iş açıktır.
> **Son güncelleme:** 2026-09-03 · İlgili: [ARCHITECTURE.md](ARCHITECTURE.md), [ENVIRONMENTS.md](ENVIRONMENTS.md)

---

## Nasıl Okunur

| Alan | Anlamı |
|---|---|
| **Önem** | 🔴 P0 = üretime çıkışı engeller · 🟠 P1 = ilk kaza buradan çıkar · 🟡 P2 = süreçsel, şimdi ucuz |
| **Ortam** | Maddenin **çözüleceği/kanıtlanacağı** ortam (bkz. [ENVIRONMENTS.md](ENVIRONMENTS.md)) |
| **Kapı** | Hangi terfi kapısını bloke ediyor — `G1` (Araştırma➜Beta) veya `G2` (Beta➜Üretim) |
| **Durum** | `⬜ Açık` · `🟨 Devam` · `✅ Kapalı` |

---

## Açık Kararlar (borç değil — verilmemiş kararlar)

Bunlar "yapılacak iş" değil, **verilmesi gereken tercihler**. Üçü de aşağıdaki maddelerin nasıl kapatılacağını belirliyor, o yüzden koda başlamadan netleşmeli.

| # | Karar | Neyi etkiler | Durum |
|---|---|---|---|
| **AK-1** | **Bar frekansı: günlük mü, saatlik mi?** | `features.py` lookback pencereleri, hedef ufku, TD-03, TD-04 (PDT), veri maliyeti, işlem maliyeti | ⬜ Açık |
| **AK-2** | **Broker: Alpaca mı, IBKR mı?** | TD-18, TD-19, transfer maliyeti, ileride AB piyasası erişimi | ⬜ Açık |
| **AK-3** | **Veri feed'i: IEX mi, 15 dk gecikmeli SIP mi, ücretli anlık SIP mi?** | TD-01 (train/serve skew), hacim feature'ı, aylık maliyet | ⬜ Açık |
| **AK-4** | **Çalıştırma mimarisi: tek konteyner mi, birden çok mu?** | Dağıtım karmaşıklığı, SQLite yazar sayısı, pozisyon durumunun sahipliği, izleme | ⬜ Açık |

**AK-1 notu:** Günlük bar tek başına dört sorunu birden çözüyor — PDT sınırı (TD-04), T+1 takas kilidi, veri maliyeti (AK-3) ve transfer/işlem ücretlerinin amortismanı. Saatlik kalınırsa dördü de ayrı ayrı çözülmek zorunda.

**AK-4 notu:** Canlıda konteyner kullanılacağı kabul ediliyor; tartışma **kaça bölüneceği**.

*Tek konteyner lehine:* Günlük barda sistem günde bir kez, birkaç saniye çalışır. Bölmek üç yeni problem doğurur — (a) SQLite tek yazar sever, çok yazarlı erişimde kilitlenme olur; (b) parçalar arası tetikleme/sıralama mekanizması gerekir; (c) pozisyon durumunun tek ve net bir sahibi olması gerekir — kesirli hissede koruyucu stop kod tarafında durduğu için (TD-19) bu kritik.

*Bölme lehine:* Bir bileşen çökerse diğerleri ayakta kalır; ayrı güncellenebilir; kaynak izolasyonu sağlar.

*Orta yol:* Yazan bileşen tek konteynerde, **okuma amaçlı izleme/rapor bileşeni ayrı** konteynerde. İzleme çökse işlem tarafı etkilenmez.

```text
┌─────────────────────────────┐
│ trader        (tek yazar)   │  veri → model → risk → emir → DB
└──────────┬──────────────────┘
           │  DB (tek yazar, çok okuyucu)
           ▼
┌─────────────────────────────┐
│ monitor       (sadece okur) │  grafik, günlük rapor, alarm
└─────────────────────────────┘
```

*Frekans bağımlılığı:* AK-1'de saatlik/dakikalık seçilirse tablo değişir — sürekli bağlantı tutan veri toplayıcıyı ayırmak o zaman gerçekten anlamlı olur, çünkü yaşam döngüleri farklılaşır.

**AK-3 notu:** Alpaca'nın **ücretsiz** planı, sorgu bitişi 15 dakikadan eskiyse **tam SIP (konsolide) geçmiş veriyi** veriyor (`feed=sip`). Yalnızca son 15 dakika IEX ile sınırlı. Günlük bar stratejisinde bu fiilen kısıt değil: kapanıştan 15 dk sonra tam bar alınır, emir ertesi açılışa verilir → **aylık $0** ve eğitim/canlı arasında feed tutarlılığı. Saatlik stratejide her sinyal 15 dk geç kalır; anlık SIP $99/ay.

---

## Özet Tablo

| ID | Başlık | Önem | Ortam | Kapı | Durum |
|---|---|---|---|---|---|
| [TD-01](#td-01--trainserve-skew--veri-üretim-hattı-ayrışması) | Train/serve skew — veri üretim hattı ayrışması | 🔴 P0 | A + B | G1, G2 | ⬜ |
| [TD-02](#td-02--doğrulama-metodolojisi-purged-walk-forward-cv) | Doğrulama metodolojisi (purged walk-forward CV) | 🔴 P0 | A | G1 | ⬜ |
| [TD-03](#td-03--hedef-y-tanımı-ve-etiketleme-şeması) | Hedef (y) tanımı ve etiketleme şeması | 🔴 P0 | A | G1 | ⬜ |
| [TD-04](#td-04--pdt-pattern-day-trader-kuralı) | PDT (Pattern Day Trader) kuralı | 🔴 P0 | B | G2 | ⬜ |
| [TD-05](#td-05--api-anahtarları-repoda--secret-yönetimi) | API anahtarları repoda — secret yönetimi | 🔴 P0 | Tümü | G2 | ⬜ |
| [TD-06](#td-06--restart--pozisyon-reconciliation-yok) | Restart & pozisyon reconciliation yok | 🟠 P1 | B | G2 | ⬜ |
| [TD-07](#td-07--emir-idempotencyi-yok-çift-emir-riski) | Emir idempotency'si yok (çift emir riski) | 🟠 P1 | B | G2 | ⬜ |
| [TD-08](#td-08--bayat-veri-stale-feed-koruması-yok) | Bayat veri (stale feed) koruması yok | 🟠 P1 | B | G2 | ⬜ |
| [TD-09](#td-09--global-devre-kesici-kill-switch-yok) | Global devre kesici (kill switch) yok | 🟠 P1 | B | G2 | ⬜ |
| [TD-10](#td-10--paper-trading-aşaması-mimaride-yok) | Paper trading aşaması mimaride yok | 🟠 P1 | B | G2 | ⬜ |
| [TD-11](#td-11--işlem-maliyeti-modeli-yok) | İşlem maliyeti modeli yok | 🟠 P1 | A + B | G1 | ⬜ |
| [TD-12](#td-12--örneklem-boyutu-vs-model-kapasitesi) | Örneklem boyutu vs model kapasitesi | 🟠 P1 | A | G1 | ⬜ |
| [TD-13](#td-13--featurespy-iki-repoya-çatallanacak) | `features.py` iki repoya çatallanacak | 🟡 P2 | A | G1 | ⬜ |
| [TD-14](#td-14--çoklu-test--p-hacking-kontrolsüz) | Çoklu test / p-hacking kontrolsüz | 🟡 P2 | A | G1 | ⬜ |
| [TD-15](#td-15--model-artifactı-şemasını-taşımıyor) | Model artifact'i şemasını taşımıyor | 🟡 P2 | A + B | G1 | ⬜ |
| [TD-16](#td-16--indikatör-kütüphanesi-ikiliği) | İndikatör kütüphanesi ikiliği | 🟡 P2 | A | G1 | ⬜ |
| [TD-17](#td-17--saat-dilimi--dst-belirsizliği) | Saat dilimi & DST belirsizliği | 🟡 P2 | A + B | G2 | ⬜ |
| [TD-18](#td-18--broker-seçimi-kesinleşmedi-alpaca-vs-ibkr) | Broker seçimi kesinleşmedi (Alpaca vs IBKR) | 🟠 P1 | B | G2 | ⬜ |
| [TD-19](#td-19--kesirli-hissede-brokerda-koruyucu-stop-kurulamıyor) | Kesirli hissede broker'da koruyucu stop kurulamıyor | 🟠 P1 | B | G2 | ⬜ |

**Dağılım:** 🔴 5 · 🟠 9 · 🟡 5 — toplam **19 madde**

---

## 🔴 P0 — Üretime Çıkışı Engelleyenler

### TD-01 — Train/serve skew — veri üretim hattı ayrışması
**Önem:** 🔴 P0 · **Ortam:** ENV-A + ENV-B · **Kapı:** G1, G2 · **Durum:** ⬜ Açık

**Sorun.** `features.py`'ı paylaşmak *hesabı* aynı yapar, *girdiyi* aynı yapmaz. Eğitimde `data/` altındaki Alpaca REST CSV'si var, canlıda LEAN Slice'ından gelen bar var. Ayrışma noktaları:
- **Split/temettü düzeltmesi:** LEAN varsayılan olarak *adjusted*, Alpaca REST varsayılan `raw` fiyat verir. AAPL'ın split geçmişi log-return serisini eğitimde bozar, canlıda bozmaz.
- **Bar inşası:** extended-hours dahil mi, eksik bar nasıl doldurulur, seansın ilk barı, yarım günler, halt'lar.

**Neden P0.** Model bir dağılımda eğitilip başka bir dağılımda çalıştırılır. Hiçbir test kırmızıya dönmez; sadece canlı performans backtest'i tutmaz ve nedenini aylarca bulamazsınız.

**Çözüm.**
1. Eğitim setini de **LEAN üzerinden** üret: backtest modunda aynı `features.calculate()` çağrısıyla vektörleri CSV'ye dök. İki hat böylece matematiksel olarak aynı olur.
2. Bu mümkün olmazsa, adjustment modunu her iki tarafta **açıkça ve aynı** ayarla ve parity testiyle kanıtla.

**DoD.**
- [ ] Eğitim veri seti LEAN backtest çıktısından üretiliyor (veya adjustment modu iki tarafta pinli)
- [ ] CI'da **parity testi**: aynı tarih aralığı için offline vektör ile LEAN vektörü arasında `max|Δ| < 1e-9` assert'i
- [ ] Test, split içeren bir tarih aralığını (AAPL) kapsıyor
- [ ] ENV-B'de canlı üretilen ilk 100 vektör, offline yeniden hesapla karşılaştırıldı ve eşleşti
- [ ] **Feed kararı (AK-3) verildi ve iki tarafta da aynı:** eğitim ile canlı aynı feed'i (IEX / SIP) kullanıyor

> **Feed notu.** Skew'in en sinsi kaynağı burada. Alpaca ücretsiz planda **geçmiş** veriyi tam SIP olarak veriyor (15 dk gecikmeli), **anlık** veriyi ise yalnızca IEX olarak. Eğitimi SIP ile yapıp canlıyı IEX ile çalıştırmak, hiçbir test kırmızıya dönmeden feature dağılımını kaydırır — özellikle hacim anomalisi feature'ını, çünkü IEX toplam hacmin ~%2'sini görür.

---

### TD-02 — Doğrulama metodolojisi (purged walk-forward CV)
**Önem:** 🔴 P0 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** Mimaride "XGBoost eğitilir" yazıyor ama cross-validation şeması tanımsız. Finansal zaman serisinde rastgele K-fold = garantili sızıntı. Dahası: `shift(-n)` olmasa bile, feature'ların lookback penceresi (20 barlık SMA, ATR) train/test sınırını aşarak sızıntı üretir.

**Neden P0.** CI'ımız `shift(-n)` arıyor ve **asıl sızıntı burada olacak, CI'a yakalanmayacak.** Sonuç: backtest'te muhteşem, canlıda rastgele bir model.

**Çözüm.** Purged & embargoed walk-forward CV. Embargo penceresi, feature'ların **en uzun lookback'inden** ve hedef ufkundan büyük olmalı.

**DoD.**
- [ ] `train.py` yalnızca walk-forward split kullanıyor; `KFold`/`train_test_split(shuffle=True)` import bile edilmiyor
- [ ] Embargo bar sayısı `features.py`'daki max lookback'ten otomatik türetiliyor (elle sabit değil)
- [ ] CI'da: rastgele shuffle'lı CV kullanımını yakalayan statik kontrol
- [ ] Fold bazlı performans dağılımı raporlanıyor (tek bir ortalama sayı değil)
- [ ] Sentetik sızıntı testi: bilerek sızdırılmış bir feature eklendiğinde metodoloji bunu yakalıyor

---

### TD-03 — Hedef (y) tanımı ve etiketleme şeması
**Önem:** 🔴 P0 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** Mimari feature tarafını ayrıntılı tanımlıyor ama **hedef değişkeni hiç tanımlamıyor.** Belirsiz kalanlar: tahmin ufku (kaç bar sonrası?), etiketleme yöntemi (sabit ufuk / triple-barrier), sınıf dengesizliği, ve `predict_proba` çıktısının hangi eşikte işleme dönüşeceği.

**Neden P0.** Model neyi tahmin ettiğini bilmiyorsa, %72 olasılık hiçbir şey ifade etmez. Eşik seçimi de backtest üzerinde optimize edilirse (in-sample), o eşik canlıda geçersizdir.

**Çözüm.** Hedefi ve karar eşiğini **kod yazmadan önce**, yazılı olarak tanımla. Eşik, walk-forward'ın yalnızca train kısmında kalibre edilmeli.

**DoD.**
- [ ] Tahmin ufku (bar cinsinden) yazılı ve gerekçeli
- [ ] Etiketleme yöntemi seçildi ve dokümante edildi (sabit ufuk / triple-barrier)
- [ ] Etiket **maliyet eşiğini** içeriyor (bkz. TD-11) — spread'i geçmeyen hareket "yön" sayılmıyor
- [ ] Sınıf dağılımı raporlanıyor; dengesizlik stratejisi yazılı
- [ ] Karar eşiği walk-forward train kısmında kalibre ediliyor, test kısmına dokunmuyor
- [ ] Hedef üretimi **yalnızca `train.py` içinde**; `features.py` bundan tamamen habersiz

---

### TD-04 — PDT (Pattern Day Trader) kuralı
**Önem:** 🔴 P0 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Hesap özkaynağı **$25.000 altındaysa**, 5 iş günü içinde 3'ten fazla gün-içi al-sat (aynı gün aç-kapa) yapılamaz. Aşılırsa hesap **90 gün** kısıtlanır. Saatlik sinyal üreten bir sistem bu limiti ilk haftada tüketir.

**Neden P0.** Bu bir yazılım hatası değil, **stratejinin uygulanabilirliğini belirleyen düzenleyici kısıt.** Mimarinin frekans seçimini doğrudan etkiler.

**Çözüm — üç seçenekten biri, ekipçe karar:**
1. Sermayeyi $25k üstünde tut (nakit gerektirir)
2. Bar frekansını günlüğe çek / pozisyonları overnight taşı (gün-içi kapanış sayılmaz)
3. Risk Manager'a **gün-içi işlem sayacı** ekle; limite yaklaşınca yeni gün-içi giriş açma

**DoD.**
- [ ] Ekip kararı yazılı olarak kaydedildi (hangi seçenek, neden)
- [ ] Seçenek 3 ise: 5 iş günlük kayan pencerede day-trade sayacı implemente edildi
- [ ] Sayaç SQLite'tan restart sonrası doğru yeniden kuruluyor
- [ ] ENV-B'de sayaç bilerek limite dayandırıldı, sistem yeni gün-içi giriş açmadı
- [ ] Alpaca hesap durumundan `pattern_day_trader` bayrağı okunup loglanıyor

> **Ek kısıt — $2.000 eşiği.** Hesap $2.000'in altındaysa margin hesabı açılamaz (Reg T); cash account'ta **T+1 takas** devreye girer, satıştan gelen para ertesi güne kadar yeniden kullanılamaz. Kullanılırsa *Good Faith Violation*, tekrarında 90 gün kısıtlama. Yani küçük hesapta PDT'ye sıra gelmeden takas hızı kilitler.
>
> **AK-1 ile bağlantı.** Günlük bar seçilirse pozisyonlar overnight taşınır, gün-içi al-sat oluşmaz — hem PDT hem T+1 sorunu kendiliğinden ortadan kalkar ve bu madde büyük ölçüde kapanır.

---

### TD-05 — API anahtarları repoda — secret yönetimi
**Önem:** 🔴 P0 · **Ortam:** Tüm ortamlar · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Mimari şemasında `config/config.json` "Alpaca API anahtarları" içeriyor ve repo kökünde duruyor. Private repo olsa bile 4 kişilik ekipte bu, **sızmış anahtar** demektir; git geçmişinden silmek de ayrı bir acıdır.

**Çözüm.** Anahtar hiçbir zaman versiyon kontrolüne girmez. Ortam bazlı kapsam ayrımı: ENV-A data-only, ENV-B paper, ENV-C live (bkz. [ENVIRONMENTS.md §8](ENVIRONMENTS.md#8-sır-secret-yönetimi--ortam-bazlı)).

**DoD.**
- [ ] Repo'da yalnızca `config/config.example.json` (placeholder) var
- [ ] `.gitignore`: `.env`, `config/config.json`, `*.db`
- [ ] ENV-C anahtarları AWS SSM Parameter Store'da (SecureString)
- [ ] CI'da secret-scan adımı, PR'ı bloke edecek şekilde
- [ ] Live anahtar hiçbir geliştirici makinesinde bulunmuyor
- [ ] Anahtar rotasyon takvimi yazılı (üretime çıkışta bir kez, sonra 6 ayda bir)
- [ ] Geçmişte commit edilmiş anahtar varsa: iptal edilip yenilendi

---

## 🟠 P1 — İlk Kaza Buradan Çıkar

### TD-06 — Restart & pozisyon reconciliation yok
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Konteyner pozisyon açıkken yeniden başlarsa: (a) 100 barlık rolling window boştur, (b) sistem kendi açık pozisyonundan habersizdir. İkisi de sessizce yanlış davranışa yol açar.

**Çözüm.** Açılış sırası: warmup → broker'dan gerçeği çek → SQLite state'i ile karşılaştır → ayrışma varsa **broker'ı doğru kabul et** ve alarm ver.

**DoD.**
- [ ] `SetWarmUp` / history request ile pencere dolmadan sinyal üretilmiyor
- [ ] Açılışta Alpaca'dan açık pozisyon + açık emirler çekiliyor
- [ ] SQLite state'i ile mutabakat yapılıyor; ayrışma loglanıyor ve alarm üretiyor
- [ ] "Broker doğruyu söyler, veritabanı değil" ilkesi kodda uygulanmış
- [ ] ENV-B tatbikatı: pozisyon açıkken `docker kill` → restart → doğru toparlanma gözlendi

---

### TD-07 — Emir idempotency'si yok (çift emir riski)
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** HTTP timeout veya WebSocket yeniden bağlanmasında aynı emir iki kez gönderilebilir. Sonuç: hedeflenenin iki katı pozisyon, yani iki katı risk.

**Çözüm.** Her emre deterministik `client_order_id` ver: `{symbol}-{bar_timestamp}-{signal_hash}`. Alpaca duplike ID'yi reddeder.

**DoD.**
- [ ] Tüm emirlerde deterministik `client_order_id` üretiliyor
- [ ] ID aynı bar + aynı sinyal için **aynı** çıkıyor (birim test)
- [ ] Timeout sonrası retry politikası yazılı: yeniden gönder, ama aynı ID ile
- [ ] ENV-B'de bilerek çift gönderim denendi; ikincisi reddedildi ve loglandı

---

### TD-08 — Bayat veri (stale feed) koruması yok
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Feed durursa LEAN son barı tutmaya devam eder; model eski veriyle işlem açar. Piyasa hareket etmişken siz geçmişe bakarak alım yaparsınız.

**Çözüm.** Risk katmanında freshness guard: `now - last_bar_time > 2 × bar_süresi` ise sinyal üretme, alarm ver.

**DoD.**
- [ ] Freshness guard implemente edildi; eşik konfigüre edilebilir
- [ ] Guard tetiklendiğinde: sinyal üretilmiyor, log + alarm çıkıyor
- [ ] Seans dışı / tatil durumu yanlış alarm üretmiyor (takvim farkındalığı)
- [ ] Feed geri geldiğinde pencere doğru tamamlanıyor, delik ile devam edilmiyor
- [ ] ENV-B tatbikatı: ağ kesilerek guard tetiklendi ve işlem açılmadığı doğrulandı

---

### TD-09 — Global devre kesici (kill switch) yok
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Şu an yalnızca işlem-başına %1 risk var. Portföy seviyesinde hiçbir fren yok. Model bozulduğunda (veri değişimi, rejim kırılması, bug) sistemi durduracak mekanizma yok.

**Çözüm.** Katmanlı limitler + manuel panik anahtarı.

**DoD.**
- [ ] Günlük maksimum zarar limiti (ör. -%3) → günü kapat, yeni giriş yok
- [ ] Maksimum eşzamanlı pozisyon / maksimum toplam maruziyet limiti
- [ ] Saatlik emir-oranı limiti (runaway loop koruması)
- [ ] Manuel "hepsini kapat ve dur" anahtarı (dosya bayrağı veya env — SSH gerektirmeyen)
- [ ] Tetiklenen her limit loglanıyor ve alarm üretiyor
- [ ] Limitler restart'a dayanıklı (SQLite'tan yeniden kuruluyor)
- [ ] ENV-B tatbikatı: kill switch elle tetiklendi, pozisyonlar kapandı, sistem durdu

---

### TD-10 — Paper trading aşaması mimaride yok
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Orijinal mimaride backtest'ten doğrudan canlıya geçiliyordu. Paper aşamasının asıl amacı P&L görmek değil: **paper fill'leri ile backtest fill'lerini karşılaştırıp backtest'in ne kadar iyimser olduğunu ölçmek.**

**Çözüm.** ENV-B ortamı olarak mimariye eklendi (bkz. [ENVIRONMENTS.md §3](ENVIRONMENTS.md#3-env-b--local-beta-testnet--beta)). Bu madde, aşamanın **tamamlanmasını** takip eder.

**DoD.**
- [ ] Kararlaştırılan süre boyunca kesintisiz ENV-B çalışması tamamlandı
- [ ] Paper fill fiyatları ile backtest fill fiyatları karşılaştırma raporu üretildi
- [ ] Sapma backtest varsayımının içinde kaldı; kalmadıysa varsayım güncellendi ve backtest yenilendi
- [ ] Aynı dönemin paper P&L'i ile backtest P&L'i yan yana raporlandı (QC edildi)
- [ ] Kapı G2 kontrol listesindeki tüm tatbikatlar bu süre içinde yapıldı

---

### TD-11 — İşlem maliyeti modeli yok
**Önem:** 🟠 P1 · **Ortam:** ENV-A + ENV-B · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** Alpaca komisyonsuz ama **spread, slippage ve SEC/TAF ücretleri** var. Backtest bunları içermiyorsa, saatlik frekanslı bir stratejide kâğıt üstündeki tüm edge maliyetin altında kalabilir.

**Çözüm.** Backtest'e açık bir maliyet modeli koy; sonuçları maliyet dahil **ve** hariç raporla ki farkı görün.

**DoD.**
- [ ] Maliyet modeli yazılı: spread varsayımı, slippage varsayımı, düzenleyici ücretler
- [ ] Backtest çıktısı hem maliyet dahil hem hariç P&L üretiyor
- [ ] QC listesine "maliyet dahil/hariç net P&L farkı" eklendi
- [ ] Strateji maliyet dahil hâlâ pozitif (değilse G1 geçilmez)
- [ ] Varsayımlar ENV-B'de ölçülen gerçek slippage ile karşılaştırıldı (TD-10 ile bağlantılı)
- [ ] Duyarlılık analizi: slippage 2x olsa strateji hâlâ pozitif mi?

---

### TD-12 — Örneklem boyutu vs model kapasitesi
**Önem:** 🟠 P1 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** Saatlik barla AAPL'da yılda ~1.750 örnek; 5 yıl ≈ 8.750 satır, ~6 feature, ve çok düşük sinyal/gürültü oranı. XGBoost bu boyutta ezberlemeye fazlasıyla yatkın.

**Çözüm.**
1. Model kapasitesini agresif sınırla: `max_depth` 2–3, güçlü regularization, düşük learning rate + early stopping (walk-forward validation üzerinde).
2. **Havuzlanmış (pooled) eğitim** düşün: 30–50 likit hisseyi aynı feature şemasıyla eğitip AAPL'da işlem yap. Örnek sayısını ~30x artırır ve modeli tek hisseye ezberlemekten kurtarır. Mimari buna zaten uygun — feature'lar sembol-bağımsız ve normalize.

**DoD.**
- [ ] Eğitim seti satır sayısı ve feature sayısı raporlanıyor
- [ ] Hiperparametre sınırları yazılı ve `train.py`'da zorunlu (derinlik üst sınırı kodda)
- [ ] Pooled eğitim kararı verildi ve gerekçesi yazıldı (yapılacak / yapılmayacak, neden)
- [ ] Learning-curve analizi: veri arttıkça performans artıyor mu, yoksa doymuş mu?
- [ ] Basit bir baseline (ör. "hep long" veya tek indikatörlü kural) ile karşılaştırma yapıldı — model bunu yenemiyorsa model yoktur

---

### TD-18 — Broker seçimi kesinleşmedi (Alpaca vs IBKR)
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık · **Karar:** AK-2

**Sorun.** Mimari Alpaca varsayıyor. Ama küçük hesapta para giriş/çıkış maliyeti Alpaca'da ciddi, IBKR'de neredeyse yok. Karar verilmeden ENV-C'ye çıkılamaz: broker seçimi hem maliyeti, hem TD-19'u, hem de ileride AB piyasası erişimini belirliyor.

**Karşılaştırma.**

| | **Alpaca** | **Interactive Brokers** |
|---|---|---|
| Para yatırma | %1,5 (tavan $40) | Ayda ilk transfer **ücretsiz** |
| Para çekme | %1,5 (tavan $40) + $50 giden havale | Ayda ilk çekim **ücretsiz**, sonrası $10 |
| Gelen havaleden kesinti | Var | Yok |
| **$1.000 gidiş-dönüş maliyet** | **~$65 + banka SWIFT** | **~$0 + banka SWIFT** |
| Entegrasyon | Saf REST/WebSocket — basit | **IB Gateway** sürekli çalışmalı — Docker'da zahmetli, reconnect dertli |
| LEAN desteği | ✅ Native | ✅ Native |
| Anlık konsolide (SIP) veri | $99/ay | Aylık birkaç dolar mertebesinde (teyit edilmeli) |
| Kesirli hisse + koruyucu stop | ❌ (bkz. TD-19) | Farklı kısıtlar — ayrıca doğrulanmalı |
| AB borsaları | ❌ Yok | ✅ Var (LEAN tarafı ayrı sorun) |
| BIST | ❌ | ❌ (IBKR Borsa İstanbul'a erişim sunmuyor) |

**Not.** Transfer maliyeti **bir kerelik** bir yüktür, işlem maliyeti süreklidir. Bu kararı tek başına transfer ücretine bakarak vermeyin — IBKR'nin ucuzluğunun karşılığı, IB Gateway'i 7/24 ayakta tutma operasyonel borcudur.

**DoD.**
- [ ] Karar yazılı: hangi broker, hangi gerekçeyle (AK-2 kapatıldı)
- [ ] Seçilen brokerın Türkiye ikametli live hesap kabul ettiği **yazılı olarak** teyit edildi
- [ ] Transfer maliyetleri planlanan ilk sermaye üzerinden gerçek rakamlarla hesaplandı
- [ ] IBKR seçilirse: IB Gateway'in Docker içinde çalıştığı ve kopma sonrası kendiliğinden toparlandığı ENV-B'de kanıtlandı
- [ ] Emir gönderen katman adaptör arkasında — broker değişimi `features.py` ve model tarafına dokunmuyor

---

### TD-19 — Kesirli hissede broker'da koruyucu stop kurulamıyor
**Önem:** 🟠 P1 · **Ortam:** ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Küçük hesapta AAPL gibi yüksek fiyatlı bir hisseyi tam adet almak mümkün değil, kesirli (fractional) almak gerekiyor. Ama Alpaca'da kesirli emirlerde:
- `time_in_force = DAY` zorunlu (GTC yok)
- **Bracket / OCO emirleri desteklenmiyor** — "pozisyonu aç + koruyucu stop'u broker'a bırak" tek işlemde kurulamıyor

**Neden önemli.** Mimaride "dinamik Trailing Stop-Loss" var ve bunun broker tarafında duracağı varsayılıyor. Duramıyor. Stop'u **kendi süreciniz** yönetmek zorunda: her barda pozisyonu kontrol edip gerekirse kapatan bir döngü.

Sonucu şu: **süreç ölürse koruma da ölür.** Borsada sizi bekleyen hiçbir koruyucu emir kalmaz, pozisyon açıkta kalır. Bu yüzden TD-06 (restart/reconciliation) ve TD-09 (kill switch) bu senaryoda "iyi olur" maddeleri değil, **koruyucu emrin yerine geçen mekanizmalardır.**

**Çözüm seçenekleri.**
1. Tam adet alınabilecek kadar sermaye ile çalış — kesirliye gerek kalmaz, koruyucu stop broker'da durur (en temizi)
2. Kesirli kal, stop'u kodda yönet, süreç dayanıklılığını (TD-06 / TD-09) buna göre sertleştir
3. Daha düşük fiyatlı bir enstrümana geç

**DoD.**
- [ ] Seçenek kararı yazılı
- [ ] Kesirli kalınacaksa: stop mantığı kodda implemente edildi ve birim testleri var
- [ ] Süreç ölümü tatbikatı: pozisyon açıkken süreç öldürüldü, yeniden başlayınca stop seviyesi doğru yeniden kuruldu (TD-06 ile birlikte)
- [ ] Koruyucu emrin broker'da **olmadığı** riski ekipçe kabul edildi ve yazılı
- [ ] Seçilen brokerın kesirli emir kısıtları güncel dokümandan doğrulandı (TD-18 ile birlikte)

---

## 🟡 P2 — Süreçsel, Şimdi Ucuz Sonra Pahalı

### TD-13 — `features.py` iki repoya çatallanacak
**Önem:** 🟡 P2 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** `features.py` `trading-core`'da yaşıyor ama araştırmacılar `trading-research` notebook'larında ona ihtiyaç duyacak → kopyalayacaklar → sessizce ayrışacak. Bu, **train/serve skew'in ikinci kapısı** (bkz. TD-01).

**Çözüm.** `features`'ı pip ile kurulabilir bir paket yap; research repo'su sürüm pinleyerek import etsin: `pip install git+ssh://...@v0.3.1`.

**DoD.**
- [ ] `features` paketlenebilir hâle geldi (`pyproject.toml`)
- [ ] `trading-research` onu sürüm pinli import ediyor; kopya dosya yok
- [ ] Research repo'sunda `features.py` kopyası bulunmadığını doğrulayan CI kontrolü
- [ ] Sürüm yükseltme prosedürü yazılı (notebook'lar hangi sürümle çalıştı, kayıtlı)

---

### TD-14 — Çoklu test / p-hacking kontrolsüz
**Önem:** 🟡 P2 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** "Tam konsensüs" kuralı kimin onayladığını kaydediyor ama **kaç hipotez denendiğini** kaydetmiyor. 40 hipotez deneyip en iyi 3'ünü seçerseniz, o 3'ünün backtest Sharpe'ı istatistiksel olarak anlamsızdır — ve bunu fark etmenin tek yolu deneme sayısını bilmektir.

**Çözüm.** `hypotheses/` klasörünü bir **kayıt defteri (pre-registration)** olarak işlet: hipotez test edilmeden *önce* yazılır, sonuç — **başarısızlar dahil** — kaydedilir.

**DoD.**
- [ ] Hipotez şablonu oluşturuldu (tarih, sahip, iddia, test planı, başarı kriteri — hepsi test öncesi)
- [ ] Başarısız hipotezler de repoda kalıyor, silinmiyor
- [ ] Toplam deneme sayısı sayılabilir durumda
- [ ] Deflated / haircut Sharpe hesabı deneme sayısını girdi olarak kullanıyor
- [ ] QC raporunda "bu sonuç kaç denemenin en iyisi?" satırı var

---

### TD-15 — Model artifact'i şemasını taşımıyor
**Önem:** 🟡 P2 · **Ortam:** ENV-A + ENV-B · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** `model.json` tek başına "hangi feature'lar, hangi sırayla" bilgisini garanti etmiyor. Feature sırası sessizce kayarsa model çalışmaya devam eder — sadece anlamsız tahminler üretir. Bulunması en zor hata türü.

**Çözüm.** Yanına `model_meta.json` koy ve yükleme anında `assert` et.

**DoD.**
- [ ] `model_meta.json` üretiliyor: feature isim listesi + sırası, eğitim tarih aralığı, kod commit SHA'sı, xgboost & pandas-ta sürümleri, feature şema hash'i
- [ ] Canlı yüklemede şema hash'i doğrulanıyor; uyuşmazlıkta sistem **başlamıyor** (sessizce devam etmiyor)
- [ ] CI'da model serileştirme testi bu doğrulamayı kapsıyor
- [ ] Model artifact'i sürümlenerek saklanıyor (hangi tag hangi modelle çalıştı, geriye dönük bilinebilir)

---

### TD-16 — İndikatör kütüphanesi ikiliği
**Önem:** 🟡 P2 · **Ortam:** ENV-A · **Kapı:** G1 · **Durum:** ⬜ Açık

**Sorun.** LEAN'in kendi native indikatörleri (RSI, ATR, BB) var, biz Pandas-TA kullanıyoruz. İkisi karışırsa farklı sayılar üretir — örneğin Wilder smoothing ile SMA farkı. Warmup'ı native indikatörle, feature'ları pandas-ta ile yapmak sessiz bir tutarsızlık kaynağıdır.

**Çözüm.** Tek kaynakta karar kıl: **feature hesabı tamamen `features.py`/pandas-ta içinde kalsın, LEAN sadece bar taşısın.**

**DoD.**
- [ ] Karar yazılı: LEAN native indikatörleri feature üretiminde kullanılmıyor
- [ ] LEAN algoritma kodunda indikatör tanımı yok (yalnızca bar toplama + `features.calculate()` çağrısı)
- [ ] `pandas-ta`, `numpy`, `pandas`, `xgboost` sürümleri pinli (`requirements.txt` / lock)
- [ ] Aynı sürümler ENV-A, ENV-B, ENV-C'de birebir aynı (imaj üzerinden garanti)

---

### TD-17 — Saat dilimi & DST belirsizliği
**Önem:** 🟡 P2 · **Ortam:** ENV-A + ENV-B · **Kapı:** G2 · **Durum:** ⬜ Açık

**Sorun.** Mimaride "saat başında senkronize eder (14:00:00)" yazıyor — UTC mi, America/New_York mı belirsiz. DST yılda iki kez kayar ve o iki günde sistem sessizce yanlış barla çalışır.

**Çözüm.** Tek kural: **hesaplama ve seans mantığı exchange time (America/New_York), tz-aware; kalıcılık UTC epoch.** Hiçbir yerde naive datetime yok.

**DoD.**
- [ ] Tüm datetime nesneleri tz-aware; naive datetime kullanımını yakalayan lint/test var
- [ ] SQLite'a UTC epoch (veya ISO-8601 + offset) yazılıyor
- [ ] Seans mantığı (açılış/kapanış, yarım günler) exchange takviminden geliyor, sabit saatten değil
- [ ] DST geçiş tarihlerini içeren bir backtest aralığı test edildi
- [ ] Yarım gün (ör. Şükran Günü sonrası) ve erken kapanış davranışı doğrulandı

---

## Önerilen Çalışma Sırası

Bağımlılıkları gözeterek — bir madde kendinden öncekiler olmadan anlamlı şekilde kapatılamaz:

| Sprint | Odak | Maddeler | Ortam |
|---|---|---|---|
| **S0** | **Açık kararlar** — koda başlamadan verilmeli | AK-1, AK-2, AK-3 | — |
| **S1** | Temeli doğru at — sonradan değiştirilirse her şey yeniden yapılır | TD-05, TD-13, TD-16, TD-17 | ENV-A |
| **S2** | Veri hattı doğruluğu — modelin altındaki zemin | TD-01, TD-03, TD-11 | ENV-A |
| **S3** | Model dürüstlüğü — sonuçlara inanabilmek | TD-02, TD-12, TD-14, TD-15 | ENV-A |
| — | **🚪 Kapı G1** | | ➜ ENV-B |
| **S4** | Operasyonel dayanıklılık — sistemin ayakta kalması | TD-06, TD-07, TD-08, TD-09, **TD-19** | ENV-B |
| **S5** | Gerçeklik kontrolü — paper çalışma + düzenleyici uyum | TD-10, TD-04, **TD-18** | ENV-B |
| — | **🚪 Kapı G2** | | ➜ ENV-C |

**Neden bu sıra:** TD-05 (secret) ve TD-13 (paketleme) sonradan yapılırsa geçmişi temizlemek gerekir. TD-01 (parity) çözülmeden TD-02'nin (CV) ürettiği sayılar zaten anlamsızdır. TD-03 (hedef) tanımsızken model eğitmek boşa emektir. Operasyonel maddeler (S4) ancak gerçek bir feed karşısında test edilebildiği için ENV-B'yi bekler.
