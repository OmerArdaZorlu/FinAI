# Algoritmik Al-Sat Sistemi — Mimari Dokümanı

> **Proje:** ABD hisse senedi piyasaları (başlangıç: `AAPL`, `SPY`) için uçtan uca, canlı, kurumsal standartta algoritmik al-sat sistemi
> **Ekip:** 4 kişi — Bilgisayar Mühendisliği (Sistem Mimarı / Lead), Elektrik-Elektronik Mühendisliği, İktisat, Metalurji & Malzeme Mühendisliği
> **Doküman durumu:** 🟡 TASLAK — ekipçe tartışılmadı, hiçbir madde kesinleşmedi
> **Son güncelleme:** 2026-09-03
> **İlgili dokümanlar:** [ENVIRONMENTS.md](ENVIRONMENTS.md) (ortam ayrımı & terfi kapıları) · [TECH_DEBT.md](TECH_DEBT.md) (açık teknik borç) · [README.md](README.md) (indeks)

---

## İçindekiler

1. [Teknoloji Yığını & Kesin Kısıtlar](#1-teknoloji-yiğini--kesin-kisitlar)
2. [İç İçe (Nested) Sistem & Dosya Dizin Hiyerarşisi](#2-iç-içe-nested-sistem--dosya-dizin-hiyerarşisi)
3. [Canlı Veri Akışı — Streaming Mikro-ETL](#3-canli-veri-akişi--streaming-mikro-etl)
4. [Çift Repo (Dual-Repo) Stratejisi](#4-çift-repo-dual-repo-stratejisi)
5. [Ekip İş Akışı — Feature Engineering Loop](#5-ekip-iş-akişi--feature-engineering-loop)
6. [Özellik (Feature) Sözleşmesi](#6-özellik-feature-sözleşmesi)
7. [Risk Yönetimi Parametreleri](#7-risk-yönetimi-parametreleri)
8. [CI/CD Kapıları (Quality Gates)](#8-cicd-kapilari-quality-gates)
9. [Ortam Ayrımı & Açık Teknik Borç](#9-ortam-ayrimi--açik-teknik-borç)

---

## 1. TEKNOLOJİ YIĞINI & KESİN KISITLAR

| Katman | Seçim |
|---|---|
| **Çekirdek diller & kütüphaneler** | Python (Pandas, NumPy, Pandas-TA), C# / Python (QuantConnect LEAN Motoru), XGBoost |
| **Orkestrasyon & Broker** | QuantConnect LEAN Engine, Alpaca Markets API (WebSocket canlı veri + REST emir yürütme) |
| **Veri depolama & kalıcılık** | SQLite — append-only, indeksli flat tablolar; canlıda üretilen tek satırlık barlar, model sinyalleri, emir/trade ve state logları |
| **Altyapı & dağıtım** | AWS EC2 (Ubuntu Linux) üzerinde Docker & Docker Compose ile izole konteyner mimarisi |
| **CI/CD** | GitHub Actions — `pytest`, NaN denetimi, veri sızıntısı (leakage / `shift(-n)`) kontrolü, model serileştirme doğrulaması, lint |

### Kesin Kısıt — No Web Scraping

> **Kesinlikle** web scraping (Node.js / Puppeteer / Selenium vb. kırılgan kazıma araçları) kullanılmayacaktır.
> Tüm veriler **resmi, yapılandırılmış (structured) REST / WebSocket API'leri** üzerinden akar.

---

## 2. İÇ İÇE (NESTED) SİSTEM & DOSYA DİZİN HİYERARŞİSİ

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
│   │ DOCKER CONTAINER (isolated runtime: python-lean-engine)                                   │   │
│   │                                                                                           │   │
│   │   ┌───────────────────────────────────────────────────────────────────────────────────┐   │   │
│   │   │ QUANTCONNECT LEAN MOTORU (C# / Python Runtime)                                     │   │   │
│   │   │                                                                                    │   │   │
│   │   │   ├── Veri Yakalama (Extract & Sync)                                               │   │   │
│   │   │   │     └── Slice Manager      ──► Alpaca WebSocket'ten gelen AAPL + SPY'ı         │   │   │
│   │   │   │                                saat başında senkronize eder (14:00:00)         │   │   │
│   │   │   │                                                                                │   │   │
│   │   │   ├── Bellek Alanı (In-Memory Buffer)                                              │   │   │
│   │   │   │     └── Rolling Window     ──► Son 100 barlık senkronize OHLCV matrisi         │   │   │
│   │   │   │                                      │                                         │   │   │
│   │   │   │                                      ▼                                         │   │   │
│   │   │   ├── Python Modülü: src/features.py (Transform / Formatlayıcı)                    │   │   │
│   │   │   │     └── calculate()        ──► Log-return, RSI, Volatilite, Rel-Return         │   │   │
│   │   │   │                                      │                                         │   │   │
│   │   │   │                                      ▼ (Tek satırlık özellik vektörü)          │   │   │
│   │   │   ├── Çıkarım Motoru: models/model.json (XGBoost Runtime)                          │   │   │
│   │   │   │     └── predict_proba()    ──► Olasılık hesabı (örn: %72 BUY)                  │   │   │
│   │   │   │                                      │                                         │   │   │
│   │   │   │                                      ▼                                         │   │   │
│   │   │   └── Portföy & Risk Yönetimi                                                      │   │   │
│   │   │         ├── Risk Manager       ──► %1 Kasa riski, Trailing Stop-Loss kontrolü      │   │   │
│   │   │         └── Execution Handler  ──► Alpaca REST API'ye HTTP POST ile emir iletimi   │   │   │
│   │   └───────────────────────────────────────────────────────────────────────────────────┘   │   │
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

---

## 4. ÇİFT REPO (DUAL-REPO) STRATEJİSİ

Proje kirliliğini önlemek ve üretim güvenliğini sağlamak amacıyla sistem iki ayrı repoya bölünmüştür.

### 4.1 `trading-research` — Ar-Ge & Laboratuvar

| | |
|---|---|
| **Erişim** | Tüm ekip (CS, EEE, Econ, Metalurji) contributor'dır |
| **İçerik** | `hypotheses/` (hipotez metinleri) · `notebooks/` (Jupyter testleri) · `data/samples/` (örnek CSV'ler) · `analysis/` (Excel/Sheets çıktıları) |
| **Çalışma kuralı** | **Tam konsensüs (Full Onay).** Bir hipotezin test edilebilir sayılması için tüm ekibin onayı gerekir |

### 4.2 `trading-core` — Üretim & Dağıtım

| | |
|---|---|
| **Erişim** | Sadece **CS Lead** ve **EEE Mühendisi** |
| **İçerik** | `src/features.py` · `src/train.py` · `models/model.json` · LEAN konfigürasyonu · `Dockerfile` · GitHub Actions workflow'ları |
| **Çalışma kuralı** | **"Buddy Sistemi" (Çapraz Denetim / Pair Review).** `main` branch korumalıdır. CS'in PR'ını EEE, EEE'nin PR'ını CS onaylamadan merge yapılamaz — **No Solo Merges** |

```text
  trading-research  (hipotez, notebook, örnek veri)   ── tüm ekip, tam konsensüs
          │
          │  istatistiksel olarak anlamlı bulunan hipotez
          ▼
  trading-core      (features.py, train.py, model, LEAN, Docker, CI)
                                                      ── sadece CS + EEE, buddy review
```

---

## 5. EKİP İŞ AKIŞI — FEATURE ENGINEERING LOOP

Teknik olmayan ekip üyelerinin kodla boğulmaması için görevler net soyutlanmıştır.

| # | Rol | Görev | Kod? |
|---|---|---|---|
| 1 | **İktisatçı** | Google Docs / Notion üzerinden piyasa hipotezi ve mantıksal şartları yazar | Sıfır kod |
| 2 | **CS & EEE** | Hipotezi geçmiş veri setinde hızlıca test eder (Jupyter). İstatistiksel olarak anlamlıysa **EEE** bunu `features.py` fonksiyonuna ekler; **CS** sızıntı / tip kontrollerini yapar | Kod |
| 3 | **CS (Lead)** | `train.py` çalıştırarak XGBoost'u eğitir; `model.json` ve simülasyon (backtest) sonuçlarını içeren CSV üretir | Kod |
| 4 | **Metalurjist** | Üretilen CSV'yi Google Sheets / Excel üzerinde kalite kontrol (QC), maksimum drawdown, arka arkaya kayıp serileri ve aykırı değer (outlier) stres testine tabi tutar | Sıfır kod |

```text
   ┌──────────────┐   hipotez    ┌──────────────┐   anlamlı?   ┌──────────────┐
   │  İKTİSATÇI   │─────────────►│  CS  +  EEE  │─────────────►│  CS  (Lead)  │
   │ (Docs/Notion)│              │  (Jupyter)   │  features.py │  train.py    │
   └──────────────┘              └──────────────┘              └──────┬───────┘
          ▲                                                           │ backtest CSV
          │                      ┌──────────────┐                     │
          └──────────────────────│  METALURJİST │◄────────────────────┘
             geri bildirim       │ (Sheets/QC)  │
             (drawdown, outlier) └──────────────┘
```

---

## 6. ÖZELLİK (FEATURE) SÖZLEŞMESİ

`src/features.py` içinde hesaplanan, durağan ve normalize edilmiş girdiler:

| Özellik | Tanım |
|---|---|
| **Logaritmik getiriler** | 1 ve 5 barlık `log(P_t / P_(t-n))` |
| **Normalize volatilite** | `ATR / Close` |
| **Bollinger bant konumu** | `%B` |
| **Hacim anomalisi** | `Volume / SMA_20(Volume)` |
| **Göreceli güç / benchmark farkı** | `AAPL log-getiri − SPY log-getiri` |
| **(opsiyonel)** | RSI |

### Değişmez Kurallar (Invariants)

1. `features.py` **tek kaynak** (single source of truth) — eğitim ve canlı çıkarım aynı fonksiyonu çağırır.
2. Modül içinde **hedef (y) üretimi yoktur**; hedef yalnızca `train.py` içinde ve açıkça oluşturulur.
3. **`shift(-n)` yasaktır** — CI bunu statik olarak denetler.
4. Çıktı, sabit sıralı ve isimlendirilmiş bir sütun şemasıdır; sıra değişimi model uyumsuzluğu sayılır.
5. NaN üretilmez; yetersiz pencere durumunda satır **açıkça** geçersiz işaretlenir, uydurma değerle doldurulmaz.

---

## 7. RİSK YÖNETİMİ PARAMETRELERİ

| Parametre | Değer / Kural |
|---|---|
| İşlem başına sermaye riski | **%1** (kasa koruma) |
| Stop mekanizması | Dinamik **Trailing Stop-Loss** |
| Pozisyon boyutu | Risk bütçesi ÷ stop mesafesi (ATR tabanlı) |
| Emir tipleri | Piyasa / limit (Alpaca REST) |
| Enstrümanlar | `AAPL` (işlem), `SPY` (benchmark & rejim) |

---

## 8. CI/CD KAPILARI (QUALITY GATES)

GitHub Actions (`.github/workflows/ci.yml`) üzerinde her PR için zorunlu kontroller:

- [ ] `pytest` — birim ve entegrasyon testleri
- [ ] **Leakage denetimi** — `shift(-n)` / gelecek referansı statik taraması
- [ ] **NaN denetimi** — feature çıktısında NaN/Inf toleransı sıfır
- [ ] **Model serileştirme doğrulaması** — `model.json` yüklenebiliyor, beklenen feature sayısı ve sırası eşleşiyor
- [ ] Lint / format
- [ ] **Branch protection:** `main` korumalı — çapraz onay (buddy review) olmadan merge yok

---

## 9. ORTAM AYRIMI & AÇIK TEKNİK BORÇ

Bu doküman sistemin **hedef mimarisini** tanımlar. Onu tamamlayan iki doküman:

### 9.1 Ortam Ayrımı — [ENVIRONMENTS.md](ENVIRONMENTS.md)

Yukarıdaki mimari üç ayrı ortamda koşar ve **kod her üçünde de aynıdır**; değişen yalnızca konfigürasyon, sır ve yetkidir:

| Ortam | Rol | Emir hedefi | Sermaye |
|---|---|---|---|
| **ENV-A** LOCAL-RESEARCH | Hipotez, eğitim, backtest — **modelin doğduğu tek yer** | Yok | — |
| **ENV-B** LOCAL-BETA (testnet) | Üretim imajının gerçek veriyle provası | Alpaca **Paper** | Sanal |
| **ENV-C** AWS-PROD | Yalnızca koşturma | Alpaca **Live** | **Gerçek** |

> **Değişmez kural:** AWS'de model eğitilmez, kod düzenlenmez, deney yapılmaz. ENV-C'ye yalnızca etiketli, ENV-B'de kanıtlanmış ve geri alınabilir bir imaj girer.

Terfi kapıları — **G1** (Araştırma ➜ Beta) ve **G2** (Beta ➜ Üretim) — kontrol listeleriyle birlikte [ENVIRONMENTS.md §6](ENVIRONMENTS.md#6-terfi-kapıları-promotion-gates)'da tanımlıdır.

### 9.2 Açık Teknik Borç — [TECH_DEBT.md](TECH_DEBT.md)

Mimari incelemesinde tespit edilen **17 açık madde** (🔴 5 P0 · 🟠 7 P1 · 🟡 5 P2). Bu dokümandaki tasarım kararları, o maddeler kapatılmadan üretimde geçerli sayılmaz. Özellikle şu üçü, bu dokümanın kendisindeki boşluklardır:

- **TD-01** Train/serve skew — §3.2'deki "birebir aynı kod" ilkesi, girdi verisinin de aynı olmasını garanti etmez
- **TD-02 / TD-03** — §6'daki feature sözleşmesi tanımlı, ancak **hedef (y) ve doğrulama metodolojisi** henüz tanımsız
- **TD-09** — §7'de işlem-başına %1 risk var, ancak **portföy seviyesinde devre kesici** yok
