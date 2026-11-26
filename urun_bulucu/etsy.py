"""Etsy talebi (resmi Etsy Open API v3): ürünün Etsy'deki benzerleri ne kadar favorileniyor?

ETSY_API_KEY varsa (biçim: "keystring:shared_secret"; developers.etsy.com > Your Apps) günlük analizde
her ürün için İngilizce adıyla aktif ilanlar aranır; ilk ETSY_SONUC_ADET ilanın favori sayıları
toplanır ve ETSY_BONUS_ESIKLERI'ne göre bonus verilir. Elle tutulan Etsy talep listesi (talep.py)
ile çakışırsa büyük olan bonus geçerlidir. Anahtar yoksa hiçbir şey yapılmaz.
"""
from __future__ import annotations

import re
import time

import httpx

from . import config, pazar


class EtsyHatasi(RuntimeError):
    pass


def sorgu(ad: str | None, en_fazla: int = 4) -> str | None:
    """Model adından Etsy araması: gürültü, sayı ve tamamı büyük harf (marka/tasarımcı) kelimeler atılır."""
    kelimeler = []
    for k in re.findall(r"[A-Za-z]+", ad or ""):
        kucuk = k.lower()
        if len(k) < 3 or kucuk in pazar.GURULTU or (k.isupper() and len(k) > 3) or kucuk in kelimeler:
            continue
        kelimeler.append(kucuk)
    return " ".join(kelimeler[:en_fazla]) or None


def ara(api_key: str, metin: str, client: httpx.Client | None = None) -> list[dict]:
    """[{'title', 'favori', 'url'}]: en alakalı aktif ilanlar."""
    client = client or httpx.Client(timeout=30)
    yanit = client.get(f"{config.ETSY_API}/listings/active", headers={"x-api-key": api_key},
                       params={"keywords": metin, "limit": config.ETSY_SONUC_ADET, "sort_on": "score"})
    if yanit.status_code == 429:
        raise EtsyHatasi("Etsy istek sınırı aşıldı")
    if yanit.status_code != 200:
        try:
            mesaj = yanit.json().get("error") or yanit.status_code
        except ValueError:
            mesaj = yanit.status_code
        raise EtsyHatasi(f"Etsy {mesaj}")
    return [{"title": x.get("title"), "favori": int(x.get("num_favorers") or 0), "url": x.get("url")}
            for x in yanit.json().get("results") or []]


def bonus(favori: int | None) -> int:
    for esik, b in config.ETSY_BONUS_ESIKLERI:
        if (favori or 0) >= esik:
            return b
    return 0


def isle(urunler: list[dict], api_key: str, client: httpx.Client | None = None,
         bekle=time.sleep) -> int:
    """Her ürüne u['etsy_favori'] ve u['etsy_sorgu'] ekler; sorulan ürün sayısı. Hata olursa durur."""
    if not api_key:
        return 0
    client = client or httpx.Client(timeout=30)
    onbellek: dict[str, int] = {}
    adet = 0
    for u in urunler[: config.ETSY_URUN_SINIRI]:
        q = sorgu(u.get("name"))
        if not q:
            continue
        if q not in onbellek:
            try:
                onbellek[q] = sum(x["favori"] for x in ara(api_key, q, client))
            except (EtsyHatasi, httpx.HTTPError, ValueError) as e:
                print(f"UYARI: Etsy araması durdu: {str(e)[:150]}")
                break
            adet += 1
            bekle(0.2)   # Etsy: saniyede en çok 10 istek
        u["etsy_favori"], u["etsy_sorgu"] = onbellek[q], q
    return adet
