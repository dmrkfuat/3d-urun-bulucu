"""Trendyol 3D mağaza analizi: en çok satan 3D baskı ürünler, aktif 3D mağazaları → MakerWorld modeli.

Kurallar (değiştirmeyin):
- Yalnızca Trendyol'un robots.txt dosyasında AÇIK olan ürün sayfaları (/<marka>/<ad>-p-<no>) okunur.
  Arama (/sr), mağaza (/magaza/... → kapalı ?sst= adresine yönlenir), sıralama (?sst=) ve
  /genel-markalar/ sayfaları kapalıdır; okunmaz. robots.txt her çalışmada yeniden okunur.
- Kimlik gizlenmez (TRENDYOL_UA), tarayıcı taklidi yoktur; sayfalar arası TRENDYOL_BEKLEME_SN beklenir.
- 403/429 veya doğrulama (captcha) sayfası görülürse o hafta durulur; engel aşılmaya çalışılmaz.
- Mağaza sahibinin kişisel bilgileri (resmi ad, e-posta, vergi no) sayfada olsa da alınmaz.

Akış (haftada bir):
1. Okunacak ürünler: geçen haftalarda takip edilenler (yeniden), elle eklenenler (TRENDYOL_TOHUMLAR),
   pazar keşfinin Lens sonuçlarındaki Trendyol ürünleri, okunan sayfalardaki "benzer ürünler"den
   3D baskı olanlar (başka 3D mağazalarına böyle ulaşılır).
2. Her üründen: mağaza, marka, kategori, fiyat, değerlendirme ve favori sayısı (sayfanın yapılandırılmış
   verisi). İki hafta arasındaki artış = SATIŞ HIZI (değerlendirme, satışla en çok örtüşen açık veridir).
3. En çok satanlar ve aktif mağazalar sıralanır; ilk ürünler için MakerWorld'de model aranır
   (isimle ücretsiz; ilk TRENDYOL_LENS_ADET ürün görselle Lens'te — birebir model ve aynı ürünü
   satan diğer Trendyol mağazaları).

Elle: python -m urun_bulucu.trendyol [--telegram] [--sinir 40]
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from . import bildirim, config, kesif, pazar
from .kaynaklar import makerworld as mw

KOK = "https://www.trendyol.com"
URUN_YOLU = re.compile(r"^/([a-z0-9-]+)/([a-z0-9-]+)-p-(\d+)$")
BENZER = re.compile(r"(?:https://www\.trendyol\.com)?(/[a-z0-9-]+/[a-z0-9-]+-p-\d+)(?!\d)")
LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
FAVORI = re.compile(r'"favoriteCount":(\d+)')
SATICI = re.compile(r'"merchant":\{"id":(\d+),"name":"((?:[^"\\]|\\.)*)"')
KATEGORI = re.compile(r'"category":\{"id":\d+,"name":"((?:[^"\\]|\\.)*)","hierarchy":"((?:[^"\\]|\\.)*)"')
HARIC_MARKALAR = {"genel-markalar", "generic-brand"}
DOGRULAMA = re.compile(r"captcha|robot olmad|challenge-platform|access denied", re.I)


class TrendyolEngel(Exception):
    """Trendyol isteği engelledi; o hafta durulur."""


# ------------------------------------------------------------------ robots.txt
class Robots:
    """robots.txt ('*' grubu): en uzun eşleşen kural geçerli, eşitlikte Allow (Google kuralları)."""

    def __init__(self, metin: str) -> None:
        gruplar: list[tuple[list[str], list[tuple[bool, str]]]] = []
        ajanlar: list[str] = []
        kurallar: list[tuple[bool, str]] | None = None
        for satir in metin.splitlines():
            satir = satir.split("#", 1)[0].strip()
            if ":" not in satir:
                continue
            alan, deger = (x.strip() for x in satir.split(":", 1))
            alan = alan.lower()
            if alan == "user-agent":
                if kurallar is not None:          # kurallardan sonra gelen user-agent yeni grup açar
                    gruplar.append((ajanlar, kurallar))
                    ajanlar, kurallar = [], None
                ajanlar.append(deger.lower())
            elif alan in ("allow", "disallow"):
                kurallar = kurallar if kurallar is not None else []
                if deger:
                    kurallar.append((alan == "allow", deger))
        if ajanlar:
            gruplar.append((ajanlar, kurallar or []))
        self.kurallar = [k for a, ks in gruplar if "*" in a for k in ks]
        self._derli = [(izin, len(d), self._regex(d)) for izin, d in self.kurallar]

    @staticmethod
    def _regex(desen: str) -> re.Pattern:
        son = desen.endswith("$")
        govde = desen[:-1] if son else desen
        return re.compile("".join(".*" if c == "*" else re.escape(c) for c in govde) + ("$" if son else ""))

    def izinli(self, yol: str) -> bool:
        en_iyi: tuple[int, bool] | None = None
        for izin, uzunluk, rx in self._derli:
            if rx.match(yol) and (en_iyi is None or uzunluk > en_iyi[0] or (uzunluk == en_iyi[0] and izin)):
                en_iyi = (uzunluk, izin)
        return True if en_iyi is None else en_iyi[1]


# ------------------------------------------------------------------ sayfa okuma
def yol_al(link: str | None) -> str | None:
    """Trendyol ürün bağlantısı → '/marka/ad-p-123' (sorgu ve parça atılır); değilse None."""
    try:
        adres = urlsplit(link or "")
    except ValueError:
        return None
    if (adres.hostname or "").lower() not in ("www.trendyol.com", "trendyol.com") or adres.scheme != "https":
        return None
    return adres.path if URUN_YOLU.match(adres.path) else None


def _metin(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _ld_urun(html: str) -> dict | None:
    for blok in LD_JSON.findall(html):
        try:
            veri = json.loads(blok)
        except ValueError:
            continue
        for x in veri if isinstance(veri, list) else [veri]:
            if isinstance(x, dict) and x.get("@type") == "Product":
                return x
    return None


def _sayi(x, tur=int):
    try:
        return tur(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def urun_ayikla(html: str, yol: str) -> dict | None:
    """Ürün sayfası → ürün bilgisi (yapılandırılmış veri + sayfa durumu); ürün sayfası değilse None."""
    m = URUN_YOLU.match(yol)
    ld = _ld_urun(html) if m else None
    if not ld or not ld.get("name"):
        return None
    marka = ld.get("brand")
    marka = marka.get("name") if isinstance(marka, dict) else marka
    teklif = ld.get("offers") or {}
    teklif = teklif[0] if isinstance(teklif, list) and teklif else teklif
    oy = ld.get("aggregateRating") or {}
    gorsel = ld.get("image")
    if isinstance(gorsel, list):
        gorsel = gorsel[0] if gorsel else None
    if isinstance(gorsel, dict):
        gorsel = gorsel.get("contentUrl") or gorsel.get("url")
    favori, satici, kategori = FAVORI.search(html), SATICI.search(html), KATEGORI.search(html)
    return {
        "urun_id": int(m.group(3)), "url": KOK + yol, "yol": yol, "marka_slug": m.group(1),
        "ad": re.sub(r"\s+", " ", str(ld["name"])).strip(), "marka": marka,
        "magaza_id": int(satici.group(1)) if satici else None,
        "magaza": _metin(satici.group(2)) if satici else None,
        "kategori": _metin(kategori.group(2) or kategori.group(1)).replace("\\u002F", "/") if kategori else None,
        "fiyat": _sayi(teklif.get("price") if isinstance(teklif, dict) else None, float),
        "degerlendirme": _sayi(oy.get("ratingCount")) or 0, "yorum": _sayi(oy.get("reviewCount")) or 0,
        "puan": _sayi(oy.get("ratingValue"), float),
        "favori": int(favori.group(1)) if favori else 0,
        "stokta": "outofstock" not in str((teklif or {}).get("availability", "") if isinstance(teklif, dict) else "").lower(),
        "gorsel": pazar.guvenli_link(str(gorsel)) if gorsel else None,
        "benzer": [b for b in dict.fromkeys(BENZER.findall(html)) if b != yol],
    }


def uc_d_mi(u: dict) -> bool:
    """3D baskı ürün mü: adında/adresinde 3D baskı işareti ya da marka/mağaza adında '3d', 'baskı'."""
    metin = f"{u['ad']} {u['yol'].replace('-', ' ')}"
    return pazar.uc_d_mi(metin, f"{u.get('marka') or ''} {u.get('magaza') or ''}".strip() or None)


def aday_mi(yol: str, bilinen_markalar: set[str]) -> bool:
    """Benzer ürün bağlantısı okunmaya değer mi (adresine bakarak; sayfa açmadan)."""
    m = URUN_YOLU.match(yol)
    if not m:
        return False
    marka, ad = m.group(1), m.group(2)
    if marka in HARIC_MARKALAR:
        return False
    return (marka in bilinen_markalar or bool(pazar.UC_D_SATICI.search(marka))
            or bool(pazar.UC_D.search(ad.replace("-", " "))))


class Okuyucu:
    def __init__(self, client: httpx.Client | None = None, bekleme_sn: float | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)
        self.bekleme = config.TRENDYOL_BEKLEME_SN if bekleme_sn is None else bekleme_sn
        self.sayfa_sayisi = 0
        self.robots: Robots | None = None
        self._son = 0.0

    def _get(self, yol: str) -> httpx.Response:
        if self._son:
            kalan = self.bekleme - (time.monotonic() - self._son)
            if kalan > 0:
                time.sleep(kalan)
        try:
            return self.client.get(KOK + yol, follow_redirects=False,
                                   headers={"User-Agent": config.TRENDYOL_UA, "Accept-Language": "tr-TR,tr;q=0.9"})
        finally:
            self._son = time.monotonic()

    def robots_yukle(self) -> None:
        r = self._get("/robots.txt")
        if r.status_code in (403, 429):
            raise TrendyolEngel(f"robots.txt isteği engellendi ({r.status_code})")
        if r.status_code != 200:
            raise TrendyolEngel(f"robots.txt okunamadı ({r.status_code}); kurallar bilinmeden sayfa açılmaz")
        self.robots = Robots(r.text)

    def urun(self, yol: str) -> dict | None:
        if self.robots is None:
            self.robots_yukle()
        m = URUN_YOLU.match(yol)
        # robots.txt'teki "/*/genel-markalar*" kuralı kelimesi kelimesine kökteki /genel-markalar/ ürünlerini
        # kapsamıyor; niyet kapatmak olduğu için temkinli davranılır, bunlar da okunmaz.
        if not m or m.group(1) in HARIC_MARKALAR or not self.robots.izinli(yol):
            return None
        r = self._get(yol)
        self.sayfa_sayisi += 1
        if r.status_code in (403, 429):
            raise TrendyolEngel(f"Trendyol isteği engelledi ({r.status_code})")
        if r.status_code != 200:
            return None   # kaldırılmış/taşınmış ürün; yönlendirme izlenmez (kapalı adrese gidebilir)
        u = urun_ayikla(r.text, yol)
        if u is None and DOGRULAMA.search(r.text[:20000]):
            raise TrendyolEngel("Trendyol doğrulama (bot kontrolü) sayfası gösterdi")
        return u


def tara(okuyucu: Okuyucu, yenilenecek: list[str], tohumlar: list[str], bilinen: set[str],
         sinir: int, goruldu: set[str] | None = None) -> tuple[list[dict], str | None]:
    """(okunan 3D baskı ürünler, durma nedeni). Önce takip edilenler, sonra tohumlar, sonra benzerler.
    `goruldu` verilirse güncellenir; içindeki yollar bir daha okunmaz."""
    sonuc: dict[int, dict] = {}
    goruldu = goruldu if goruldu is not None else set()
    kuyruk: deque[str] = deque()
    for y in yenilenecek[: int(sinir * config.TRENDYOL_YENILEME_ORANI)] + tohumlar:
        if y not in goruldu:
            goruldu.add(y)
            kuyruk.append(y)
    neden, hata = None, 0
    while kuyruk and okuyucu.sayfa_sayisi < sinir:
        yol = kuyruk.popleft()
        try:
            u = okuyucu.urun(yol)
            hata = 0
        except TrendyolEngel as e:
            neden = str(e)
            break
        except httpx.HTTPError as e:
            hata += 1
            if hata >= 3:
                neden = f"bağlantı hatası: {e}"
                break
            continue
        if not u or not uc_d_mi(u):
            continue
        sonuc[u["urun_id"]] = u
        bilinen.add(u["marka_slug"])
        for b in u["benzer"]:
            if b not in goruldu and aday_mi(b, bilinen):
                goruldu.add(b)
                kuyruk.append(b)
    return list(sonuc.values()), neden


# ------------------------------------------------------------------ analiz
def _toplam(u: dict) -> float:
    return u["degerlendirme"] + u["favori"] / 10


def hiz_ekle(urunler: list[dict], gecmis: list[dict], bugun: date) -> None:
    """Önceki okumaya göre haftalık değerlendirme/favori artışı (7 güne ölçeklenir)."""
    onceki: dict[int, dict] = {}
    for r in sorted(gecmis, key=lambda r: str(r["tarih"])):
        if str(r["tarih"])[:10] < bugun.isoformat():
            onceki[int(r["urun_id"])] = r
    for u in urunler:
        o = onceki.get(u["urun_id"])
        gun = (bugun - date.fromisoformat(str(o["tarih"])[:10])).days if o else 0
        if o and gun >= 3:
            olcek = 7 / gun
            u["artis_degerlendirme"] = round(max(0, u["degerlendirme"] - (o["degerlendirme"] or 0)) * olcek)
            u["artis_favori"] = round(max(0, u["favori"] - (o["favori"] or 0)) * olcek)
            u["haftalik"] = u["artis_degerlendirme"] + u["artis_favori"] / 10
            u["onceki_gun"] = gun


def sirala(urunler: list[dict]) -> list[dict]:
    """Haftalık artışı bilinenler önce (satış hızı), sonra toplam değerlendirme + favori/10."""
    return sorted(urunler, key=lambda u: (u.get("haftalik") is not None, u.get("haftalik") or 0, _toplam(u)),
                  reverse=True)


def magazalar(urunler: list[dict]) -> list[dict]:
    gruplar: dict[str, list[dict]] = defaultdict(list)
    for u in urunler:
        gruplar[str(u.get("magaza_id") or u.get("magaza") or u.get("marka") or "?")].append(u)
    sonuc = []
    for liste in gruplar.values():
        liste = sirala(liste)
        haftalik = [u["haftalik"] for u in liste if u.get("haftalik") is not None]
        sonuc.append({"magaza": liste[0].get("magaza") or liste[0].get("marka") or "?",
                      "magaza_id": liste[0].get("magaza_id"),
                      "markalar": sorted({u["marka"] for u in liste if u.get("marka")}),
                      "urun": len(liste), "degerlendirme": sum(u["degerlendirme"] for u in liste),
                      "favori": sum(u["favori"] for u in liste),
                      "haftalik": round(sum(haftalik), 1) if haftalik else None, "en_iyi": liste[:3]})
    return sorted(sonuc, key=lambda m: (m["haftalik"] is not None, m["haftalik"] or 0,
                                        m["degerlendirme"] + m["favori"] / 10), reverse=True)


def _kume(u: dict) -> dict:
    ad = u["ad"]
    if u.get("marka") and ad.lower().startswith(u["marka"].lower()):
        ad = ad[len(u["marka"]):]
    kel = kesif.kelimeler(ad)
    return {"ad": ad.strip(" -–"), "kelimeler": kel, "ayirt": kesif.ayirt_edici(kel), "cekirdek": set()}


def eslestir(urunler: list[dict], kaynak: mw.MakerWorldKaynak, api_key: str, lens_hakki: int,
             client: httpx.Client | None = None) -> tuple[list[dict], list[str]]:
    """İlk ürünler için MakerWorld modeli. (kaydedilecek MakerWorld ürünleri, Lens'te çıkan Trendyol yolları)."""
    tum_mw: list[dict] = []
    kopya_yollari: list[str] = []
    for u in urunler[: config.TRENDYOL_ESLESTIR_ADET]:
        kume = _kume(u)
        modeller: list[dict] = []
        if lens_hakki > 0 and api_key and u.get("gorsel"):
            lens_hakki -= 1
            try:
                yanit = pazar._istek(api_key, {"engine": "google_lens", "url": u["gorsel"], "hl": "tr",
                                               "country": "tr"}, client)
                ilanlar, modeller = kesif.lens_incele(yanit, kume)
                u["lens_yapildi"] = True
                u["kopya_ilanlar"] = [i for i in ilanlar if yol_al(i.get("link")) != u["yol"]]
                kopya_yollari += [y for y in (yol_al(i.get("link")) for i in ilanlar) if y and y != u["yol"]]
            except (pazar.PazarHatasi, httpx.HTTPError) as e:
                print(f"UYARI: Lens ({u['ad'][:40]}): {e}")
        u["diger_kaynaklar"] = [m for m in modeller if m["site"] != "MakerWorld"]
        u["eslesmeler"], mw_urunler = kesif.makerworld_eslestir(kaynak, kume, modeller, u.get("fiyat"))
        u["mw_sorgu"] = kume.get("mw_sorgu")
        tum_mw += mw_urunler
    return tum_mw, list(dict.fromkeys(kopya_yollari))


def satir(bugun: date, u: dict) -> dict:
    return {"tarih": bugun.isoformat(), **{a: u.get(a) for a in
            ("urun_id", "url", "ad", "marka", "magaza_id", "magaza", "kategori", "fiyat", "degerlendirme",
             "yorum", "puan", "favori", "gorsel")}}


# ------------------------------------------------------------------ çıktı
def _sayilar(u: dict) -> str:
    p = [f"{u['degerlendirme']} değerlendirme", f"{u['favori']} favori"]
    if u.get("haftalik") is not None:
        p.append(f"bu hafta +{u['artis_degerlendirme']} değ. / +{u['artis_favori']} fav")
    return " · ".join(p)


def _fiyat(u: dict) -> str:
    if u.get("stokta") is False:
        return "stokta yok"
    return f"{u['fiyat']:.0f} TL" if u.get("fiyat") else "fiyat yok"


def markdown(bugun: date, urunler: list[dict], magaza_listesi: list[dict], okunan: int,
             neden: str | None) -> str:
    hizli = any(u.get("haftalik") is not None for u in urunler)
    s = [f"# Trendyol 3D mağaza analizi — {bugun.isoformat()}", "",
         f"{okunan} ürün sayfası okundu, {len(urunler)} 3D baskı ürün, {len(magaza_listesi)} mağaza. "
         + ("Sıralama: **bu haftaki değerlendirme artışı** (satış hızı); favori artışı onda bir sayılır."
            if hizli else
            "İlk okuma: sıralama **toplam değerlendirme** (+ favori/10). Gelecek haftadan itibaren haftalık "
            "artışa (satış hızına) göre sıralanır."), ""]
    if neden:
        s += [f"> ⚠️ Okuma erken durdu: {neden}", ""]
    s += ["## En çok satan 3D baskı ürünler", ""]
    for n, u in enumerate(urunler[: config.TRENDYOL_RAPOR_ADET], 1):
        s.append(f"### {n}. {u['ad'][:90]}")
        if u.get("gorsel"):
            s += ["", f"![]({u['gorsel']})", ""]
        s.append(f"- **Mağaza:** {u.get('magaza') or '?'} · marka {u.get('marka') or '?'} · {_fiyat(u)}"
                 f" · [Trendyol]({u['url']})")
        s.append(f"- **Talep:** {_sayilar(u)}" + (f" · puan {u['puan']:.1f}" if u.get("puan") else ""))
        if u.get("kategori"):
            s.append(f"- **Kategori:** {u['kategori']}")
        if "eslesmeler" in u:
            if u["eslesmeler"]:
                s.append("- **MakerWorld:**")
                for e in u["eslesmeler"]:
                    s.append(f"  - {kesif.ESLESME_ETIKETI[e['eslesme']]}: [{e['name'][:70]}]({e['url']})"
                             f" — {kesif._model_satiri(e)}")
            else:
                s.append("- **MakerWorld:** eşleşen model bulunamadı"
                         + (f" (aranan: \"{u['mw_sorgu']}\")" if u.get("mw_sorgu") else ""))
            if u.get("diger_kaynaklar"):
                s.append("- **Diğer model siteleri:** " + ", ".join(
                    f"[{m['site']}]({m['link']})" for m in u["diger_kaynaklar"][:3]))
            if u.get("kopya_ilanlar"):
                s.append(f"- **Aynı ürünü satan diğer ilanlar (Lens):** {len(u['kopya_ilanlar'])}")
        s.append("")
    s += ["## Aktif 3D mağazaları", "",
          "| # | Mağaza | Ürün | Değerlendirme | Favori | Bu hafta | En çok satanı |",
          "|---|---|---|---|---|---|---|"]
    for n, m in enumerate(magaza_listesi[: config.TRENDYOL_MAGAZA_ADET], 1):
        en = m["en_iyi"][0]
        s.append(f"| {n} | {m['magaza']} | {m['urun']} | {m['degerlendirme']} | {m['favori']} | "
                 f"{'+' + str(m['haftalik']) if m['haftalik'] is not None else '—'} | "
                 f"[{en['ad'][:45]}]({en['url']}) |")
    s += ["", "_Yalnızca robots.txt'te açık ürün sayfaları okundu; satış adedi Trendyol'da açık değildir, "
          "değerlendirme ve favori artışı satışın en yakın göstergesidir._"]
    return "\n".join(s)


def telegram_mesaji(bugun: date, urunler: list[dict], magaza_listesi: list[dict], panel_url: str | None = None,
                    neden: str | None = None, sinir: int = 4096) -> str | None:
    if not urunler:
        return (f"<b>🛒 Trendyol 3D analizi</b> ({bugun.isoformat()})\n⚠️ Okuma yapılamadı: {bildirim._e(neden)}"
                if neden else None)
    e_ = bildirim._e
    hizli = any(u.get("haftalik") is not None for u in urunler)
    metin = (f"<b>🛒 Trendyol'da en çok satan 3D baskılar</b> ({bugun.isoformat()})\n<i>"
             + ("sıralama: bu haftaki değerlendirme artışı" if hizli else "ilk okuma: toplam değerlendirme")
             + "</i>")
    if neden:
        metin += f"\n⚠️ Okuma erken durdu: {e_(neden)}"
    for n, u in enumerate(urunler[:10], 1):
        p = [f"<b>{n}. <a href=\"{bildirim._href(u['url'])}\">{e_(u['ad'][:60])}</a></b>",
             f"   🏪 {e_(u.get('magaza') or '?')} · {e_(_fiyat(u))} · {e_(_sayilar(u))}"]
        for e in (u.get("eslesmeler") or [])[:1]:
            isaret = "🎯" if e["eslesme"] == "görsel" else "🔤"
            p.append(f"   {isaret} <a href=\"{bildirim._href(e['url'])}\">{e_(e['name'][:45])}</a> · "
                     f"{e_(kesif._model_satiri(e))}")
        parca = "\n".join(p)
        if len(metin) + len(parca) + 400 > sinir:
            break
        metin += "\n\n" + parca
    mag = "\n".join(f"{n}. {e_(m['magaza'])} — {m['urun']} ürün, {m['degerlendirme']} değ."
                    + (f", bu hafta +{m['haftalik']}" if m["haftalik"] is not None else "")
                    for n, m in enumerate(magaza_listesi[:5], 1))
    if len(metin) + len(mag) + 120 <= sinir:
        metin += "\n\n<b>🏪 Aktif 3D mağazaları</b>\n" + mag
    if panel_url:
        metin += f"\n\n📊 {e_(panel_url)}"
    return metin


# ------------------------------------------------------------------ çalıştırma
def zamani_geldi(depo, bugun: date) -> bool:
    son = depo.ty_son_tarih()
    return son is None or (bugun - date.fromisoformat(str(son)[:10])).days >= config.TRENDYOL_ARALIK_GUN


def calistir(depo, ayarlar: config.Ayarlar, bugun: date, kaynak: mw.MakerWorldKaynak | None = None,
             okuyucu: Okuyucu | None = None, zorla: bool = False, sinir: int | None = None,
             client: httpx.Client | None = None) -> dict | None:
    """Zamanı geldiyse okur, sıralar, eşleştirir, kaydeder, rapor yazar. Sonuç sözlüğü ya da None."""
    try:
        if not zorla and not zamani_geldi(depo, bugun):
            return None
        gecmis = depo.ty_gecmis((bugun - timedelta(days=config.TRENDYOL_TAKIP_GUN)).isoformat())
    except Exception as e:  # noqa: BLE001
        print(f"Trendyol analizi atlandı: kayıt tablosu okunamadı ({str(e)[:120]}). "
              "Supabase'te supabase/guncelleme_2026-11-11_trendyol.sql çalıştırıldı mı?")
        return None
    sinir = sinir or config.TRENDYOL_SAYFA_SINIRI
    okuyucu = okuyucu or Okuyucu()
    kaynak = kaynak or mw.MakerWorldKaynak()

    son_kayit: dict[int, dict] = {}
    for r in sorted(gecmis, key=lambda r: str(r["tarih"])):
        son_kayit[int(r["urun_id"])] = r
    yenilenecek = [y for y in (yol_al(r["url"]) for r in sorted(son_kayit.values(), key=_toplam, reverse=True)) if y]
    bilinen = {URUN_YOLU.match(y).group(1) for y in yenilenecek}
    tohum_linkleri = list(config.TRENDYOL_TOHUMLAR)
    try:
        tohum_linkleri += [i.get("link") for i in depo.kesif_ilanlari()]
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Pazar keşfi ilanları okunamadı: {e}")
    tohumlar = list(dict.fromkeys(y for y in map(yol_al, tohum_linkleri) if y))

    goruldu: set[str] = set()
    try:
        okuyucu.robots_yukle()
        urunler, neden = tara(okuyucu, yenilenecek, tohumlar, bilinen, sinir, goruldu)
    except (TrendyolEngel, httpx.HTTPError) as e:
        urunler, neden = [], str(e)
    hiz_ekle(urunler, gecmis, bugun)
    urunler = sirala(urunler)

    lens_hakki = 0
    if ayarlar.serpapi_key and config.TRENDYOL_LENS_ADET:
        kalan = pazar.kalan_hak(ayarlar.serpapi_key, client)
        lens_hakki = config.TRENDYOL_LENS_ADET if kalan is not None and kalan >= config.KESIF_KOTA_ESIGI else 0
    mw_urunler, kopyalar = eslestir(urunler, kaynak, ayarlar.serpapi_key, lens_hakki, client) if urunler else ([], [])

    # Lens'te çıkan, aynı ürünü satan diğer Trendyol mağazaları: kalan sayfa hakkıyla okunur.
    if kopyalar and not neden and okuyucu.sayfa_sayisi < sinir:
        bilinen_idler = {u["urun_id"] for u in urunler}
        ek, neden = tara(okuyucu, [], [y for y in kopyalar if y not in goruldu], bilinen, sinir, goruldu)
        ek = [u for u in ek if u["urun_id"] not in bilinen_idler]
        hiz_ekle(ek, gecmis, bugun)
        urunler = sirala(urunler + ek)

    if mw_urunler:
        try:
            idler = depo.urunleri_kaydet(list({u["external_id"]: u for u in mw_urunler}.values()))
            for u in urunler:
                for e in u.get("eslesmeler") or []:
                    e["product_id"] = idler.get((mw.KAYNAK_ID, e["external_id"]))
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: Eşleşen modeller kaydedilemedi: {e}")
    if urunler:
        try:
            depo.ty_kaydet([satir(bugun, u) for u in urunler])
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: Trendyol ürünleri kaydedilemedi: {e}\n"
                  "Supabase'te supabase/guncelleme_2026-11-11_trendyol.sql çalıştırıldı mı?")
    magaza_listesi = magazalar(urunler)
    config.RAPOR_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = config.RAPOR_KLASORU / f"trendyol-{bugun.isoformat()}.md"
    yol.write_text(markdown(bugun, urunler, magaza_listesi, okuyucu.sayfa_sayisi, neden), encoding="utf-8")
    print(f"Trendyol analizi: {okuyucu.sayfa_sayisi} sayfa, {len(urunler)} 3D ürün, {len(magaza_listesi)} mağaza"
          + (f" (durdu: {neden})" if neden else "") + f" → {yol}")
    return {"urunler": urunler, "magazalar": magaza_listesi, "neden": neden, "yol": str(yol),
            "okunan": okuyucu.sayfa_sayisi}


def ana() -> int:
    from .db import depo_olustur
    ayarlar = config.ayarlari_oku()
    depo = depo_olustur(ayarlar)
    bugun = datetime.now(timezone.utc).date()
    sinir = None
    if "--sinir" in sys.argv:
        sinir = int(sys.argv[sys.argv.index("--sinir") + 1])
    sonuc = calistir(depo, ayarlar, bugun, zorla=True, sinir=sinir)
    if sonuc is None:
        return 1
    mesaj = telegram_mesaji(bugun, sonuc["urunler"], sonuc["magazalar"], ayarlar.panel_url or None, sonuc["neden"])
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
