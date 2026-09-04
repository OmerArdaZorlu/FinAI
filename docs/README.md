# Dokümantasyon İndeksi

Algoritmik al-sat sistemi — ABD hisse senedi piyasaları (`AAPL`, `SPY`).

| Doküman | İçerik |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Sistem mimarisi, teknoloji yığını, nested dizin hiyerarşisi, canlı veri akışı (mikro-ETL), dual-repo stratejisi, iş akışı, feature sözleşmesi, risk parametreleri, CI/CD kapıları |
| [ENVIRONMENTS.md](ENVIRONMENTS.md) | Üç ortam ayrımı (LOCAL-RESEARCH / LOCAL-BETA / AWS-PROD), terfi kapıları G1–G2, sürüm & deploy akışı, secret yönetimi |
| [TECH_DEBT.md](TECH_DEBT.md) | 19 maddelik teknik borç kayıt defteri — önem, ortam, tanım-of-done ve önerilen sprint sırası |

---

## Hızlı Yön Bulma

**"Sistem nasıl çalışıyor?"** → [ARCHITECTURE.md §2–§3](ARCHITECTURE.md#2-i̇ç-i̇çe-nested-sistem--dosya-dizin-hiyerarşisi)

**"Bunu nerede çalıştıracağım?"** → [ENVIRONMENTS.md §5](ENVIRONMENTS.md#5-ortam-farkları--tek-tablo)

**"Canlıya çıkabilir miyiz?"** → [ENVIRONMENTS.md §6 Kapı G2](ENVIRONMENTS.md#-kapı-g2--env-b--env-c-beta--üretim)

**"Sırada ne var?"** → [TECH_DEBT.md — Önerilen Çalışma Sırası](TECH_DEBT.md#önerilen-çalışma-sırası)

---

## Üç Cümlelik Sistem Sözleşmesi

1. **Öğrenmek local'de olur** — model ENV-A'da doğar, başka hiçbir yerde eğitilmez.
2. **Kanıtlamak beta'da olur** — üretim kodunun kendisi, gerçek veriyle ve sanal parayla, kararlaştırılan süre boyunca ENV-B'de yaşar.
3. **AWS sadece koşturur** — ENV-C'de yeni hiçbir şey denenmez; oraya yalnızca etiketli, kanıtlanmış ve geri alınabilir bir imaj girer.
