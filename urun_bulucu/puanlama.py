"""İçerik puanı (0-100).

Ağırlıklar: popülerlik 30, 7 günlük artış 25, görsel çekicilik 20,
kısa baskı süresi 15, lisans uygunluğu 10. Etsy talep listesiyle eşleşen
ürünler +5 bonus alır (en fazla 100). Popülerlik ve artış, her kaynağın
(Thingiverse, MakerWorld) kendi en yükseğine göre 0-1 arasına çekilir.
"""
from __future__ import annotations

import math
from datetime import date, datetime

from . import analiz, lisans, talep
from .config import KISA_BASKI_SAAT

AGIRLIK = {"populerlik": 30, "artis": 25, "gorsel": 20, "sure": 15, "lisans": 10}
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

    # Popülerlik ve artış her kaynağın kendi içinde ölçeklenir: MakerWorld'deki sayılar
    # Thingiverse'tekilerden çok büyük olduğu için ortak ölçek bir kaynağı ezerdi.
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
        }
        puan = sum(AGIRLIK[k] * v for k, v in bilesen.items())
        etsy = talep.eslesen(u, talepler)
        if etsy:
            puan += ETSY_BONUS
        u["score"] = round(min(100.0, puan), 1)
        u["score_detail"] = {
            **{k: round(v, 3) for k, v in bilesen.items()},
            "gunluk_ilgi_artisi": round(artis_ham[u["id"]], 1),
            "artis_tipi": artis_tipi[u["id"]],
            "etsy_talep": etsy["anahtar_kelime"] if etsy else None,
        }
    return sorted(urunler, key=lambda x: x["score"], reverse=True)
