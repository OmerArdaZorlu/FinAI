# Algoritmik Al-Sat Sistemi — Mimari Dokümanı

> **Proje:** ABD hisse senedi piyasaları (başlangıç: `AAPL`, `SPY`) için uçtan uca, canlı, kurumsal standartta algoritmik al-sat sistemi
> **Doküman durumu:** 🟡 TASLAK — ekipçe tartışılmadı, hiçbir madde kesinleşmedi
> **Son güncelleme:** 2026-09-03
> **İlgili dokümanlar:** [ENVIRONMENTS.md](ENVIRONMENTS.md) (ortam ayrımı & terfi kapıları) · [TECH_DEBT.md](TECH_DEBT.md) (açık teknik borç) · [README.md](README.md) (indeks)

---

## İçindekiler

1. [Teknoloji Yığını & Kesin Kısıtlar](#1-teknoloji-yiğini--kesin-kisitlar)
2. [İç İçe (Nested) Sistem & Dosya Dizin Hiyerarşisi](#2-iç-içe-nested-sistem--dosya-dizin-hiyerarşisi)
3. [Canlı Veri Akışı — Streaming Mikro-ETL](#3-canli-veri-akişi--streaming-mikro-etl)
4. [Çift Repo (Dual-Repo) Stratejisi](#4-çift-repo-dual-repo-stratejisi)
5. [İş Akışı — Feature Engineering Loop](#5-iş-akişi--feature-engineering-loop)
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

```text
  trading-research  (hipotez, notebook, örnek veri)   ── tüm ekip, tam konsensüs
          │
          │  istatistiksel olarak anlamlı bulunan hipotez
          ▼
  trading-core      (features.py, train.py, model, LEAN, Docker, CI)
                                                      ── erişimi kısıtlı
```

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

## 8. CI/CD KAPILARI (QUALITY GATES)

GitHub Actions (`.github/workflows/ci.yml`) üzerinde her PR için zorunlu kontroller:

- [ ] `pytest` — birim ve entegrasyon testleri
- [ ] **Leakage denetimi** — `shift(-n)` / gelecek referansı statik taraması
- [ ] **NaN denetimi** — feature çıktısında NaN/Inf toleransı sıfır
- [ ] **Model serileştirme doğrulaması** — `model.json` yüklenebiliyor, beklenen feature sayısı ve sırası eşleşiyor
- [ ] Lint / format

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