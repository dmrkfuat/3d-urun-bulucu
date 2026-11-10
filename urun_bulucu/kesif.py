"""Pazar keşfi: Türkiye'de çok satan 3D baskı ürünler → MakerWorld'deki birebir modeli.

Günlük analizin tersi: MakerWorld'de popüler olandan değil, Türkiye'de SATILANDAN başlar.

1. Google Alışveriş'te (SerpApi) kategori aramaları: "3d baskı fidget", "3d baskı saksı"...
   Yalnızca 3D baskı fiziksel ürünler tutulur (pazar.alisveris_sonuclari).
2. Aynı ürünün ilanları kümelenir. Google Alışveriş satış adedi/yorum vermez; çok satanın en
   güçlü işareti, aynı ürünü KAÇ AYRI İLANIN satmasıdır (satıcılar satan ürünü kopyalar).
3. En çok ilanı olan kümelerin görseliyle Google Lens: (a) aynı ürünü satan diğer Türk pazar
   yeri ilanları sayılır, (b) sonuçlarda MakerWorld/Printables model sayfası çıkarsa o modelin
   kaynağıdır ("görsel eşleşme"; birebir model).
4. Ayrıca ürün adının İngilizcesiyle MakerWorld'de ücretsiz arama ("isim eşleşmesi"; panelde
   görseller yan yana gösterilir, sen doğrularsın).
5. Eşleşen modellerin baskı süresi/maliyeti MakerWorld'den alınır; piyasa ortanca fiyatıyla
   ilan başına ve saat başına kâr hesaplanır.

Haftada bir (KESIF_ARALIK_GUN) günlük analizle birlikte çalışır; elle: python -m urun_bulucu.kesif
SerpApi kotası: hafta başına ~len(sorgular) + KESIF_LENS_ADET arama (ayda ~70).
"""
from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

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
# Pazar yeri başlıklarında sık geçen, CEVIRI'de olmayan Türkçe kelimeler → İngilizce.
TR_EN_EK = {
    "cetvel": "ruler", "top": "ball", "topu": "ball", "yumurta": "egg", "yumurtası": "egg",
    "figür": "figure", "heykel": "statue", "stres": "stress", "çark": "spinner", "çarklı": "spinner",
    "şemsiye": "umbrella", "dokunsal": "tactile", "katlanabilir": "folding", "kaydırmalı": "slider",
    "kalemlik": "pen holder", "kulaklık": "headphone", "kartvizitlik": "card holder", "zar": "dice",
    "kumbara": "piggy bank", "lamba": "lamp", "abajur": "lamp", "isimlik": "name plate",
    "anahtarlık": "keychain", "saksı": "planter", "vazo": "vase", "mumluk": "candle holder",
}
MODEL_SAYFASI = [
    ("MakerWorld", re.compile(r"makerworld\.com/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?models/(\d+)", re.I)),
    ("Printables", re.compile(r"printables\.com/(?:[a-z]{2}/)?model/(\d+)", re.I)),
    ("Thingiverse", re.compile(r"thingiverse\.com/thing:(\d+)", re.I)),
    ("Cults3D", re.compile(r"cults3d\.com/[a-z]{2}/(?:3d-model|3d-print|3d-bask%C4%B1|3d-baskı|modelo-3d)/"
                           r"[^/]+/([^/?#]+)", re.I)),
]


def _kucuk(metin: str) -> str:
    return (metin or "").replace("I", "ı").replace("İ", "i").lower()


def _n(kelime: str) -> str:
    """Karşılaştırma biçimi: ı → i (İngilizce 'Infinity' ile Türkçe 'KIRMIZI' aynı kurala uysun)."""
    return kelime.replace("ı", "i")


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


def gorunen_ad(baslik: str) -> str:
    ad = re.sub(r"\b3\s?d\b\s*(?:bask[ıi](?:l[ıi]|s[ıi])?|yaz[ıi]c[ıi](?:\s+bask[ıi]s[ıi])?)?", " ",
                _bas(baslik), flags=re.I)
    ad = re.sub(r"\s+", " ", ad).strip(" -–—|")
    return (ad or _bas(baslik))[:70]


def site_adi(site: str | None) -> str:
    """'trendruum.com' ile 'trendruum' aynı satıcı."""
    return re.sub(r"\.(com|net|org)(\.tr)?$", "", (site or "").strip(), flags=re.I) or "?"


def talep_puani(ilanlar: list[dict]) -> int:
    """Sıralama: her siteden en fazla 5 ilan sayılır (tek mağazanın 14 farklı ürünü talep değildir)."""
    return sum(min(n, 5) for n in Counter(site_adi(i.get("site")) for i in ilanlar).values())


def site_sayisi(ilanlar: list[dict]) -> int:
    return len({site_adi(i.get("site")) for i in ilanlar})


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
    for k in kumeler:
        # Ad: en kısa (markasız olma ihtimali en yüksek) başlık.
        def bas(i: dict) -> str:
            return i.get("ham_baslik") or i.get("title") or ""
        temsil = min(k["ilanlar"], key=lambda i: (len(kelimeler(bas(i))), len(bas(i))))
        k["ad"] = gorunen_ad(bas(temsil))
        k["anahtar"] = " ".join(sorted(ayirt_edici(kelimeler(bas(temsil)))))[:120]
        k["kelimeler"] = kelimeler(bas(temsil))
        k["ayirt"] = set().union(*k["_uyeler"])
        k["gorsel"] = next((i.get("thumbnail") for i in k["ilanlar"] if i.get("thumbnail")), None)
        del k["_uyeler"], k["_kelimeler"]
    return sorted(kumeler, key=lambda k: (-talep_puani(k["ilanlar"]), -len(k["ilanlar"])))


def _ilgili(baslik: str | None, ayirt: set[str]) -> bool:
    return bool(ayirt_edici(kelimeler(baslik or "")) & ayirt)


def lens_incele(yanit: dict, kume: dict) -> tuple[list[dict], list[dict]]:
    """Lens sonucu → (aynı ürünü satan Türk pazar yeri ilanları, model sayfaları)."""
    ilanlar, modeller = [], []
    for x in yanit.get("visual_matches") or []:
        link = pazar.guvenli_link(x.get("link"))
        if not link:
            continue
        for site, desen in MODEL_SAYFASI:
            m = desen.search(link)
            if m:
                if not model_ilgili_mi(x.get("title"), kume):
                    break   # şekli benzeyen başka model (ör. sabunluk)
                modeller.append({"site": site, "id": m.group(1), "link": link, "sira": x.get("position"),
                                 "title": pazar.temiz_baslik(x.get("title")), "thumbnail": x.get("thumbnail")})
                break
        else:
            site = pazar.site_bul(link, x.get("source"))
            if site and _ilgili(x.get("title"), kume["ayirt"]) and not pazar.dijital_site_mi(link):
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
        if m["site"] == "MakerWorld" and len([h for h in hedefler if h[1] == "görsel"]) < config.KESIF_GORSEL_ESLESME:
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


def kesfet(depo, api_key: str, bugun: date, kaynak: mw.MakerWorldKaynak | None = None,
           client: httpx.Client | None = None) -> list[dict]:
    """Keşfi yapar, veritabanına yazar; rapor için kümeleri döndürür."""
    kaynak = kaynak or mw.MakerWorldKaynak()
    ilanlar = []
    for q in sorgular(bugun):
        yanit = pazar.alisveris_ara(api_key, q, client)
        ham = {}
        for x in yanit.get("shopping_results") or []:
            link = pazar.guvenli_link(x.get("link")) or pazar.guvenli_link(x.get("product_link"))
            ham.setdefault(link, x.get("title"))
        for i in pazar.alisveris_sonuclari(yanit):
            ilanlar.append({**i, "sorgu": q, "ham_baslik": ham.get(i["link"])})
    kumeler = [k for k in kumele(ilanlar) if len(k["ilanlar"]) >= config.KESIF_EN_AZ_ILAN
               and site_sayisi(k["ilanlar"]) >= config.KESIF_EN_AZ_SITE]
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
        k["siteler"] = dict(Counter(site_adi(i["site"]) for i in k["ilanlar"]).most_common())
        fiyatlar = [i["price"] for i in k["ilanlar"] if i.get("price")]
        k["fiyat_min"], k["fiyat_max"] = (min(fiyatlar), max(fiyatlar)) if fiyatlar else (None, None)
        k["fiyat_medyan"] = _medyan(k["ilanlar"])
        k["diger_kaynaklar"] = modeller
        k["eslesmeler"], urunler = makerworld_eslestir(kaynak, k, modeller, k["fiyat_medyan"])
        tum_urunler += urunler
    kumeler.sort(key=lambda k: (-talep_puani(k["ilanlar"]), -len(k["ilanlar"])))

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
    return kumeler


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


def markdown(bugun: date, kumeler: list[dict]) -> str:
    s = [f"# Türkiye'de çok satan 3D baskılar → MakerWorld — {bugun.isoformat()}", "",
         "Google Alışveriş'teki 3D baskı ilanları ürün ürün kümelendi. **İlan sayısı** = aynı ürünü satan "
         "ayrı ilanlar (Google Alışveriş + görsel arama); satış adedi değil, talep işaretidir. "
         "🎯 görsel eşleşme: ürünün fotoğrafı MakerWorld'deki modele götürdü. 🔤 isimle bulundu: "
         "görselleri karşılaştırıp doğrula. Kâr = piyasa ortancası − maliyet (kaba tahmin).", ""]
    for n, k in enumerate(kumeler, 1):
        s += [f"## {n}. {k['ad']} — {len(k['ilanlar'])} ilan", ""]
        if k.get("gorsel"):
            s += [f"![{k['ad']}]({k['gorsel']})", ""]
        s.append(f"- **Satıldığı yerler:** " + ", ".join(f"{a} {b}" for a, b in k["siteler"].items()))
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
    return "\n".join(s)


def telegram_mesaji(bugun: date, kumeler: list[dict], panel_url: str | None = None, sinir: int = 4096) -> str | None:
    if not kumeler:
        return None
    e_ = bildirim._e
    metin = f"<b>🔥 Türkiye'de çok satan 3D baskılar → MakerWorld</b> ({bugun.isoformat()})\n<i>ilan sayısı = aynı ürünü satan ayrı ilan</i>"
    for n, k in enumerate(kumeler, 1):
        p = [f"<b>{n}. {e_(k['ad'])}</b> — {len(k['ilanlar'])} ilan ({e_(', '.join(list(k['siteler'])[:4]))})",
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
    if panel_url:
        metin += f"\n📊 Panelde görseller yan yana: {e_(panel_url)}"
    return metin


def calistir(depo, ayarlar: config.Ayarlar, bugun: date, kaynak: mw.MakerWorldKaynak | None = None,
             zorla: bool = False, client: httpx.Client | None = None) -> tuple[list[dict], str | None]:
    """Zamanı geldiyse ve kota yetiyorsa keşif. (kümeler, rapor yolu)."""
    if not ayarlar.serpapi_key:
        return [], None
    if not zorla:
        try:
            if not zamani_geldi(depo, bugun):
                return [], None
        except Exception as e:  # noqa: BLE001 — tablo yoksa her gün kota harcanmasın
            print(f"Pazar keşfi atlandı: kayıt tablosu okunamadı ({str(e)[:120]}). "
                  "Supabase'te supabase/guncelleme_2026-11-10_kesif.sql çalıştırıldı mı?")
            return [], None
    kalan = pazar.kalan_hak(ayarlar.serpapi_key, client)
    if kalan is None or kalan < config.KESIF_KOTA_ESIGI:
        print(f"Pazar keşfi atlandı: SerpApi'de kalan hak {kalan} (en az {config.KESIF_KOTA_ESIGI} gerekli).")
        return [], None
    kumeler = kesfet(depo, ayarlar.serpapi_key, bugun, kaynak, client)
    config.RAPOR_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = config.RAPOR_KLASORU / f"cok-satanlar-{bugun.isoformat()}.md"
    yol.write_text(markdown(bugun, kumeler), encoding="utf-8")
    print(f"Pazar keşfi: {len(kumeler)} çok satan ürün, "
          f"{sum(1 for k in kumeler if any(e['eslesme'] == 'görsel' for e in k['eslesmeler']))} görsel eşleşme → {yol}")
    return kumeler, str(yol)


def ana() -> int:
    from .db import depo_olustur
    ayarlar = config.ayarlari_oku()
    if not ayarlar.serpapi_key:
        print("SERPAPI_KEY yok; pazar keşfi yapılamaz.")
        return 1
    depo = depo_olustur(ayarlar)
    bugun = datetime.now(timezone.utc).date()
    kumeler, _ = calistir(depo, ayarlar, bugun, zorla=True)
    mesaj = telegram_mesaji(bugun, kumeler, ayarlar.panel_url or None)
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
