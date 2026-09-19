"""Araştırma / kasa sınırı — tek kopya.

Kasa (2024-07-01 → bugün), stratejinin hiç görmediği son sınav verisidir.
Açılması ayrı ve bilinçli bir karardır; bir kez bakılınca geri alınamaz.

Sınır önce yalnızca `lab/splits.py`'deydi. Arayüzün backtest katmanı da
kasada durmak zorunda, ama arayüz üretim kodu ve `src/` `lab/`'ı import
edemez. Sabit buraya taşındı; `lab/splits.py` buradan alıyor.
"""

RESEARCH_END = "2024-06-30"   # araştırma alanının son günü (dahil)
VAULT_BEGINS = "2024-07-01"   # kasa buradan başlar (dahil)
