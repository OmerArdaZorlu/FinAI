# FinAI

**Hisse senedi piyasaları için kural tabanlı algoritmik al-sat sistemi.**

Bugün çalışan sistem: AAPL'in saatlik barlarında son 140 barın en yükseği ve
en düşüğünden bir kanal çıkarır, dibin biraz üstünde alır, takip eden stopla
çıkar. Emirler Alpaca **paper** hesabına gider. Model yok, kurallar sabit ve
elle yazılmış — makine öğrenmesi katmanı ileride eklenecek (bkz.
[docs/ARCHITECTURE_TASARIM.md](docs/ARCHITECTURE_TASARIM.md)).

Enstrümanlar: `AAPL` (işlem) · `SPY` (karşılaştırma endeksi)

> Bkz. [DISCLAIMER.md](DISCLAIMER.md)


## Sistem ne yapıyor

Döngü her saatin :20'sinde bir tur atar:

```
   Alpaca (geçmiş barlar, 15 dk gecikmeli)
            │
            ▼
   ┌─────────────────┐
   │  1. VERİ        │   Depo kaldığı yerden tazelenir, seans dışı barlar elenir
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  2. ÇİZGİ       │   Son 140 barın en yükseği (tepe) ve en düşüğü (dip)
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  3. KARAR       │   kural.py: alış = dip + %10 × genişlik
   └────────┬────────┘              stop = dip − 2 × genişlik
            ▼                       tepeye değince takip eden stop
   ┌─────────────────┐
   │  4. EMİR        │   Aynıysa dokunma · değiştiyse yerinde güncelle (PATCH)
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │  5. KAYIT       │   Sinyal, emir, tur ve uyarılar SQLite'a yazılır
   └─────────────────┘
```

Turlar arasında **dakikada bir koruma bekçisi**: elimizdeki hisse kadar stop
emri borsada duruyor mu, yoksa koyar.

### Temel tasarım ilkesi

> **Kuralların tek kopyası `src/engine/kural.py`'dedir.**
> Backtest de canlı motor da aynı fonksiyonu çağırır; iki ayrı hesap yolu
> yoktur. Bu, algoritmik sistemlerin en sinsi hatası olan *train/serve skew*'i
> (geçmişte test edilen ile canlıda çalışanın farklı olması) yapısal olarak
> engeller. `python scripts/parite.py` her değişiklikten sonra bunu doğrular.

---

## Teknoloji

| Katman | Kullanılan |
|---|---|
| Dil & kütüphaneler | Python 3.11 · Pandas · NumPy · requests |
| Veri | Alpaca Market Data REST — ücretsiz SIP, 15 dakika gecikmeli |
| Emir | Alpaca Trading REST — yalnızca **paper** adresi |
| Kalıcılık | SQLite (append-only, indeksli): barlar + motor kütüğü |
| Panel | FastAPI + lightweight-charts (salt-okur izleme arayüzü) |
| Test | pytest — 297 test, ağa çıkmaz |
| Çalıştırma | Yerel makine; döngü kendi saatini izler (cron yok) |

## Üç ortam

Kod her ortamda **aynıdır**; değişen yalnızca konfigürasyon, sır ve yetkidir.

| | **LOCAL-RESEARCH** | **LOCAL-BETA** | **AWS-PROD** |
|---|---|---|---|
| Rol | Hipotez, backtest | Gerçek veriyle prova | Yalnızca koşturma |
| Emir | Yok | Kâğıt üstü (paper) | **Gerçek** |
| Sermaye | — | Sanal | **Gerçek** |
| Durum | ✅ var | ✅ var | ❌ kurulmadı |

> **Değişmez kural:** üretimde kod düzenlenmez, deney yapılmaz. Oraya yalnızca
> etiketli, beta'da kanıtlanmış ve geri alınabilir bir sürüm girer.

Detay ve terfi kapıları: [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md)

---

## Çalışma döngüsü

Sistemin asıl işi kod yazmak değil, **hipotez deneyip elemektir**:

```
   hipotez yazar          "Kanal dibinde al, takip eden stopla çık"
          ↓
    kurala döker                 alış = dip + %10 × (tepe − dip)
          ↓
 Araştırma verisinde test        lab/backtest.py · 2016-01 → 2024-06
          ↓
 Kabul kriteri karşılandı mı?    (kriter SONUCA BAKMADAN ÖNCE yazılır)
          ├── hayır → kayda geç, bırak
          └── evet  → hypotheses/ altına kabul belgesi + motora taşı
          ↓
      Kayıt               hypotheses/REGISTRY.md — deneme sayacı dahil
```

Reddedilen hipotezler de kayıtta tutulur. Kaç hipotez denendiği bilinmezse,
şans beceri sanılır. **Kasa** (2024-07-01 sonrası) hiç bakılmamış sınav
verisidir; açma kararı verilmedi.

## Paper motorunu çalıştırmak (ENV-B)

```bash
pip install -r requirements.txt

python -m src.engine.dongu --kuru     # emir göndermeden, saat başı tur (izlemek için)
python -m src.engine.dongu            # Alpaca PAPER hesabına gerçek emir
python -m src.engine.saglik           # sistem sağlam mı? (çıkış kodu 0/1)
python -m src.engine.rapor            # backtest varsayımı vs gerçekleşme
python -m src.arayuz                  # panel: http://127.0.0.1:8000
python -m src.engine.gosterim         # panelin grafik verisi (1m/1D) — döngü zaten her turda yapar
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
* **Panelin grafiği:** 1m / 1H / 1D bar aralığı, Indicators menüsünden SMA,
  EMA, Bollinger (fiyatın üstüne) ve Volume, RSI, MACD, AO (altta ayrı
  panelde). Tepe/dip/alış çizgileri yalnızca **1H**'de görünür — kurallar
  saatlik hesaplanıyor. Dakikalık ve günlük veriyi döngü her tur sonunda
  tazeler (`src/engine/gosterim.py`), karar yolunun dışında. Ücretsiz SIP
  15 dakika gecikmeli olduğu için en yeni mum ~16 dakika geridedir.
* Günlük: `data/gunluk/motor.log` (UTF-8, 5 MB × 5 dosya).
* E-posta alarmı ve panel komut anahtarı `.env`'de (`SMTP_*`, `ALARM_ALICI`,
  `ARAYUZ_ANAHTARI`). Boşsa alarm yalnızca log'a yazar, komutlar yalnızca bu
  makineden kabul edilir.

**Panel komutları** (borsa jargonuyla İngilizce; eski Türkçe adlar takma ad
olarak çalışır): `/status`, `/runs`, `/log`, `/alerts`, `/pause` (yeni alım
durur, pozisyon ve koruyucu stop kalır), `/resume`, `/flatten confirm` (tüm
emirler iptal, **pozisyon piyasadan kapatılır**), `/unhalt confirm`.

> **Panel yerel ağa açıktır** (`0.0.0.0`). Ortak wifi'da aynı ağdaki herkes
> görebilir. Sunucuya (AWS vb.) taşındığında portu güvenlik grubunda
> **kapalı** tut; erişim Tailscale ya da SSH tüneliyle. Yalnızca bu makine
> için: `python -m src.arayuz --host 127.0.0.1`.

## Depo yapısı

```
trading_project/
├── src/
│   ├── data/        bar indirme ve depo (ağa çıkan tek yer: senkron.py)
│   ├── engine/      kural · backtest · broker · motor · döngü · sağlık · alarm
│   └── arayuz/      izleme paneli (salt-okur, emir göndermez)
├── lab/             araştırma defterleri ve backtest
├── hypotheses/      deney kayıt defteri, kabul edilen sistem
├── scripts/         veri indirme, parite kontrolü, görsel üretimi
├── tests/           297 test
├── docs/            mimari, ortam ayrımı, teknik borç
└── data/            veritabanları, günlükler, bayrak dosyaları (repoda değil)
```

---

## Dokümanlar

| Doküman | İçerik |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **Bugünkü sistem:** dizin haritası, bir turun akışı, değişmez kurallar, panel |
| [docs/ARCHITECTURE_TASARIM.md](docs/ARCHITECTURE_TASARIM.md) | Kod yazılmadan önceki hedef mimari (model, konteyner, bulut — kurulmadı) |
| [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) | Üç ortam, terfi kapıları (G1/G2), sürüm & deploy akışı, sır yönetimi |
| [docs/TECH_DEBT.md](docs/TECH_DEBT.md) | 19 maddelik teknik borç kayıt defteri + açık kararlar |

---

## Açık kararlar

Koda başlamadan verilmesi gereken tercihler:

| # | Karar | Durum |
|---|---|---|
| **AK-1** | Bar frekansı — günlük mü, saatlik mi? | ✅ Saatlik |
| **AK-2** | Broker | ✅ Alpaca |
| **AK-3** | Veri feed'i | ✅ 15 dk gecikmeli SIP |
| — | Kasa (2024-07 →) açılsın mı | ⏳ verilmedi |
| — | Paper koşusunun bitiş kriteri | ⏳ verilmedi |
| — | Gerçek paraya geçiş (ENV-C) | ⏳ verilmedi |

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
