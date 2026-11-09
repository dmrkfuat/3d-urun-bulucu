"""Etsy talep listesi: Etsy'de çok satan ürünleri elle yazdığınız CSV dosyası.

Sütunlar: anahtar_kelime, ulke, not
Örnek satır: articulated dragon,US,Etsy'de ilk sayfada çok yorum
"""
from __future__ import annotations

import csv
import re
from pathlib import Path


def oku(yol: Path) -> list[dict]:
    if not yol.exists():
        return []
    with yol.open(encoding="utf-8-sig", newline="") as f:
        satirlar = []
        for r in csv.DictReader(f):
            kelime = (r.get("anahtar_kelime") or "").strip()
            if kelime and not kelime.startswith("#"):
                satirlar.append({"anahtar_kelime": kelime.lower(),
                                 "ulke": (r.get("ulke") or "").strip().upper(),
                                 "not": (r.get("not") or "").strip()})
        return satirlar


def eslesen(urun: dict, talepler: list[dict]) -> dict | None:
    metin = " ".join([urun.get("name") or "", " ".join(urun.get("tags") or [])]).lower()
    for t in talepler:
        if re.search(r"(?<![a-z0-9])" + re.escape(t["anahtar_kelime"]) + r"(?![a-z0-9])", metin):
            return t
    return None
