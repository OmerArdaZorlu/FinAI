"""Alpaca Trading API — emir gönderme, pozisyon ve borsa saati (paper).

Kapsam ayrımı
-------------
`src/data/alpaca.py` yalnızca **geçmiş veri** indirir ve broker uç noktasına
hiç dokunmaz (ENV-A kuralı). Emir gönderen tek yer burasıdır. Anahtar okuma
ve yeniden deneme desenleri oradan alınmıştır.

Canlı uç nokta koruması
-----------------------
Bu modül `paper-api.alpaca.markets` dışında bir adrese emir göndermeyi
**reddeder**. `.env`'deki adres yanlışlıkla canlıya çevrilirse kod açılışta
patlar, sessizce gerçek para harcamaz (ENVIRONMENTS.md §8: paper ve live
anahtarları aynı yerde tutulmaz). Bilinçli bir canlı koşu için
`canli_onayi=True` gerekir — proje içinde hiçbir yerde kullanılmaz.

Emir tipleri ve neden böyle
---------------------------
* **Alış — limit, `day`.** Seviye her bar değiştiği için emir bar sonunda
  iptal edilip yenisi konur. Bekleyen emir borsada durduğundan motor uyurken
  de dolar; 15 dakikalık veri gecikmesi gerçekleşmeyi etkilemez.
* **Koruma — stop, `gtc`.** Pozisyon gece taşındığı için emir de gece
  yaşamalı. Tam hisse kullanmamızın sebebi bu: kesirli hissede Alpaca
  koruyucu emir tutamıyor ve stop bizim sürecimizde durmak zorunda kalıyor
  (TECH_DEBT.md TD-19).
* **`extended_hours=False`** her ikisinde de. Backtest uzatılmış seansı
  görmüyor (`src/data/session.py`); emirler de orada tetiklenmemeli, yoksa
  canlı sistem test edilmemiş barlarda işlem yapar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from src.data.alpaca import Credentials, get_credentials

PAPER_HOST = "paper-api.alpaca.markets"
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.5
TIMEOUT = 30

# Emir tipleri — `durum.py`'deki `emirler.tip` sütunuyla aynı sözcükler
LIMIT_AL = "limit_al"
STOP_SAT = "stop_sat"


class BrokerError(RuntimeError):
    """Broker çağrısı kurtarılamaz biçimde başarısız olduğunda."""


class CanliUcNoktaError(BrokerError):
    """Paper beklenirken canlı uç nokta bulundu — emir gönderilmedi."""


@dataclass(frozen=True, slots=True)
class Hesap:
    nakit: float
    ozkaynak: float
    alim_gucu: float
    islem_engelli: bool
    hesap_engelli: bool

    @property
    def calisabilir(self) -> bool:
        return not (self.islem_engelli or self.hesap_engelli)


@dataclass(frozen=True, slots=True)
class Pozisyon:
    sembol: str
    adet: int
    ortalama_maliyet: float
    guncel_fiyat: float


@dataclass(frozen=True, slots=True)
class Emir:
    """Broker'daki bir emrin hali."""

    broker_id: str
    client_order_id: str
    sembol: str
    yon: str                  # 'buy' | 'sell'
    tip: str                  # 'limit' | 'stop' | ...
    adet: int
    seviye: float             # limit_price ya da stop_price
    durum: str                # 'new','accepted','filled','canceled','rejected',...
    dolan_adet: int
    dolan_ortalama_fiyat: float

    @property
    def dolu(self) -> bool:
        return self.durum == "filled"

    @property
    def bekliyor(self) -> bool:
        return self.durum in ("new", "accepted", "pending_new", "partially_filled",
                              "accepted_for_bidding")


@dataclass(frozen=True, slots=True)
class BorsaSaati:
    acik: bool
    su_an: str
    sonraki_acilis: str
    sonraki_kapanis: str


class Broker:
    """Alpaca paper hesabına bağlanan ince istemci.

    Args:
        credentials: Verilmezse `.env`'den okunur.
        base_url: Verilmezse `.env`'deki `APCA_API_BASE_URL`. Adres `/v2` ile
            bitiyorsa olduğu gibi kullanılır.
        canli_onayi: Canlı uç noktaya izin vermek için bilinçli onay.
            Varsayılan `False` — paper dışı adres hata verir.
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        base_url: str | None = None,
        dotenv_path: str | Path = ".env",
        canli_onayi: bool = False,
    ) -> None:
        import os

        self._creds = credentials or get_credentials(dotenv_path)
        adres = (base_url or os.environ.get("APCA_API_BASE_URL", "")).strip().rstrip("/")
        if not adres:
            raise BrokerError(
                "Emir uç noktası bulunamadı.\n"
                "  .env dosyasına ekleyin:\n"
                "    APCA_API_BASE_URL=https://paper-api.alpaca.markets/v2"
            )
        if not adres.endswith("/v2"):
            adres = f"{adres}/v2"

        host = urlparse(adres).hostname or ""
        if host != PAPER_HOST and not canli_onayi:
            raise CanliUcNoktaError(
                f"Paper uç noktası bekleniyordu ama adres '{host}'.\n"
                f"  Beklenen: {PAPER_HOST}\n"
                "  Gerçek parayla işlem yapılacaksa bu bilinçli bir karardır;\n"
                "  Broker(canli_onayi=True) ile açıkça belirtilmelidir."
            )
        self.base_url = adres
        self.paper = host == PAPER_HOST

    # ------------------------------------------------------------ istek --

    def _istek(self, yontem: str, yol: str, **kw: Any) -> Any:
        """HTTP + üstel geri çekilme. 429 ve 5xx yeniden denenir, 4xx anında patlar.

        `src/data/alpaca.py:_get_with_retry` ile aynı davranış, tüm yöntemler için.
        """
        url = f"{self.base_url}{yol}"
        son_hata = ""
        for deneme in range(MAX_RETRIES):
            try:
                yanit = requests.request(
                    yontem, url, headers=self._creds.headers, timeout=TIMEOUT, **kw
                )
            except requests.RequestException as exc:
                son_hata = f"ağ hatası: {exc}"
            else:
                if yanit.status_code in (200, 204):
                    return yanit.json() if yanit.content else None
                if yanit.status_code in (401, 403):
                    raise BrokerError(
                        f"Kimlik doğrulama reddedildi (HTTP {yanit.status_code}). "
                        "Anahtarlar paper hesabına mı ait?"
                    )
                if yanit.status_code == 404:
                    return None
                if yanit.status_code < 500 and yanit.status_code != 429:
                    raise BrokerError(f"HTTP {yanit.status_code}: {yanit.text[:500]}")
                son_hata = f"HTTP {yanit.status_code}: {yanit.text[:200]}"

            if deneme < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE_SECONDS * (2**deneme))

        raise BrokerError(f"{MAX_RETRIES} denemenin ardından başarısız — son hata: {son_hata}")

    # ------------------------------------------------------------ okuma --

    def hesap(self) -> Hesap:
        h = self._istek("GET", "/account")
        return Hesap(
            nakit=float(h["cash"]),
            ozkaynak=float(h["equity"]),
            alim_gucu=float(h["buying_power"]),
            islem_engelli=bool(h.get("trading_blocked")),
            hesap_engelli=bool(h.get("account_blocked")),
        )

    def borsa_saati(self) -> BorsaSaati:
        """Borsa açık mı. Tatiller ve yarım günler buradan gelir — ayrı takvim yok."""
        s = self._istek("GET", "/clock")
        return BorsaSaati(
            acik=bool(s["is_open"]),
            su_an=s["timestamp"],
            sonraki_acilis=s["next_open"],
            sonraki_kapanis=s["next_close"],
        )

    def pozisyon(self, sembol: str) -> Pozisyon | None:
        """Sembolde açık pozisyon; yoksa None."""
        p = self._istek("GET", f"/positions/{sembol}")
        if not p:
            return None
        return Pozisyon(
            sembol=p["symbol"],
            adet=int(float(p["qty"])),
            ortalama_maliyet=float(p["avg_entry_price"]),
            guncel_fiyat=float(p.get("current_price") or "nan"),
        )

    def bekleyen_emirler(self, sembol: str | None = None) -> list[Emir]:
        params = {"status": "open", "limit": 500}
        if sembol:
            params["symbols"] = sembol
        return [_emre_cevir(e) for e in (self._istek("GET", "/orders", params=params) or [])]

    def emir_sorgula(self, client_order_id: str) -> Emir | None:
        """Kimliğe göre emrin son hali. Yoksa None."""
        e = self._istek(
            "GET", "/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
        )
        return _emre_cevir(e) if e else None

    # ------------------------------------------------------------- emir --

    def limit_al(
        self, sembol: str, adet: int, seviye: float, client_order_id: str,
    ) -> Emir:
        """Bekleyen limit alış emri — bar boyunca borsada durur, gün sonunda düşer."""
        return self._emir_gonder({
            "symbol": sembol,
            "qty": str(int(adet)),
            "side": "buy",
            "type": "limit",
            "time_in_force": "day",
            "limit_price": f"{seviye:.2f}",
            "client_order_id": client_order_id,
            "extended_hours": False,
        })

    def stop_sat(
        self, sembol: str, adet: int, seviye: float, client_order_id: str,
    ) -> Emir:
        """Koruyucu stop satış — gece dahil yaşar (gtc), broker'da durur."""
        return self._emir_gonder({
            "symbol": sembol,
            "qty": str(int(adet)),
            "side": "sell",
            "type": "stop",
            "time_in_force": "gtc",
            "stop_price": f"{seviye:.2f}",
            "client_order_id": client_order_id,
            "extended_hours": False,
        })

    def piyasadan_sat(self, sembol: str, adet: int, client_order_id: str) -> Emir:
        """Piyasa emriyle çık — yalnızca acil durdurmada kullanılır."""
        return self._emir_gonder({
            "symbol": sembol,
            "qty": str(int(adet)),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_order_id,
        })

    def _emir_gonder(self, govde: dict) -> Emir:
        return _emre_cevir(self._istek("POST", "/orders", json=govde))

    def emri_iptal(self, broker_id: str) -> None:
        """Tek emri iptal eder. Zaten dolmuşsa broker 422 döner — sessizce geçilir."""
        try:
            self._istek("DELETE", f"/orders/{broker_id}")
        except BrokerError as exc:
            if "422" not in str(exc):
                raise

    def tum_emirleri_iptal(self) -> None:
        """Bekleyen tüm emirleri iptal eder — acil durdurmada kullanılır."""
        self._istek("DELETE", "/orders")


def _emre_cevir(e: dict) -> Emir:
    """Alpaca emir JSON'unu kendi tipimize çevirir."""
    seviye = e.get("limit_price") or e.get("stop_price") or "nan"
    return Emir(
        broker_id=e["id"],
        client_order_id=e.get("client_order_id", ""),
        sembol=e["symbol"],
        yon=e["side"],
        tip=e["type"],
        adet=int(float(e["qty"])),
        seviye=float(seviye),
        durum=e["status"],
        dolan_adet=int(float(e.get("filled_qty") or 0)),
        dolan_ortalama_fiyat=float(e.get("filled_avg_price") or "nan"),
    )
