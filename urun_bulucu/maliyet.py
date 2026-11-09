"""Baskı maliyeti, önerilen satış fiyatı ve saat başına kazanç tahmini.

Kaba bir tahmindir: filament gramı ve baskı süresi MakerWorld'deki P1S profilinden gelir,
fiyatlar config.py'deki ayarlardan. Etsy/kargo ücretleri ve işçilik dahil değildir.
"""
from __future__ import annotations

from . import config


def hesapla(gram: int | None, dakika: int | None) -> dict | None:
    """{'maliyet_tl', 'fiyat_tl', 'saatlik_kazanc_tl'} döndürür; gram veya süre yoksa None."""
    if not gram or not dakika:
        return None
    saat = dakika / 60
    filament = gram * (1 + config.FIRE_ORANI) * config.FILAMENT_TL_KG / 1000
    makine = saat * config.SAAT_MALIYETI_TL
    maliyet = filament + makine
    fiyat = max(config.EN_DUSUK_FIYAT_TL, maliyet * config.FIYAT_CARPANI)
    fiyat = _yuvarla(fiyat)
    return {
        "maliyet_tl": round(maliyet, 1),
        "fiyat_tl": fiyat,
        "saatlik_kazanc_tl": round((fiyat - maliyet) / saat, 1),
    }


def _yuvarla(tl: float) -> int:
    """Fiyatı 5 TL'nin katına yukarı yuvarlar (ör. 83 → 85)."""
    return int(-(-tl // 5) * 5)


def yazi(urun: dict) -> str:
    if urun.get("cost_tl") is None:
        return "hesaplanamadı (filament gramı veya baskı süresi yok)"
    return (f"~{urun['cost_tl']:.0f} TL maliyet ({urun.get('weight_g')} g filament) · "
            f"önerilen fiyat ~{urun['price_tl']} TL · saat başına ~{urun['hourly_profit_tl']:.0f} TL kazanç")
