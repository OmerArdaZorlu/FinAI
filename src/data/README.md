# `src/data` — Veri Katmanı

İki **ayrı** pipe, **tek** ortak sözleşme, **tek** depo.

| Dosya | Rol | Ortam | Durum |
|---|---|---|---|
| `schema.py` | Kanonik bar sözleşmesi + doğrulama (ortak) | hepsi | ✅ |
| `db.py` | SQLite kalıcılık — `bars`, `ingest_log` (ortak) | hepsi | ✅ |
| `alpaca.py` | **Pipe 1 — Geçmiş**: REST `/v2/stocks/bars` | ENV-A | ✅ |
| `load.py` | Araştırma tarafının okuma arayüzü | ENV-A | ✅ |
| `stream.py` | **Pipe 2 — Canlı**: WebSocket, bar bar | ENV-B/C | ⬜ Henüz yok |

## Neden iki pipe, tek sözleşme

Geçmiş veri **toplu** gelir (bir seferde 10 yıl, sayfalanmış). Canlı veri **tek tek**
gelir (sürekli bağlantı, RAM'de kayan pencere). Yaşam döngüleri, hata modları ve
yeniden deneme mantıkları farklıdır.

Ama ikisi de `schema.py`'ye uyar ve ikisi de `bars` tablosuna yazar. Canlı bar
geçmiş bardan farklı bir şekle girerse model, eğitildiğinden başka sayılar görür
ve canlı davranış backtest'e benzemez — `features.py` için geçerli "tek kaynak"
kuralının (ARCHITECTURE_TASARIM.md §6) veri katmanındaki karşılığı budur.

## Depo şeması — `data/market_data.db`

```sql
bars (symbol, timeframe, adjustment, timestamp,     -- ← birincil anahtar
      open, high, low, close, volume, trade_count, vwap)

ingest_log (id, symbol, timeframe, adjustment, feed,
            requested_start/end, actual_start/end,
            rows_fetched, rows_written, source, fetched_at_utc)
```

**Birincil anahtar neden dört sütun?** Bir barın kimliği yalnızca sembol+zaman
değildir. `adjustment=raw` ile `adjustment=all`, *aynı barın farklı fiyatıdır*.
Düzeltme anahtarda olmasaydı tek bir `raw` indirme, tüm `all` serisini sessizce
ezerdi — ve bunu ancak aylar sonra, model bölünme günlerinde sahte sinyal
üretmeye başlayınca fark ederdik. `tests/test_db.py::test_adjustment_is_part_of_identity`
bu senaryoyu koruyor.

**`ingest_log` neden append-only?** Barlar tazelenir (UPSERT), künye tazelenmez.
"Bu veriyi ne zaman, hangi parametrelerle çektim?" sorusunun geriye dönük ve
değiştirilemez cevabı. Aynı analizi 6 ay sonra tekrarlayınca sonuç değişirse,
verinin mi yoksa kodun mu değiştiğini buradan anlarsınız.

## Kullanım

```bash
python scripts/fetch_bars.py --symbols SPY AAPL --timeframe 1Day --start 2016-01-01
```

Komut **idempotent**: aynı komutu iki kez çalıştırmak yinelenen bar üretmez,
mevcut satırları tazeler. Yalnızca `ingest_log`'a yeni bir künye satırı ekler.

```python
from src.data.load import load_bars, available_series, load_ingest_log

df = load_bars("SPY")                                   # tüm seri
df = load_bars("SPY", start="2024-01-01", end="2024-12-31")   # aralık (uçlar dahil)
available_series()   # DB'de ne var: sembol, frekans, düzeltme, bar sayısı, aralık
load_ingest_log()    # indirme geçmişi
```

CSV gerekirse (Excel/Sheets ile QC için, ARCHITECTURE_TASARIM.md §5 adım 4):

```bash
python scripts/fetch_bars.py --symbols SPY --csv-dir data/export
```

CSV **türetilmiş çıktıdır**; kaynak-doğru (source of truth) her zaman veritabanıdır.

## Kararlar

- **`adjustment=all`** — bölünme + temettü düzeltmeli. Doğrulandı: AAPL'ın
  31.08.2020 tarihli 4:1 bölünmesinde seri sürekli (`120.96 → 125.06`).
  `raw` olsaydı burada sahte bir −%74 çöküş görünürdü.
- **`feed=sip`** — konsolide (tüm borsalar). Ücretsiz planda 15 dakikadan eski
  sorgular için tam SIP geliyor; günlük barda fiilen kısıt değil (TECH_DEBT.md AK-3).
- **Zaman TEXT (ISO-8601 UTC)** — SQLite'ın datetime tipi yok. ISO-8601 UTC metni
  sözlüksel ve kronolojik olarak aynı sırada dizilir, gözle okunur, tz belirsizliği
  taşımaz. Epoch integer daha ucuz olurdu ama her hata ayıklamada zihinsel çeviri
  gerektirirdi.
- **`--end` varsayılanı dün** — bugünün kapanmamış yarım barı asla indirilmez.
  Yarım bar, `high`/`low`'u henüz belli olmadığı için sızıntının en sinsi türüdür.
- **Doğrulama yazmadan önce koşar** — NaN, sıra bozukluğu, `high < low` gibi
  ihlallerde satır diske hiç ulaşmaz. Sessizce temizlenen veri, fark edilmeyen
  veridir (ARCHITECTURE_TASARIM.md §6, Kural 5).
