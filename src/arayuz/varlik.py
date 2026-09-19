"""Sembolün varlık sınıfı — panelin izleme listesi ve tabloları için.

Ağa çıkmaz. Alpaca'nın kendi sınıfı (`us_equity`, `crypto`, `us_option`)
biliniyorsa önce ona bakılır; ama Alpaca ETF'yi ve emtia fonunu da
`us_equity` sayar, o yüzden onlar aşağıdaki tablolardan ayrılır. Yeni bir
fon eklemek: tabloya tek satır.
"""

from __future__ import annotations

import re

STOCKS = "Stocks"
ETFS = "ETFs"
COMMODITIES = "Commodities"
CRYPTO = "Crypto"
OPTIONS = "Options"
OTHER = "Other"

SINIFLAR = (STOCKS, ETFS, COMMODITIES, CRYPTO, OPTIONS, OTHER)

# Emtia fonları: altın, gümüş, petrol, doğalgaz, tarım, geniş sepet.
EMTIA = frozenset({
    "GLD", "IAU", "GLDM", "SGOL", "SLV", "SIVR", "PPLT", "PALL",
    "USO", "BNO", "UNG", "DBA", "DBC", "PDBC", "CORN", "WEAT", "CPER",
})

# Borsada işlem gören fonlar: endeks, sektör, tahvil, uluslararası.
ETF = frozenset({
    "SPY", "VOO", "IVV", "QQQ", "QQQM", "DIA", "IWM", "VTI", "VT", "VEA", "VWO",
    "EFA", "EEM", "SCHD", "VIG", "VUG", "VTV", "RSP", "MDY", "IJH", "IJR", "ARKK",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SMH", "SOXX", "KRE", "XBI", "GDX", "GDXJ",
    "TLT", "IEF", "SHY", "BND", "AGG", "LQD", "HYG", "TIP", "BIL", "SGOV",
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "VXX",
})

# OCC opsiyon sembolü: kök + YYMMDD + C/P + 8 hane kullanım fiyatı.
_OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def sinif(sembol: str, alpaca_sinifi: str | None = None) -> str:
    """Sembolün varlık sınıfı (`SINIFLAR`'dan biri)."""
    s = sembol.upper().strip()
    if alpaca_sinifi == "crypto" or "/" in s:
        return CRYPTO
    if alpaca_sinifi == "us_option" or _OCC.match(s):
        return OPTIONS
    if s in EMTIA:
        return COMMODITIES
    if s in ETF:
        return ETFS
    if alpaca_sinifi in (None, "", "us_equity"):
        return STOCKS
    return OTHER
