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
from urllib.parse import quote_plus, urlparse

import httpx

from . import config

API = "https://serpapi.com/search.json"
HESAP_API = "https://serpapi.com/account.json"


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
    # Boşluk ve ( ) [ ] Markdown bağlantısını, tırnak ve açılı ayraç HTML özniteliğini bozar: yüzde kodlanır.
    return (u.geturl().replace(" ", "%20").replace('"', "%22").replace("'", "%27")
            .replace("<", "%3C").replace(">", "%3E").replace("(", "%28").replace(")", "%29")
            .replace("[", "%5B").replace("]", "%5D"))


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
    "infinity cube": "sonsuz küp", "fidget spinner": "fidget spinner",
    "name tag": "isimlik", "name plate": "isimlik", "bottle opener": "açacak", "dice tower": "zar kulesi",
    "text embosser": "kabartma mühür", "paper embosser": "kabartma mühür",
    "wall art": "duvar dekoru", "night light": "gece lambası", "business card": "kartvizitlik",
}
CEVIRI = {
    "magnetic": "manyetik", "swing": "salıncak", "diorama": "diorama", "gnome": "cüce", "gnomo": "cüce",
    "nordic": "nordik", "knitted": "örgü", "sweater": "kazak", "tiny": "minik", "cute": "sevimli",
    "fidget": "fidget", "ring": "yüzük", "spinner": "spinner", "toy": "oyuncak", "toys": "oyuncak",
    "dragon": "ejderha", "flexi": "eklemli", "articulated": "eklemli", "snake": "yılan",
    "cat": "kedi", "dog": "köpek", "dachshund": "sosis köpek", "octopus": "ahtapot", "gecko": "kertenkele",
    "lizard": "kertenkele", "axolotl": "aksolotl", "turtle": "kaplumbağa", "shark": "köpekbalığı",
    "dinosaur": "dinozor", "dino": "dinozor", "fish": "balık", "bird": "kuş", "owl": "baykuş",
    "bunny": "tavşan", "rabbit": "tavşan", "bear": "ayı", "frog": "kurbağa", "butterfly": "kelebek",
    "skeleton": "iskelet", "skull": "kafatası", "doll": "bebek", "wand": "asa", "magic": "sihirli",
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
    # ayırt edici mekanik/şekil kelimeleri
    "impossible": "imkansız", "thread": "vida", "bolt": "cıvata", "nut": "somun", "screw": "vida",
    "gear": "dişli", "gears": "dişli", "spring": "yay", "infinity": "sonsuz", "spiral": "spiral",
    "clicker": "clicker", "slider": "kaydırmalı", "rotating": "dönen", "spinning": "dönen",
    "folding": "katlanır", "collapsible": "katlanır", "bracelet": "bileklik", "necklace": "kolye",
    "text": "yazı", "press": "pres", "earring": "küpe", "bowl": "kase", "dish": "tabak", "planet": "gezegen", "moon": "ay", "star": "yıldız",
    "lithophane": "litofan", "mandala": "mandala", "bag": "çanta", "wallet": "cüzdan", "comb": "tarak",
    # karakter/tema adları (Türk satıcılar da aynen yazar)
    "grinch": "grinch", "pikachu": "pikachu", "pokemon": "pokemon", "minecraft": "minecraft",
    "creeper": "creeper", "batman": "batman", "stitch": "stitch", "mario": "mario", "sonic": "sonic",
    "groot": "groot", "yoda": "yoda", "coraline": "coraline", "hogwarts": "hogwarts", "harry": "harry potter",
    # MakerWorld'de sık görülen İspanyolca/Portekizce/İtalyanca kelimeler
    "varita": "asa", "giratoria": "dönen", "giratorio": "dönen", "lagartixa": "kertenkele",
    "navidad": "yılbaşı", "natal": "yılbaşı", "natale": "yılbaşı", "maceta": "saksı", "llavero": "anahtarlık",
    "chaveiro": "anahtarlık", "portachiavi": "anahtarlık", "papai": "noel baba",
    "reindeer": "geyik", "deer": "geyik", "snowflake": "kar tanesi", "angel": "melek", "elf": "elf",
}
GURULTU = {
    "print", "printed", "printing", "in", "place", "pip", "no", "ams", "tpu", "the", "a", "an", "for", "with",
    "and", "of", "to", "3d", "mini", "v2", "v3", "version", "remix", "easy", "super", "ultra", "satisfying",
    "free", "sell", "support", "supports", "without", "multi", "color", "colour", "plate", "set", "kit",
    "custom", "extra", "long", "big", "small", "large", "new", "best", "my", "your", "simple", "cool",
    "stile", "maglia", "natalizio", "style", "edition", "model", "design", "project", "file", "files",
}


def sorgu_olustur(ad: str | None, en_fazla_kelime: int = 3) -> str | None:
    """Model adından Türkçe arama metni.

    Bilinen ifade/kelimeler çevrilir; gürültü atılır. Sözlükte olmayan kelimeler yalnızca hiç
    bilinen kelime yoksa kullanılır; tamamı büyük harfle yazılmış bilinmeyen kelimeler (çoğunlukla
    marka/tasarımcı adı, ör. "MYLITOS") hiçbir zaman kullanılmaz.
    """
    ham = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", ad or "")
    hepsi_buyuk = bool(ham) and all(k.isupper() for k in ham if len(k) > 1)
    metin = " ".join(k.lower() for k in ham)
    sonuc: list[str] = []
    for ifade, tr in IFADELER.items():
        if re.search(rf"\b{ifade}\b", metin):
            sonuc.append(tr)
            metin = re.sub(rf"\b{ifade}\b", " ", metin)
    kalan = set(metin.split())
    bilinmeyen: list[str] = []
    for orijinal in ham:
        k = orijinal.lower()
        if k not in kalan or k in GURULTU or len(k) < 3:
            continue
        tr = CEVIRI.get(k) or CEVIRI.get(k.rstrip("s"))
        if tr:
            if tr not in sonuc:
                sonuc.append(tr)
        elif not orijinal.isupper() and not hepsi_buyuk and k not in bilinmeyen:
            bilinmeyen.append(k)
    if not sonuc:
        sonuc = bilinmeyen[:2]
    return " ".join(sonuc[:en_fazla_kelime]) or None


# Ürün tipi: Türk satıcılar ilanı ürünün ne olduğuyla yazar ("Grinch Figür", "Yılbaşı Süsü").
# Model adı yalnızca karakter/tema söylüyorsa (ör. "MINI GRINCH") ad + etiketlerden tip eklenir.
TIP_KURALLARI = [
    (("keychain", "keyring", "key chain"), "anahtarlık"),
    (("stamp", "embosser"), "mühür"),
    (("ornament", "decoration", "decor"), "süs"),
    (("figure", "figurine", "statue", "bust", "diorama", "character"), "figür"),
    (("vase",), "vazo"),
    (("planter", "plant pot", "flower pot"), "saksı"),
    (("lamp", "night light", "lithophane"), "lamba"),
]
KARAKTERLER = {"grinch", "pikachu", "pokemon", "creeper", "batman", "stitch", "mario", "sonic", "groot",
               "yoda", "coraline", "harry potter", "örümcek adam", "noel baba", "kardan adam"}
TIP_ISIMLERI = {tip for _, tip in TIP_KURALLARI} | {
    "anahtarlık", "kalemlik", "isimlik", "mumluk", "yüzük", "bileklik", "kolye", "küpe", "oyuncak", "stand",
    "standı", "tutucu", "düzenleyici", "kutu", "çerçeve", "askı", "raf", "tepsi", "kase", "tabak", "süsü",
    "kartvizitlik", "açacak", "altlığı", "kulesi", "çanta", "cüzdan", "tarak", "maske", "kılıç", "fırlatıcı"}
BOYUT = re.compile(r"\b(?:mini|tiny|little|small)\b")


def urun_tipi(ad: str | None, etiketler: list[str] | None = None, mevcut: str | None = None) -> str | None:
    """Sorguya eklenecek ürün tipi (ör. "mini figür", "süsü"); sorguda zaten bir tip varsa None."""
    mevcut_kelimeler = set((mevcut or "").split())
    if mevcut_kelimeler & TIP_ISIMLERI:
        return None
    metin = " | ".join([(ad or "").lower(), *[str(e).lower() for e in etiketler or []]])

    def bul(kaynak: str) -> str | None:
        return next((tr for ingilizce, tr in TIP_KURALLARI
                     if any(re.search(rf"\b{re.escape(k)}s?\b", kaynak) for k in ingilizce)), None)

    karakter = any(re.search(rf"(?<![a-zçğıöşü]){re.escape(k)}(?![a-zçğıöşü])", mevcut or "")
                   for k in KARAKTERLER)
    # Karakterli modellerde yalnızca ada bakılır: etiketlerdeki genel "decoration" yüzünden
    # "MINI GRINCH" figürü "süs" sanılmasın. Ad bir şey söylemiyorsa çoğunlukla figürdür.
    tip = (bul((ad or "").lower()) or "figür") if karakter else bul(metin)
    if tip == "süs" and "yılbaşı" in mevcut_kelimeler:
        tip = "süsü"    # "yılbaşı süsü"
    if tip == "figür" and BOYUT.search(metin):
        tip = "mini figür"
    return tip


# Genişletilmiş (ikinci) aramada kullanılır: Türk pazar yerlerinde daha yaygın karşılıklar.
ES_ANLAMLI = {"fidget": "stres oyuncağı", "manyetik": "mıknatıslı", "eklemli": "hareketli",
              "kabartma mühür": "kabartma damga", "imkansız vida": "spiral vida"}


def genis_metin(sorgu: str | None) -> str | None:
    """Az sonuç gelirse kullanılacak daha geniş sorgu: eş anlamlılarla değiştirilir; değişmediyse
    ilk kelime (çoğunlukla sıfat) atılır."""
    if not sorgu:
        return None
    govde = re.sub(r"\s*3d baskı$", "", sorgu)
    yeni = govde
    for k, es in ES_ANLAMLI.items():
        yeni = re.sub(rf"(?<![a-zçğıöşü]){re.escape(k)}(?![a-zçğıöşü])", es, yeni)
    if yeni == govde:
        parcalar = _parcalar(govde)
        if len(parcalar) < 3:
            return None
        yeni = " ".join(parcalar[1:])
    return f"{yeni} 3d baskı"


def _parcalar(govde: str) -> list[str]:
    """Sorguyu bölünmemesi gereken ifadeleriyle parçalar ("noel baba", "yılbaşı ağacı" tek parça)."""
    ifadeler = sorted({v for v in [*IFADELER.values(), *CEVIRI.values(), *KARAKTERLER, *ES_ANLAMLI.values(),
                                   "yılbaşı süsü", "mini figür"] if " " in v}, key=len, reverse=True)
    parcalar, kalan = [], govde.split()
    while kalan:
        uyan = next((i for i in ifadeler if kalan[:len(i.split())] == i.split()), None)
        n = len(uyan.split()) if uyan else 1
        parcalar.append(" ".join(kalan[:n]))
        kalan = kalan[n:]
    return parcalar


# Lens'in bulduğu Türkçe 3D baskı başlıklarından ek kelimeler (satıcıların kullandığı Türkçe).
TR_DURAK = {
    "ve", "ile", "için", "icin", "bir", "bu", "da", "de", "fiyatı", "fiyati", "fiyatları", "satın", "al",
    "adet", "set", "li", "lı", "lu", "lü", "model", "modeli", "renk", "renkli", "yeni", "marka", "markalar",
    "genel", "baskı", "baski", "boyutlu", "yazıcı", "yazici", "trendyol", "hepsiburada", "n11", "amazon",
    "taksit", "seçenekleri", "secenekleri", "özellikleri", "ozellikleri", "ürün", "urun", "cm", "mm", "gr",
    "studio", "store", "shop", "official", "hediyelik", "hediye", "print", "printed", "pla", "petg",
}
TR_HARF = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


def tr_baslik_mi(x: dict) -> bool:
    """Türkiye'den bir satış sonucu mu? (.tr alan adı veya Türkçe harfli pazar yeri başlığı)"""
    host = (urlparse(x.get("link") or "").hostname or "").lower()
    if host.endswith(".tr"):
        return True
    return bool(site_bul(x.get("link"), x.get("source"))) and bool(TR_HARF.search(x.get("title") or ""))


def lens_kelimeleri(lens_yaniti: dict, en_fazla: int = 2) -> list[str]:
    """Lens'in bulduğu Türkçe 3D baskı ürün başlıklarında en az 2 başlıkta geçen kelimeler.
    Tek başlıkta geçen kelime (çoğunlukla marka) kullanılmaz."""
    sayac: dict[str, int] = {}
    for x in (lens_yaniti.get("visual_matches") or []) + (lens_yaniti.get("exact_matches") or []):
        if not tr_baslik_mi(x) or not uc_d_mi(x.get("title"), None, x.get("link")):
            continue
        for k in set(re.findall(r"[a-zçğıöşü]{3,}", (x.get("title") or "").lower())):
            if k not in TR_DURAK and k not in GURULTU:
                sayac[k] = sayac.get(k, 0) + 1
    return [k for k, n in sorted(sayac.items(), key=lambda x: (-x[1], x[0])) if n >= 2][:en_fazla]


def arama_metni(ad: str | None, lens_yaniti: dict | None = None,
                etiketler: list[str] | None = None) -> str | None:
    """İsimden üretilen metin (isimden çıkmazsa etiketlerden) + ürün tipi + (varsa) Lens'teki Türkçe
    3D baskı başlıklarından kelimeler + '3d baskı'."""
    temel = sorgu_olustur(ad) or sorgu_olustur(" ".join(str(e) for e in (etiketler or [])[:6]))
    kelimeler = temel.split() if temel else []
    tip = urun_tipi(ad, etiketler, temel) if kelimeler else None
    for k in (tip or "").split():
        if k not in kelimeler:
            kelimeler.append(k)
    for k in lens_kelimeleri(lens_yaniti or {}):
        if k not in kelimeler and len(kelimeler) < 5:
            kelimeler.append(k)
    return f"{' '.join(kelimeler)} 3d baskı" if kelimeler else None


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


def lens_ara(api_key: str, gorsel_url: str, metin: str | None = None,
             client: httpx.Client | None = None) -> dict:
    """Google Lens (Türkiye). `metin` verilirse görsel + metin birlikte aranır (Lens "multisearch"):
    ör. "fidget yüzük 3d baskı" eklenince 3D baskı ürün eşleşmeleri belirgin şekilde artar."""
    params = {"engine": "google_lens", "url": gorsel_url, "hl": "tr", "country": "tr"}
    if metin:
        params |= {"type": "visual_matches", "q": metin}
    return _istek(api_key, params, client)


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
DIJITAL = re.compile(r"bask[ıi]\s?modeli|\bstl\b|\b3mf\b|dosyas[ıi]|dijital|digital|download"
                     r"|\b(?:print|printer|printable|3d)\s?files?\b", re.I)


# Dijital model dosyası satan/paylaşan siteler: fiziksel ürün satmazlar, karşılaştırmaya girmez.
DIJITAL_SITELER = ("cults3d", "thingiverse", "printables", "makerworld", "cgtrader", "myminifactory",
                   "thangs", "3dexport", "turbosquid", "stlfinder", "yeggi", "crealitycloud", "creality cloud",
                   "3dgo", "makeronline", "free3d", "sketchfab")


def dijital_site_mi(link: str | None, satici: str | None = None) -> bool:
    metin = ((urlparse(link or "").hostname or "") + " " + (satici or "")).lower().replace(" ", "")
    return any(d.replace(" ", "") in metin for d in DIJITAL_SITELER)


# Yurt dışı toptan/ucuz pazar yerleri: başlıktaki "3D" çoğu zaman 3D baskı değil (3D efekt, kalıp
# üretim); bağımsız 3D baskı mağazası sayılmazlar.
YABANCI_PAZARLAR = ("temu", "dhgate", "aliexpress", "alibaba", "made-in-china", "madeinchina", "shein",
                    "wish.com", "banggood", "joom")


def yabanci_pazar_mi(link: str | None, satici: str | None = None) -> bool:
    metin = ((urlparse(link or "").hostname or "") + " " + (satici or "")).lower().replace(" ", "")
    return any(y in metin for y in YABANCI_PAZARLAR)


def uc_d_mi(baslik: str | None, satici: str | None = None, link: str | None = None) -> bool:
    baslik = baslik or ""
    if DIJITAL.search(baslik) or dijital_site_mi(link, satici):
        return False
    return bool(UC_D.search(baslik) or (satici and UC_D_SATICI.search(satici)))


# ---------------------------------------------------------------- satış sayfası bağlantısı
# Google Alışveriş sonuçları Google'ın ürün sayfasına gider. Pazar yeri sonuçlarında kullanıcının
# tıklayacağı bağlantı olarak sitenin kendi arama sayfası (ürün adıyla) verilir.
SITE_ARAMA = {
    "Trendyol": "https://www.trendyol.com/sr?q={q}",
    "Hepsiburada": "https://www.hepsiburada.com/ara?q={q}",
    "n11": "https://www.n11.com/arama?q={q}",
    "Amazon TR": "https://www.amazon.com.tr/s?k={q}",
    "Çiçeksepeti": "https://www.ciceksepeti.com/arama?query={q}",
    "Pazarama": "https://www.pazarama.com/arama?q={q}",
    "PttAVM": "https://www.pttavm.com/arama?q={q}",
    "Etsy": "https://www.etsy.com/search?q={q}",
}


def satis_linki(r: dict) -> str | None:
    """Sonucun satıldığı siteye giden bağlantı: doğrudan ürün sayfası > sitenin arama sayfası > Google."""
    link = r.get("link")
    host = (urlparse(link or "").hostname or "").lower()
    if host and any(_alan_eslesir(host, alan) for alan in config.PAZAR_SITELERI):
        return link
    sablon = SITE_ARAMA.get(r.get("site")) if r.get("pazar_yeri") else None
    if sablon and r.get("title"):
        return sablon.format(q=quote_plus(r["title"][:80]))
    return link


def satis_yerleri(o: dict | None, en_fazla: int = 3) -> list[dict]:
    """Mesajda gösterilecek siteler: her siteden bir sonuç; önce pazar yerleri, sonra en ucuz."""
    adaylar = sorted((o or {}).get("results") or [],
                     key=lambda r: (not r.get("pazar_yeri"), r.get("price") is None, r.get("price") or 0))
    secilen, siteler = [], set()
    for r in adaylar:
        if r.get("kaynak") == "sosyal":
            continue  # sosyal medya ayrı gösterilir (sosyal_yerler)
        link = satis_linki(r)
        if (not link or r["site"] in siteler or dijital_site_mi(r.get("link"), r.get("site"))
                or DIJITAL.search(r.get("title") or "")):
            continue  # dijital dosya siteleri (eski kayıtlarda kalmış olabilir) gösterilmez
        siteler.add(r["site"])
        secilen.append({"site": r["site"], "price": r.get("price"), "link": link,
                        "pazar_yeri": r.get("pazar_yeri", True)})
        if len(secilen) >= en_fazla:
            break
    return secilen


# ---------------------------------------------------------------- dış metinleri temizleme
# Satıcı adları ve ürün başlıkları dışarıdan gelir; rapora (Markdown) ve Telegram'a yazılır.
_MD_ISARET = re.compile(r"[\[\]()<>*_`|!#\\\r\n\t]")


def temiz_baslik(metin: str | None, uzunluk: int = 120) -> str | None:
    if not metin:
        return None
    return re.sub(r"\s+", " ", _MD_ISARET.sub(" ", str(metin))).strip()[:uzunluk] or None


def bagimsiz_etiket(satici: str | None) -> str | None:
    """Bağımsız mağaza adı: yalnızca güvenli karakterler; bir pazar yeri adına benziyorsa
    "(bağımsız)" eki alır, böylece pazar yeri gibi görünemez."""
    ad = re.sub(r"\s+", " ", re.sub(r"[^\w\s.&'\-]", "", satici or "")).strip()[:40]
    if not ad:
        return None
    sade = ad.lower().replace(" ", "")
    for alan, pazar_adi in config.PAZAR_SITELERI.items():
        if alan.split(".")[0] in sade or pazar_adi.lower().replace(" ", "") in sade:
            return f"{ad} (bağımsız)"
    return ad


# ---------------------------------------------------------------- ayıklama
def ilgili_mi(baslik: str | None, anahtarlar: set[str] | None) -> bool:
    """Başlıkta ürünle ilgili bir kelime var mı? (anahtarlar None ise kontrol yapılmaz)"""
    if anahtarlar is None:
        return True
    kucuk = (baslik or "").lower()
    return any(re.search(rf"(?<![a-zçğıöşü]){re.escape(k)}(?![a-zçğıöşü])", kucuk) for k in anahtarlar)


def lens_sonuclari(yanit: dict, anahtarlar: set[str] | None = None) -> list[dict]:
    """Görsel eşleşmeler dünya çapındadır: yalnızca PAZAR_SITELERI'ndeki 3D baskı ürünler tutulur.
    `anahtarlar` verilirse başlıkta ürünle ilgili bir kelime de aranır (yalnızca şekli benzeyen
    başka ürünler karşılaştırmaya girmesin)."""
    sonuc = []
    for x in (yanit.get("visual_matches") or []) + (yanit.get("exact_matches") or []):
        site = site_bul(x.get("link"), x.get("source"))
        if not site or not uc_d_mi(x.get("title"), x.get("source"), x.get("link")):
            continue
        if not ilgili_mi(x.get("title"), anahtarlar):
            continue
        f = x.get("price") if isinstance(x.get("price"), dict) else {}
        fiyat = f.get("extracted_value")
        sonuc.append({"site": site, "pazar_yeri": True, "title": temiz_baslik(x.get("title")),
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
        if not link or not uc_d_mi(x.get("title"), satici, x.get("link") or x.get("product_link")):
            continue
        site = site_bul(x.get("link") or x.get("product_link"), satici)
        pazar_yeri = site is not None   # yalnızca alan adı / Google satıcı eşleşmesi pazar yeri sayılır
        if not pazar_yeri:
            if not config.PAZAR_BAGIMSIZ_MAGAZALAR or yabanci_pazar_mi(x.get("link") or x.get("product_link"), satici):
                continue
            site = bagimsiz_etiket(satici)
            if not site:
                continue
        fiyat = x.get("extracted_price")
        if fiyat is None:
            fiyat = _fiyat_metinden(x.get("price"))
        if fiyat is not None and float(fiyat) < config.PAZAR_EN_DUSUK_FIYAT_TL:
            continue  # dosya satışı veya hatalı fiyat
        sonuc.append({"site": site, "pazar_yeri": pazar_yeri,
                      "title": temiz_baslik(x.get("title")), "link": link,
                      "price": float(fiyat) if fiyat is not None else None,
                      "thumbnail": x.get("thumbnail"), "kaynak": "metin"})
    return sonuc


# ---------------------------------------------------------------- sosyal medya (Instagram, TikTok, YouTube, Facebook)
# Bu siteler doğrudan taranmaz (giriş zorunluluğu ve kullanım şartları). Google Lens görselle ararken
# bu sayfaları da bulur; aynı modelin görsel benzeri oldukları için 3D şartı aranmaz. Şahıs
# işletmelerinin mağaza sayfalarını öne çıkarmak için Türkçe ve satış belirtileri işaretlenir.
SOSYAL = {"instagram.com": "Instagram", "tiktok.com": "TikTok", "youtube.com": "YouTube",
          "youtu.be": "YouTube", "facebook.com": "Facebook"}
# Not: re.I ile "ı" harfi "I/i" ile de eşleşir ("Satisfying" → "satış" sanılır); bu yüzden kelime
# sınırları kullanılır ve Türkçe harf kontrolü büyük/küçük harfe duyarlı yapılır.
SATIS_IZI = re.compile(
    r"\bsipari[şs]|\bsat[ıi][şs](?:ta)?\b|\bsat[ıi]l[ıi]k\b|\bfiyat|\bkargo|\bdm\b|\bstokta\b|"
    r"\d\s?(?:tl|₺)\b|₺|\border\b|for sale|\bshop\b|\bstore\b|\bavailable\b|\bprice\b|sold out|"
    r"get (?:yours|them)|link in bio|"
    r"متوفر|للطلب|\bvenda\b|\bencomend", re.I)
_TR_HARF_DUYARLI = re.compile(r"[çğışöüÇĞİŞÖÜ]")
_TR_SOZ = re.compile(r"\b(?:ve|ile|için|baskı|sipariş|fiyat|fiyatı|hediye|tasarım|kargo|satışta)\b")


class _TrKelime:
    @staticmethod
    def search(metin: str) -> bool:
        return bool(_TR_HARF_DUYARLI.search(metin) or _TR_SOZ.search(metin.lower()))


TR_KELIME = _TrKelime()


def anahtar_kelimeler(ad: str | None, sorgu: str | None = None) -> set[str]:
    """Sosyal medya gönderisinin bu ürünle ilgili olduğunu gösteren kelimeler: model adındaki
    anlamlı kelimeler (4+ harf) ve Türkçe arama metninin kelimeleri."""
    kelimeler = {k.lower() for k in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4,}", ad or "")}
    kelimeler |= set((sorgu or "").lower().split())
    return {k for k in kelimeler if k not in GURULTU and k not in TR_DURAK and k not in ("baskı", "satisfying")}


def sosyal_sonuclari(yanit: dict, anahtarlar: set[str] | None = None, en_fazla: int = 6) -> list[dict]:
    """Lens'in bulduğu sosyal medya sayfaları. İlgisiz eşleşmeleri (görsel olarak benzeyen başka
    ürünler, eğitim videoları) elemek için başlıkta ürünle ilgili bir kelime veya 3D baskı işareti
    aranır; dosya indirme sayfaları atılır."""
    sonuc, gorulen = [], set()
    for x in (yanit.get("visual_matches") or []) + (yanit.get("exact_matches") or []):
        link = guvenli_link(x.get("link"))
        host = (urlparse(link or "").hostname or "").lower()
        site = next((ad for alan, ad in SOSYAL.items() if host and _alan_eslesir(host, alan)), None)
        baslik = temiz_baslik(x.get("title"))
        if not site or not link or link in gorulen:
            continue
        if not baslik or baslik.lower() in ("youtube", "tiktok", "instagram", "facebook"):
            continue  # başlıksız/genel sayfa
        kucuk = (x.get("title") or "").lower()
        if DIJITAL.search(kucuk) or re.search(r"\b(?:3d model|free stl)\b", kucuk):
            continue  # dosya indirme
        if anahtarlar is not None and not (ilgili_mi(kucuk, anahtarlar) or UC_D.search(kucuk)):
            continue  # ürünle ilgisiz görünüyor
        gorulen.add(link)
        ham = x.get("title") or ""
        sonuc.append({"site": site, "pazar_yeri": False, "title": baslik, "link": link, "price": None,
                      "thumbnail": x.get("thumbnail"), "kaynak": "sosyal",
                      "tr": bool(TR_KELIME.search(ham)), "satis": bool(SATIS_IZI.search(ham))})
    # Önce Türkçe ve satış belirtisi olanlar
    sonuc.sort(key=lambda r: (not r["tr"], not r["satis"]))
    return sonuc[:en_fazla]


def sosyal_yerler(o: dict | None, en_fazla: int = 3) -> list[dict]:
    return [r for r in (o or {}).get("results") or [] if r.get("kaynak") == "sosyal"][:en_fazla]


def sosyal_yazi(o: dict | None) -> str | None:
    sosyal = [r for r in (o or {}).get("results") or [] if r.get("kaynak") == "sosyal"]
    if not sosyal:
        return None
    sayac: dict[str, int] = {}
    for r in sosyal:
        sayac[r["site"]] = sayac.get(r["site"], 0) + 1
    metin = ", ".join(f"{s} {n}" for s, n in sorted(sayac.items(), key=lambda x: (-x[1], x[0])))
    tr = sum(1 for r in sosyal if r.get("tr"))
    satis = sum(1 for r in sosyal if r.get("satis"))
    ek = [f"{tr} Türkçe" if tr else "", f"{satis} satış belirtili" if satis else ""]
    ek = [e for e in ek if e]
    return f"Sosyal medyada: {metin}" + (f" ({', '.join(ek)})" if ek else "")


def sosyal_etiket(r: dict) -> str:
    isaret = [e for e, var in (("Türkçe", r.get("tr")), ("satış", r.get("satis"))) if var]
    return f" ({', '.join(isaret)})" if isaret else ""


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
        "found_count": sum(1 for r in sonuclar if r.get("kaynak") != "sosyal"),   # satış sitesi sonuçları
        "min_price": min(fiyatlar) if fiyatlar else None,
        "max_price": max(fiyatlar) if fiyatlar else None,
        "currency": "TL" if fiyatlar else None,
        "results": [{**r, "sorgu": sorgu} for r in sonuclar],  # hangi Türkçe metinle arandığı görünsün
    }


def medyan(o: dict) -> float | None:
    fiyatlar = _fiyat_kumesi((o or {}).get("results") or [])
    return statistics.median(fiyatlar) if fiyatlar else None


def _zaman(t: object) -> datetime:
    return datetime.fromisoformat(str(t).replace("Z", "+00:00"))


def gecerli_mi(o: dict | None) -> bool:
    """Kayıt güncel kurallarla (3D şartı) mı yapılmış?"""
    try:
        return bool(o) and _zaman(o["checked_at"]) >= _zaman(config.PAZAR_KURAL_TARIHI)
    except (KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------- akış
def secilecekler(secimler: list[dict], kontrol_tarihleri: dict[int, str], simdi: datetime | None = None,
                 adet: int | None = None) -> list[dict]:
    """Bugün aranacak ürünler: özetteki sıraya göre (1. ürün önce); yakında aranmışlar atlanır.
    PAZAR_KURAL_TARIHI'nden önceki aramalar (eski kurallarla yapılmış) eskimiş sayılır."""
    simdi = simdi or datetime.now(timezone.utc)
    adet = config.PAZAR_GUNLUK_ADET if adet is None else adet
    sinir = max(simdi - timedelta(days=config.PAZAR_YENILEME_GUN),
                datetime.fromisoformat(config.PAZAR_KURAL_TARIHI))

    def taze(pid: int) -> bool:
        t = kontrol_tarihleri.get(pid)
        return bool(t) and datetime.fromisoformat(str(t).replace("Z", "+00:00")) >= sinir

    adaylar = [s for s in secimler if s["urun"].get("image_url") and not taze(s["product_id"])]
    adaylar.sort(key=lambda s: s["rank"])
    return adaylar[:adet]


def urun_ara(api_key: str, urun: dict, client: httpx.Client | None = None) -> tuple[list[dict], str | None]:
    """1) Görsel + metinle (Lens): pazar yeri sonuçları + sosyal medya sayfaları + Türkçe başlıklardan
       kelimeler. Görselin yanına ürün adının Türkçesi ve '3d baskı' eklenir.
    2) İsimle (Alışveriş): model adının Türkçesi + ürün tipi + Lens kelimeleri + '3d baskı'.
    3) Satış sonucu PAZAR_YEDEK_ALT_SINIR'dan azsa ve kota yetiyorsa daha geniş metinle bir kez daha."""
    ad, etiketler = urun.get("name"), urun.get("tags")
    temel = arama_metni(ad, None, etiketler)
    lens = lens_ara(api_key, urun["image_url"], temel, client) if urun.get("image_url") else {}
    sorgu = arama_metni(ad, lens, etiketler)
    anahtarlar = anahtar_kelimeler(ad, sorgu)
    gorsel = lens_sonuclari(lens, anahtarlar)
    sosyal = sosyal_sonuclari(lens, anahtarlar)
    metin = alisveris_sonuclari(alisveris_ara(api_key, sorgu, client)) if sorgu else []
    satis = birlestir(gorsel, metin)
    if config.PAZAR_YEDEK_ARAMA and len(satis) < config.PAZAR_YEDEK_ALT_SINIR:
        genis = genis_metin(sorgu)
        kalan = kalan_hak(api_key, client) if genis else None
        if genis and kalan is not None and kalan >= config.PAZAR_YEDEK_KOTA_ESIGI:
            satis = birlestir(gorsel, metin, alisveris_sonuclari(alisveris_ara(api_key, genis, client)))
            sorgu = f"{sorgu} · {genis}"
    return satis + sosyal, sorgu


def kalan_hak(api_key: str, client: httpx.Client | None = None) -> int | None:
    """SerpApi'de bu ay kalan arama hakkı (hesap sorgusu ücretsizdir, hak düşmez). Okunamazsa None
    döner; o durumda ek arama yapılmaz."""
    try:
        yanit = (client or httpx.Client(timeout=30)).get(HESAP_API, params={"api_key": api_key})
        veri = yanit.json() if yanit.status_code == 200 else {}
        kalan = veri.get("total_searches_left", veri.get("plan_searches_left"))
        return int(kalan) if kalan is not None else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


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
        if r.get("kaynak") != "sosyal":
            sayac[r["site"]] = sayac.get(r["site"], 0) + 1
    siteler = ", ".join(f"{s} {n}" for s, n in sorted(sayac.items(), key=lambda x: -x[1])[:4])
    metin = f"3D baskı benzeri: {siteler}"
    if o.get("min_price") is not None:
        md = medyan(o)
        metin += f" · {o['min_price']:.0f}–{o['max_price']:.0f} TL (ortanca {md:.0f} TL)"
        if onerilen_fiyat:
            metin += f" · senin önerilen fiyatın {onerilen_fiyat:.0f} TL"
    return metin
