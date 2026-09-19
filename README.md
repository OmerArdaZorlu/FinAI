# FinAI

**Hisse senedi piyasaları için uçtan uca algoritmik al-sat sistemi.**

Makine öğrenmesi tabanlı sinyal üretimi, kural bazlı risk yönetimi ve otomatik emir
yürütmeyi tek bir canlı boru hattında birleştiren, kurumsal standartta bir araştırma
ve üretim projesi.

Başlangıç enstrümanları: `AAPL` (işlem) · `SPY` (karşılaştırma endeksi)

> Bkz. [DISCLAIMER.md](DISCLAIMER.md)


## Sistem ne yapıyor

Piyasa açıkken sistem şu döngüyü tekrarlar:

```
   Alpaca (borsa verisi)
            │
            ▼
   ┌─────────────────┐
   │  1. VERİ ALMA   │   AAPL ve SPY barları aynı zaman damgasında senkronize edilir
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  2. DÖNÜŞTÜRME  │   Ham fiyatlar → durağan, normalize 6 sayı
   └────────┬────────┘   (features.py — eğitimde ve canlıda BİREBİR aynı kod)
            ▼
   ┌─────────────────┐
   │  3. TAHMİN      │   XGBoost modeli → "yükselme olasılığı %68"
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  4. RİSK        │   %1 sermaye riski · pozisyon boyutu · trailing stop
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  5. EMİR        │   Alpaca REST API üzerinden alım/satım
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  6. KAYIT       │   Her bar, sinyal ve emir SQLite'a yazılır (append-only)
   └─────────────────┘
```

### Temel tasarım ilkesi

> **`features.py` tek kaynaktır.**
> Model eğitilirken de canlı çalışırken de aynı fonksiyon çağrılır. İki ayrı hesap
> yolu yoktur. Bu, algoritmik sistemlerin en sık ve en sinsi hatası olan
> *train/serve skew*'i (eğitim ile canlının farklı sayılarla çalışması) yapısal
> olarak engeller.

---

## Teknoloji yığını

| Katman | Seçim |
|---|---|
| Dil & kütüphaneler | Python · Pandas · NumPy · XGBoost |
| Motor | QuantConnect LEAN |
| Broker & veri | Alpaca Markets (WebSocket veri + REST emir) |
| Kalıcılık | SQLite (append-only, indeksli) |
| Dağıtım | AWS EC2 (Ubuntu) · Docker · Docker Compose |
| CI/CD | GitHub Actions (pytest, sızıntı denetimi, NaN kontrolü, model doğrulama) |

## Üç ortam

Kod her üç ortamda **aynıdır**; değişen yalnızca konfigürasyon, sır ve yetkidir.

| | **LOCAL-RESEARCH** | **LOCAL-BETA** | **AWS-PROD** |
|---|---|---|---|
| Rol | Hipotez, eğitim, backtest | Gerçek veriyle prova | Yalnızca koşturma |
| Veri | Geçmiş | Canlı | Canlı |
| Emir | Yok | Kâğıt üstü (paper) | **Gerçek** |
| Sermaye | — | Sanal | **Gerçek** |
| Model eğitimi | ✅ Tek yer burası |

> **Değişmez kural:** AWS'de model eğitilmez, kod düzenlenmez, deney yapılmaz.
> Üretime yalnızca etiketli, beta'da kanıtlanmış ve geri alınabilir bir imaj girer.

Detay ve terfi kapıları: [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md)

---

## Çalışma döngüsü

Sistemin asıl işi kod yazmak değil, **hipotez deneyip elemektir**:

```
   hipotez yazar          "Endeksten geri kalan hisse toparlar"
          ↓
    formüle döker                rel_ret_5 = AAPL 5g getiri − SPY 5g getiri
          ↓
 Yeni sütun eklenir               features.py
          ↓
 Model yeniden eğitilir           python -m src.train
          ↓
 Kabul kriteri karşılandı mı?     (kriter SONUCA BAKMADAN ÖNCE yazılır)
          ├── hayır → sütunu çıkar, kayda geç
          └── evet  → sütun kalır, kayda geç
          ↓
      QC yapar               drawdown, kayıp serileri, aykırı değerler
```

Reddedilen hipotezler de kayıtta tutulur. Kaç hipotez denendiği bilinmezse,
şans beceri sanılır.

## Paper motorunu çalıştırmak (ENV-B)

```bash
pip install -r requirements.txt

python -m src.engine.dongu --kuru     # emir göndermeden, saat başı tur (izlemek için)
python -m src.engine.dongu            # Alpaca PAPER hesabına gerçek emir
python -m src.engine.saglik           # sistem sağlam mı? (çıkış kodu 0/1)
python -m src.engine.rapor            # backtest varsayımı vs gerçekleşme
python -m src.arayuz                  # panel: http://127.0.0.1:8000
python scripts/parite.py              # karar mantığı değişmedi mi? (9.9004 / 28 + parmak izi)
```

* Döngü her saatin **:20'sinde** (UTC) tur atar; işletim sistemi zamanlayıcısı
  kullanmaz. Aynı anda ikinci bir döngü başlatılamaz (`data/dongu.pid`).
* Arada, borsa açıkken **dakikada bir koruma bekçisi** çalışır: elimizdeki
  hisse kadar taban (stop) emri borsada mı, değilse koyar/düzeltir. Kısmen
  dolan alışın kalanını iptal eder. Her müdahale panelin **Uyarılar**
  tablosuna düşer.
* **Hisse bölünmesi:** depo günde bir kez son 60 günü baştan indirir;
  fiyatlarda %25'ten büyük sıçrama görülürse hemen indirir ve düzelmezse
  emir göndermez. Araştırma verisinin tamamı için bölünmeden sonra tüm
  geçmiş yeniden indirilmeli:
  `python scripts/fetch_bars.py --symbols AAPL --timeframe 1Hour --start 2016-01-01`
  (bölünme sonrası `9.9004` parite değeri de değişebilir — önce veriye bak).
* Günlük: `data/gunluk/motor.log` (UTF-8, 5 MB × 5 dosya).
* E-posta alarmı ve panel komut anahtarı `.env`'de (`SMTP_*`, `ALARM_ALICI`,
  `ARAYUZ_ANAHTARI`). Boşsa alarm yalnızca log'a yazar, komutlar yalnızca bu
  makineden kabul edilir.

**Panel komutları:** `/durum`, `/turlar`, `/gunluk`, `/uyarilar`, `/duraklat` (yeni alım
durur, pozisyon ve koruyucu stop kalır), `/devam`, `/stop onayla` (tüm emirler
iptal, **pozisyon piyasadan kapatılır**), `/sifirla onayla`.

> **Panel yerel ağa açıktır** (`0.0.0.0`). Ortak wifi'da aynı ağdaki herkes
> görebilir. Sunucuya (AWS vb.) taşındığında portu güvenlik grubunda
> **kapalı** tut; erişim Tailscale ya da SSH tüneliyle. Yalnızca bu makine
> için: `python -m src.arayuz --host 127.0.0.1`.

## Depo yapısı

```
FinAI/
├── docs/               Mimari, ortam ayrımı, teknik borç kayıt defteri
├── notebooks/          Hipotez testleri (kişi başına ayrı dosya)
├── hypotheses/         Hipotez metinleri ve kabul kriterleri
├── LICENSE             Tüm hakları saklı
└── DISCLAIMER.md       Sorumluluk reddi
```

Üretim kodu (`features.py`, `train.py`, LEAN yapılandırması, Dockerfile) erişimi
kısıtlı ayrı bir depoda tutulacaktır.

---

## Dokümanlar

| Doküman | İçerik |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Sistem mimarisi, dizin hiyerarşisi, veri akışı, feature sözleşmesi |
| [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) | Üç ortam, terfi kapıları (G1/G2), sürüm & deploy akışı, sır yönetimi |
| [docs/TECH_DEBT.md](docs/TECH_DEBT.md) | 19 maddelik teknik borç kayıt defteri + açık kararlar |

---

## Açık kararlar

Koda başlamadan verilmesi gereken tercihler:

| # | Karar | Durum |
|---|---|---|
| **AK-1** | Bar frekansı — günlük mü, saatlik mi? |
| **AK-2** | Broker — Alpaca mı, Interactive Brokers mı? |
| **AK-3** | Veri feed'i — IEX mi, 15 dk gecikmeli SIP mi, ücretli anlık mı? |

Ayrıntı ve etkileri: [docs/TECH_DEBT.md](docs/TECH_DEBT.md#açık-kararlar-borç-değil--verilmemiş-kararlar)

---

## Bilinen kısıtlar

Küçük sermayeyle ABD piyasasında işlem yapmanın somut engelleri — hiçbiri
yazılım hatası değil, hepsi dışsal kural:

- **$25.000 altı:** haftada en fazla 3 gün-içi al-sat (PDT kuralı)
- **$2.000 altı:** marj hesabı açılamaz, T+1 takas nedeniyle sermaye bir gün bloke kalır
- **Kesirli hisse:** broker tarafında otomatik koruyucu stop emri kurulamaz — stop kod tarafında yönetilmek zorunda
- **Ücretsiz anlık veri:** yalnızca IEX (toplam hacmin ~%2'si). Tam veri 15 dakika gecikmeli olarak ücretsiz, anlık tam veri aylık ücretli

---

*Bu bir öğrenci araştırma projesidir. Yatırım tavsiyesi içermez.*
