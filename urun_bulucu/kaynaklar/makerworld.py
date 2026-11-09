"""MakerWorld (https://makerworld.com) — sitenin kendi kullandığı JSON uçları.

Resmi/belgelenmiş bir API değildir; anahtar gerektirmez. robots.txt tüm siteye
izin veriyor ve kullanım şartlarında otomatik erişimi yasaklayan bir madde yok
(Kasım 2026 kontrolü). Yine de kibar olmak için istekler arasında bekleme yapılır,
istek sayısı sınırlı tutulur ve program kendini User-Agent'ta tanıtır.
Uçlar haber verilmeden değişebilir; o durumda MakerWorldHatasi fırlatılır ve
analiz yalnızca diğer kaynaklarla devam eder.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .. import analiz, config, lisans, maliyet

API = "https://makerworld.com/api/v1"
SITE = "https://makerworld.com/en/models"
KAYNAK_ID = "makerworld"
YAZICI_MODELI = "P1S"  # baskı süresi bu yazıcı için hazırlanmış profilden alınır
AMS_ETIKETI = "çok renkli (AMS)"


class MakerWorldHatasi(RuntimeError):
    pass


class MakerWorldKaynak:
    def __init__(self, client: httpx.Client | None = None, bekleme_sn: float = 1.5) -> None:
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "User-Agent": "3d-urun-bulucu/0.1 (kisisel arastirma)",
            "Accept": "application/json",
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
                time.sleep(min(float(yanit.headers.get("Retry-After", 30)), 120))
                continue
            if yanit.status_code == 403:
                raise MakerWorldHatasi("MakerWorld isteği engelledi (403, bot koruması olabilir).")
            if yanit.status_code >= 500 and deneme < 2:
                time.sleep(5)
                continue
            yanit.raise_for_status()
            try:
                return yanit.json()
            except ValueError as e:
                raise MakerWorldHatasi(f"MakerWorld beklenmeyen yanıt verdi: {yol}") from e
        raise MakerWorldHatasi(f"MakerWorld çok fazla istek uyarısı verdi: {yol}")

    # --- uçlar ---
    def ara(self, terim: str, adet: int = 30, gun: int | None = 30) -> list[dict]:
        params: dict[str, Any] = {"keyword": terim, "limit": adet, "offset": 0, "orderBy": "downloadCount"}
        if gun:
            params["designCreateSince"] = gun  # yalnızca son N günde yüklenenler
        veri = self._get("/search-service/select/design2", params)
        if not isinstance(veri, dict) or "hits" not in veri:
            raise MakerWorldHatasi("MakerWorld arama yanıtının biçimi değişmiş.")
        return list(veri.get("hits") or [])

    def trend(self, adet: int = 30) -> list[dict]:
        """MakerWorld ana sayfasındaki "Trending" listesi (sitenin kendi sıralaması)."""
        veri = self._get("/search-service/select/design/nav", {"navKey": "Trending", "offset": 0, "limit": adet})
        if not isinstance(veri, dict) or "hits" not in veri:
            raise MakerWorldHatasi("MakerWorld trend yanıtının biçimi değişmiş.")
        return list(veri.get("hits") or [])

    def detay(self, design_id: int | str) -> dict:
        return self._get(f"/design-service/design/{design_id}")

    def tasarimci_modelleri(self, uid: int | str, adet: int = 5) -> list[dict]:
        """Bir tasarımcının yayınladığı modeller, en yenisi önce."""
        veri = self._get(f"/design-service/published/{uid}/design", {"limit": adet, "offset": 0})
        if not isinstance(veri, dict) or "hits" not in veri:
            raise MakerWorldHatasi("MakerWorld tasarımcı yanıtının biçimi değişmiş.")
        return [h for h in veri.get("hits") or [] if h.get("id") and not _atlanacak(h)]

    # --- toplama ---
    def topla(
        self,
        kategoriler: dict[str, list[str]],
        arama_adet: int = 30,
        detay_limiti: int = 40,
        gun: int | None = 30,
        trend_adet: int = 0,
    ) -> list[dict]:
        # 1) Trend listesi: sitenin kendi sıralaması; kelime aramasının kaçırdıklarını yakalar.
        trend_sira: dict[str, int] = {}
        trend_secilen: list[tuple[str, dict]] = []
        if trend_adet:
            for sira, hit in enumerate(self.trend(max(30, trend_adet * 2)), start=1):
                if not hit.get("id") or _atlanacak(hit):
                    continue
                trend_sira[str(hit["id"])] = sira
                if len(trend_secilen) < trend_adet:
                    trend_secilen.append((kategori_bul(hit, kategoriler), hit))

        # 2) Kategori kelimeleriyle arama.
        secilen_idler = {str(h["id"]) for _, h in trend_secilen}
        adaylar: dict[str, tuple[str, dict]] = {}
        for kategori, terimler in kategoriler.items():
            for terim in terimler:
                for hit in self.ara(terim, arama_adet, gun):
                    if not hit.get("id") or _atlanacak(hit) or str(hit["id"]) in secilen_idler:
                        continue
                    adaylar.setdefault(str(hit["id"]), (kategori, hit))

        sirali = sorted(adaylar.values(), key=lambda x: _sayi(x[1].get("downloadCount")), reverse=True)
        sirali = trend_secilen + _kategoriye_dengeli(sirali, detay_limiti)

        urunler = []
        for kategori, hit in sirali:
            try:
                tasarim = self.detay(hit["id"])
            except httpx.HTTPStatusError:
                continue
            if not isinstance(tasarim, dict) or not tasarim.get("id") or _atlanacak(tasarim):
                continue
            urunler.append(urune_cevir(tasarim, kategori, trend_sira.get(str(tasarim["id"]))))
        return urunler


TREND_KATEGORI = "Trend / sezonluk"


def kategori_bul(hit: dict, kategoriler: dict[str, list[str]]) -> str:
    """Trend listesinden gelen modeli başlık ve etiketlerine göre bizim kategorilerimize yerleştirir."""
    metin = " ".join([hit.get("title") or "", *[str(t) for t in hit.get("tags") or []]]).lower()
    for kategori, terimler in kategoriler.items():
        if any(terim.lower() in metin for terim in terimler):
            return kategori
    return TREND_KATEGORI


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


def _atlanacak(d: dict) -> bool:
    """NSFW, ücretli veya basılamayan modeller elenir."""
    if d.get("nsfw"):
        return True
    if (d.get("paidSetting") or {}).get("isPaid"):
        return True
    basilabilir = d.get("isPrintable", d.get("is_printable", True))
    return basilabilir is False


def _yazici(profil: dict) -> str | None:
    uyum = ((profil.get("extention") or {}).get("modelInfo") or {}).get("compatibility") or {}
    return uyum.get("devProductName")


def profil_sec(tasarim: dict) -> dict | None:
    """Baskı süresi için profil: P1S için hazırlanmış varsayılan > herhangi bir P1S > varsayılan > ilk."""
    profiller = [p for p in tasarim.get("instances") or [] if isinstance(p, dict)]
    if not profiller:
        return None
    varsayilan_id = tasarim.get("defaultInstanceId")

    def oncelik(p: dict) -> tuple[int, int]:
        varsayilan = p.get("id") == varsayilan_id or bool(p.get("isDefault"))
        return (0 if _yazici(p) == YAZICI_MODELI else 1, 0 if varsayilan else 1)

    return min(profiller, key=oncelik)


def _malzeme(profil: dict | None) -> str | None:
    turler: list[str] = []
    for f in (profil or {}).get("instanceFilaments") or []:
        tur = (f.get("type") or "").strip()
        if tur and tur not in turler:
            turler.append(tur)
    return ", ".join(turler[:3]) or None


def filament_listesi(profil: dict | None) -> list[dict]:
    """Profildeki filamentler: [{"type": "PLA", "color": "#5E43B7", "grams": 21.0}]"""
    sonuc = []
    for f in (profil or {}).get("instanceFilaments") or []:
        try:
            gram = round(float(f.get("usedG") or 0), 1)
        except (TypeError, ValueError):
            gram = 0.0
        sonuc.append({"type": (f.get("type") or "?").strip(), "color": (f.get("color") or "").upper() or None,
                      "grams": gram})
    return sonuc


def urune_cevir(tasarim: dict, kategori: str, trend_sirasi: int | None = None) -> dict:
    etiketler = [str(t) for t in tasarim.get("tags") or [] if t][:30]
    metin = analiz.temiz_metin(tasarim.get("summary"))
    profil = profil_sec(tasarim)

    sure_sn = _sayi((profil or {}).get("prediction"))
    sure_dk = round(sure_sn / 60) if sure_sn else analiz.baski_suresi_dk(metin)

    ozellikler = analiz.gorsel_ozellikler(tasarim.get("title"), " ".join(etiketler), metin)
    if profil is not None:
        # Çok renklilik metinden tahmin edilmek yerine profilin kendisinden okunur.
        cok_renk = _sayi(profil.get("materialColorCnt")) >= 2 or bool(profil.get("needAms"))
        ozellikler = [o for o in ozellikler if o != AMS_ETIKETI]
        if cok_renk:
            ozellikler.append(AMS_ETIKETI)

    lisans_metni = tasarim.get("license") or None
    tid = tasarim["id"]
    gram = _sayi((profil or {}).get("weight")) or None
    tahmin = maliyet.hesapla(gram, sure_dk) or {}
    return {
        "source_id": KAYNAK_ID,
        "external_id": str(tid),
        "name": (tasarim.get("title") or "").strip(),
        "url": f"{SITE}/{tid}",
        "category": kategori,
        "creator": (tasarim.get("designCreator") or {}).get("name"),
        "downloads": _sayi(tasarim.get("downloadCount")),
        "likes": _sayi(tasarim.get("likeCount")),
        "makes": _sayi(tasarim.get("printCount")),
        "views": _sayi(tasarim.get("readCount")),
        "published_at": tasarim.get("createTime"),
        "license": lisans_metni,
        "license_flag": (lisans.TICARI_SERBEST if config.MAKERWORLD_HEPSI_SATILABILIR
                         else lisans.siniflandir(lisans_metni)),
        "print_time_min": sure_dk,
        "material": _malzeme(profil) or analiz.malzeme_bul(metin),
        "image_url": tasarim.get("coverUrl") or tasarim.get("cover"),
        "tags": etiketler,
        "features": ozellikler,
        "weight_g": gram,
        "color_count": _sayi((profil or {}).get("materialColorCnt")) or None,
        "cost_tl": tahmin.get("maliyet_tl"),
        "price_tl": tahmin.get("fiyat_tl"),
        "hourly_profit_tl": tahmin.get("saatlik_kazanc_tl"),
        "trend_rank": trend_sirasi,
        "creator_uid": _sayi((tasarim.get("designCreator") or {}).get("uid")) or None,
        "creator_handle": (tasarim.get("designCreator") or {}).get("handle") or None,
        "filaments": filament_listesi(profil),
    }
