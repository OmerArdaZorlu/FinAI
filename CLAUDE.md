# CLAUDE.md — kalıcı çalışma kuralları

Ayrıntı dokümanlarda; burası yalnızca her oturumda bilinmesi gerekenler.
Güncel durum için önce `HANDOFF.md` (varsa), sonra `docs/TECH_DEBT.md`.

## İletişim

- **Sade Türkçe, jargonsuz, kısa.** Teknik terim gerekiyorsa bir kez sade karşılığıyla.
- Soru sorulunca **cevap ver, kod yazmaya başlama.** Değişiklik önce anlatılır, onay alınır.
- Bir şeyi anlatırken: tek konu, tek örnek, adım adım (zaman çizelgesi işe yarıyor, tablo yaramadı).
- İstenmeyeni ekleme. **Hiçbir deneyi silme.**
- Commit'i kullanıcı yapar.

## Mimari kurallar

- `src/` asla `lab/`'ı import etmez (`lab/` → `src/` serbest).
- Al-sat kurallarının **tek kopyası** `src/engine/kural.py`; backtest (`src/engine/tekrar.py`) ve motor aynı fonksiyonları çağırır (TD-01).
- `data/paper.db`'ye yazan tek süreç döngüdür (motor onun içinde). Arayüz (`src/arayuz/`) salt-okurdur; komutları **bayrak dosyasıyla** iletir (`data/DUR`, `data/DURAKLAT`).
- Emir gönderen tek yer `src/engine/broker.py`; yalnızca `paper-api.alpaca.markets`'e izin verir.
- Ağa çıkıp bar deposunu güncelleyen tek yer `src/data/senkron.py`; `src/data/load.py` asla ağa çıkmaz.
- Borsadaki emir **iptal + yeniden** değil, **yerinde güncellenir** (`emri_guncelle`); aynıysa dokunulmaz.

## Araştırma disiplini

- **Kasa (2024-07-01 →) kapalı.** Açma kararı verilmedi; kasaya bakan analiz yapma (`src/data/kasa.py`).
- Her deney `hypotheses/REGISTRY.md`'ye yazılır (deneme sayacı dahil).
- Sırlar yalnızca `.env`'de. `.env.example` açılmaz.

## Her değişiklikten sonra

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q     # hepsi yeşil
PYTHONIOENCODING=utf-8 python scripts/parite.py       # backtest 9.9004 / 28, parmak izi d1e6ef7289d0e7f5
```

Parite bozulduysa karar mantığı değişmiştir — bilinçli değilse geri al.

## Komutlar

```bash
python -m src.engine.dongu [--kuru]    # saat başı tur + dakikalık koruma bekçisi
python -m src.engine.saglik            # sağlık kontrolü (çıkış 0/1)
python -m src.engine.rapor             # backtest varsayımı vs gerçekleşme
python -m src.arayuz                   # panel http://127.0.0.1:8000
```

## Ortam tuzakları (Windows)

- `/tmp` yok → oturumun scratchpad klasörü.
- Konsolda Türkçe için `PYTHONIOENCODING=utf-8`.
- Bash heredoc'ta uzun Python betiği bozuluyor (`\n` gerçek satır sonuna dönüyor, tırnaklar takılıyor) → betiği Write ile dosyaya yaz, sonra çalıştır.
- **`os.kill(pid, 0)` Windows'ta süreci öldürür** — süreç yoklaması kilit dosyasının zamanıyla.
- Headless Chrome en az 504 px genişlik açıyor.
- Alpaca ücretsiz SIP: sorgu bitişi şimdiden ≥16 dk geride olmalı, yoksa 403.
