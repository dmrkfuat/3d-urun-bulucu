"""Thingiverse resmi REST API'si (https://api.thingiverse.com).

Uygulama anahtarı (App Token) ile çalışır. İstekler arasında bekleme yapılır.
"""
from __future__ import annotations

import time
from typing import Any, Iterable
from urllib.parse import quote

import httpx

from .. import analiz, lisans

API = "https://api.thingiverse.com"
KAYNAK_ID = "thingiverse"


class ThingiverseHatasi(RuntimeError):
    pass


class ThingiverseKaynak:
    def __init__(
        self,
        token: str,
        client: httpx.Client | None = None,
        bekleme_sn: float = 1.0,
    ) -> None:
        if not token:
            raise ThingiverseHatasi("THINGIVERSE_TOKEN boş. README'deki 'Thingiverse anahtarı' adımına bakın.")
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "3d-urun-bulucu/0.1 (kisisel arastirma)",
        }
        self._bekleme = bekleme_sn
        self.istek_sayisi = 0

    # --- düşük seviye ---
    def _get(self, yol: str, params: dict[str, Any] | None = None) -> Any:
        for deneme in range(3):
            if self.istek_sayisi:
                time.sleep(self._bekleme)
            self.istek_sayisi += 1
            yanit = self._client.get(f"{API}{yol}", params=params, headers=self._headers)
            if yanit.status_code == 429:
                bekle = float(yanit.headers.get("Retry-After", 30))
                time.sleep(min(bekle, 120))
                continue
            if yanit.status_code == 401:
                raise ThingiverseHatasi("Thingiverse anahtarı geçersiz veya süresi dolmuş (401).")
            if yanit.status_code >= 500 and deneme < 2:
                time.sleep(5)
                continue
            yanit.raise_for_status()
            return yanit.json()
        raise ThingiverseHatasi(f"Thingiverse çok fazla istek uyarısı verdi: {yol}")

    # --- API çağrıları ---
    def ara(self, terim: str, adet: int = 30, donem: str | None = None) -> list[dict]:
        params = {"type": "things", "sort": "popular", "per_page": adet, "page": 1}
        if donem:
            params["posted_after"] = donem  # ör. "now-30d": yalnızca son 30 günde yüklenenler
        veri = self._get(f"/search/{quote(terim)}", params)
        if isinstance(veri, dict):
            return list(veri.get("hits") or [])
        return list(veri or [])

    def detay(self, thing_id: int | str) -> dict:
        return self._get(f"/things/{thing_id}")

    # --- toplama ---
    def topla(
        self,
        kategoriler: dict[str, list[str]],
        arama_adet: int = 30,
        detay_limiti: int = 80,
        donem: str | None = None,
    ) -> list[dict]:
        adaylar: dict[str, tuple[str, dict]] = {}
        for kategori, terimler in kategoriler.items():
            for terim in terimler:
                for hit in self.ara(terim, arama_adet, donem):
                    if hit.get("is_nsfw") or not hit.get("id"):
                        continue
                    adaylar.setdefault(str(hit["id"]), (kategori, hit))

        # En çok beğenilenlerin detayını çek (istek sayısını sınırlı tutmak için).
        sirali = sorted(adaylar.values(), key=lambda x: _sayi(x[1].get("like_count")), reverse=True)
        sirali = _kategoriye_dengeli(sirali, detay_limiti)

        urunler = []
        for kategori, hit in sirali:
            try:
                thing = self.detay(hit["id"])
            except httpx.HTTPStatusError:
                continue
            if thing.get("is_nsfw"):
                continue
            urunler.append(urune_cevir(thing, kategori))
        return urunler


def _kategoriye_dengeli(sirali: list[tuple[str, dict]], limit: int) -> list[tuple[str, dict]]:
    """Her kategoriden sırayla alarak limit kadar aday seçer."""
    gruplar: dict[str, list[tuple[str, dict]]] = {}
    for oge in sirali:
        gruplar.setdefault(oge[0], []).append(oge)
    secilen: list[tuple[str, dict]] = []
    while len(secilen) < limit and any(gruplar.values()):
        for grup in gruplar.values():
            if grup and len(secilen) < limit:
                secilen.append(grup.pop(0))
    return secilen


def _sayi(deger: Any) -> int:
    try:
        return int(deger or 0)
    except (TypeError, ValueError):
        return 0


def _etiketler(thing: dict) -> list[str]:
    ham: Iterable = thing.get("tags") or []
    if not isinstance(ham, list):
        return []
    return [t.get("name", "") if isinstance(t, dict) else str(t) for t in ham if t][:30]


def _gorsel(thing: dict) -> str | None:
    img = thing.get("default_image") or {}
    if isinstance(img, dict):
        for boyut in img.get("sizes") or []:
            if boyut.get("type") == "display" and boyut.get("size") == "large":
                return boyut.get("url")
        if img.get("url"):
            return img["url"]
    return thing.get("preview_image") or thing.get("thumbnail")


def urune_cevir(thing: dict, kategori: str) -> dict:
    metin = analiz.temiz_metin(
        thing.get("description"), thing.get("instructions"), thing.get("details")
    )
    etiketler = _etiketler(thing)
    lisans_metni = thing.get("license") or None
    ozellikler = analiz.gorsel_ozellikler(thing.get("name"), " ".join(etiketler), metin)
    return {
        "source_id": KAYNAK_ID,
        "external_id": str(thing["id"]),
        "name": (thing.get("name") or "").strip(),
        "url": thing.get("public_url") or f"https://www.thingiverse.com/thing:{thing['id']}",
        "category": kategori,
        "creator": (thing.get("creator") or {}).get("name"),
        "downloads": _sayi(thing.get("download_count")),
        "likes": _sayi(thing.get("like_count")),
        "makes": _sayi(thing.get("make_count")),
        "views": _sayi(thing.get("view_count")),
        "published_at": thing.get("added"),
        "license": lisans_metni,
        "license_flag": lisans.siniflandir(lisans_metni),
        "print_time_min": analiz.baski_suresi_dk(metin),
        "material": analiz.malzeme_bul(metin),
        "image_url": _gorsel(thing),
        "tags": etiketler,
        "features": ozellikler,
    }
