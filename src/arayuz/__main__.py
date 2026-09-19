"""Arayüzü başlatır.

    python -m src.arayuz                    # yerel ağa açık, port 8000
    python -m src.arayuz --host 127.0.0.1   # yalnızca bu makine
"""

from __future__ import annotations

import argparse
import socket
import sys

import uvicorn

from src.engine import gunluk

from .sunucu import ArayuzAyar, uygulama


def _yerel_ag_ip() -> str | None:
    """Bu makinenin yerel ağ adresi (paket göndermeden: UDP 'bağlantısı')."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KABUL-1 izleme ve kontrol paneli.")
    p.add_argument("--host", default="0.0.0.0",
                   help="0.0.0.0 = yerel ağa açık, 127.0.0.1 = yalnızca bu makine")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    gunluk.kur(gunluk.VARSAYILAN_DOSYA.with_name("arayuz.log"), ad="arayuz")
    ayar = ArayuzAyar.ortamdan()

    print(f"Panel: http://127.0.0.1:{args.port}")
    if args.host in ("0.0.0.0", "::"):
        ip = _yerel_ag_ip()
        if ip:
            print(f"Yerel ağdan (telefon vb.): http://{ip}:{args.port}")
        print("UYARI: yerel ağa açık. Ortak wifi'da aynı ağdaki herkes paneli görebilir.\n"
              "       Sunucuya (AWS vb.) taşınırsa portu dışarıya KAPALI tut.")
    if ayar.anahtar:
        print("Komutlar ARAYUZ_ANAHTARI ile korunuyor.")
    else:
        print("ARAYUZ_ANAHTARI tanımlı değil: komutlar yalnızca bu makineden kabul edilir.")

    uvicorn.run(uygulama(ayar), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
