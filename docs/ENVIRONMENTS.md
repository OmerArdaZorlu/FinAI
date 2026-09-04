# Ortam Ayrımı & Terfi (Promotion) Sözleşmesi

> **İlke:** Kod her ortamda **aynıdır**; değişen tek şey **konfigürasyon, sır (secret) ve yetkidir.**
> **İlke:** Eğitim (training) ve deney **yalnızca local**'de yapılır. **AWS = üretim.** AWS'de model eğitilmez, kod yazılmaz, deney yapılmaz.
> **Son güncelleme:** 2026-09-03 · İlgili: [ARCHITECTURE.md](ARCHITECTURE.md), [TECH_DEBT.md](TECH_DEBT.md)

---

## 0. Terminoloji Notu — "Testnet" Karşılığı

Hisse senedi piyasasında kripto dünyasındaki gibi bir "testnet" zinciri yoktur. Bizim testnet karşılığımız **Alpaca Paper Trading**'dir:

| | Endpoint | Para | Emirler |
|---|---|---|---|
| **Paper (testnet)** | `https://paper-api.alpaca.markets` | Sanal | Gerçek piyasaya **gitmez**, simüle fill |
| **Live (üretim)** | `https://api.alpaca.markets` | **Gerçek** | Gerçek borsaya iletilir |

Veri (market data) akışı her iki modda da **gerçek ve canlıdır** — sadece emir yürütme simüledir. Bu bizim için ideal: veri hattını gerçek koşullarda test ederken sermaye riski sıfırdır.

---

## 1. Üç Ortam

```text
┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│  ENV-A  LOCAL-RESEARCH  │    │   ENV-B  LOCAL-BETA     │    │    ENV-C  AWS-PROD      │
│  "Laboratuvar"          │───►│   "Testnet / Beta"      │───►│    "Üretim"             │
│                         │ G1 │                         │ G2 │                         │
│  Jupyter · train.py     │    │  Docker · LEAN · Paper  │    │  EC2 · Docker · Live    │
│  Geçmiş veri            │    │  Canlı veri, sanal emir │    │  Canlı veri, GERÇEK emir│
│  Sermaye: yok           │    │  Sermaye: sanal         │    │  Sermaye: GERÇEK        │
└─────────────────────────┘    └─────────────────────────┘    └─────────────────────────┘
      tüm ekip                      CS + EEE                        CS Lead (+ EEE)
```

---

## 2. ENV-A — LOCAL-RESEARCH (Laboratuvar)

| | |
|---|---|
| **Nerede** | Ekip üyelerinin kendi makineleri |
| **Repo** | `trading-research` (+ `features` paketi pinli import) |
| **Kim** | Tüm ekip: CS, EEE, İktisat, Metalurji |
| **Amaç** | Hipotez testi, feature keşfi, model eğitimi, backtest, QC |
| **Veri** | `data/` altındaki geçmiş Alpaca CSV/Parquet — **ve** LEAN backtest çıktısı |
| **Broker bağlantısı** | **YOK.** Alpaca API anahtarı bu ortamda emir yetkisi taşımaz (yalnızca `data`-only anahtar veya offline dosya) |
| **Çıktılar** | `model.json` + `model_meta.json`, backtest CSV, hipotez raporu |

### Burada yapılan işler
- İktisatçı hipotezi yazar → `hypotheses/` kayıt defterine girer (test edilmeden **önce**)
- CS & EEE Jupyter'de test eder, anlamlıysa `features.py`'a ekler
- CS Lead `train.py` ile XGBoost'u eğitir → **model artifact'i burada doğar**
- Metalurjist backtest CSV'sini Excel/Sheets'te QC eder (drawdown, kayıp serileri, outlier)

### Burada YAPILMAYAN işler
- ❌ Gerçek ya da sanal emir gönderme
- ❌ Canlı WebSocket'e bağlanıp sürekli çalışan servis koşturma

---

## 3. ENV-B — LOCAL-BETA (Testnet / Beta)

| | |
|---|---|
| **Nerede** | Local makine (veya ayrı bir local Docker host), **ENV-C ile birebir aynı imaj** |
| **Repo** | `trading-core` — `main` veya `release/*` branch |
| **Kim** | CS Lead + EEE |
| **Amaç** | **Üretim kodunun kendisini** gerçek veri akışıyla, sanal parayla doğrulamak |
| **Veri** | Alpaca **canlı WebSocket** (gerçek piyasa verisi) |
| **Broker** | Alpaca **Paper** endpoint — `paper-api.alpaca.markets` |
| **Model** | ENV-A'da eğitilmiş `model.json` — burada **asla yeniden eğitilmez** |
| **DB** | `./local_data/market_data_beta.db` (üretim DB'sinden tamamen ayrı dosya) |
| **Süre** | **Minimum 4–6 hafta kesintisiz** çalışma (bkz. Kapı G2) |

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

> **Kritik kural:** ENV-B, ENV-C'nin **provası değil, aynısıdır.** Aynı Docker imajı (aynı digest), aynı `docker-compose` servis tanımı, aynı kod. Fark yalnızca: endpoint (paper), API anahtarları, DB yolu, log yolu.

---

## 4. ENV-C — AWS-PROD (Üretim)

| | |
|---|---|
| **Nerede** | AWS EC2 (Ubuntu), Docker & Docker Compose |
| **Repo** | `trading-core` — **yalnızca sürüm etiketi (git tag)**, asla `main`'in ucu değil |
| **Kim** | Deploy yetkisi: CS Lead. Onay: EEE (No Solo Deploy) |
| **Amaç** | Gerçek sermaye ile işlem |
| **Broker** | Alpaca **Live** — `api.alpaca.markets` |
| **DB** | `/var/data/market_data.db` (volume mount, append-only, günlük yedek) |
| **Log** | `/var/log/trading_bot.log` |

### ENV-C'de KESİNLİKLE YASAK

| Yasak | Neden |
|---|---|
| ❌ Model eğitimi (`train.py` çalıştırmak) | Üretim makinesi bir laboratuvar değildir; CPU/RAM rekabeti ve reproducibility kaybı |
| ❌ Jupyter / notebook kurulumu | Saldırı yüzeyi ve elle müdahale kapısı |
| ❌ Sunucuda dosya düzenlemek (`vim src/...`) | Imaj ile git arasında sessiz ayrışma (drift). Değişiklik → PR → yeni imaj → redeploy |
| ❌ `docker exec` ile elle emir göndermek | Denetlenemez işlem; SQLite logu ile gerçeklik ayrışır |
| ❌ Etiketlenmemiş (`latest`) imaj kullanmak | Neyin çalıştığı bilinemez; geri alma (rollback) imkânsızlaşır |
| ❌ Paper ve Live anahtarlarını aynı yerde tutmak | Yanlış anahtarla gerçek emir riski |

### ENV-C'ye giren tek şey
1. **Sürüm etiketli Docker imajı** (immutable, digest ile pinli)
2. **Model artifact'i** — `model.json` + `model_meta.json` (ENV-A'da üretilmiş, imaja gömülü veya S3'ten sürüm pinli çekilen)
3. **Secret'lar** — AWS SSM Parameter Store / `.env` (repo'da **asla**, bkz. TD-05)

---

## 5. Ortam Farkları — Tek Tablo

| Boyut | ENV-A LOCAL-RESEARCH | ENV-B LOCAL-BETA | ENV-C AWS-PROD |
|---|---|---|---|
| Konum | Kişisel makine | Local Docker | EC2 Docker |
| Repo / branch | `trading-research` | `trading-core` `main` | `trading-core` **git tag** |
| Kod tabanı | Notebook + paket | **Üretim imajı** | **Üretim imajı (aynı digest)** |
| Veri kaynağı | Geçmiş CSV/Parquet | Canlı WebSocket | Canlı WebSocket |
| Emir hedefi | Yok | `paper-api.alpaca.markets` | `api.alpaca.markets` |
| Sermaye | — | Sanal | **Gerçek** |
| Model eğitimi | ✅ Tek yer burası | ❌ | ❌ |
| Model kullanımı | Backtest | Inference | Inference |
| DB | Geçici / notebook | `market_data_beta.db` | `/var/data/market_data.db` |
| Kill switch | — | ✅ test edilir | ✅ canlı zorunlu |
| PDT sayacı | — | ✅ doğrulanır | ✅ zorunlu |
| Erişim | Tüm ekip | CS + EEE | CS Lead (deploy), EEE (onay) |
| Secret kapsamı | Data-only / yok | Paper anahtarı | **Live anahtarı** |
| İzleme | — | Log + elle inceleme | Log + alarm + günlük rapor |

---

## 6. Terfi Kapıları (Promotion Gates)

Bir şeyin bir sonraki ortama geçmesi için **tüm** kutular işaretli olmalı. Kapılar tartışmaya açık değildir; geçilmiyorsa geçilmez.

### 🚪 Kapı G1 — ENV-A ➜ ENV-B (Araştırma ➜ Beta)

- [ ] Hipotez `hypotheses/` kayıt defterinde, **test öncesi** yazılmış (TD-13)
- [ ] Tüm ekipten tam konsensüs onayı alınmış
- [ ] Feature `features.py`'a eklenmiş, `shift(-n)` ve NaN denetimlerinden geçmiş
- [ ] **Walk-forward + purged/embargoed CV** ile doğrulanmış, rastgele K-fold **kullanılmamış** (TD-02)
- [ ] Backtest **maliyet dahil** (spread + slippage + ücretler) hâlâ pozitif (TD-11)
- [ ] Metalurjist QC raporu tamam: max drawdown, arka arkaya kayıp serisi, outlier stresi
- [ ] `model_meta.json` üretilmiş: feature listesi + sırası, tarih aralığı, commit SHA, kütüphane sürümleri (TD-14)
- [ ] `trading-core` PR'ı buddy review'dan geçmiş (CS↔EEE)

### 🚪 Kapı G2 — ENV-B ➜ ENV-C (Beta ➜ Üretim)

- [ ] **Minimum 4–6 hafta** kesintisiz paper çalışma tamamlandı
- [ ] Paper sonuçları backtest beklentisiyle tutarlı — sapma açıklanabilir durumda
- [ ] **Slippage ölçüldü** ve backtest varsayımının içinde kaldı (TD-10)
- [ ] Restart tatbikatı yapıldı: pozisyon açıkken kill → restart → reconciliation doğru (TD-06)
- [ ] Feed kesintisi tatbikatı yapıldı: stale guard tetiklendi, sistem işlem açmadı (TD-08)
- [ ] Kill switch elle tetiklendi, tüm pozisyonlar kapandı, sistem durdu (TD-09)
- [ ] Çift emir üretilmediği loglarla kanıtlandı (TD-07)
- [ ] PDT sayacı doğru çalıştı **veya** sermaye $25k üstü doğrulandı (TD-04)
- [ ] Secret'lar SSM/env'e taşındı, repoda anahtar yok, secret-scan CI'da yeşil (TD-05)
- [ ] Imaj etiketlendi (`v0.x.y`), digest kaydedildi, **rollback prosedürü yazıldı ve denendi**
- [ ] Üretim başlangıç sermayesi **kaybedilmesi göze alınabilir** miktarda (kademeli artış planı yazılı)

---

## 7. Sürüm & Deploy Akışı

```text
  ENV-A                     ENV-B                        ENV-C
  ─────                     ─────                        ─────
  train.py
    │
    ├─► model.json + model_meta.json ──────────────────────────┐
    │                                                          │
  feature/PR ──► buddy review ──► main ──► CI yeşil            │
                                            │                  │
                                            ▼                  │
                                    docker build               │
                                    imaj: sha-abc123           │
                                            │                  │
                                            ├──► ENV-B (paper) │
                                            │    4-6 hafta     │
                                            │    Kapı G2 ✓     │
                                            ▼                  ▼
                                    git tag v0.x.y ──► ENV-C (live)
                                                        aynı digest
                                                        + SSM secrets
```

**Kural:** ENV-C'ye giden imaj, ENV-B'de koşan imajın **birebir aynısıdır** (yeniden build edilmez, digest ile taşınır). Yeniden build = test edilmemiş kod demektir.

**Rollback:** Her deploy öncesi bir önceki imaj digest'i ve model artifact'i kaydedilir. Geri alma tek komutla mümkün olmalı ve **deploy'dan önce en az bir kez denenmiş olmalı.**

---

## 8. Sır (Secret) Yönetimi — Ortam Bazlı

| Ortam | Anahtar tipi | Saklama | Kapsam |
|---|---|---|---|
| ENV-A | Data-only veya yok | Local `.env` (gitignore'lu) | Emir yetkisi **yok** |
| ENV-B | Alpaca **Paper** | Local `.env` (gitignore'lu) | Sanal emir |
| ENV-C | Alpaca **Live** | **AWS SSM Parameter Store** (SecureString) | Gerçek emir |

- Repo'da yalnızca `config/config.example.json` bulunur — içi placeholder.
- `.gitignore`: `.env`, `config/config.json`, `*.db`, `models/*.json` (artifact ayrı kanaldan taşınır)
- Live anahtar hiçbir zaman bir geliştirici makinesine inmez.
- Anahtar rotasyonu: üretime çıkıştan önce bir kez, sonra 6 ayda bir.

---

## 9. Özet — Üç Cümlelik Sözleşme

1. **Öğrenmek local'de olur** — model ENV-A'da doğar, başka hiçbir yerde eğitilmez.
2. **Kanıtlamak beta'da olur** — üretim kodunun kendisi, gerçek veriyle ve sanal parayla, en az 4–6 hafta ENV-B'de yaşar.
3. **AWS sadece koşturur** — ENV-C'de yeni hiçbir şey denenmez; oraya yalnızca etiketli, kanıtlanmış ve geri alınabilir bir imaj girer.
