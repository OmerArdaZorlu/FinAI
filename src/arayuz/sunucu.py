"""İzleme ve kontrol arayüzünün sunucusu (FastAPI).

Motordan AYRI süreç. Çökerse işlem etkilenmez; veritabanlarını yalnızca okur,
komutları bayrak dosyasıyla iletir (bkz. `komut.py`).

Güvenlik
--------
Görüntüleme (grafik, sağlık, günlük) anahtarsız. **Komut göndermek**
`.env`'deki `ARAYUZ_ANAHTARI`'nı ister (`X-Arayuz-Anahtari` başlığı, sabit
zamanlı karşılaştırma). Anahtar tanımlı değilse komutlar yalnızca bu
makineden (127.0.0.1) kabul edilir. Aynı ağdaki başka bir cihaz izleyebilir
ama `/stop` yazamaz.

Sunucu AWS gibi bir yere taşınırsa portu güvenlik grubunda kapalı tut; erişim
Tailscale ya da SSH tüneliyle. `0.0.0.0` orada doğrudan internet demektir.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.data.alpaca import load_dotenv
from src.data.kasa import VAULT_BEGINS
from src.engine import gunluk
from src.engine.motor import Ayarlar

from . import komut, veri

STATIK = Path(__file__).resolve().parent / "static"
YEREL = {"127.0.0.1", "::1", "localhost"}
SAGLIK_ONBELLEK_SN = 20


@dataclass
class ArayuzAyar:
    motor: Ayarlar = field(default_factory=Ayarlar)
    anahtar: str | None = None
    gunluk_dosyasi: Path = gunluk.VARSAYILAN_DOSYA

    @classmethod
    def ortamdan(cls, dotenv_yolu: Path | str = ".env") -> "ArayuzAyar":
        load_dotenv(dotenv_yolu)
        return cls(anahtar=os.environ.get("ARAYUZ_ANAHTARI", "").strip() or None)


class KomutIstegi(BaseModel):
    metin: str


def uygulama(ayar: ArayuzAyar | None = None) -> FastAPI:
    ayar = ayar or ArayuzAyar.ortamdan()
    m = ayar.motor
    app = FastAPI(title="KABUL-1 paneli", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIK), name="static")

    saglik_onbellek: dict = {"zaman": 0.0, "veri": None}
    saglik_kilidi = threading.Lock()

    def yetki(request: Request) -> str:
        """Komut yetkisi. Kaynağı (IP) döndürür — kütüğe yazılır."""
        kaynak = request.client.host if request.client else ""
        if ayar.anahtar:
            gelen = request.headers.get("x-arayuz-anahtari", "")
            if not hmac.compare_digest(gelen.encode(), ayar.anahtar.encode()):
                raise HTTPException(401, "Komut anahtarı yanlış ya da eksik.")
        elif kaynak not in YEREL:
            raise HTTPException(403, "ARAYUZ_ANAHTARI tanımlı değil: komutlar yalnızca "
                                     "bu makineden kabul edilir. .env'e anahtar ekle.")
        return kaynak

    @app.get("/", include_in_schema=False)
    def ana_sayfa():
        return FileResponse(STATIK / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/yapilandirma")
    def yapilandirma():
        return {"motor_sembolu": m.sembol, "anahtar_gerekli": bool(ayar.anahtar),
                "araliklar": veri.ARALIKLAR, "kasa_baslangici": VAULT_BEGINS}

    @app.get("/api/hisseler")
    def hisseler():
        return veri.hisseler(m.veri_db, m.paper_db, m.sembol)

    @app.get("/api/barlar")
    def barlar(sembol: str, aralik: str = "60g"):
        return veri.barlar(m.veri_db, sembol, _aralik(aralik))

    @app.get("/api/katman/canli")
    def canli(sembol: str, aralik: str = "60g"):
        if sembol != m.sembol:
            return {"cizgiler": {a: [] for a in veri.CIZGILER}, "islemler": [],
                    "sinyal_sayisi": 0, "not": "motor bu sembolde işlem yapmıyor"}
        return veri.canli_katman(m.paper_db, m.veri_db, sembol, _aralik(aralik))

    @app.get("/api/katman/backtest")
    def backtest(sembol: str, aralik: str = "60g"):
        return veri.backtest_katmani(m.veri_db, sembol, _aralik(aralik))

    @app.get("/api/ozet")
    def ozet():
        """Başlık çubuğu için ucuz özet — broker'a gitmez."""
        turlar = veri.son_turlar(m.paper_db, 1)
        kilit = m.kilit_dosyasi
        kilit_yasi = time.time() - kilit.stat().st_mtime if kilit.exists() else None
        return {"son_tur": turlar[0] if turlar else None,
                "dongu_ayakta": kilit_yasi is not None and kilit_yasi < 120,
                "dur": m.dur_dosyasi.exists(),
                "duraklat": m.duraklat_dosyasi.exists()}

    @app.get("/api/saglik")
    def saglik_raporu(taze: bool = False):
        """Tam sağlık kontrolü (broker'a gider). 20 sn önbellekli."""
        from src.engine import saglik
        with saglik_kilidi:
            if taze or time.time() - saglik_onbellek["zaman"] > SAGLIK_ONBELLEK_SN:
                sonuclar = saglik.kontroller(m)
                saglik_onbellek["veri"] = {
                    "saglam": saglik.saglam_mi(sonuclar),
                    "kontroller": [{"ad": k.ad, "seviye": k.seviye, "mesaj": k.mesaj}
                                   for k in sonuclar]}
                saglik_onbellek["zaman"] = time.time()
            return saglik_onbellek["veri"]

    @app.get("/api/uyarilar")
    def uyarilar(adet: int = 20):
        return veri.son_uyarilar(m.paper_db, max(1, min(adet, 200)))

    @app.get("/api/gunluk")
    def gunluk_son(satir: int = 200):
        return {"satirlar": gunluk.son_satirlar(ayar.gunluk_dosyasi, max(1, min(satir, 2000)))}

    @app.post("/api/komut")
    def komut_calistir(istek: KomutIstegi, kaynak: str = Depends(yetki)):
        s = komut.calistir(istek.metin, m, kaynak=kaynak, gunluk_dosyasi=ayar.gunluk_dosyasi)
        saglik_onbellek["zaman"] = 0.0          # bir sonraki sağlık sorgusu taze olsun
        return JSONResponse({"metin": s.metin, "basarili": s.basarili,
                             "tehlikeli": s.tehlikeli})

    return app


def _aralik(aralik: str) -> str:
    return aralik if aralik in veri.ARALIKLAR else "60g"
