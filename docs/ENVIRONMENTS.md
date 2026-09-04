# Ortam Ayrımı & Terfi (Promotion) Sözleşmesi

> **İlke:** Kod her ortamda **aynıdır**; değişen tek şey **konfigürasyon, sır (secret) ve yetkidir.**
> **İlke:** Eğitim (training) ve deney **yalnızca local**'de yapılır. **AWS = üretim.** AWS'de model eğitilmez, kod yazılmaz, deney yapılmaz.
> **Doküman durumu:** 🟡 TASLAK — ekipçe tartışılmadı, hiçbir madde kesinleşmedi
> **Son güncelleme:** 2026-09-04 · İlgili: [ARCHITECTURE.md](ARCHITECTURE.md), [TECH_DEBT.md](TECH_DEBT.md)

---

## 0. Doğrulanmış Bulgular

| Konu | Durum | Tarih |
|---|---|---|
| Alpaca — Türkiye ikametli **live** bireysel hesap | ✅ **Açılabiliyor** (hesap açıldı) | 2026-09-04 |
| Alpaca — ücretsiz planda tam SIP geçmiş veri (15 dk gecikmeli) | ✅ Mevcut | 2026-09-04 |
| AlgoLab (BIST API) | ❌ **Kapandı** — 31.12.2025 | 2026-09-04 |

---

## 0b. Terminoloji Notu — "Testnet" Karşılığı

Hisse senedi piyasasında kripto dünyasındaki gibi bir "testnet" zinciri yoktur. Bizim testnet karşılığımız **Alpaca Paper Trading**'dir:

| | Endpoint | Para | Emirler |
|---|---|---|---|
| **Paper (testnet)** | `https://paper-api.alpaca.markets` | Sanal | Gerçek piyasaya **gitmez**, simüle fill |
| **Live (üretim)** | `https://api.alpaca.markets` | **Gerçek** | Gerçek borsaya iletilir |

Veri (market data) akışı her iki modda da **gerçek ve canlıdır** — sadece emir yürütme simüledir. Bu bizim için ideal: veri hattını gerçek koşullarda test ederken sermaye riski sıfırdır.

---

## 1. Üç Ortam

> **Not:** Bu doküman **araçtan bağımsızdır.** Hangi motor, çalıştırma biçimi veya bulut sağlayıcı
> seçilirse seçilsin ortam ayrımı ilkesi aynıdır. Araç seçimleri açık karar olarak
> [TECH_DEBT.md](TECH_DEBT.md#açık-kararlar-borç-değil--verilmemiş-kararlar) içinde takip edilir (AK-4 dahil).

```text
┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│  ENV-A  LOCAL-RESEARCH  │    │   ENV-B  LOCAL-BETA     │    │    ENV-C  AWS-PROD      │
│  "Laboratuvar"          │───►│   "Testnet / Beta"      │───►│    "Üretim"             │
│                         │ G1 │                         │ G2 │                         │
│  Jupyter · train.py     │    │  Paper endpoint         │    │  Sunucu · Live endpoint │
│  Geçmiş veri            │    │  Canlı veri, sanal emir │    │  Canlı veri, GERÇEK emir│
│  Sermaye: yok           │    │  Sermaye: sanal         │    │  Sermaye: GERÇEK        │
└─────────────────────────┘    └─────────────────────────┘    └─────────────────────────┘
```

---

## 2. ENV-A — LOCAL-RESEARCH (Laboratuvar)

| | |
|---|---|
| **Nerede** | Geliştiricinin kendi makinesi |
| **Repo** | `FinAI` — araştırma tarafı (`notebooks/`, `hypotheses/`) |
| **Amaç** | Hipotez testi, feature keşfi, model eğitimi, backtest, QC |
| **Veri** | `data/` altındaki geçmiş Alpaca verisi |
| **Broker bağlantısı** | **YOK.** Alpaca API anahtarı bu ortamda emir yetkisi taşımaz (yalnızca `data`-only anahtar veya offline dosya) |
| **Çıktılar** | `model.json` + `model_meta.json`, backtest CSV, hipotez raporu |

### Burada yapılan işler
- Hipotez yazılır → `hypotheses/` kayıt defterine girer (test edilmeden **önce**)
- Jupyter'de test edilir, anlamlıysa `features.py`'a eklenir
- `train.py` ile model eğitilir → **model artifact'i burada doğar**
- Backtest CSV'si Excel/Sheets'te QC edilir (drawdown, kayıp serileri, outlier)

### Burada YAPILMAYAN işler
- ❌ Gerçek ya da sanal emir gönderme
- ❌ Canlı WebSocket'e bağlanıp sürekli çalışan servis koşturma

---

## 3. ENV-B — LOCAL-BETA (Testnet / Beta)

| | |
|---|---|
| **Nerede** | Local makine — **ENV-C ile birebir aynı sürüm paketi** |
| **Repo** | Üretim kodu deposu — *henüz oluşturulmadı* |
| **Amaç** | **Üretim kodunun kendisini** gerçek veri akışıyla, sanal parayla doğrulamak |
| **Veri** | Alpaca **canlı WebSocket** (gerçek piyasa verisi) |
| **Broker** | Alpaca **Paper** endpoint — `paper-api.alpaca.markets` |
| **Model** | ENV-A'da eğitilmiş `model.json` — burada **asla yeniden eğitilmez** |
| **DB** | Üretim veritabanından **tamamen ayrı dosya** |
| **Süre** | Kesintisiz çalışma süresi — *kararlaştırılmadı* (öneri: birkaç hafta) |

### Burada ve yalnızca burada test edilecekler
Bunlar ENV-A'da test **edilemez**, ENV-C'de test **edilmemelidir**:

- [ ] WebSocket kopma / yeniden bağlanma davranışı
- [ ] Konteyner restart — warmup ve **pozisyon reconciliation** (bkz. TD-06)
- [ ] Emir idempotency — çift emir gitmediğinin kanıtı (TD-07)
- [ ] Bayat veri (stale feed) koruması tetikleniyor mu (TD-08)
- [ ] Kill switch / günlük zarar limiti tatbikatı — **elle tetikleyip gözlemleyin** (TD-09)
- [ ] PDT gün-içi işlem sayacı doğru sayıyor mu (TD-04)
- [ ] Saat dilimi & DST geçişi, yarım gün seansları, halt davranışı (TD-16)
- [ ] **Paper fill vs backtest fill karşılaştırması** → gerçek slippage ölçümü (TD-10, TD-11)
- [ ] Train/serve parity — canlı üretilen feature vektörü ile offline vektör eşleşiyor mu (TD-01)

> **Kritik kural:** ENV-B, ENV-C'nin **provası değil, aynısıdır.** Aynı sürüm paketi, aynı servis tanımı, aynı kod. Fark yalnızca: endpoint (paper), API anahtarları, DB yolu, log yolu.

---

## 4. ENV-C — AWS-PROD (Üretim)

| | |
|---|---|
| **Nerede** | Sunucu — sağlayıcı ve çalıştırma biçimi kararlaştırılmadı (bkz. AK-4) |
| **Repo** | Üretim kodu deposu — **yalnızca sürüm etiketi (git tag)**, asla `main`'in ucu değil |
| **Amaç** | Gerçek sermaye ile işlem |
| **Broker** | Alpaca **Live** — `api.alpaca.markets` |
| **DB** | Kalıcı diskte, append-only, günlük yedek |

### ENV-C'de KESİNLİKLE YASAK

| Yasak | Neden |
|---|---|
| ❌ Model eğitimi (`train.py` çalıştırmak) | Üretim makinesi bir laboratuvar değildir; CPU/RAM rekabeti ve reproducibility kaybı |
| ❌ Jupyter / notebook kurulumu | Saldırı yüzeyi ve elle müdahale kapısı |
| ❌ Sunucuda dosya düzenlemek | Çalışan sürüm ile git arasında sessiz ayrışma (drift). Değişiklik → PR → yeni sürüm → yeniden dağıtım |
| ❌ Sunucuya bağlanıp elle emir göndermek | Denetlenemez işlem; veritabanı logu ile gerçeklik ayrışır |
| ❌ Etiketlenmemiş sürüm kullanmak | Neyin çalıştığı bilinemez; geri alma (rollback) imkânsızlaşır |
| ❌ Paper ve Live anahtarlarını aynı yerde tutmak | Yanlış anahtarla gerçek emir riski |

### ENV-C'ye giren tek şey
1. **Sürüm etiketli, değiştirilemez paket** (parmak izi ile pinli)
2. **Model artifact'i** — `model.json` + `model_meta.json` (ENV-A'da üretilmiş, sürüm pinli)
3. **Sırlar** — sır yöneticisi veya ortam değişkeni (repo'da **asla**, bkz. TD-05)

---

## 5. Ortam Farkları — Tek Tablo

| Boyut | ENV-A LOCAL-RESEARCH | ENV-B LOCAL-BETA | ENV-C AWS-PROD |
|---|---|---|---|
| Konum | Kişisel makine | Local | Sunucu |
| Repo / branch | `FinAI` | üretim deposu | üretim deposu, **git tag** |
| Kod tabanı | Notebook + paket | **Üretim paketi** | **Aynı üretim paketi** |
| Veri kaynağı | Geçmiş CSV/Parquet | Canlı WebSocket | Canlı WebSocket |
| Emir hedefi | Yok | `paper-api.alpaca.markets` | `api.alpaca.markets` |
| Sermaye | — | Sanal | **Gerçek** |
| Model eğitimi | ✅ Tek yer burası | ❌ | ❌ |
| Model kullanımı | Backtest | Inference | Inference |
| DB | Geçici / notebook | Ayrı beta dosyası | Üretim dosyası |
| Kill switch | — | ✅ test edilir | ✅ canlı zorunlu |
| PDT sayacı | — | ✅ doğrulanır | ✅ zorunlu |
| Secret kapsamı | Data-only / yok | Paper anahtarı | **Live anahtarı** |
| İzleme | — | Log + elle inceleme | Log + alarm + günlük rapor |

---

## 6. Terfi Kapıları (Promotion Gates)

Bir şeyin bir sonraki ortama geçmesi için **tüm** kutular işaretli olmalı. Kapılar tartışmaya açık değildir; geçilmiyorsa geçilmez.

Madde numaraları [TECH_DEBT.md](TECH_DEBT.md)'ye atıftır.

### 🚪 Kapı G0 — koda başlamadan

Açık kararlar verilmeden aşağıdaki kapıların çoğu anlamsızdır:

- [ ] **AK-1** Bar frekansı seçildi (günlük / saatlik)
- [ ] **AK-2** Broker seçildi (Alpaca / IBKR)
- [ ] **AK-3** Veri feed'i seçildi (IEX / gecikmeli SIP / ücretli anlık)
- [ ] **AK-4** Çalıştırma mimarisi seçildi (tek konteyner / bölünmüş)

### 🚪 Kapı G1 — ENV-A ➜ ENV-B (Araştırma ➜ Beta)

**Veri ve hesap doğruluğu**
- [ ] Eğitim verisi ile canlı veri aynı kaynaktan ve aynı ayarlarla geliyor; parity testi yeşil (TD-01)
- [ ] Özellik hesabı tek kaynakta, sürüm pinli paket olarak import ediliyor; kopya dosya yok (TD-13)
- [ ] Gösterge kütüphanesi kararı yazılı, sürümler pinli (TD-16)
- [ ] Özellikler `shift(-n)` ve NaN denetimlerinden geçmiş

**Model dürüstlüğü**
- [ ] Hedef (y) tanımı ve karar eşiği yazılı; eşik yalnızca eğitim kısmında kalibre edildi (TD-03)
- [ ] **Walk-forward + purged/embargoed CV** ile doğrulanmış, rastgele K-fold **kullanılmamış** (TD-02)
- [ ] Örneklem boyutu raporlandı; model basit bir baseline'ı yeniyor (TD-12)
- [ ] Backtest **maliyet dahil** (spread + slippage + ücretler) hâlâ pozitif (TD-11)

**Kayıt ve izlenebilirlik**
- [ ] Hipotez kayıt defterinde, **test öncesi** ve kabul kriteriyle birlikte yazılmış; reddedilenler de duruyor (TD-14)
- [ ] `model_meta.json` üretilmiş: feature listesi + sırası, şema parmak izi, tarih aralığı, commit SHA, kütüphane sürümleri (TD-15)
- [ ] QC raporu tamam: max drawdown, arka arkaya kayıp serisi, outlier stresi

### 🚪 Kapı G2 — ENV-B ➜ ENV-C (Beta ➜ Üretim)

**Gerçeklik kontrolü**
- [ ] Kararlaştırılan süre boyunca kesintisiz paper çalışma tamamlandı (TD-10)
- [ ] Paper sonuçları backtest beklentisiyle tutarlı — sapma açıklanabilir durumda
- [ ] **Slippage ölçüldü** ve backtest varsayımının içinde kaldı (TD-11)
- [ ] Canlı üretilen özellik vektörleri offline hesapla eşleşti (TD-01)

**Dayanıklılık tatbikatları** — hepsi ENV-B'de fiilen yapılmış olmalı
- [ ] Restart: pozisyon açıkken süreç öldürüldü → yeniden başladı → broker ile mutabakat doğru (TD-06)
- [ ] Çift emir üretilmediği loglarla kanıtlandı (TD-07)
- [ ] Feed kesintisi: bayat veri koruması tetiklendi, sistem işlem açmadı (TD-08)
- [ ] Kill switch elle tetiklendi, pozisyonlar kapandı, sistem durdu (TD-09)
- [ ] Koruyucu stop'un broker'da **duramadığı** senaryo test edildi ve risk yazılı olarak kabul edildi (TD-19)
- [ ] Saat dilimi / DST geçişi ve yarım gün seansları doğrulandı (TD-17)

**Düzenleyici ve operasyonel**
- [ ] PDT sayacı doğru çalıştı **veya** sermaye $25k üstü doğrulandı (TD-04)
- [ ] Broker kararı kesinleşti; seçilen brokerın Türkiye ikametli live hesabı yazılı teyitli (TD-18)
- [ ] Sırlar ortam değişkeni / sır yöneticisine taşındı, repoda anahtar yok, secret-scan CI'da yeşil (TD-05)
- [ ] Sürüm etiketlendi (`v0.x.y`), parmak izi kaydedildi, **rollback prosedürü yazıldı ve denendi**
- [ ] Üretim başlangıç sermayesi **kaybedilmesi göze alınabilir** miktarda (kademeli artış planı yazılı)

---

## 7. Sürüm & Deploy Akışı

```text
  ENV-A                        ENV-B                      ENV-C
  ─────                        ─────                      ─────

  train.py
     │
     └─► model.json + model_meta.json ──────────────────────────┐
                                                                │
  kod ──► git ──► CI yeşil                                      │
                     │                                          │
                     ▼                                          │
             paket derlenir                                     │
             parmak izi: sha-abc123                             │
                     │                                          │
                     ├──────────────► ENV-B (paper)             │
                     │                sanal para, gerçek veri   │
                     │                Kapı G2 ✓                 │
                     ▼                                          ▼
             sürüm etiketi: v0.1.0 ─────────────► ENV-C (live)
                                                  AYNI paket
                                                  + sırlar
```

**Kural:** ENV-C'ye giden paket, ENV-B'de koşan paketin **birebir aynısıdır** (yeniden derlenmez, parmak iziyle taşınır). Yeniden derleme = test edilmemiş kod demektir.

**Rollback:** Her deploy öncesi bir önceki sürümün parmak izi ve model artifact'i kaydedilir. Geri alma tek komutla mümkün olmalı ve **deploy'dan önce en az bir kez denenmiş olmalı.**

---

## 8. Sır (Secret) Yönetimi — Ortam Bazlı

| Ortam | Anahtar tipi | Saklama | Kapsam |
|---|---|---|---|
| ENV-A | Data-only veya yok | Local `.env` (gitignore'lu) | Emir yetkisi **yok** |
| ENV-B | Alpaca **Paper** | Local `.env` (gitignore'lu) | Sanal emir |
| ENV-C | Alpaca **Live** | **Sır yöneticisi** (şifreli, sunucuda dosya olarak durmaz) | Gerçek emir |

- Repo'da yalnızca `config/config.example.json` bulunur — içi placeholder.
- `.gitignore`: `.env`, `config/config.json`, `*.db`, `models/*.json` (artifact ayrı kanaldan taşınır)
- Live anahtar hiçbir zaman bir geliştirici makinesine inmez.
- Anahtar rotasyonu: üretime çıkıştan önce bir kez, sonra 6 ayda bir.

---

## 9. Özet — Üç Cümlelik Sözleşme

1. **Öğrenmek local'de olur** — model ENV-A'da doğar, başka hiçbir yerde eğitilmez.
2. **Kanıtlamak beta'da olur** — üretim kodunun kendisi, gerçek veriyle ve sanal parayla, kararlaştırılan süre boyunca ENV-B'de yaşar.
3. **Üretim sadece koşturur** — ENV-C'de yeni hiçbir şey denenmez; oraya yalnızca etiketli, kanıtlanmış ve geri alınabilir bir sürüm girer.
