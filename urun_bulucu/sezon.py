"""Sezon takvimi: yaklaşan özel günlere uyan modeller öne çıkar.

Bir sezon, tarihinden `once_gun` gün öncesinden başlayıp tarihin kendisine kadar "aktif"tir.
Aktif sezonun anahtar kelimelerinden biri model adında veya etiketlerinde geçerse model
SEZON_BONUS kadar ek puan alır ve raporda/Telegram'da sezon notu görünür.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

SEZON_BONUS = 5


@dataclass(frozen=True)
class Sezon:
    ad: str
    emoji: str
    once_gun: int
    kelimeler: tuple[str, ...]


def _ninci_pazar(yil: int, ay: int, n: int) -> date:
    ilk = date(yil, ay, 1)
    ilk_pazar = ilk + timedelta(days=(6 - ilk.weekday()) % 7)
    return ilk_pazar + timedelta(weeks=n - 1)


# Dini bayramlar her yıl ~11 gün kayar; Diyanet takvimine göre yılda bir güncelleyin.
BAYRAM_TARIHLERI = {
    "Ramazan Bayramı": [date(2026, 3, 20), date(2027, 3, 9), date(2028, 2, 26)],
    "Kurban Bayramı": [date(2026, 5, 27), date(2027, 5, 16), date(2028, 5, 5)],
}

SEZONLAR: list[tuple[Sezon, object]] = [
    (Sezon("Yılbaşı", "🎄", 56, ("christmas", "xmas", "santa", "noel", "new year", "yılbaşı", "ornament",
                                 "snowman", "snowflake", "reindeer", "grinch", "gingerbread", "advent",
                                 "nativity", "elf")),
     lambda y: date(y, 12, 31)),
    (Sezon("Sevgililer Günü", "❤️", 35, ("valentine", "heart", "love", "couple", "sevgili", "kalp")),
     lambda y: date(y, 2, 14)),
    (Sezon("Anneler Günü", "💐", 35, ("mother", "mom", "mum", "anne", "flower", "rose", "tulip")),
     lambda y: _ninci_pazar(y, 5, 2)),
    (Sezon("Babalar Günü", "👔", 35, ("father", "dad", "baba", "beer", "bottle opener")),
     lambda y: _ninci_pazar(y, 6, 3)),
    (Sezon("Cadılar Bayramı", "🎃", 42, ("halloween", "pumpkin", "spooky", "skull", "ghost", "witch",
                                         "skeleton", "bat", "zombie")),
     lambda y: date(y, 10, 31)),
    (Sezon("Okula dönüş", "🎒", 35, ("school", "pencil", "pen holder", "bookmark", "okul", "kalemlik",
                                     "desk organizer", "ruler")),
     lambda y: date(y, 9, 8)),
    (Sezon("Öğretmenler Günü", "🍎", 28, ("teacher", "öğretmen", "bookmark", "pen holder")),
     lambda y: date(y, 11, 24)),
    (Sezon("Ramazan Bayramı", "🌙", 35, ("ramadan", "ramazan", "eid", "crescent", "lantern", "mosque",
                                         "bayram", "hilal")),
     "Ramazan Bayramı"),
    (Sezon("Kurban Bayramı", "🌙", 28, ("eid", "bayram", "mosque", "crescent", "hilal")),
     "Kurban Bayramı"),
]


def _sonraki_tarih(kural: object, bugun: date) -> date | None:
    if isinstance(kural, str):
        return next((t for t in BAYRAM_TARIHLERI.get(kural, []) if t >= bugun), None)
    for yil in (bugun.year, bugun.year + 1):
        t = kural(yil)  # type: ignore[operator]
        if t >= bugun:
            return t
    return None


def aktif_sezonlar(bugun: date) -> list[tuple[Sezon, int]]:
    """(sezon, kalan gün) listesi; en yakın önce."""
    sonuc = []
    for sezon, kural in SEZONLAR:
        t = _sonraki_tarih(kural, bugun)
        if t is not None and (t - bugun).days <= sezon.once_gun:
            sonuc.append((sezon, (t - bugun).days))
    return sorted(sonuc, key=lambda x: x[1])


def _kelime_var(metin: str, kelime: str) -> bool:
    return re.search(r"(?<![a-zçğıöşü0-9])" + re.escape(kelime) + r"(?![a-zçğıöşü0-9])", metin) is not None


def eslesen(urun: dict, aktifler: list[tuple[Sezon, int]]) -> tuple[Sezon, int] | None:
    metin = " ".join([urun.get("name") or "", *[str(t) for t in urun.get("tags") or []]]).lower()
    for sezon, kalan in aktifler:
        if any(_kelime_var(metin, k) for k in sezon.kelimeler):
            return sezon, kalan
    return None


def yazi(sezon: Sezon, kalan: int) -> str:
    if kalan == 0:
        return f"{sezon.emoji} {sezon.ad}: bugün"
    return f"{sezon.emoji} {sezon.ad}: {kalan} gün kaldı"
