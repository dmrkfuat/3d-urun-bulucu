"""Pazar keşfi: Türkiye'de çok satan 3D baskı ürünler → MakerWorld'deki birebir modeli.

Günlük analizin tersi: MakerWorld'de popüler olandan değil, Türkiye'de SATILANDAN başlar.

1. Google Alışveriş'te (SerpApi) kategori aramaları: "3d baskı fidget", "3d baskı saksı"...
   Yalnızca 3D baskı fiziksel ürünler tutulur (pazar.alisveris_sonuclari).
2. Aynı ürünün ilanları kümelenir. Google Alışveriş satış adedi/yorum vermez; çok satanın en
   güçlü işareti, aynı ürünü KAÇ FARKLI SATICININ satmasıdır (satıcılar satan ürünü kopyalar).
   Satıcı başlıktaki markadan anlaşılır; bir satıcının her renk için açtığı ilanlar tek sayılır,
   tek mağazanın ürünü (en az KESIF_EN_AZ_SATICI satıcı yoksa) listelenmez.
3. En çok ilanı olan kümelerin görseliyle Google Lens: (a) aynı ürünü satan diğer Türk pazar
   yeri ilanları sayılır, (b) sonuçlarda MakerWorld/Printables model sayfası çıkarsa o modelin
   kaynağıdır ("görsel eşleşme"; birebir model).
4. Ayrıca ürün adının İngilizcesiyle MakerWorld'de ücretsiz arama ("isim eşleşmesi"; panelde
   görseller yan yana gösterilir, sen doğrularsın).
5. Eşleşen modellerin baskı süresi/maliyeti MakerWorld'den alınır; piyasa ortanca fiyatıyla
   ilan başına ve saat başına kâr hesaplanır.
6. Trendyol yelpazesi: her kategori Google Alışveriş'in kendi "Mağazalar → Trendyol" süzgeciyle bir
   kez daha aranır (Trendyol'a istek atılmaz; Google'ın dizini). Trendyol'daki 3D baskı ürün
   çeşitliliği, fiyat düzeyi ve en çok ürünü olan satıcılar raporlanır; bu ilanlar kümelemeye de girer.

Haftada bir (KESIF_ARALIK_GUN) günlük analizle birlikte çalışır; elle: python -m urun_bulucu.kesif
SerpApi kotası: hafta başına ~len(sorgular) + KESIF_LENS_ADET arama (ayda ~70).
"""
from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from . import bildirim, config, pazar, sezon
from .kaynaklar import makerworld as mw

KATEGORI = "Pazarda çok satan"

# Başlıktan atılan kelimeler (anahtar ve ad için anlamsız).
DURAK = {
    "3d", "baskı", "baski", "baskılı", "baskili", "baskısı", "baskisi", "yazıcı", "yazici", "printed",
    "ve", "ile", "için", "icin", "adet", "set", "li", "lı", "lu", "lü", "1", "2", "3", "x", "the", "a",
    "model", "modeli", "yeni", "özel", "ozel", "hediyelik", "dekoratif", "orijinal", "kaliteli",
}
RENKLER = {
    "kırmızı", "kirmizi", "mavi", "yeşil", "yesil", "sarı", "sari", "siyah", "beyaz", "mor", "pembe",
    "turuncu", "gri", "lacivert", "kahverengi", "mint", "renkli", "rengi", "renk", "altın", "gümüş",
}
# Tek başına ürünü tanımlamayan kelimeler: kümeleme bunlarla yapılmaz.
GENEL = {"fidget", "oyuncak", "oyuncağı", "oyuncagi", "stres", "toy", "giderici", "atıcı", "rahatlatıcı",
         "hareketli", "masaüstü", "dekor", "süs", "hediye", "figür", "obje", "aksesuar", "mini", "büyük"}
# Ürün TİPİ kelimeleri: aynı ürünü ayırt etmez ("Kartal Gece Lambası" ile "Baykuş Gece Lambası" farklı
# ürünlerdir; ortak "gece lambası" onları birleştirmemeli).
GENEL |= {"saksı", "saksısı", "saksi", "lamba", "lambası", "gece", "aplik", "kalemlik", "vazo", "vazosu",
          "biblo", "heykel", "heykeli", "anahtarlık", "anahtarlığı", "düzenleyici", "organizer", "organizer",
          "çiçek", "cicek", "seti", "modern", "şık", "sevimli", "tasarım", "tasarımlı", "küçük", "boy",
          "masa", "ofis", "ev", "duvar", "dekorasyon", "aydınlatma", "minimal", "çanta", "standı", "stand",
          "tutucu", "kutu", "kutusu", "tepsi", "tepsisi", "pilli", "ledli", "led", "üretim", "şeklinde",
          "seklinde", "üretilmiş", "uretilmis", "boyutlu", "yazıcı", "renkli"}
# Pazar yerlerinin markasız ürünler için kullandığı ad: satıcı değildir.
GENEL_MARKALAR = {"genel", "markalar", "markasız", "markasiz", "diğer", "diger", "no", "brand", "tr"}
DURAK |= {"genel", "markalar", "markasız", "fiyatı", "fiyati", "pttavm"}   # kümelemede de yok sayılır
# Pazar yeri başlıklarında sık geçen, CEVIRI'de olmayan Türkçe kelimeler → İngilizce.
TR_EN_EK = {
    "cetvel": "ruler", "top": "ball", "topu": "ball", "yumurta": "egg", "yumurtası": "egg",
    "figür": "figure", "heykel": "statue", "stres": "stress", "çark": "spinner", "çarklı": "spinner",
    "şemsiye": "umbrella", "dokunsal": "tactile", "katlanabilir": "folding", "kaydırmalı": "slider",
    "kalemlik": "pen holder", "kulaklık": "headphone", "kartvizitlik": "card holder", "zar": "dice",
    "kumbara": "piggy bank", "lamba": "lamp", "abajur": "lamp", "isimlik": "name plate",
    "anahtarlık": "keychain", "saksı": "planter", "vazo": "vase", "mumluk": "candle holder",
}
# (site, alan adı, YOL deseni). Önce alan adı (veya alt alanı) doğrulanır, desen yalnızca yola
# uygulanır: "https://baska.site/?x=printables.com/model/1" gibi bağlantılar model sayılmaz.
MODEL_SAYFASI = [
    ("MakerWorld", "makerworld.com", re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?models/(\d+)", re.I)),
    ("Printables", "printables.com", re.compile(r"^/(?:[a-z]{2}/)?model/(\d+)", re.I)),
    ("Thingiverse", "thingiverse.com", re.compile(r"^/thing:(\d+)", re.I)),
    ("Cults3D", "cults3d.com", re.compile(r"^/[a-z]{2}/(?:3d-model|3d-print|3d-bask%C4%B1|3d-baskı|modelo-3d)/"
                                          r"[^/]+/([^/?#]+)", re.I)),
]


def model_sayfasi(link: str) -> tuple[str, str] | None:
    """(site, model kimliği) — bağlantı bilinen bir model sitesinin model sayfasıysa."""
    try:
        adres = urlsplit(link)
    except ValueError:
        return None
    host = (adres.hostname or "").lower()
    for site, alan, desen in MODEL_SAYFASI:
        if pazar._alan_eslesir(host, alan):
            m = desen.match(adres.path)
            return (site, m.group(1)) if m else None
    return None


def _kucuk(metin: str) -> str:
    return (metin or "").replace("I", "ı").replace("İ", "i").lower()


_KATLA = str.maketrans("çğıöşü", "cgiosu")


def _n(kelime: str) -> str:
    """Karşılaştırma biçimi: Türkçe harfler sadeleşir ("Çok Bölmeli" = "cok Bolmeli"; İngilizce
    'Infinity' ile Türkçe 'KIRMIZI' da aynı kurala uyar)."""
    return kelime.translate(_KATLA)


DURAK = {_n(k) for k in DURAK}
RENKLER = {_n(k) for k in RENKLER}
GENEL = {_n(k) for k in GENEL}


def _kok(kelime: str) -> str:
    """Kaba Türkçe ek atma: 'cetveli' → 'cetvel', 'oyuncakları' → 'oyuncak'."""
    for ek in ("ları", "leri", "sı", "si", "su", "sü", "ı", "i", "u", "ü"):
        if kelime.endswith(ek) and len(kelime) - len(ek) >= 3:
            return kelime[: -len(ek)]
    return kelime


def _bas(baslik: str) -> str:
    """Başlığın ürün adı kısmı: ' - ', ' | ', '(' veya ',' sonrası (renk, açıklama) atılır."""
    bas = re.split(r"\s[-–—|]\s|\(|,|\s/\s", baslik or "")[0]
    return re.sub(r"\s+", " ", bas).strip()


def kelimeler(baslik: str) -> list[str]:
    kel = [_n(k) for k in re.findall(r"[a-zçğıöşü0-9]+", _kucuk(_bas(baslik)))]
    return [k for k in kel if len(k) >= 2 and k not in DURAK and k not in RENKLER]


def ayirt_edici(kel: list[str] | set[str]) -> set[str]:
    return {_kok(k) for k in kel if k not in GENEL and _kok(k) not in GENEL}


def gorunen_ad(baslik: str, site: str | None = None, cekirdek: set[str] | None = None) -> str:
    """Rapor adı: '3D Baskı' ve baştaki marka atılır ('UCSESUAR 3D Baskı Çok Bölmeli...' → 'Çok Bölmeli...')."""
    baslik = re.sub(r"^\s*[A-Za-zÇĞİÖŞÜçğıöşü0-9.]+:\s*", "", baslik or "")   # "PTTAVM: ..." → "..."
    baslik = re.sub(r"^\s*(?:genel\s+markalar|genel\s+tr|markas[ıi]z)\s+", "", baslik, flags=re.I)
    on = marka_kelimeleri({"title": baslik, "site": site}, cekirdek) or []   # ürün kelimesi marka sayılmaz
    if on:
        sozcukler = _bas(baslik).split()
        kalan = " ".join(sozcukler[len(on):])
        if len(kelimeler(kalan)) >= 2:
            baslik = kalan
    ad = re.sub(r"\b3\s?d\b\s*(?:bask[ıi](?:l[ıi]|s[ıi])?|yaz[ıi]c[ıi](?:\s+bask[ıi]s[ıi])?)?", " ",
                _bas(baslik), flags=re.I)
    ad = re.sub(r"\s+", " ", ad).strip(" -–—|")
    return (ad or _bas(baslik))[:70]


def site_adi(site: str | None) -> str:
    """'trendruum.com' ile 'trendruum' aynı satıcı."""
    return re.sub(r"\.(com|net|org)(\.tr)?$", "", (site or "").strip(), flags=re.I) or "?"


def satici(ilan: dict, cekirdek: set[str]) -> str:
    """İlanın satıcısı için anahtar. Pazar yeri başlıkları çoğunlukla markayla başlar
    ("Bezos 3D Baskı Dokunsal...", "MODA Sonsuz Küp..."): ürün kelimelerinden önceki kısım marka
    sayılır. Marka yoksa aynı sitede aynı başlık (renk hariç) aynı satıcı sayılır; bağımsız mağaza
    kendisidir. Böylece bir satıcının her renk için açtığı ayrı ilanlar tek sayılır."""
    site = site_adi(ilan.get("site"))
    if ilan.get("pazar_yeri") is False:
        return site.lower()
    on = marka_kelimeleri(ilan, cekirdek)
    if on:
        # Markanın ilk kelimesi: "WORK3D Kartal..." ile "WORK3D Pilli Kartal..." aynı satıcı.
        return f"{site.lower()}:{on[0]}"
    site_kel = set(re.findall(r"[a-z0-9]+", _n(_kucuk(site))))
    kel = [_n(k) for k in re.findall(r"[a-zçğıöşü0-9]+", _kucuk(ilan.get("ham_baslik") or ilan.get("title") or ""))]
    govde = [k for k in kel if k not in RENKLER and k not in site_kel]
    return f"{site.lower()}:{' '.join(govde)[:80]}"


def marka_kelimeleri(ilan: dict, cekirdek: set[str] | None = None) -> list[str] | None:
    """Başlığın başındaki marka/satıcı kelimeleri (en çok 3); yoksa None."""
    cekirdek = cekirdek or set()
    site_kel = set(re.findall(r"[a-z0-9]+", _n(_kucuk(site_adi(ilan.get("site"))))))
    kel = [_n(k) for k in re.findall(r"[a-zçğıöşü0-9]+", _kucuk(ilan.get("ham_baslik") or ilan.get("title") or ""))]
    on: list[str] = []
    for k in kel:
        if k in site_kel and not on:
            continue   # "PTTAVM: Northcity 3D Baskı ..." → site adı atlanır
        if (k in ("3d", "3", "boyutlu") or k.isdigit() or k in DURAK or k in GENEL or k in cekirdek
                or _kok(k) in cekirdek):
            break
        on.append(k)
    if not on or len(on) > 3 or on[0] in GENEL_MARKALAR:
        return None
    return on


def marka(ilan: dict) -> str | None:
    """Görünen satıcı/marka adı (başlıktaki yazılışıyla): 'Mays3Dstudio', 'Atatug'."""
    on = marka_kelimeleri(ilan)
    if not on:
        return None
    sozcukler = (ilan.get("ham_baslik") or ilan.get("title") or "").split()
    ilk = [w for w in sozcukler if _n(_kucuk(re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w)))][: len(on)]
    if [_n(_kucuk(re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w))) for w in ilk] == on:
        return " ".join(re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w) for w in ilk)
    return " ".join(w.capitalize() for w in on)


# ------------------------------------------------------------------ Trendyol yelpazesi
def trendyol_filtresi(yanit: dict) -> str | None:
    """Google Alışveriş yanıtındaki 'Mağazalar → Trendyol' süzgecinin belirteci (sorguya özel)."""
    for f in yanit.get("filters") or []:
        if _kucuk(f.get("type") or f.get("name") or "") not in ("mağazalar", "satıcılar", "stores", "sellers"):
            continue
        for o in f.get("options") or []:
            if _kucuk(o.get("text") or "") in ("trendyol", "trendyol.com") and o.get("shoprs"):
                return o["shoprs"]
    return None


def trendyol_ozeti(sorgu_ilanlari: dict[str, list[dict]]) -> dict:
    """{toplam, sorgular: [{sorgu, adet, fiyat_min, fiyat_medyan, fiyat_max, ornekler}], saticilar: [{ad, adet}]}"""
    goruldu: dict[str, dict] = {}
    sorgular_ = []
    for q, ilanlar in sorgu_ilanlari.items():
        fiyatlar = [i["price"] for i in ilanlar if i.get("price")]
        sorgular_.append({"sorgu": q, "adet": len(ilanlar),
                          "fiyat_min": min(fiyatlar) if fiyatlar else None,
                          "fiyat_medyan": round(statistics.median(fiyatlar)) if fiyatlar else None,
                          "fiyat_max": max(fiyatlar) if fiyatlar else None,
                          "ornekler": [{a: i.get(a) for a in ("title", "link", "price", "thumbnail")}
                                       | {"marka": marka(i)} for i in ilanlar[:5]]})
        for i in ilanlar:
            goruldu.setdefault(i["link"], i)
    sayac: Counter = Counter()
    yazilis: dict[str, Counter] = {}
    for i in goruldu.values():
        m = marka(i)
        if m:
            anahtar = _n(_kucuk(m.split()[0]))
            sayac[anahtar] += 1
            yazilis.setdefault(anahtar, Counter())[m.split()[0]] += 1
    return {"toplam": len(goruldu), "sorgular": sorgular_,
            "saticilar": [{"ad": yazilis[a].most_common(1)[0][0], "adet": n}
                          for a, n in sayac.most_common(10) if n >= 2]}


def trendyol_markdown(o: dict | None) -> list[str]:
    if not o or not o.get("toplam"):
        return []
    s = ["## Trendyol'da 3D baskı ürün yelpazesi", "",
         f"Google Alışveriş'in Trendyol süzgeciyle (Trendyol'a istek atılmadan) {o['toplam']} farklı 3D baskı ilanı.", "",
         "| Arama | Ürün | Fiyat aralığı | Ortanca |", "|---|---:|---|---:|"]
    for q in o["sorgular"]:
        aralik = f"{q['fiyat_min']:.0f}–{q['fiyat_max']:.0f} TL" if q.get("fiyat_min") else "-"
        s.append(f"| {q['sorgu']} | {q['adet']} | {aralik} | "
                 + (f"{q['fiyat_medyan']} TL" if q.get("fiyat_medyan") else "-") + " |")
    if o["saticilar"]:
        s += ["", "**En çok 3D baskı ürünü olan Trendyol satıcıları (rakipler):** "
              + ", ".join(f"{x['ad']} ({x['adet']})" for x in o["saticilar"])]
    s += ["", "### Kategoriye göre öne çıkan Trendyol ürünleri", ""]
    for q in o["sorgular"]:
        if not q["ornekler"]:
            continue
        s.append(f"**{q['sorgu']}**")
        for i in q["ornekler"]:
            link = pazar.satis_linki({**i, "site": "Trendyol"}) or i.get("link")
            s.append(f"- [{(i.get('title') or 'ürün')[:70]}]({link})"
                     + (f" — {i['price']:.0f} TL" if i.get("price") else ""))
        s.append("")
    return s


def trendyol_telegram(o: dict | None) -> str:
    if not o or not o.get("toplam"):
        return ""
    e_ = bildirim._e
    satir = [f"<b>🛍 Trendyol 3D yelpazesi</b> ({o['toplam']} ilan)"]
    for q in o["sorgular"]:
        if q["adet"]:
            satir.append(f"• {e_(q['sorgu'].replace('3d baskı ', ''))}: {q['adet']} ürün"
                         + (f" · ortanca {q['fiyat_medyan']} TL" if q.get("fiyat_medyan") else ""))
    if o["saticilar"]:
        satir.append("Rakipler: " + e_(", ".join(f"{x['ad']} ({x['adet']})" for x in o["saticilar"][:6])))
    return "\n".join(satir)


def saticilar(ilanlar: list[dict], cekirdek: set[str]) -> dict[str, int]:
    """{site: farklı satıcı sayısı}, çoktan aza."""
    gruplar: dict[str, set[str]] = {}
    for i in ilanlar:
        gruplar.setdefault(site_adi(i.get("site")), set()).add(satici(i, cekirdek))
    return dict(sorted(((s, len(v)) for s, v in gruplar.items()), key=lambda x: -x[1]))


def satici_sayisi(k: dict) -> int:
    return sum(saticilar(k["ilanlar"], k.get("cekirdek") or set()).values())


def benzer(a: set[str], b: set[str]) -> bool:
    """İki ilan aynı ürün mü (ayırt edici kelimelere göre)."""
    if not a or not b:
        return False
    ortak = len(a & b)
    if ortak == 0:
        return False
    kucuk = min(len(a), len(b))
    return ortak / len(a | b) >= 0.5 or (kucuk >= 2 and ortak == kucuk)


def kumele(ilanlar: list[dict]) -> list[dict]:
    """Aynı ürünün ilanlarını toplar. Küme: ad, anahtar, ilanlar, görsel, siteler, fiyatlar."""
    kumeler: list[dict] = []
    for ilan in ilanlar:
        kel = kelimeler(ilan.get("ham_baslik") or ilan.get("title") or "")
        ayirt = ayirt_edici(kel)
        if not ayirt:
            continue   # yalnızca "fidget oyuncak" gibi genel başlık: hangi ürün olduğu belli değil
        hedef = next((k for k in kumeler if any(benzer(ayirt, u) for u in k["_uyeler"])), None)
        if hedef is None:
            hedef = {"_uyeler": [], "ilanlar": [], "_kelimeler": []}
            kumeler.append(hedef)
        hedef["_uyeler"].append(ayirt)
        hedef["_kelimeler"].append(kel)
        if all(i["link"] != ilan["link"] for i in hedef["ilanlar"]):
            hedef["ilanlar"].append(ilan)
    # Sıra bağımlılığını gider: "Bezos ... Cetveli" ile "Nexora ... Cetveli" doğrudan benzemez ama
    # markasız "Dokunsal Fidget Cetveli" ikisine de benzer; böyle köprülenen kümeler birleşir.
    birlesti = True
    while birlesti:
        birlesti = False
        for i in range(len(kumeler)):
            for j in range(len(kumeler) - 1, i, -1):
                a, b = kumeler[i], kumeler[j]
                if any(benzer(x, y) for x in a["_uyeler"] for y in b["_uyeler"]):
                    a["_uyeler"] += b["_uyeler"]
                    a["_kelimeler"] += b["_kelimeler"]
                    a["ilanlar"] = _birlestir(a["ilanlar"], b["ilanlar"])
                    del kumeler[j]
                    birlesti = True
    for k in kumeler:
        # Ad: en kısa (markasız olma ihtimali en yüksek) başlık.
        def bas(i: dict) -> str:
            return i.get("ham_baslik") or i.get("title") or ""
        temsil = min(k["ilanlar"], key=lambda i: (len(kelimeler(bas(i))), len(bas(i))))
        k["anahtar"] = " ".join(sorted(ayirt_edici(kelimeler(bas(temsil)))))[:120]
        k["kelimeler"] = kelimeler(bas(temsil))
        k["ayirt"] = set().union(*k["_uyeler"])
        # Çekirdek (ürün kelimeleri): FARKLI kelimeyle başlayan en az 2 başlıkta geçen kelimeler.
        # Marka yalnızca kendi ilanlarında geçer ("WORK3D Kartal...", "WORK3D Pilli Kartal..." →
        # work3d çekirdek değil; "kartal" hem "Kartal Şeklinde..." hem "WORK3D Kartal..." → çekirdek).
        baslar: dict[str, set[str]] = {}
        for ayirt_, kel_ in zip(k["_uyeler"], k["_kelimeler"]):
            for x in ayirt_:
                baslar.setdefault(x, set()).add(kel_[0] if kel_ else "")
        k["cekirdek"] = {x for x, b in baslar.items() if len(b) >= 2}
        k["ad"] = gorunen_ad(bas(temsil), temsil.get("site"), k["cekirdek"])
        k["gorsel"] = next((i.get("thumbnail") for i in k["ilanlar"] if i.get("thumbnail")), None)
        del k["_uyeler"], k["_kelimeler"]
    return sorted(kumeler, key=lambda k: (-satici_sayisi(k), -len(k["ilanlar"])))


def _ilgili(baslik: str | None, ayirt: set[str]) -> bool:
    return bool(ayirt_edici(kelimeler(baslik or "")) & ayirt)


def lens_incele(yanit: dict, kume: dict) -> tuple[list[dict], list[dict]]:
    """Lens sonucu → (aynı ürünü satan Türk pazar yeri ilanları, model sayfaları)."""
    ilanlar, modeller = [], []
    for x in yanit.get("visual_matches") or []:
        link = pazar.guvenli_link(x.get("link"))
        if not link:
            continue
        sayfa = model_sayfasi(link)
        if sayfa:
            if model_ilgili_mi(x.get("title"), kume):   # şekli benzeyen başka model (ör. sabunluk) atlanır
                modeller.append({"site": sayfa[0], "id": sayfa[1], "link": link, "sira": x.get("position"),
                                 "title": pazar.temiz_baslik(x.get("title")), "thumbnail": x.get("thumbnail")})
        else:
            site = pazar.site_bul(link, x.get("source"))
            # Aynı şartlar: 3D baskı işareti olmalı (plastik enjeksiyon saksı vb. sayılmaz), dosya satışı değil.
            if (site and _ilgili(x.get("title"), kume["ayirt"]) and not pazar.dijital_site_mi(link)
                    and pazar.uc_d_mi(x.get("title"), x.get("source"), link)):
                f = x.get("price") if isinstance(x.get("price"), dict) else {}
                fiyat = f.get("extracted_value")
                ilanlar.append({"site": site, "title": pazar.temiz_baslik(x.get("title")), "link": link,
                                "price": float(fiyat) if fiyat is not None and pazar._tl_mi(f.get("currency"))
                                else None, "thumbnail": x.get("thumbnail"), "kaynak": "görsel"})
    return ilanlar, modeller


def _tr_en() -> dict[str, str]:
    sozluk: dict[str, str] = {}
    for en, tr in list(pazar.IFADELER.items()) + list(pazar.CEVIRI.items()):
        sozluk.setdefault(_n(_kucuk(tr)), en)
    sozluk.update({_n(k): v for k, v in TR_EN_EK.items()})
    return sozluk


def model_ilgili_mi(baslik: str | None, kume: dict) -> bool:
    """Model başlığı kümenin ayırt edici bir kelimesini (Türkçe veya İngilizce karşılığı) içeriyor mu."""
    sozluk = _tr_en()
    hedef = set(kume["ayirt"])
    for k in kume["ayirt"] | {_kok(x) for x in kume.get("kelimeler", [])}:
        en = sozluk.get(k)
        if en:
            hedef |= set(en.split())
    hedef -= {"fidget", "toy", "stress"}
    model = {_kok(x) for x in kelimeler(baslik or "")} | set(kelimeler(baslik or ""))
    return bool(model & hedef)


def ingilizce_kelimeler(kel: list[str]) -> tuple[list[str], list[str]]:
    """(ayırt edici, genel) İngilizce karşılıklar; bilinmeyen (marka vb.) kelimeler atılır."""
    sozluk, ingilizce = _tr_en(), set(pazar.CEVIRI) | {w for k in pazar.IFADELER for w in k.split()}
    ayirt, genel = [], []
    for k in kel:
        en = sozluk.get(k) or sozluk.get(_kok(k)) or (k if k in ingilizce and k.isascii() else None)
        if not en or en in ayirt + genel:
            continue
        (genel if k in GENEL or en in ("fidget", "toy", "stress") else ayirt).append(en)
    return ayirt, genel


def isim_uyar(baslik: str | None, ayirt_en: list[str]) -> bool:
    """MakerWorld model adı, aranan ayırt edici kelimelerin HEPSİNİ içeriyor mu (çoğul -s serbest).
    MakerWorld araması indirme sayısına göre sıraladığı için ilgisiz popüler modeller de gelir."""
    adlar = set(re.findall(r"[a-z0-9]+", (baslik or "").lower()))
    adlar |= {a[:-1] for a in adlar if a.endswith("s")}
    return bool(ayirt_en) and all(set(w.split()) <= adlar for w in ayirt_en)


def ingilizce_sorgu(kel: list[str], en_fazla: int = 3) -> str | None:
    """MakerWorld araması için İngilizce kelimeler; bilinmeyen (marka vb.) kelimeler atılır."""
    sozluk, ingilizce = _tr_en(), set(pazar.CEVIRI) | {w for k in pazar.IFADELER for w in k.split()}
    ayirt, genel = [], []
    for k in kel:
        en = sozluk.get(k) or sozluk.get(_kok(k)) or (k if k in ingilizce and k.isascii() else None)
        if not en or en in ayirt + genel:
            continue
        (genel if k in GENEL or en in ("fidget", "toy", "stress") else ayirt).append(en)
    secilen = (ayirt + genel)[:en_fazla]
    if not ayirt:
        return None   # yalnızca "fidget toy" gibi genel: isimle aramak anlamsız
    return " ".join(dict.fromkeys(" ".join(secilen).split()))


def _medyan(ilanlar: list[dict]) -> float | None:
    fiyatlar = [i["price"] for i in ilanlar if i.get("price")]
    return round(statistics.median(fiyatlar), 2) if fiyatlar else None


def model_ozeti(u: dict, eslesme: str, medyan: float | None, lens_sira: int | None = None) -> dict:
    kar = round(medyan - u["cost_tl"], 0) if medyan and u.get("cost_tl") is not None else None
    saat = (u.get("print_time_min") or 0) / 60
    return {"external_id": u["external_id"], "name": u["name"], "url": u["url"], "image_url": u.get("image_url"),
            "creator": u.get("creator"), "downloads": u.get("downloads"), "likes": u.get("likes"),
            "print_time_min": u.get("print_time_min"), "weight_g": u.get("weight_g"), "cost_tl": u.get("cost_tl"),
            "color_count": u.get("color_count"), "eslesme": eslesme, "lens_sira": lens_sira,
            "kar_tl": kar, "saatlik_kar_tl": round(kar / saat, 0) if kar is not None and saat > 0 else None}


def makerworld_eslestir(kaynak: mw.MakerWorldKaynak, kume: dict, modeller: list[dict],
                        medyan: float | None) -> tuple[list[dict], list[dict]]:
    """(özetler, products tablosuna yazılacak ürünler). Önce görsel eşleşmeler, sonra isimle arama."""
    hedefler: list[tuple[str, str, int | None]] = []
    for m in modeller:
        if m["site"] == "MakerWorld" and all(h[0] != m["id"] for h in hedefler) and len([h for h in hedefler if h[1] == "görsel"]) < config.KESIF_GORSEL_ESLESME:
            hedefler.append((m["id"], "görsel", m.get("sira")))
    # İsimle arama yalnızca en az 2 ayırt edici kelime varsa ("cute cat planter" evet, tek başına
    # "keychain" hayır: her anahtarlık eşleşirdi).
    ayirt_en = ingilizce_kelimeler(kume["kelimeler"])[0]
    sorgu = ingilizce_sorgu(kume["kelimeler"]) if len(ayirt_en) >= 2 else None
    if sorgu:
        try:
            isim = 0
            for hit in kaynak.ara(sorgu, adet=30, gun=None):
                if isim >= config.KESIF_ISIM_ESLESME:
                    break
                if not isim_uyar(hit.get("title"), ayirt_en):
                    continue
                if hit.get("id") and not mw._atlanacak(hit) and all(str(hit["id"]) != h[0] for h in hedefler):
                    hedefler.append((str(hit["id"]), "isim", None))
                    isim += 1
        except (mw.MakerWorldHatasi, httpx.HTTPError) as e:
            print(f"UYARI: MakerWorld araması ({sorgu}): {e}")
    kume["mw_sorgu"] = sorgu
    ozetler, urunler = [], []
    for tid, tur, sira in hedefler:
        try:
            tasarim = kaynak.detay(tid)
        except (mw.MakerWorldHatasi, httpx.HTTPError):
            continue
        if not isinstance(tasarim, dict) or not tasarim.get("id") or mw._atlanacak(tasarim):
            continue
        u = mw.urune_cevir(tasarim, KATEGORI)
        urunler.append(u)
        ozetler.append(model_ozeti(u, tur, medyan, sira))
    return ozetler, urunler


def sorgular(bugun: date) -> list[str]:
    ek = [f"3d baskı {s.ad.lower()}" for s, _ in sezon.aktif_sezonlar(bugun)]
    return list(dict.fromkeys(config.KESIF_SORGULARI + ek))


def zamani_geldi(depo, bugun: date) -> bool:
    son = depo.kesif_son_tarih()
    return son is None or (bugun - date.fromisoformat(str(son)[:10])).days >= config.KESIF_ARALIK_GUN


def _ilanlar(yanit: dict, q: str) -> list[dict]:
    ham = {}
    for x in yanit.get("shopping_results") or []:
        link = pazar.guvenli_link(x.get("link")) or pazar.guvenli_link(x.get("product_link"))
        ham.setdefault(link, x.get("title"))
    return [{**i, "sorgu": q, "ham_baslik": ham.get(i["link"])} for i in pazar.alisveris_sonuclari(yanit)]


def kesfet(depo, api_key: str, bugun: date, kaynak: mw.MakerWorldKaynak | None = None,
           client: httpx.Client | None = None) -> tuple[list[dict], dict | None]:
    """Keşfi yapar, veritabanına yazar; (kümeler, Trendyol özeti) döndürür."""
    kaynak = kaynak or mw.MakerWorldKaynak()
    ilanlar: list[dict] = []
    trendyol: dict[str, list[dict]] = {}
    for q in sorgular(bugun):
        yanit = pazar.alisveris_ara(api_key, q, client)
        ilanlar += _ilanlar(yanit, q)
        belirtec = trendyol_filtresi(yanit) if config.KESIF_TRENDYOL else None
        if belirtec:
            try:
                ty = pazar._istek(api_key, {"engine": "google_shopping", "q": q, "gl": "tr", "hl": "tr",
                                            "shoprs": belirtec}, client)
                trendyol[q] = [i for i in _ilanlar(ty, q) if site_adi(i["site"]) == "Trendyol"]
                ilanlar += trendyol[q]
            except (pazar.PazarHatasi, httpx.HTTPError) as e:
                print(f"UYARI: Trendyol süzgeçli arama ({q}): {e}")
    ilanlar = _birlestir(ilanlar, [])
    kumeler = [k for k in kumele(ilanlar) if len(k["ilanlar"]) >= config.KESIF_EN_AZ_ILAN
               and satici_sayisi(k) >= config.KESIF_EN_AZ_SATICI]
    kumeler = kumeler[: config.KESIF_RAPOR_ADET]

    en_erken = (bugun - timedelta(days=config.KESIF_YENILEME_GUN)).isoformat()
    try:
        onceki = depo.kesif_onceki([k["anahtar"] for k in kumeler], en_erken)
    except Exception as e:  # noqa: BLE001 — tablo yoksa önbelleksiz devam
        print(f"UYARI: Önceki keşif kayıtları okunamadı: {e}")
        onceki = {}
    lens_hakki = config.KESIF_LENS_ADET
    tum_urunler: list[dict] = []
    for k in kumeler:
        eski = onceki.get(k["anahtar"])
        modeller: list[dict] = []
        if eski and eski.get("lens_yapildi"):
            k["lens_yapildi"] = True
            k["ilanlar"] = _birlestir(k["ilanlar"], eski.get("ilanlar") or [])
            modeller = eski.get("diger_kaynaklar") or []
        elif lens_hakki > 0 and k.get("gorsel"):
            lens_hakki -= 1
            try:
                yanit = pazar._istek(api_key, {"engine": "google_lens", "url": k["gorsel"], "hl": "tr",
                                               "country": "tr"}, client)
                lens_ilan, modeller = lens_incele(yanit, k)
                k["ilanlar"] = _birlestir(k["ilanlar"], lens_ilan)
                k["lens_yapildi"] = True
            except (pazar.PazarHatasi, httpx.HTTPError) as e:
                print(f"UYARI: Lens ({k['ad']}): {e}")
        k["siteler"] = saticilar(k["ilanlar"], k["cekirdek"])   # site başına farklı satıcı
        k["satici_sayisi"] = sum(k["siteler"].values())
        fiyatlar = [i["price"] for i in k["ilanlar"] if i.get("price")]
        k["fiyat_min"], k["fiyat_max"] = (min(fiyatlar), max(fiyatlar)) if fiyatlar else (None, None)
        k["fiyat_medyan"] = _medyan(k["ilanlar"])
        k["diger_kaynaklar"] = modeller
        k["eslesmeler"], urunler = makerworld_eslestir(kaynak, k, modeller, k["fiyat_medyan"])
        tum_urunler += urunler
    kumeler.sort(key=lambda k: (-k["satici_sayisi"], -len(k["ilanlar"])))

    if tum_urunler:
        try:
            idler = depo.urunleri_kaydet(list({u["external_id"]: u for u in tum_urunler}.values()))
            for k in kumeler:
                for e in k["eslesmeler"]:
                    e["product_id"] = idler.get((mw.KAYNAK_ID, e["external_id"]))
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: Eşleşen modeller kaydedilemedi: {e}")
    try:
        depo.kesif_kaydet([satir(bugun, k) for k in kumeler])
    except Exception as e:  # noqa: BLE001 — rapor ve Telegram yine çıkar
        print(f"UYARI: Keşif kaydedilemedi: {e}\n"
              "Supabase'te supabase/guncelleme_2026-11-10_kesif.sql çalıştırıldı mı?")
    return kumeler, (trendyol_ozeti(trendyol) if trendyol else None)


def _birlestir(a: list[dict], b: list[dict]) -> list[dict]:
    goruldu, sonuc = set(), []
    for i in a + b:
        if i.get("link") and i["link"] not in goruldu:
            goruldu.add(i["link"])
            sonuc.append(i)
    return sonuc


def satir(bugun: date, k: dict) -> dict:
    return {"kesif_tarihi": bugun.isoformat(), "anahtar": k["anahtar"], "ad": k["ad"],
            "ilan_sayisi": len(k["ilanlar"]), "siteler": k.get("siteler") or {},
            "fiyat_min": k.get("fiyat_min"), "fiyat_medyan": k.get("fiyat_medyan"), "fiyat_max": k.get("fiyat_max"),
            "gorsel": k.get("gorsel"), "sorgu": k["ilanlar"][0].get("sorgu") if k["ilanlar"] else None,
            "lens_yapildi": bool(k.get("lens_yapildi")), "mw_sorgu": k.get("mw_sorgu"),
            "ilanlar": [{a: i.get(a) for a in ("site", "title", "link", "price", "kaynak")} for i in k["ilanlar"][:20]],
            "eslesmeler": k.get("eslesmeler") or [], "diger_kaynaklar": k.get("diger_kaynaklar") or []}


# ------------------------------------------------------------------ çıktı
def _sure(dk: int | None) -> str:
    from .analiz import sure_yazi
    return sure_yazi(dk)


def _fiyat_araligi(k: dict) -> str:
    if not k.get("fiyat_medyan"):
        return "fiyat yok"
    return f"{k['fiyat_min']:.0f}–{k['fiyat_max']:.0f} TL (ortanca {k['fiyat_medyan']:.0f} TL)"


def _model_satiri(e: dict) -> str:
    parca = [f"{_sure(e.get('print_time_min'))} baskı"]
    if e.get("cost_tl") is not None:
        parca.append(f"maliyet ~{e['cost_tl']:.0f} TL")
    if e.get("kar_tl") is not None:
        parca.append(f"ilan başına ~{e['kar_tl']:.0f} TL kâr"
                     + (f" (saatte ~{e['saatlik_kar_tl']:.0f} TL)" if e.get("saatlik_kar_tl") else ""))
    return " · ".join(parca)


ESLESME_ETIKETI = {"görsel": "🎯 görsel eşleşme", "isim": "🔤 isimle bulundu (görseli karşılaştır)"}


def markdown(bugun: date, kumeler: list[dict], trendyol: dict | None = None) -> str:
    s = [f"# Türkiye'de çok satan 3D baskılar → MakerWorld — {bugun.isoformat()}", "",
         "Google Alışveriş'teki 3D baskı ilanları ürün ürün kümelendi. **Satıcı sayısı** = aynı ürünü satan "
         "farklı satıcılar (başlıktaki markaya göre; bir satıcının renk ilanları tek sayılır). Satış adedi "
         "değil, talep işaretidir. "
         "🎯 görsel eşleşme: ürünün fotoğrafı MakerWorld'deki modele götürdü. 🔤 isimle bulundu: "
         "görselleri karşılaştırıp doğrula. Kâr = piyasa ortancası − maliyet (kaba tahmin).", ""]
    for n, k in enumerate(kumeler, 1):
        s += [f"## {n}. {k['ad']} — {k['satici_sayisi']} satıcı, {len(k['ilanlar'])} ilan", ""]
        if k.get("gorsel"):
            s += [f"![{k['ad']}]({k['gorsel']})", ""]
        s.append(f"- **Satıcılar:** " + ", ".join(f"{a} {b}" for a, b in k["siteler"].items()))
        s.append(f"- **Fiyat:** {_fiyat_araligi(k)}")
        for i in k["ilanlar"][:4]:
            s.append(f"  - {i['site']}: [{(i.get('title') or 'ilan')[:60]}]({pazar.satis_linki(i) or i['link']})"
                     + (f" — {i['price']:.0f} TL" if i.get("price") else ""))
        if k.get("eslesmeler"):
            s.append("- **MakerWorld:**")
            for e in k["eslesmeler"]:
                s.append(f"  - {ESLESME_ETIKETI[e['eslesme']]}: [{e['name'][:70]}]({e['url']}) — {_model_satiri(e)}")
        else:
            s.append("- **MakerWorld:** eşleşen model bulunamadı"
                     + (f" (aranan: \"{k['mw_sorgu']}\")" if k.get("mw_sorgu") else ""))
        diger = [m for m in k.get("diger_kaynaklar") or [] if m["site"] != "MakerWorld"]
        if diger:
            s.append("- **Diğer model siteleri (görsel eşleşme):** "
                     + ", ".join(f"[{m['site']}]({m['link']})" for m in diger[:3]))
        s.append("")
    s += trendyol_markdown(trendyol)
    return "\n".join(s)


def telegram_mesaji(bugun: date, kumeler: list[dict], panel_url: str | None = None, sinir: int = 4096,
                    trendyol: dict | None = None) -> str | None:
    if not kumeler:
        return None
    e_ = bildirim._e
    metin = f"<b>🔥 Türkiye'de çok satan 3D baskılar → MakerWorld</b> ({bugun.isoformat()})\n<i>satıcı = aynı ürünü satan farklı satıcı</i>"
    for n, k in enumerate(kumeler, 1):
        siteler = ", ".join(f"{a} {b}" for a, b in list(k["siteler"].items())[:4])
        p = [f"<b>{n}. {e_(k['ad'])}</b> — {k['satici_sayisi']} satıcı ({e_(siteler)})",
             f"   💰 {e_(_fiyat_araligi(k))}"]
        for e in k.get("eslesmeler", [])[:2]:
            isaret = "🎯" if e["eslesme"] == "görsel" else "🔤"
            p.append(f"   {isaret} <a href=\"{bildirim._href(e['url'])}\">{e_(e['name'][:50])}</a> · {e_(_model_satiri(e))}")
        if not k.get("eslesmeler"):
            p.append("   MakerWorld'de eşleşme yok")
        parca = "\n".join(p)
        if len(metin) + len(parca) + 80 > sinir:
            break
        metin += "\n\n" + parca
    metin += "\n\n🎯 görselle eşleşti · 🔤 isimle bulundu, görseli kontrol et"
    ty = trendyol_telegram(trendyol)
    if ty and len(metin) + len(ty) + 120 <= sinir:
        metin += "\n\n" + ty
    if panel_url:
        metin += f"\n📊 Panelde görseller yan yana: {e_(panel_url)}"
    return metin


def calistir(depo, ayarlar: config.Ayarlar, bugun: date, kaynak: mw.MakerWorldKaynak | None = None,
             zorla: bool = False, client: httpx.Client | None = None
             ) -> tuple[list[dict], str | None, dict | None]:
    """Zamanı geldiyse ve kota yetiyorsa keşif. (kümeler, rapor yolu, Trendyol özeti)."""
    if not ayarlar.serpapi_key:
        return [], None, None
    if not zorla:
        try:
            if not zamani_geldi(depo, bugun):
                return [], None, None
        except Exception as e:  # noqa: BLE001 — tablo yoksa her gün kota harcanmasın
            print(f"Pazar keşfi atlandı: kayıt tablosu okunamadı ({str(e)[:120]}). "
                  "Supabase'te supabase/guncelleme_2026-11-10_kesif.sql çalıştırıldı mı?")
            return [], None, None
    kalan = pazar.kalan_hak(ayarlar.serpapi_key, client)
    if kalan is None or kalan < config.KESIF_KOTA_ESIGI:
        print(f"Pazar keşfi atlandı: SerpApi'de kalan hak {kalan} (en az {config.KESIF_KOTA_ESIGI} gerekli).")
        return [], None, None
    kumeler, trendyol = kesfet(depo, ayarlar.serpapi_key, bugun, kaynak, client)
    config.RAPOR_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = config.RAPOR_KLASORU / f"cok-satanlar-{bugun.isoformat()}.md"
    yol.write_text(markdown(bugun, kumeler, trendyol), encoding="utf-8")
    print(f"Pazar keşfi: {len(kumeler)} çok satan ürün, "
          f"{sum(1 for k in kumeler if any(e['eslesme'] == 'görsel' for e in k['eslesmeler']))} görsel eşleşme → {yol}")
    if trendyol:
        print(f"Trendyol yelpazesi: {trendyol['toplam']} ilan, {len(trendyol['saticilar'])} rakip satıcı")
    return kumeler, str(yol), trendyol


def ana() -> int:
    from .db import depo_olustur
    ayarlar = config.ayarlari_oku()
    if not ayarlar.serpapi_key:
        print("SERPAPI_KEY yok; pazar keşfi yapılamaz.")
        return 1
    depo = depo_olustur(ayarlar)
    bugun = datetime.now(timezone.utc).date()
    kumeler, _, trendyol = calistir(depo, ayarlar, bugun, zorla=True)
    mesaj = telegram_mesaji(bugun, kumeler, ayarlar.panel_url or None, trendyol=trendyol)
    if mesaj and ayarlar.telegram_token and ayarlar.telegram_chat_id and "--telegram" in sys.argv:
        bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id,
                        [{"metot": "sendMessage", "veri": {"text": mesaj, "disable_web_page_preview": True}}])
        print("Telegram'a gönderildi.")
    return 0


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(ana())
