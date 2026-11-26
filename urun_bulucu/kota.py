"""SerpApi aylık bütçesi: kalan arama hakkı ayın kalan günlerine bölünür.

Ücretsiz plan ayda 250 arama verir. Günlük e-ticaret araması (ürün başına 2) ve haftalık keşif
(~26 arama) birlikte harcarsa hak ay ortasında biterdi. Burada:
- Günlük arama: o gün en çok `kalan // kalan_gün` arama (ürün başına 2) yapılır.
- Keşif (ve Trendyol Lens): yalnızca sonrasında her gün için KOTA_GUNLUK_ASGARI arama kalıyorsa.
Hakkın yenilendiği gün config.SERPAPI_YENILEME_GUNU'dür.
"""
from __future__ import annotations

from datetime import date

from . import config


# SerpApi hesabının bildirdiği yenileme tarihi (pazar.kalan_hak okurken ayarlar); yoksa ayardaki gün.
YENILEME: date | None = None


def yenileme_ayarla(metin: str | None) -> None:
    global YENILEME
    try:
        YENILEME = date.fromisoformat(str(metin)[:10]) if metin else None
    except ValueError:
        YENILEME = None


def sonraki_yenileme(bugun: date, gun: int | None = None) -> date:
    if gun is None and YENILEME and YENILEME > bugun:
        return YENILEME
    gun = gun or config.SERPAPI_YENILEME_GUNU

    def ayin(yil: int, ay: int) -> date:
        for g in range(min(gun, 31), 27, -1):   # 31'i olmayan aylarda ayın son günü
            try:
                return date(yil, ay, g)
            except ValueError:
                continue
        return date(yil, ay, min(gun, 28))

    bu_ay = ayin(bugun.year, bugun.month)
    if bu_ay > bugun:
        return bu_ay
    yil, ay = (bugun.year + 1, 1) if bugun.month == 12 else (bugun.year, bugun.month + 1)
    return ayin(yil, ay)


def kalan_gun(bugun: date) -> int:
    """Bugün dahil, hak yenilenene kadar kaç gün (en az 1)."""
    return max(1, (sonraki_yenileme(bugun) - bugun).days)


def gunluk_arama(kalan: int | None, bugun: date) -> int:
    """Bugün harcanabilecek arama sayısı. Kalan bilinmiyorsa 0 (arama yapılmaz)."""
    if not kalan or kalan <= 0:
        return 0
    return kalan // kalan_gun(bugun)


def gunluk_urun(kalan: int | None, bugun: date) -> int:
    """Bugün e-ticarette aranacak ürün sayısı (ürün başına 2 arama), en çok PAZAR_GUNLUK_ADET."""
    return min(config.PAZAR_GUNLUK_ADET, gunluk_arama(kalan, bugun) // 2)


def buyuk_is_izinli(kalan: int | None, bugun: date, tahmini: int | None = None) -> bool:
    """Keşif gibi tek seferde çok arama harcayan iş yapılabilir mi: sonrasında yenilemeye kadar her gün
    için en az KOTA_GUNLUK_ASGARI arama kalmalı."""
    if kalan is None:
        return False
    tahmini = config.KESIF_TAHMINI_ARAMA if tahmini is None else tahmini
    return kalan - tahmini >= (kalan_gun(bugun) - 1) * config.KOTA_GUNLUK_ASGARI


def yazi(kalan: int | None, bugun: date) -> str:
    if kalan is None:
        return "SerpApi hakkı okunamadı"
    return (f"SerpApi: {kalan} hak, yenilemeye {kalan_gun(bugun)} gün "
            f"({sonraki_yenileme(bugun).isoformat()}); bugün en çok {gunluk_arama(kalan, bugun)} arama")
