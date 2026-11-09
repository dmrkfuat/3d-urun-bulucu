"""Model açıklamasından baskı süresi, malzeme ve görsel özellik çıkarımı."""
from __future__ import annotations

import html
import re

# Görsel olarak ilgi çekici özellikler: etiket -> (ağırlık, anahtar kelimeler)
GORSEL_OZELLIKLER: dict[str, tuple[float, list[str]]] = {
    "hareketli parça": (0.5, [
        "print in place", "print-in-place", "printinplace", "pip", "articulated", "articulating",
        "flexi", "moving parts", "kinetic", "mechanism", "gear", "gears", "hinge", "hinged",
        "spinner", "transforming", "folding", "collapsible", "retractable",
    ]),
    "çok renkli (AMS)": (0.3, [
        "multicolor", "multi-color", "multi color", "multicolour", "multi-colour", "ams",
        "color change", "colour change", "multi-material", "multimaterial", "2 color", "3 color",
        "4 color", "two color", "dual color",
    ]),
    "satisfying": (0.3, [
        "satisfying", "fidget", "infinity cube", "clicker", "illusion", "impossible",
        "puzzle", "asmr", "stress relief", "spiral",
    ]),
    "ışık/şeffaf efekt": (0.2, [
        "lithophane", "lamp", "light", "led", "vase mode", "spiral vase", "translucent", "glow",
    ]),
}

_MALZEMELER = ["PLA+", "Silk PLA", "PLA", "PETG", "TPU", "ABS", "ASA", "PC", "Nylon", "Wood PLA"]

_SURE_SAAT_DK = re.compile(
    r"(?:print(?:ing)?\s*time|time\s*to\s*print|print\s*duration|baskı\s*süresi)"
    r"[^0-9\n]{0,25}(\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hour|hours|saat|sa)\b"
    r"(?:\s*(?:and\s*)?(\d+)\s*(?:m|min|mins|minute|minutes|dk)\b)?",
    re.I,
)
_SURE_DK = re.compile(
    r"(?:print(?:ing)?\s*time|time\s*to\s*print|print\s*duration|baskı\s*süresi)"
    r"[^0-9\n]{0,25}(\d+)\s*(?:m|min|mins|minute|minutes|dk)\b",
    re.I,
)
_ETIKET = re.compile(r"<[^>]+>")


def temiz_metin(*parcalar: str | None) -> str:
    metin = " ".join(p for p in parcalar if p)
    return html.unescape(_ETIKET.sub(" ", metin))


def _kelime_var(metin: str, kelime: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(kelime) + r"(?![a-z0-9])", metin) is not None


def baski_suresi_dk(metin: str) -> int | None:
    """Açıklamada yazıyorsa baskı süresini dakika olarak döndürür."""
    eslesme = _SURE_SAAT_DK.search(metin)
    if eslesme:
        saat = float(eslesme.group(1).replace(",", "."))
        dakika = int(eslesme.group(2) or 0)
        return round(saat * 60) + dakika
    eslesme = _SURE_DK.search(metin)
    if eslesme:
        return int(eslesme.group(1))
    return None


def malzeme_bul(metin: str) -> str | None:
    bulunan = []
    for m in _MALZEMELER:
        if _kelime_var(metin.lower(), m.lower()) and not any(m in b for b in bulunan):
            bulunan.append(m)
    return ", ".join(bulunan[:3]) or None


_OLUMSUZ_ONCE = re.compile(r"\b(?:no|without|non|not)[\s-]+(?:\w+[\s-]+)?$")
_OLUMSUZ_SONRA = re.compile(r"^[^.\n]{0,25}?\b(?:not (?:required|needed|necessary)|optional|unnecessary)\b")


def _olumlu_kelime_var(metin: str, kelime: str) -> bool:
    """Kelime geçiyor ve yanında olumsuzluk yoksa True.

    Önce: "no AMS", "without supports". Sonra: "AMS: not required", "multicolor optional".
    """
    for m in re.finditer(r"(?<![a-z0-9])" + re.escape(kelime) + r"(?![a-z0-9])", metin):
        if _OLUMSUZ_ONCE.search(metin[max(0, m.start() - 20):m.start()]):
            continue
        if _OLUMSUZ_SONRA.search(metin[m.end():m.end() + 40]):
            continue
        return True
    return False


def gorsel_ozellikler(*parcalar: str | None) -> list[str]:
    metin = " ".join(p for p in parcalar if p).lower().replace("_", " ")
    return [
        etiket
        for etiket, (_, kelimeler) in GORSEL_OZELLIKLER.items()
        if any(_olumlu_kelime_var(metin, k) for k in kelimeler)
    ]


def gorsel_puan(ozellikler: list[str]) -> float:
    return min(1.0, sum(GORSEL_OZELLIKLER[o][0] for o in ozellikler if o in GORSEL_OZELLIKLER))


def sure_yazi(dakika: int | None) -> str:
    if dakika is None:
        return "bilinmiyor (modelin sayfasında yazmıyor)"
    saat, dk = divmod(dakika, 60)
    if saat and dk:
        return f"~{saat} sa {dk} dk"
    if saat:
        return f"~{saat} sa"
    return f"~{dk} dk"
