"""Günlük (log) — testler.

Kritik: Türkçe karakter süreci öldürmemeli (Windows cp1252 sorunu) ve kur()
iki kez çağrılınca her satır iki kez yazılmamalı.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import gunluk  # noqa: E402


def test_turkce_karakter_dosyaya_utf8_yazilir(tmp_path):
    yol = tmp_path / "motor.log"
    log = gunluk.kur(yol, konsol=False)
    log.info("ığüşöç İĞÜŞÖÇ — alış emri")
    for k in log.handlers:
        k.flush()
    assert "ığüşöç İĞÜŞÖÇ — alış emri" in yol.read_text(encoding="utf-8")


def test_iki_kez_kurulunca_satir_cogalmaz(tmp_path):
    yol = tmp_path / "motor.log"
    gunluk.kur(yol, konsol=False)
    log = gunluk.kur(yol, konsol=False)
    log.info("tek satır")
    for k in log.handlers:
        k.flush()
    assert yol.read_text(encoding="utf-8").count("tek satır") == 1
    assert len(log.handlers) == 1


def test_zaman_utc_ve_bicim(tmp_path):
    yol = tmp_path / "motor.log"
    log = gunluk.kur(yol, konsol=False)
    log.warning("uyarı")
    for k in log.handlers:
        k.flush()
    satir = yol.read_text(encoding="utf-8").strip()
    zaman, seviye, mesaj = [p.strip() for p in satir.split("|")]
    assert zaman.endswith("Z") and "T" in zaman
    assert seviye == "WARNING" and mesaj == "uyarı"


def test_dosya_klasoru_yoksa_olusturulur(tmp_path):
    yol = tmp_path / "yok" / "alt" / "motor.log"
    gunluk.kur(yol, konsol=False).info("x")
    assert yol.exists()


def test_son_satirlar(tmp_path):
    yol = tmp_path / "motor.log"
    log = gunluk.kur(yol, konsol=False)
    for i in range(30):
        log.info("satır %d", i)
    for k in log.handlers:
        k.flush()
    son = gunluk.son_satirlar(yol, 5)
    assert len(son) == 5 and son[-1].endswith("satır 29")


def test_son_satirlar_dosya_yoksa_bos(tmp_path):
    assert gunluk.son_satirlar(tmp_path / "yok.log") == []


def teardown_module():
    for k in list(logging.getLogger(gunluk.KAYDEDICI_ADI).handlers):
        logging.getLogger(gunluk.KAYDEDICI_ADI).removeHandler(k)
        k.close()
