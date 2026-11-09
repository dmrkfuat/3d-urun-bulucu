"""İçerik puanı (0-100).

Ağırlıklar: popülerlik 25, 7 günlük artış 25, satış potansiyeli 20, görsel çekicilik 15,
kısa baskı süresi 10, lisans uygunluğu 5. Etsy talep listesiyle eşleşen ürünler ve MakerWorld
trend listesindekiler +5, sezon ürünleri +5 bonus alır; Türkiye piyasa verisi olanlar -3..+5
(piyasa bonusu). En fazla 100. Popülerlik ve artış, her kaynağın
kendi en yükseğine göre 0-1 arasına çekilir (ileride başka kaynak eklenirse diye).
"""
from __future__ import annotations

import math
from datetime import date, datetime

from . import analiz, config, lisans, sezon, talep
from .config import KISA_BASKI_SAAT, TREND_BONUS

AGIRLIK = {"populerlik": 25, "artis": 25, "satis": 20, "gorsel": 15, "sure": 10, "lisans": 5}
ETSY_BONUS = 5
LISANS_PUANI = {lisans.TICARI_SERBEST: 1.0, lisans.NC_SADECE_ICERIK: 0.8, lisans.KONTROL_ET: 0.4}


def sure_puani(dakika: int | None) -> float:
    if dakika is None:
        return 0.5  # bilinmiyor: nötr
    if dakika <= 120:
        return 1.0
    if dakika <= 360:
        return 0.85
    if dakika <= KISA_BASKI_SAAT * 60:
        return 0.7
    return 0.15  # tek seferde bitmeyecek kadar uzun


def fiyat_bandi_puani(fiyat: float) -> float:
    """Alıcının kolay karar verdiği fiyat aralığı daha iyi: ≤300 TL en iyi, 1000 TL üstü zor satar."""
    if fiyat <= 300:
        return 1.0
    if fiyat <= 600:
        return 0.8
    if fiyat <= 1000:
        return 0.5
    return 0.2


def satis_puani(u: dict) -> float:
    """Satış potansiyeli (0-1): saat başına kazanç %40, parça başına kâr %30, fiyat aralığı %30.
    Maliyet bilinmiyorsa nötr (0.5)."""
    if u.get("cost_tl") is None or u.get("price_tl") is None or u.get("hourly_profit_tl") is None:
        return 0.5
    saatlik = min(1.0, max(0.0, u["hourly_profit_tl"]) / config.SATIS_TAM_SAATLIK_TL)
    parca = min(1.0, max(0.0, u["price_tl"] - u["cost_tl"]) / config.SATIS_TAM_PARCA_KAR_TL)
    return 0.4 * saatlik + 0.3 * parca + 0.3 * fiyat_bandi_puani(u["price_tl"])


def piyasa_bonusu(u: dict) -> tuple[int, str | None]:
    """Türkiye'deki 3D baskı benzerlerinin fiyatına göre bonus (piyasa verisi olan ürünler):
    piyasa fiyatı maliyeti iyi karşılıyorsa +, karşılamıyorsa -; pazar çok kalabalıksa -2."""
    p = u.get("piyasa")
    if not p or not u.get("cost_tl"):
        return 0, None
    oran = p["medyan"] / u["cost_tl"]
    if oran >= 5:
        bonus = 5
    elif oran >= 3:
        bonus = 3
    elif oran >= 1.5:
        bonus = 0
    else:
        bonus = -3
    kalabalik = p.get("satis_sonucu", 0) >= 12
    if kalabalik:
        bonus -= 2
    metin = (f"Türkiye'de 3D baskı benzerleri ortanca {p['medyan']} TL (maliyetin {oran:.0f} katı)"
             + ("; pazar kalabalık" if kalabalik else ""))
    return bonus, metin


def fiyat_ayrintisi(u: dict) -> dict:
    """score_detail'e yazılan fiyat bilgisi (panel ve rapor için)."""
    return {"fiyat_kaynagi": "piyasa" if u.get("piyasa") else "maliyet",
            "maliyet_fiyati": u.get("maliyet_fiyati"), "piyasa_bilgisi": u.get("piyasa")}


def _gun_farki(baslangic: str | None, bugun: date) -> int:
    if not baslangic:
        return 365
    try:
        d = datetime.fromisoformat(baslangic.replace("Z", "+00:00")).date()
    except ValueError:
        return 365
    return max(1, (bugun - d).days)


def _ilgi(downloads: int, likes: int) -> int:
    return int(downloads or 0) + 3 * int(likes or 0)


def puanla(urunler: list[dict], onceki: dict[int, dict], bugun: date,
           talepler: list[dict] | None = None) -> list[dict]:
    """Her ürüne score ve score_detail ekler; puana göre sıralı döndürür."""
    if not urunler:
        return []
    talepler = talepler or []
    aktif_sezonlar = sezon.aktif_sezonlar(bugun)

    pop_ham, artis_ham, artis_tipi = {}, {}, {}
    for u in urunler:
        pop_ham[u["id"]] = math.log1p(u["likes"] * 3 + u["downloads"] + u.get("makes", 0) * 10)
        onc = onceki.get(u["id"])
        gun = _gun_farki(onc["snap_date"], bugun) if onc else 0
        if onc and gun >= 3:
            fark = _ilgi(u["downloads"], u["likes"]) - _ilgi(onc["downloads"], onc["likes"])
            artis_ham[u["id"]] = max(0.0, fark / gun)
            artis_tipi[u["id"]] = f"son {gun} gün"
        else:
            gun = _gun_farki(u.get("published_at"), bugun)
            artis_ham[u["id"]] = _ilgi(u["downloads"], u["likes"]) / gun
            artis_tipi[u["id"]] = "yayından beri günlük ortalama"

    # Popülerlik ve artış her kaynağın kendi içinde ölçeklenir: sitelerin sayı büyüklükleri
    # çok farklı olduğundan ortak ölçek bir kaynağı ezerdi.
    pop_max: dict[str, float] = {}
    artis_max: dict[str, float] = {}
    for u in urunler:
        k = u.get("source_id")
        pop_max[k] = max(pop_max.get(k, 0.0), pop_ham[u["id"]])
        artis_max[k] = max(artis_max.get(k, 0.0), math.log1p(artis_ham[u["id"]]))

    for u in urunler:
        k = u.get("source_id")
        bilesen = {
            "populerlik": pop_ham[u["id"]] / (pop_max[k] or 1),
            "artis": math.log1p(artis_ham[u["id"]]) / (artis_max[k] or 1),
            "gorsel": analiz.gorsel_puan(u.get("features") or []),
            "sure": sure_puani(u.get("print_time_min")),
            "lisans": LISANS_PUANI.get(u.get("license_flag"), 0.4),
            "satis": satis_puani(u),
        }
        puan = sum(AGIRLIK[k] * v for k, v in bilesen.items())
        etsy = talep.eslesen(u, talepler)
        if etsy:
            puan += ETSY_BONUS
        if u.get("trend_rank"):
            puan += TREND_BONUS
        sezon_eslesme = sezon.eslesen(u, aktif_sezonlar)
        if sezon_eslesme:
            puan += sezon.SEZON_BONUS
        p_bonus, p_metin = piyasa_bonusu(u)
        puan += p_bonus
        u["score"] = round(max(0.0, min(100.0, puan)), 1)
        u["score_detail"] = {
            **{k: round(v, 3) for k, v in bilesen.items()},
            "gunluk_ilgi_artisi": round(artis_ham[u["id"]], 1),
            "artis_tipi": artis_tipi[u["id"]],
            "etsy_talep": etsy["anahtar_kelime"] if etsy else None,
            "trend_sirasi": u.get("trend_rank"),
            "sezon": sezon.yazi(*sezon_eslesme) if sezon_eslesme else None,
            "piyasa": p_metin,
            "piyasa_bonusu": p_bonus,
            **fiyat_ayrintisi(u),
        }
    return sorted(urunler, key=lambda x: x["score"], reverse=True)
