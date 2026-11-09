"""Baskı maliyeti, önerilen satış fiyatı ve saat başına kazanç tahmini.

Kaba bir tahmindir: filament gramı ve baskı süresi MakerWorld'deki P1S profilinden gelir,
fiyatlar config.py'deki ayarlardan. Etsy/kargo ücretleri ve işçilik dahil değildir.

Önerilen fiyat önce maliyetten (maliyet × FIYAT_CARPANI) hesaplanır. Ürünün Türkiye'deki 3D baskı
benzerlerinin fiyatları biliniyorsa (e-ticaret araması) piyasaya göre fiyat kullanılır:
ortancanın biraz altı, ama maliyetin en az PIYASA_EN_AZ_KAR_CARPANI katı.
"""
from __future__ import annotations

import statistics

from . import config, pazar


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


def piyasa_fiyati(maliyet: float, medyan: float) -> int:
    return max(_yuvarla(medyan * config.PIYASA_FIYAT_ORANI),
               _yuvarla(maliyet * config.PIYASA_EN_AZ_KAR_CARPANI), config.EN_DUSUK_FIYAT_TL)


def piyasaya_uygula(urunler: list[dict], kayitlar: dict[int, dict]) -> list[dict]:
    """Piyasa verisi (yeterli fiyatlı 3D baskı benzeri) olan ürünlerde önerilen fiyatı ve saatlik
    kazancı piyasaya göre günceller; ürüne 'piyasa' ve 'maliyet_fiyati' ekler. Güncellenenleri döndürür."""
    guncellenen = []
    for u in urunler:
        o = kayitlar.get(u.get("id"))
        if not o or u.get("cost_tl") is None or not u.get("print_time_min"):
            continue
        fiyatlar = pazar.fiyat_kumesi(o.get("results") or [])
        if len(fiyatlar) < config.PIYASA_EN_AZ_FIYATLI:
            continue
        medyan = statistics.median(fiyatlar)
        u.setdefault("maliyet_fiyati", u.get("price_tl"))
        u["price_tl"] = piyasa_fiyati(u["cost_tl"], medyan)
        u["hourly_profit_tl"] = round((u["price_tl"] - u["cost_tl"]) / (u["print_time_min"] / 60), 1)
        u["piyasa"] = {"medyan": round(medyan), "fiyatli": len(fiyatlar),
                       "satis_sonucu": int(o.get("found_count") or 0)}
        guncellenen.append(u)
    return guncellenen


def yazi(urun: dict) -> str:
    if urun.get("cost_tl") is None:
        return "hesaplanamadı (filament gramı veya baskı süresi yok)"
    d = urun.get("score_detail") or {}
    piyasa = urun.get("piyasa") or d.get("piyasa_bilgisi")
    maliyet_fiyati = urun.get("maliyet_fiyati") or d.get("maliyet_fiyati")
    fiyat = f"önerilen fiyat ~{urun['price_tl']} TL"
    if piyasa:
        fiyat += (f" (Türkiye'deki {piyasa['fiyatli']} benzerin ortancası {piyasa['medyan']} TL'ye göre; "
                  f"maliyete göre {maliyet_fiyati} TL olurdu)")
    return (f"~{urun['cost_tl']:.0f} TL maliyet ({urun.get('weight_g')} g filament) · {fiyat} · "
            f"saat başına ~{urun['hourly_profit_tl']:.0f} TL kazanç")
