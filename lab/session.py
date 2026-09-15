"""Geriye dönük uyumluluk — seans filtresinin gerçek yeri `src/data/session.py`.

Dosya 2026-09-15'te `src/data/`'ya taşındı: motorun da bu filtreye ihtiyacı var
ve üretim kodu (`src/`) araştırma koduna (`lab/`) bağımlı olamaz
(docs/ENVIRONMENTS.md §7, bağımlılık yönü). Filtre araştırmaya özel bir şey
değil, bar tablosu üzerinde bir veri dönüşümü — yeri `src/data/schema.py`'nin
yanı.

Bu yönlendirme, mevcut defterlerdeki `from lab.session import regular_hours`
satırları çalışmaya devam etsin diye duruyor. Yeni kod doğrudan
`src.data.session`'ı import etmeli.
"""

from __future__ import annotations

from src.data.session import (  # noqa: F401
    EXCHANGE_TZ,
    FIRST_RTH_HOUR,
    LAST_RTH_HOUR,
    bars_per_day,
    exchange_hour,
    regular_hours,
    regular_minutes,
    session_report,
)
