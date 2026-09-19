# Mimari — bugün gerçekte ne var

> **Durum:** 2026-09-20 · Kod okunarak yazıldı, hedef değil **mevcut** sistem.
> **Tasarım belgesi ayrı:** [ARCHITECTURE_TASARIM.md](ARCHITECTURE_TASARIM.md) —
> kod yazılmadan önceki hedef mimari (LEAN motoru, XGBoost modeli, Docker,
> AWS, WebSocket). Hiçbiri kurulmadı; oradaki kararların bugün de geçerli
> olanları aşağıda "Tasarımdan korunan kararlar" başlığında.
> **İlgili:** [ENVIRONMENTS.md](ENVIRONMENTS.md) · [TECH_DEBT.md](TECH_DEBT.md) ·
> [ALIM_SATIM_MOTORU.md](ALIM_SATIM_MOTORU.md) · kök dizindeki `HANDOFF.md`

---

## 1. Sistem tek cümlede

Tek bir hisseyi (AAPL) saatlik barlarla izleyen, son 140 barın en yükseği ve
en düşüğünden bir kanal çıkarıp dipte alan ve takip eden stopla çıkan, Alpaca
**paper** hesabına emir gönderen bir Python programı; yanında salt-okur bir
izleme paneli.

Model yok, makine öğrenmesi yok, konteyner yok, bulut yok. Kurallar sabit ve
elle yazılmış (`src/engine/kural.py`).

## 2. Teknoloji

| Katman | Gerçekte kullanılan |
|---|---|
| Dil | Python 3.11 (pandas, numpy, requests) |
| Veri | Alpaca Market Data REST — ücretsiz SIP, **15 dakika gecikmeli** |
| Emir | Alpaca Trading REST — yalnızca `paper-api.alpaca.markets` |
| Depo | SQLite: `data/market_data.db` (barlar), `data/paper.db` (motor kütüğü) |
| Panel | FastAPI + lightweight-charts v4 (tek sayfa, bağımlılık paketi yok) |
| Test | pytest — 297 test, ağa çıkmaz |
| Çalıştırma | Yerel makinede `python -m ...`; zamanlayıcı yok, döngü saati kendi izler |

## 3. Dosya haritası

```text
trading_project/
├── src/
│   ├── data/                 barların indirilmesi ve saklanması
│   │   ├── alpaca.py         REST indirici (yalnızca geçmiş veri, emir yok)
│   │   ├── senkron.py        AĞA ÇIKAN TEK YER: kaldığı yerden tazeler
│   │   ├── db.py, schema.py  SQLite yazma/okuma + sabit bar şeması
│   │   ├── load.py           depodan okuma (asla ağa çıkmaz)
│   │   ├── session.py        seans filtresi (09:30–16:00 ET), 09:00 mumu düzeltmesi
│   │   └── kasa.py           araştırma/kasa sınırı: 2024-06-30 | 2024-07-01
│   ├── engine/               çalışan sistem
│   │   ├── kural.py          AL-SAT KURALLARININ TEK KOPYASI (yan etkisiz)
│   │   ├── tekrar.py         aynı kuralları geçmişte yürüten backtest
│   │   ├── broker.py         EMİR GÖNDEREN TEK YER (paper adresi zorunlu)
│   │   ├── durum.py          paper.db şeması + okuma/yazma (motorun hafızası)
│   │   ├── motor.py          bir tur: veri → karar → emir → kayıt
│   │   ├── dongu.py          turu saatinde çalıştırır, bekçiyi ve bayrakları işler
│   │   ├── gosterim.py       panelin grafik verisi (1m/1D) — karar yolu dışında
│   │   ├── saglik.py         sistem sağlam mı (çıkış kodu 0/1)
│   │   ├── alarm.py          e-posta + uyarı tablosu
│   │   ├── rapor.py          backtest varsayımı ile gerçekleşmeyi karşılaştırır
│   │   └── gunluk.py         log kurulumu
│   └── arayuz/               panel (SALT-OKUR)
│       ├── sunucu.py         FastAPI uçları
│       ├── veri.py           veritabanlarından okuma, grafik biçimine çevirme
│       ├── varlik.py         sembol → varlık sınıfı (Stocks/ETFs/Crypto/...)
│       ├── komut.py          terminal komutları (bayrak dosyası bırakır)
│       └── static/           index.html · uygulama.js · gosterge.js · stil.css
├── lab/                      araştırma: defterler, backtest, grafikler
├── hypotheses/               deney kayıt defteri (REGISTRY.md) + kabul edilen sistem
├── scripts/                  fetch_bars.py · parite.py · kabul1_gorsel.py
├── tests/                    297 test
└── data/                     veritabanları, günlükler, bayrak dosyaları
```

## 4. Akış — bir tur

Döngü her saatin **:20**'sinde bir tur atar. Bar hh:00'da kapanır, veri 15
dakika gecikmeli, motor `şimdi − 16 dk`'ya kadar olan barları ister; :20'de o
bar tamamlanmış olur.

```text
  dongu.py  ── saat :20 ──►  motor.bir_tur(ayarlar)
                                 │
   1. borsa açık mı?  ───────────┤ broker.borsa_saati()   kapalıysa burada biter
   2. mutabakat       ───────────┤ broker'daki pozisyon = paper.db'deki mi
   3. veri            ───────────┤ senkron.tazele() → market_data.db → seans filtresi
   4. bayat/sıçrama kontrolü ────┤ en yeni bar eskiyse ya da %25 sıçrama varsa EMİR YOK
   5. karar           ───────────┤ kural.emir_seviyeleri(durum, cizgi, kurallar)
   6. emir            ───────────┤ broker: aynıysa dokunma · farklıysa PATCH · yoksa POST
   7. kayıt           ───────────┘ paper.db: sinyaller, emirler, turlar, uyarilar
                                 │
   tur sonrası: bildirimler (alarm) ve gosterim.tazele() (panelin 1m/1D verisi)
```

Turlar arasında, **dakikada bir** koruma bekçisi (`motor.koruma_turu`):
elimizdeki hisse kadar stop emri borsada duruyor mu? Yoksa koyar, yanlışsa
düzeltir, mutabakat bozuksa hiçbir şeye dokunmaz ve uyarı yazar. Boştayken
broker'a hiç gitmez.

Döngü uyurken 5 saniyede bir `data/DUR` ve `data/DURAKLAT` bayraklarına bakar;
`DUR` görünürse acil tur hemen çalışır.

## 5. Değişmez kurallar (kodda uygulanıyor)

1. **Kuralların tek kopyası** `src/engine/kural.py`. Backtest de motor da aynı
   fonksiyonu çağırır; `scripts/parite.py` her değişiklikten sonra bunu
   doğrular (9.9004 / 28 işlem, parmak izi `d1e6ef7289d0e7f5`).
2. **Emir gönderen tek yer** `broker.py`, ve yalnızca paper adresine.
   `Broker(canli_onayi=True)` demeden canlı uç nokta reddedilir.
3. **Ağa çıkıp depoyu güncelleyen tek yer** `senkron.py`. `load.py` ve panel
   asla ağa çıkmaz.
4. **`paper.db`'ye yazan tek süreç döngüdür.** Panel salt-okur bağlantı
   (`mode=ro`) kullanır; komutları bayrak dosyasıyla iletir.
5. **`src/` asla `lab/`'ı import etmez.** Tersi serbest.
6. **Borsadaki emir yerinde güncellenir** (PATCH), iptal+yeniden değil.
7. **Kasa (2024-07-01 →) kapalı.** Backtest katmanı orada durur; panel mumları
   gösterir ama sonuç hesaplamaz.

## 6. Veri

- **`market_data.db`** araştırma ile ortak. Barlar `(symbol, timeframe,
  adjustment, timestamp)` birincil anahtarıyla, `adjustment` anahtarın
  parçası: aynı anın düzeltilmiş ve ham fiyatı farklı satırlardır.
- Seriler: AAPL 1Min/1Hour/1Day, SPY 1Hour/1Day (1Min henüz inmedi). Depo
  315 MB.
- **Bölünme koruması:** depo günde bir son 60 günü baştan indirir; iki bar
  arası %25'ten büyük sıçrama görülürse hemen yeniler, düzelmezse emir
  gönderilmez.
- **Seans filtresi:** Alpaca saatlikte uzatılmış seansı da döndürür; kanal
  hesabı bozulmasın diye `session.regular_hours` eler. Bilinen açık: 09:00
  saatlik barı seans öncesini içeriyor (REGISTRY §6.11).

## 7. Panel

Motordan ayrı süreç, çökerse işlem etkilenmez. Asıl kullanıcısı bir yapay
zekâ: Alpaca'nın kendi ekranının yerine geçiyor, bu yüzden terimler İngilizce
borsa jargonu.

- **Grafik:** 1m / 1H / 1D; mumlar ekrana göre parça parça yüklenir (görünen
  sürenin 2 katı, geriye sürükleyince bir parça daha).
- **Katmanlar:** Live (motorun gerçekte gördüğü seviyeler + gerçek işlemler),
  Backtest (aynı kurallar geçmişte, kasada durur). Yalnızca 1H'de.
- **Göstergeler:** SMA, EMA, Bollinger fiyatın üstüne; Volume, RSI, MACD, AO
  altta ayrı panellerde (`static/gosterge.js`, saf fonksiyonlar).
- **Tablolar:** Watchlist (varlık sınıfına göre gruplu), Positions, Orders —
  Alpaca'dan salt-okur, 10 sn önbellekli; ulaşılamazsa panel çalışmaya devam
  eder.
- **Terminal:** `/status`, `/runs`, `/log`, `/alerts`, `/pause`, `/resume`,
  `/flatten confirm`, `/unhalt confirm`. Komut bayrak dosyası bırakır, döngü
  5 saniye içinde uygular.
- Sayfa ile sunucu `ARAYUZ_SURUMU` üzerinden anlaşır; uyuşmazsa panel uyarır.

## 8. Ortamlar

[ENVIRONMENTS.md](ENVIRONMENTS.md)'deki üç ortam ayrımı geçerli, ama bugün
yalnızca ikisi var:

| Ortam | Durum |
|---|---|
| **ENV-A** yerel araştırma | ✅ Var — defterler, backtest, deney kaydı |
| **ENV-B** paper | ✅ Var — `python -m src.engine.dongu`, henüz gerçek koşu başlamadı |
| **ENV-C** canlı/AWS | ❌ Yok — kurulmadı, karar da verilmedi |

## 9. Tasarımdan korunan kararlar

Eski belgedeki şu kararlar bugün de geçerli:

- **Tek private repo**, ayrım klasör düzeyinde (`src/` · `lab/` · `tests/`).
- **Ortam ayrımı ve terfi kapıları** (G1, G2) — ENVIRONMENTS.md.
- **Sızıntı yasağı:** geleceğe bakan hesap (`shift(-n)`) yok; kural
  fonksiyonu bir barlık gecikmeyle çalışır (çizgiler `shift(1)`).
- **Append-only, indeksli SQLite**, zaman ISO-8601 UTC metin.
- Model/özellik katmanı yazıldığı gün geçerli olacak **feature sözleşmesi**
  (ARCHITECTURE_TASARIM.md §6) — bugün uygulanacak kod yok.

## 10. Henüz olmayanlar

Tasarımda olup kurulmayanlar, karar sırasıyla: model ve özellik hattı
(`features.py`, `train.py`), orkestratör (çoklu hipotez), Docker imajı ve AWS
dağıtımı, GitHub Actions CI, WebSocket canlı akış (veri REST ve 15 dk
gecikmeli), risk limitleri (günlük zarar, maruziyet, emir oranı — TD-09).
