"""E-ticaret araştırması: bu modelin 3D BASKI benzerleri Türkiye'de satılıyor mu, kaça?

Karşılaştırma birebir olsun diye yalnızca 3D baskı ürünler sayılır (fabrika üretimi oyuncaklar,
dijital model dosyaları elenir; bkz. uc_d_mi).

Pazar yerleri otomatik aramaya kapalıdır (Trendyol robots.txt aramayı yasaklıyor, Hepsiburada/n11
otomatik istekleri engelliyor). Bu yüzden siteler doğrudan taranmaz; Google SerpApi üzerinden aranır:

1) Google Lens: kapak görseliyle (country=tr) — yalnızca PAZAR_SITELERI'ndeki 3D baskı ürünler.
2) Google Alışveriş (gl=tr): "<Türkçe ad> 3d baskı" metniyle — pazar yerleri ve (PAZAR_BAGIMSIZ_MAGAZALAR
   açıksa) 3D baskı satan bağımsız Türk mağazaları; fiyat hep var.

SerpApi ücretsiz planı ayda 250 arama verir; ürün başına 2 arama yapıldığından günde en fazla
PAZAR_GUNLUK_ADET ürüne bakılır ve aynı ürün PAZAR_YENILEME_GUN gün içinde tekrar aranmaz.
SERPAPI_KEY yoksa hiçbir şey yapılmaz. Sonuçlar "benzer ürün" olarak okunmalıdır.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from . import config

API = "https://serpapi.com/search.json"


class PazarHatasi(RuntimeError):
    pass


# ---------------------------------------------------------------- site süzgeci
def guvenli_link(link: str | None) -> str | None:
    """Yalnızca https bağlantıları kabul edilir (javascript:, data: vb. elenir)."""
    if not link:
        return None
    u = urlparse(str(link).strip())
    if u.scheme != "https" or not u.hostname:
        return None
    return u.geturl().replace(" ", "%20")  # Google bağlantılarındaki boşluklar Markdown bağlantısını bozuyordu


def _alan_eslesir(host: str, alan: str) -> bool:
    return host == alan or host.endswith("." + alan)


def site_bul(link: str | None, kaynak: str | None) -> str | None:
    """Sonucun PAZAR_SITELERI'nden hangisine ait olduğu; değilse None (sonuç elenir).

    Öncelik bağlantının alan adıdır (tam alan adı veya alt alanı; "trendyol.evil.com" eşleşmez).
    Bağlantı Google Alışveriş ürün sayfasına gidiyorsa satıcı adına bakılır.
    """
    host = (urlparse(link or "").hostname or "").lower()
    for alan, ad in config.PAZAR_SITELERI.items():
        if host and _alan_eslesir(host, alan):
            return ad
    google = bool(host) and (_alan_eslesir(host, "google.com") or _alan_eslesir(host, "google.com.tr"))
    if google:
        kaynak = (kaynak or "").strip().lower()
        for alan, ad in config.PAZAR_SITELERI.items():
            if kaynak == ad.lower() or kaynak == alan or kaynak.startswith(alan + " ") or kaynak == alan.split(".")[0]:
                return ad
    return None


def _fiyat_metinden(metin: str | None) -> float | None:
    """'₺1.200,50' / '₺599*' → 1200.5 / 599.0"""
    if not metin:
        return None
    sayi = re.sub(r"[^0-9.,]", "", str(metin))
    if not sayi:
        return None
    if "," in sayi:
        sayi = sayi.replace(".", "").replace(",", ".")
    elif sayi.count(".") >= 1 and len(sayi.split(".")[-1]) == 3:
        sayi = sayi.replace(".", "")  # 1.200 → binlik ayırıcı
    try:
        return float(sayi)
    except ValueError:
        return None


def _tl_mi(para: str | None) -> bool:
    return (para or "").strip().upper() in ("₺", "TL", "TRY")


# ---------------------------------------------------------------- Türkçe arama metni
# Çok kelimeli ifadeler tek kelimelerden önce çevrilir.
IFADELER = {
    "cable car": "teleferik", "phone stand": "telefon standı", "phone holder": "telefon tutucu",
    "pen holder": "kalemlik", "pencil holder": "kalemlik", "desk organizer": "masa düzenleyici",
    "cable organizer": "kablo düzenleyici", "key holder": "anahtarlık", "tealight holder": "mumluk",
    "candle holder": "mumluk", "christmas tree": "yılbaşı ağacı", "fidget toy": "fidget oyuncak",
    "stress toy": "stres oyuncağı", "spider man": "örümcek adam", "spiderman": "örümcek adam",
    "headphone stand": "kulaklık standı", "watch stand": "saat standı", "plant pot": "saksı",
}
CEVIRI = {
    "magnetic": "manyetik", "swing": "salıncak", "diorama": "diorama", "gnome": "cüce", "gnomo": "cüce",
    "nordic": "nordik", "knitted": "örgü", "sweater": "kazak", "tiny": "minik", "cute": "sevimli",
    "fidget": "fidget", "ring": "yüzük", "spinner": "spinner", "toy": "oyuncak", "toys": "oyuncak",
    "dragon": "ejderha", "flexi": "eklemli", "articulated": "eklemli", "snake": "yılan", "cat": "kedi",
    "dog": "köpek", "octopus": "ahtapot", "gecko": "kertenkele", "lizard": "kertenkele", "axolotl": "aksolotl",
    "turtle": "kaplumbağa", "shark": "köpekbalığı", "dinosaur": "dinozor", "dino": "dinozor", "fish": "balık",
    "bird": "kuş", "owl": "baykuş", "bunny": "tavşan", "rabbit": "tavşan", "bear": "ayı", "frog": "kurbağa",
    "butterfly": "kelebek", "skeleton": "iskelet", "doll": "bebek", "wand": "asa", "magic": "sihirli",
    "vase": "vazo", "planter": "saksı", "pot": "saksı", "flower": "çiçek", "rose": "gül", "lamp": "lamba",
    "light": "lamba", "candle": "mum", "tealight": "tealight mumluk", "holder": "tutucu", "stand": "stand",
    "pen": "kalem", "pencil": "kalem", "organizer": "düzenleyici", "desk": "masa", "box": "kutu",
    "tray": "tepsi", "coaster": "bardak altlığı", "keychain": "anahtarlık", "phone": "telefon",
    "cable": "kablo", "charger": "şarj", "headphone": "kulaklık", "watch": "saat", "clock": "saat",
    "christmas": "yılbaşı", "xmas": "yılbaşı", "ornament": "süs", "tree": "ağaç", "santa": "noel baba",
    "snowman": "kardan adam", "train": "tren", "car": "araba", "house": "ev", "village": "köy",
    "halloween": "cadılar bayramı", "pumpkin": "balkabağı", "heart": "kalp", "gift": "hediye",
    "puzzle": "puzzle", "cube": "küp", "embosser": "kabartma", "stamp": "mühür", "frame": "çerçeve",
    "hook": "askı", "hanger": "askı", "wall": "duvar", "shelf": "raf", "bookmark": "kitap ayracı",
    "mask": "maske", "sword": "kılıç", "gun": "tabanca", "launcher": "fırlatıcı", "spider": "örümcek",
}
GURULTU = {
    "print", "printed", "printing", "in", "place", "pip", "no", "ams", "tpu", "the", "a", "an", "for", "with",
    "and", "of", "to", "3d", "mini", "v2", "v3", "version", "remix", "easy", "super", "ultra", "satisfying",
    "free", "sell", "support", "supports", "without", "multi", "color", "colour", "plate", "set", "kit",
}


def sorgu_olustur(ad: str | None, en_fazla_kelime: int = 3) -> str | None:
    """Model adından Türkçe arama metni: bilinen kelimeler çevrilir, gürültü atılır."""
    metin = " ".join(re.findall(r"[a-zçğıöşü]+", (ad or "").lower()))
    sonuc: list[str] = []
    for ifade, tr in IFADELER.items():
        if re.search(rf"\b{ifade}\b", metin):
            sonuc.append(tr)
            metin = re.sub(rf"\b{ifade}\b", " ", metin)
    kelimeler = metin.split()
    for k in kelimeler:
        if k in GURULTU or len(k) < 3:
            continue
        tr = CEVIRI.get(k) or CEVIRI.get(k.rstrip("s"))
        if tr and tr not in sonuc:
            sonuc.append(tr)
    if not sonuc:  # hiç bilinen kelime yoksa ilk anlamlı İngilizce kelimeler
        sonuc = [k for k in kelimeler if k not in GURULTU and len(k) >= 3][:2]
    return " ".join(sonuc[:en_fazla_kelime]) or None


# ---------------------------------------------------------------- SerpApi
def _istek(api_key: str, params: dict, client: httpx.Client | None) -> dict:
    client = client or httpx.Client(timeout=90)
    yanit = client.get(API, params={**params, "api_key": api_key})
    try:
        veri = yanit.json()
    except ValueError as e:
        raise PazarHatasi(f"SerpApi beklenmeyen yanıt verdi ({yanit.status_code}).") from e
    if yanit.status_code != 200 or veri.get("error"):
        hata = veri.get("error") or yanit.status_code
        if "hasn't returned any results" in str(hata):
            return {}
        raise PazarHatasi(f"SerpApi: {hata}")
    return veri


def lens_ara(api_key: str, gorsel_url: str, client: httpx.Client | None = None) -> dict:
    return _istek(api_key, {"engine": "google_lens", "url": gorsel_url, "hl": "tr", "country": "tr"}, client)


def alisveris_ara(api_key: str, sorgu: str, client: httpx.Client | None = None) -> dict:
    return _istek(api_key, {"engine": "google_shopping", "q": sorgu, "gl": "tr", "hl": "tr"}, client)


# ---------------------------------------------------------------- 3D baskı şartı
# Karşılaştırma birebir olsun diye yalnızca 3D baskı ürünler sayılır: başlıkta veya satıcı adında
# 3D baskı işareti olmalı; dijital model dosyaları (STL/3MF, "baskı modeli") fiziksel ürün değildir.
UC_D = re.compile(
    r"3\s?d\s?(?:bask[ıi]|print|printed|printing|yaz[ıi]c[ıi])|3\s?boyutlu|üç\s?boyutlu|3d-printed"
    r"|\bpla\b|\bpetg\b|filament",
    re.I,
)
UC_D_SATICI = re.compile(r"3\s?d|bask[ıi]|print", re.I)
DIJITAL = re.compile(r"bask[ıi]\s?modeli|\bstl\b|\b3mf\b|dosyas[ıi]|dijital|digital|download", re.I)


def uc_d_mi(baslik: str | None, satici: str | None = None) -> bool:
    baslik = baslik or ""
    if DIJITAL.search(baslik):
        return False
    return bool(UC_D.search(baslik) or (satici and UC_D_SATICI.search(satici)))


# ---------------------------------------------------------------- ayıklama
def lens_sonuclari(yanit: dict) -> list[dict]:
    """Görsel eşleşmeler dünya çapındadır: yalnızca PAZAR_SITELERI'ndeki 3D baskı ürünler tutulur."""
    sonuc = []
    for x in (yanit.get("visual_matches") or []) + (yanit.get("exact_matches") or []):
        site = site_bul(x.get("link"), x.get("source"))
        if not site or not uc_d_mi(x.get("title")):
            continue
        f = x.get("price") if isinstance(x.get("price"), dict) else {}
        fiyat = f.get("extracted_value")
        sonuc.append({"site": site, "pazar_yeri": True, "title": x.get("title"),
                      "link": guvenli_link(x.get("link")),
                      "price": float(fiyat) if fiyat is not None and _tl_mi(f.get("currency")) else None,
                      "thumbnail": x.get("thumbnail"), "kaynak": "görsel"})
    return sonuc


def alisveris_sonuclari(yanit: dict) -> list[dict]:
    """Google Alışveriş (Türkiye, TL): 3D baskı ürünler; pazar yerleri ve (ayara göre) bağımsız
    3D baskı mağazaları tutulur."""
    sonuc = []
    for x in yanit.get("shopping_results") or []:
        link = guvenli_link(x.get("link")) or guvenli_link(x.get("product_link"))
        satici = (x.get("source") or "").strip()
        if not link or not uc_d_mi(x.get("title"), satici):
            continue
        site = site_bul(x.get("link") or x.get("product_link"), satici)
        if not site:
            if not config.PAZAR_BAGIMSIZ_MAGAZALAR or not satici:
                continue
            site = satici[:40]
        fiyat = x.get("extracted_price")
        if fiyat is None:
            fiyat = _fiyat_metinden(x.get("price"))
        if fiyat is not None and float(fiyat) < config.PAZAR_EN_DUSUK_FIYAT_TL:
            continue  # dosya satışı veya hatalı fiyat
        sonuc.append({"site": site, "pazar_yeri": site in config.PAZAR_SITELERI.values(),
                      "title": x.get("title"), "link": link,
                      "price": float(fiyat) if fiyat is not None else None,
                      "thumbnail": x.get("thumbnail"), "kaynak": "metin"})
    return sonuc


def birlestir(*listeler: list[dict], en_fazla: int = 15) -> list[dict]:
    """Tekrarları atar; önce görsel eşleşmeler (daha benzer), sonra metin sonuçları."""
    gorulen, sonuc = set(), []
    for liste in listeler:
        for r in liste:
            anahtar = (r["site"], (r.get("title") or "").lower()[:60]) if r.get("title") else r.get("link")
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            sonuc.append(r)
    return sonuc[:en_fazla]


def _fiyat_kumesi(sonuclar: list[dict]) -> list[float]:
    """Fiyat istatistiği: tüm fiyatlı 3D baskı sonuçlar; ortancadan 5 kat uzak uç değerler atılır."""
    fiyatlar = [r["price"] for r in sonuclar if r.get("price") is not None]
    if len(fiyatlar) < 3:
        return fiyatlar
    orta = statistics.median(fiyatlar)
    return [f for f in fiyatlar if orta / 5 <= f <= orta * 5]


def ozetle(product_id: int, sonuclar: list[dict], sorgu: str | None = None) -> dict:
    fiyatlar = _fiyat_kumesi(sonuclar)
    return {
        "product_id": product_id,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "found_count": len(sonuclar),
        "min_price": min(fiyatlar) if fiyatlar else None,
        "max_price": max(fiyatlar) if fiyatlar else None,
        "currency": "TL" if fiyatlar else None,
        "results": [{**r, "sorgu": sorgu} for r in sonuclar],  # hangi Türkçe metinle arandığı görünsün
    }


def medyan(o: dict) -> float | None:
    fiyatlar = _fiyat_kumesi((o or {}).get("results") or [])
    return statistics.median(fiyatlar) if fiyatlar else None


# ---------------------------------------------------------------- akış
def secilecekler(secimler: list[dict], kontrol_tarihleri: dict[int, str], simdi: datetime | None = None,
                 adet: int | None = None) -> list[dict]:
    """Bugün aranacak ürünler: önce trend listesindekiler, sonra puan sırası; yakında aranmışlar atlanır.
    PAZAR_KURAL_TARIHI'nden önceki aramalar (eski kurallarla yapılmış) eskimiş sayılır."""
    simdi = simdi or datetime.now(timezone.utc)
    adet = config.PAZAR_GUNLUK_ADET if adet is None else adet
    sinir = max(simdi - timedelta(days=config.PAZAR_YENILEME_GUN),
                datetime.fromisoformat(config.PAZAR_KURAL_TARIHI))

    def taze(pid: int) -> bool:
        t = kontrol_tarihleri.get(pid)
        return bool(t) and datetime.fromisoformat(str(t).replace("Z", "+00:00")) >= sinir

    adaylar = [s for s in secimler if s["urun"].get("image_url") and not taze(s["product_id"])]
    adaylar.sort(key=lambda s: (s["urun"].get("trend_rank") is None, s["rank"]))
    return adaylar[:adet]


def urun_ara(api_key: str, urun: dict, client: httpx.Client | None = None) -> tuple[list[dict], str | None]:
    gorsel = lens_sonuclari(lens_ara(api_key, urun["image_url"], client)) if urun.get("image_url") else []
    sorgu = sorgu_olustur(urun.get("name"))
    sorgu = f"{sorgu} 3d baskı" if sorgu else None
    metin = alisveris_sonuclari(alisveris_ara(api_key, sorgu, client)) if sorgu else []
    return birlestir(gorsel, metin), sorgu


def calistir(depo, secimler: list[dict], api_key: str, client: httpx.Client | None = None) -> dict[int, dict]:
    """Seçilen ürünleri arar, veritabanına yazar; {product_id: özet} döndürür (bugün aranmış olanlar)."""
    hedefler = secilecekler(secimler, depo.pazar_kontrol_tarihleri([s["product_id"] for s in secimler]))
    ozetler = {}
    for s in hedefler:
        sonuclar, sorgu = urun_ara(api_key, s["urun"], client)
        ozetler[s["product_id"]] = ozetle(s["product_id"], sonuclar, sorgu)
    depo.pazar_kaydet(list(ozetler.values()))
    return ozetler


def fiyat_yazi(o: dict, onerilen_fiyat: float | None = None) -> str:
    if not o or not o.get("found_count"):
        return "3D baskı benzeri satışta bulunamadı"
    sayac: dict[str, int] = {}
    for r in o["results"]:
        sayac[r["site"]] = sayac.get(r["site"], 0) + 1
    siteler = ", ".join(f"{s} {n}" for s, n in sorted(sayac.items(), key=lambda x: -x[1])[:4])
    metin = f"3D baskı benzeri: {siteler}"
    if o.get("min_price") is not None:
        md = medyan(o)
        metin += f" · {o['min_price']:.0f}–{o['max_price']:.0f} TL (ortanca {md:.0f} TL)"
        if onerilen_fiyat:
            metin += f" · senin önerilen fiyatın {onerilen_fiyat:.0f} TL"
    return metin
