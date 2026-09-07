# Algoritmik Al-Sat Sistemi — Mimari Dokümanı

> **Proje:** ABD hisse senedi piyasaları (başlangıç: `AAPL`, `SPY`) için uçtan uca, canlı, kurumsal standartta algoritmik al-sat sistemi
> **Doküman durumu:** 🟡 TASLAK — ekipçe tartışılmadı, hiçbir madde kesinleşmedi
> **Son güncelleme:** 2026-09-08
> **İlgili dokümanlar:** [ENVIRONMENTS.md](ENVIRONMENTS.md) (ortam ayrımı & terfi kapıları) · [TECH_DEBT.md](TECH_DEBT.md) (açık teknik borç) · [README.md](README.md) (indeks)

---

## İçindekiler

1. [Teknoloji Yığını & Kesin Kısıtlar](#1-teknoloji-yiğini--kesin-kisitlar)
2. [İç İçe (Nested) Sistem & Dosya Dizin Hiyerarşisi](#2-iç-içe-nested-sistem--dosya-dizin-hiyerarşisi)
3. [Canlı Veri Akışı — Streaming Mikro-ETL](#3-canli-veri-akişi--streaming-mikro-etl)
4. [Repo Stratejisi — Tek Private Repo](#4-repo-stratejisi--tek-private-repo)
5. [İş Akışı — Feature Engineering Loop](#5-iş-akişi--feature-engineering-loop)
6. [Özellik (Feature) Sözleşmesi](#6-özellik-feature-sözleşmesi)
7. [Çoklu Hipotez, Model Ayrımı & Orkestratör](#7-çoklu-hipotez-model-ayrimi--orkestratör)
8. [Risk Yönetimi Parametreleri](#8-risk-yönetimi-parametreleri)
9. [CI/CD Kapıları (Quality Gates)](#9-cicd-kapilari-quality-gates)
10. [Ortam Ayrımı & Açık Teknik Borç](#10-ortam-ayrimi--açik-teknik-borç)
11. [Uçtan Uca Akış — Hipotezden Canlı Emre](#11-uçtan-uca-akiş--hipotezden-canli-emre)

---

## 1. TEKNOLOJİ YIĞINI & KESİN KISITLAR

| Katman | Seçim |
|---|---|
| **Çekirdek diller & kütüphaneler** | Python (Pandas, NumPy, Pandas-TA), C# / Python (QuantConnect LEAN Motoru), XGBoost |
| **Orkestrasyon & Broker** | QuantConnect LEAN Engine, Alpaca Markets API (WebSocket canlı veri + REST emir yürütme) |
| **Veri depolama & kalıcılık** | SQLite — append-only, indeksli flat tablolar; canlıda üretilen tek satırlık barlar, model sinyalleri, emir/trade ve state logları |
| **Altyapı & dağıtım** | AWS EC2 (Ubuntu Linux) üzerinde Docker & Docker Compose ile izole konteyner mimarisi |
| **CI/CD** | GitHub Actions — `pytest`, NaN denetimi, veri sızıntısı (leakage / `shift(-n)`) kontrolü, model serileştirme doğrulaması, lint |

---

## 2. NESTED SİSTEM & DOSYA DİZİN HİYERARŞİSİ

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ GITHUB (Bulut & Versiyon Kontrolü)                                                               │
│                                                                                                  │
│   ├── .github/workflows/                                                                         │
│   │     └── ci.yml                     ──► [GitHub Actions Runner] (pytest, lint, leakage test)  │
│   │                                                                                              │
│   └── Repo Kök Dizini                                                                            │
│         ├── data/                      ──► Alpaca geçmiş CSV/Parquet (train için)                │
│         ├── src/                                                                                 │
│         │     ├── features.py          ──► Ortak formatlayıcı (XGBoost girdileri)                │
│         │     └── train.py             ──► Model eğitim ve hiperparametre script'i               │
│         ├── models/                                                                              │
│         │     └── model.json           ──► Eğitilmiş XGBoost ağırlık kütüğü                      │
│         ├── config/                                                                              │
│         │     └── config.json          ──► Alpaca API anahtarları, sembol listesi                │
│         ├── Dockerfile                 ──► Konteyner derleme talimatları                         │
│         └── docker-compose.yml         ──► Servis orkestrasyonu                                  │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼ (Deploy / git pull)
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ AWS EC2 INSTANCE (Linux Ubuntu Host / Cloud OS)                                                  │
│                                                                                                  │
│   ├── Host Dosya Sistemi (Persistent Storage / Disk)                                             │
│   │     ├── /var/log/trading_bot.log   ──► Standart çıktı ve hata logları                        │
│   │     └── /var/data/market_data.db   ──► SQLite Veritabanı (Append-only flat tables, indeksli) │
│   │           ▲                                                                                  │
│   │           │ (Volume Mount: /app/data -> /var/data)                                           │
│   │           ▼                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────────────────────┐   │
│   │ DOCKER CONTAINER (isolated runtime: python-lean-engine)                                  │   │
│   │                                                                                          │   │
│   │   ┌───────────────────────────────────────────────────────────────────────────────────┐  │   │
│   │   │ QUANTCONNECT LEAN MOTORU (C# / Python Runtime)                                    │  │   │
│   │   │                                                                                   │  │   │
│   │   │   ├── Veri Yakalama (Extract & Sync)                                              │  │   │
│   │   │   │     └── Slice Manager      ──► Alpaca WebSocket'ten gelen AAPL + SPY'ı        │  │   │
│   │   │   │                                saat başında senkronize eder (14:00:00)        │  │   │
│   │   │   │                                                                               │  │   │
│   │   │   ├── Bellek Alanı (In-Memory Buffer)                                             │  │   │
│   │   │   │     └── Rolling Window     ──► Son 100 barlık senkronize OHLCV matrisi        │  │   │
│   │   │   │                                      │                                        │  │   │
│   │   │   │                                      ▼                                        │  │   │
│   │   │   ├── Python Modülü: src/features.py (Transform / Formatlayıcı)                   │  │   │
│   │   │   │     └── calculate()        ──► Log-return, RSI, Volatilite, Rel-Return        │  │   │
│   │   │   │                                      │                                        │  │   │
│   │   │   │                                      ▼ (Tek satırlık özellik vektörü)         │  │   │
│   │   │   ├── Çıkarım Motoru: models/model.json (XGBoost Runtime)                         │  │   │
│   │   │   │     └── predict_proba()    ──► Olasılık hesabı (örn: %72 BUY)                 │  │   │
│   │   │   │                                      │                                        │  │   │
│   │   │   │                                      ▼                                        │  │   │
│   │   │   └── Portföy & Risk Yönetimi                                                     │  │   │
│   │   │         ├── Risk Manager       ──► %1 Kasa riski, Trailing Stop-Loss kontrolü     │  │   │
│   │   │         └── Execution Handler  ──► Alpaca REST API'ye HTTP POST ile emir iletimi  │  │   │
│   │   └───────────────────────────────────────────────────────────────────────────────────┘  │   │
│   └──────────────────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. CANLI VERİ AKIŞI — STREAMING MİKRO-ETL

Canlı sistem şu iç içe (nested) döngüde çalışır:

### 3.1 Extract & Sync
LEAN **Slice Engine**, Alpaca WebSocket üzerinden gelen `AAPL` ve `SPY` dakikalık/saatlik barlarını **aynı zaman damgasında** (dahili saat bariyeri) senkronize eder.
RAM'de **son 100 barlık** senkron bir kayan pencere (Rolling Window) tutulur.

### 3.2 Transform — `src/features.py`
Ham borsa kütüğü (OHLCV), XGBoost için **durağan (stationary)** ve normalize edilmiş bir özellik vektörüne dönüştürülür.

> **Kural:** `features.py` hem offline eğitimde hem de canlı çıkarımda (inference) **birebir aynı** çalışan ortak bir "hesap makinesi / formatlayıcıdır".
> İçinde **asla** hedef değişken (y) veya gelecek sızıntısı (`shift(-n)`) bulunmaz.

### 3.3 Inference & Risk Engine
Çıkarılan tek satırlık vektör, diske serialize edilmiş `models/model.json` (XGBoost) modeline verilir → `predict_proba()`.
Üretilen sinyal LEAN risk katmanına girer: sermaye koruma **%1 risk**, dinamik **Trailing Stop-Loss**.

### 3.4 Load & Execution
Uygun sinyal oluştuğunda Alpaca REST API üzerinden piyasa/limit emri iletilir; **eşzamanlı olarak** bar ve işlem bilgisi, diske volume-mount edilmiş SQLite veritabanına loglanır.

### 3.5 Akış Şeması

```text
  Alpaca WebSocket
        │  (AAPL bar, SPY bar)
        ▼
  ┌─────────────────┐
  │ 1. EXTRACT&SYNC │  LEAN Slice Manager — ortak timestamp bariyeri
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ Rolling Window  │  RAM: son 100 bar × senkron OHLCV
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ 2. TRANSFORM    │  features.calculate()  →  [f1, f2, ... fN]  (1 satır)
  └────────┬────────┘  * offline eğitim ile BİREBİR aynı kod *
           ▼
  ┌─────────────────┐
  │ 3. INFERENCE    │  XGBoost model.json → predict_proba() → p(BUY)
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ 3b. RISK ENGINE │  %1 kasa riski · pozisyon boyutu · Trailing SL
  └────────┬────────┘
           ▼
  ┌─────────────────┐        ┌──────────────────────────┐
  │ 4. EXECUTION    │───────►│ Alpaca REST (order POST) │
  └────────┬────────┘        └──────────────────────────┘
           │
           ▼
  ┌───────────────────────────────────────────┐
  │ SQLite (append-only): bars · signals ·     │
  │ orders · fills · state   → /var/data/*.db  │
  └───────────────────────────────────────────┘
```

## 4. REPO STRATEJİSİ — TEK PRIVATE REPO

**Karar (2026-09-08): Her şey tek bir private repoda tutulur.** Araştırma ve
üretim kodu ayrı depolara bölünmez; ayrım **klasör düzeyinde** yapılır.

```text
  trading_project/  (tek private repo)
        │
        ├── hypotheses/   hipotez kayıt defteri, reddedilenler dahil
        ├── lab/          notebook'lar, keşif
        │                 ── CI denetlemez, dağınık olabilir
        │
        ├── src/          features.py, train.py, data katmanı
        ├── tests/        ── CI burayı denetler: sızıntı, NaN, şema
        └── models/
```

**Gerekçe.** Çift repo ayrımının gerekçeleri (yetki ayrımı, patlama yarıçapı,
farklı değişim hızı) birden fazla kişi varsayar; proje tek geliştiricili.
Kalan tek gerçek gerekçe olan CI disiplini ise klasör kapsamıyla çözülür:
CI yalnızca `src/` ve `tests/`'i denetler, `lab/` altını görmez.

Tek repo aynı zamanda `features.py`'ın çatallanma riskini kökten kaldırır —
notebook doğrudan `from src.features import calculate` der, kopyalanacak bir
şey yoktur (§6, Değişmez Kural 1).

**Ne zaman bölünür.** Repoya ikinci bir kişi commit atmaya başladığında ve bu
kişinin canlı emir veren koda push yetkisi olmaması gerektiğinde. O gün
`features` kurulabilir paket yapılır, araştırma tarafı sürüm pinleyerek import
eder — kopyalama asla.

---

## 5. İŞ AKIŞI — FEATURE ENGINEERING LOOP

Döngü, hipotezden hükme kadar dört adımdan oluşur.

| Adım | Yapılan iş | Kod gerekir mi |
|---|---|---|
| 1 | Piyasa hipotezi ve mantıksal şartları yazılır (Docs / Notion) | Hayır |
| 2 | Hipotez geçmiş veri setinde test edilir (Jupyter); anlamlıysa `features.py`'a eklenir, sızıntı ve tip kontrolleri yapılır | Evet |
| 3 | `train.py` çalıştırılır; `model.json` ve backtest sonuçlarını içeren CSV üretilir | Evet |
| 4 | Üretilen CSV kalite kontrolden geçirilir: maksimum drawdown, arka arkaya kayıp serileri, aykırı değer stresi | Hayır |

```text
   ┌───────────────┐   hipotez    ┌───────────────┐  anlamlı?  ┌───────────────┐
   │   HİPOTEZ     │─────────────►│     TEST      │───────────►│    EĞİTİM     │
   │ (Docs/Notion) │              │   (Jupyter)   │ features.py│   (train.py)  │
   └───────────────┘              └───────────────┘            └───────┬───────┘
           ▲                                                           │
           │                      ┌───────────────┐   backtest CSV     │
           └──────────────────────│  KALİTE KONT. │◄───────────────────┘
              geri bildirim       │  (Sheets/QC)  │
              (drawdown, outlier) └───────────────┘
```

---

## 6. ÖZELLİK (FEATURE) SÖZLEŞMESİ

`src/features.py` içinde hesaplanan, durağan ve normalize edilmiş girdilerin bulunacağı sayfa.

### Değişmez Kurallar (Invariants)

1. `features.py` **tek kaynak** — eğitim ve canlı çıkarım aynı fonksiyonu çağırır.
2. Modül içinde **hedef (y) üretimi yoktur**; hedef yalnızca `train.py` içinde ve açıkça oluşturulur.
3. **`shift(-n)` yasaktır** — CI bunu statik olarak denetler.
4. Çıktı, sabit sıralı ve isimlendirilmiş bir sütun şemasıdır; sıra değişimi model uyumsuzluğu sayılır.
5. NaN üretilmez; yetersiz pencere durumunda satır **açıkça** geçersiz işaretlenir, uydurma değerle doldurulmaz.

---

## 7. ÇOKLU HİPOTEZ, MODEL AYRIMI & ORKESTRATÖR

Sistem tek bir hipoteze değil, **birbirinden bağımsız birden çok hipoteze** dayanır.
Bu bölüm üç soruyu cevaplar: bir hipotez ne zaman ayrı model olur, **çelişen
çıktılar** nasıl tek emre indirgenir, ve çok deneme yapmanın bedeli nasıl ödenir.

### 7.1 Katman Şeması

```text
   H-001 modeli  ─┐
   H-002 modeli  ─┤
   H-003 modeli  ─┼──► ORKESTRATÖR ──► RİSK ──► EXECUTION ──► LOG
        ...      ─┤    birleştirme     %1 kasa   Alpaca REST   SQLite
   H-00N modeli  ─┘    fonksiyonu      trailing SL
                       tek net sinyal
```

**Değişmez kural:** Hiçbir model borsa API'sine doğrudan gitmez. Emir yalnızca
orkestratör → risk zincirinden geçtikten sonra, **tek** bir noktadan çıkar.

### 7.2 Bir Hipotez Ne Zaman Ayrı Model Olur

Bölen çizgi **hedeftir (y)**, fikrin ne kadar farklı hissettirdiği değil:

| Durum | Karar | Gerekçe |
|---|---|---|
| Hipotezler **aynı y**'yi paylaşıyor | Tek model, her hipotez bir **sütun** | Bir eğitim tablosunda tek cevap sütunu vardır. Ayrıca ağaç, hipotezler arası **etkileşimi** öğrenir — "kanal dibi VE düşük oynaklık" gibi bileşik şartlar ancak tek modelde temsil edilir. |
| Hipotezlerin **y'si farklı** (farklı ufuk, meta-etiketleme) | **Ayrı model** | Farklı y = farklı tablo = farklı model. Tercih değil, zorunluluk. |

Karar hipotez **kayıt anında** verilir ve `hypotheses/REGISTRY.md` içinde hedefiyle
birlikte yazılır; böylece "ayıralım mı" tartışması her seferinde yeniden yapılmaz.

### 7.3 Orkestratör — Birleştirme Fonksiyonu

Orkestratörün çözdüğü problem şudur: **modeller çelişirse hangisini ne kadar
ciddiye alacağız?** Cevap sözel/ayrık bir kural değil (ör. "hepsi aynı yönü
söylerse işlem"), **kapalı formda bir fonksiyondur.** Ayrık oylama üç bilgiyi
birden çöpe atar: sinyalin şiddetini, modelin güvenilirliğini, ve N büyüdükçe
işlem frekansını sıfıra düşürür.

```text
             Σᵢ  tᵢ · wᵢ
    S  =  ─────────────────           S ∈ [-1, +1]
             Σᵢ  tᵢ  +  ε

              ⎧  AL      S > +τ
    karar  =  ⎨  SAT     S < −τ
              ⎩  BEKLE   aksi halde
```

| Sembol | Anlam | Aralık |
|---|---|---|
| `wᵢ` | Model *i*'nin çıktısı — yön **ve** şiddet, işaretli | `[-1, +1]` |
| `tᵢ` | Model *i*'nin **güvenilirliği** — ne kadar ciddiye alınacağı | `> 0` |
| `τ` | İşlem eşiği — tek serbest parametre | `[0, 1)` |
| `ε` | Sıfıra bölmeyi engeller | küçük sabit |

**Neden `w` işaretli:** Alış ve satış taraflarını ayrı büyüklükler olarak tutup
çıkarmaya gerek yok; işaretli `w` ile çelişen modeller toplamda kendiliğinden
birbirini götürür. İki model `+1` ve `−1` derse `S = 0` → **BEKLE**. Biri `+1`,
diğeri `−0.3` derse `S = +0.35` → yön yukarı, şiddet zayıf.

**Neden normalize:** `Σtᵢ`'ye bölünmezse `S` model sayısıyla büyür; 3 modelde
anlamlı olan `τ`, 6 modelde anlamsız kalır ve her yeni modelde eşiği yeniden
ayarlamak gerekir — ki bu da §7.4'e göre yeni bir deneme demektir. Normalize
edilince `τ`, N'den bağımsız kalır.

**Başlangıçta `t = 1` — tüm modeller için.** Yani her model eşit ciddiyette
dinlenir ve `S`, çıktıların basit ortalaması olur. Bu bilinçli bir tercih:
sıfır serbest parametre, dolayısıyla aşırı uyum yüzeyi yok. `t`'nin veriden
nasıl türetileceği açık madde olarak **TECH_DEBT.md TD-20**'de takip edilir.

**Diğer sözleşme maddeleri:**

| | Kural |
|---|---|
| **Girdi** | Model `wᵢ` üretir; ham lot/adet **üretmez** — pozisyon boyutu risk katmanının işidir. |
| **İzolasyon** | Her modele veri salt-okunur (kopya) verilir; biri diğerinin girdisini değiştiremez. |
| **Belirlenimcilik** | Zaman aşımı, paralel yarış, makine yüküne bağlı davranış **yasak**. Aynı girdi her koşuda aynı `S`'i vermek zorundadır; aksi halde backtest canlıda tekrar edilemez. |

Kod, ikinci model ortaya çıkana kadar yazılmaz; fonksiyon belli olduğu için o
kısım küçük bir iştir. Tetik şartı: **farklı hedefe sahip ikinci doğrulanmış hipotez.**

### 7.4 Çoklu Deneme Disiplini

Bağımsız modeller birbirini **kirletmez** — ama en iyisini seçmek skoru şişirir.
Tamamen değersiz 50 strateji denenirse, aralarındaki en iyisi ortalama **~2.1 sigma**
(p ≈ 0.02) çıkar. Düzeltme yapılmazsa gürültüye "anlamlı" damgası basılır.

Ayrıntılı DoD **TD-14**'te; buradaki özet:

1. **Deneme sayacı — `hypotheses/REGISTRY.md`.** Hipotez test edilmeden **önce**
   kaydedilir. **Reddedilenler kayıtta kalır**; yalnızca kazananlar kaydedilirse
   deneme sayısı bilinemez ve düzeltme anlamsızlaşır. Aynı hipotezin farklı
   frekansta (günlük/saatlik) sınanması **iki deneme** sayılır. `τ` eşiği ve
   `t` şeması da birer denemedir (TD-20).
2. **Eşik düzeltmesi.** Bonferroni (α/m) veya Benjamini-Hochberg (FDR).
   Finans karşılığı: **Deflated Sharpe Ratio**.
3. **Efektif deneme sayısı (N_eff).** Birbirinin türevi olan hipotezler
   (RSI-14 / RSI-21) tek deneme sayılır; ceza bağımsız küme sayısı üzerinden
   kesilir. **Kümeleme sonuçlara bakılmadan**, özellik korelasyonuna göre yapılır —
   aksi halde cezayı istediğin kadar küçültebileceğin bir kaçış kapısı açılır.

### 7.5 Veri Bölme Politikası

```text
2016-01 ──────────────────── 2024-06 │embargo│ 2024-07 ──────── 2026-09
   ARAŞTIRMA ALANI (~%80)                        KİLİTLİ KASA (~%20)
   walk-forward / purged CV                      tek seferlik
   hipotez seçimi, pencere seçimi, τ, t          nihai birleşik sistem
   sınırsız bakılır                              BİR KEZ açılır
```

- Sınırlar **tek yerde** sabitlenir (`src/splits.py`); her hipotez birebir aynı
  kesimi kullanır, yoksa sonuçlar karşılaştırılamaz.
- **Eğitim seti tüm hipotezlerde ortaktır** ve sınırsız kullanılır — performans
  tahmini oradan alınmadığı için yakılacak bir tarafsızlığı yoktur.
- **Embargo**, etiket ufku (K bar) kadar; sızıntının tehlikeli yönü özellik
  penceresi değil **etikettir**.
- Kasa açıldıktan sonra son doğrulama geçmiş veride değil, **ENV-B paper trading**
  üzerinde yapılır — kendini her gün yenileyen, hiç bakılmamış gerçek holdout.

Yöntem ayrıntısı TD-02 (purged walk-forward CV) ve TD-12 (örneklem boyutu vs
model kapasitesi) altında takip edilir.

---

## 8. RİSK YÖNETİMİ PARAMETRELERİ

> ⚠️ **EKSİK BÖLÜM.** Bu başlık içindekiler listesinde vardı ancak gövdesi
> dokümanda hiç yazılmamış. Doldurulması gereken asgari maddeler: işlem başına
> kasa riski (%1), pozisyon boyutu formülü, trailing stop parametreleri,
> günlük/haftalık kayıp limitleri, eşzamanlı açık pozisyon tavanı, kesirli
> hissede koruyucu stop'un nerede durduğu (bkz. TECH_DEBT.md TD-19).

---

## 9. CI/CD KAPILARI (QUALITY GATES)

GitHub Actions (`.github/workflows/ci.yml`) üzerinde her PR için zorunlu kontroller:

- [ ] `pytest` — birim ve entegrasyon testleri
- [ ] **Leakage denetimi** — `shift(-n)` / gelecek referansı statik taraması
- [ ] **NaN denetimi** — feature çıktısında NaN/Inf toleransı sıfır
- [ ] **Model serileştirme doğrulaması** — `model.json` yüklenebiliyor, beklenen feature sayısı ve sırası eşleşiyor
- [ ] Lint / format

---

## 10. ORTAM AYRIMI & AÇIK TEKNİK BORÇ

Bu doküman sistemin **hedef mimarisini** tanımlar. Onu tamamlayan iki doküman:

### 10.1 Ortam Ayrımı — [ENVIRONMENTS.md](ENVIRONMENTS.md)

Yukarıdaki mimari üç ayrı ortamda koşar ve **kod her üçünde de aynıdır**; değişen yalnızca konfigürasyon, sır ve yetkidir:

| Ortam | Rol | Emir hedefi | Sermaye |
|---|---|---|---|
| **ENV-A** LOCAL-RESEARCH | Hipotez, eğitim, backtest — **modelin doğduğu tek yer** | Yok | — |
| **ENV-B** LOCAL-BETA (testnet) | Üretim imajının gerçek veriyle provası | Alpaca **Paper** | Sanal |
| **ENV-C** AWS-PROD | Yalnızca koşturma | Alpaca **Live** | **Gerçek** |

> **Değişmez kural:** AWS'de model eğitilmez, kod düzenlenmez, deney yapılmaz. ENV-C'ye yalnızca etiketli, ENV-B'de kanıtlanmış ve geri alınabilir bir imaj girer.

Terfi kapıları — **G1** (Araştırma ➜ Beta) ve **G2** (Beta ➜ Üretim) — kontrol listeleriyle birlikte [ENVIRONMENTS.md §6](ENVIRONMENTS.md#6-terfi-kapıları-promotion-gates)'da tanımlıdır.
---

## 11. UÇTAN UCA AKIŞ — HİPOTEZDEN CANLI EMRE

> Her kutu bir adım. Ok üstündeki yazı, o adımdan **ne çıktığı**.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  1  HİPOTEZ                                                                 │
│                                                                             │
│     Bir cümle yazılır:                                                      │
│     "Dünkü oynaklık düşükse, bugün kapanış yukarı gitme olasılığı artar."   │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  ÇIKTI: ölçülebilir hale getirilmiş cümle
                                   │         oynaklık = ATR(14) / Close
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2  VERİ ÇEKME                                                              │
│                                                                             │
│     Alpaca REST  →  AAPL + SPY günlük barları                               │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  ÇIKTI: aapl_daily.csv   (dosya)
                                   │  tarih      | open | high | low | close | volume
                                   │  2024-01-03 | 184  | 185  | 182 | 184   | 58.4M
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3  TEST  (Jupyter)                                                         │
│                                                                             │
│     Hipotezi TEK BAŞINA ölç:                                                │
│     ATR/Close düşük olan günleri ayır → ertesi gün ne olmuş, say.           │
│                                                                             │
│     düşük oynaklık günleri : %54 yukarı                                     │
│     diğer günler           : %50 yukarı                                     │
└───────────────┬──────────────────────────────────────┬──────────────────────┘
                │                                      │
       ANLAMSIZ │                                      │ ANLAMLI
                │                                      │
                ▼                                      ▼
        ┌───────────────┐        ┌─────────────────────────────────────────────┐
        │  ÇÖP          │        │  4  ÖZELLİK OLARAK EKLE                     │
        │  hipotez      │        │                                             │
        │  kaydedilir,  │        │     features.py'a yeni bir SÜTUN eklenir:   │
        │  1'e dönülür  │        │     atr_orani = ATR(14) / Close             │
        └───────────────┘        └──────────────────┬──────────────────────────┘
                                                    │
                                                    │  ÇIKTI: features.py'da 1 sütun daha
                                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5  TABLO                                                                   │
│                                                                             │
│     Her SATIR = bir gün.  Her SÜTUN = bir hipotez.  Son sütun = CEVAP (y).  │
│                                                                             │
│     tarih      | getiri | atr_orani | hacim_oranı | ... |  y                │
│     2024-01-03 | -0.004 |   0.021   |    1.12     | ... |  1   ← yarın çıktı │
│     2024-01-04 |  0.011 |   0.019   |    0.87     | ... |  0   ← yarın düştü │
│                                                                             │
│     KURAL: y, o satırın GELECEĞİNDEN gelir. Sütunlar ise yalnızca           │
│            o gün ve öncesinden. Karışırsa sızıntı olur, model yalan söyler. │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  ÇIKTI: eğitim tablosu (satır × sütun)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  6  BÖLME                                                                   │
│                                                                             │
│     ZAMANA GÖRE ikiye ayrılır — rastgele DEĞİL.                             │
│                                                                             │
│     2016 ─────────────── 2023 │ boşluk │ 2024 ──────── 2025               │
│           EĞİTİM (model burayı görür)     TEST (hiç görmez)                  │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  ÇIKTI: eğitim seti + test seti
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  7  EĞİTİM  —  train.py                                                     │
│                                                                             │
│     XGBoost İLE eğitilir:                                                   │
│     ağaç ekle → hatayı ölç → kalan hataya bir ağaç daha ekle → ...          │
│     (yüzlerce kez)                                                          │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  ÇIKTI: model.json        (eğitilmiş model)
                                   │         rapor.csv         (test sonucu)
                                   │         önem tablosu      (hangi sütun işe yaradı)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  8  KALİTE KONTROL                                                          │
│                                                                             │
│     Baseline'ı geçti mi?  (hep "yukarı" desek ne olurdu?)                   │
│     Maliyet düşünce hâlâ kârlı mı?  Maksimum düşüş katlanılır mı?           │
└───────────────┬──────────────────────────────────────┬──────────────────────┘
                │                                      │
         GEÇMEZ │                                      │ GEÇER
                │                                      │
                └──────────► 1'e dön                   ▼
                             yeni hipotez   ┌──────────────────────────────────┐
                                            │  9  CANLI                        │
                                            └──────────────┬───────────────────┘
                                                           ▼
```

### Canlı taraf (adım 9'un içi)

```text
   her işlem günü, kapanıştan sonra bir kez:

   ┌──────────────┐   bugünün barı    ┌──────────────┐   1 satırlık tablo
   │  VERİ ÇEK    │──────────────────►│ features.py  │──────────────────────┐
   │  Alpaca REST │                   │  AYNI KOD    │                      │
   └──────────────┘                   └──────────────┘                      │
                                       ▲                                    ▼
                                       │                          ┌──────────────────┐
                            eğitimde   │                          │   model.json     │
                            kullanılan │                          │  predict_proba() │
                            dosyanın   │                          └────────┬─────────┘
                            AYNISI ────┘                                   │
                                                                  olasılık │ p = 0.63
                                                                           ▼
                                                                 ┌──────────────────┐
                                                                 │  RİSK KONTROL    │
                                                                 │  eşiği geçti mi  │
                                                                 │  kaç lot alınır  │
                                                                 │  günlük limit    │
                                                                 └────────┬─────────┘
                                                                          │ karar
                                                                          ▼
                                                                 ┌──────────────────┐
                                                                 │  EMİR  (Alpaca)  │
                                                                 └────────┬─────────┘
                                                                          ▼
                                                                 ┌──────────────────┐
                                                                 │  KAYIT (SQLite)  │
                                                                 └──────────────────┘
```

> **Tek kritik nokta:** 4. adımdaki `features.py` ile 9. adımdaki `features.py`
> **aynı dosyadır.** İkisi ayrışırsa model, eğitildiğinden farklı sayılar görür ve
> canlıdaki davranışı backtest'e hiç benzemez.
