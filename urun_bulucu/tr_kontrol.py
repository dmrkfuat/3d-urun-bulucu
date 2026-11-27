"""Türkiye pazar kontrolü: kategorilerimiz dışından gelen ürün Türkiye'de satılıyor mu?

Kategorilerimiz (config.KATEGORILER) Türkiye'de satıldığı bilinen ürün tipleri. Onların dışından gelen
ürünler (MakerWorld'ün anahtar kelimesiz aramasından "Diğer · …" ve kategorimize uymayan trend modelleri;
ürün sözlüğünde "genel" işaretli) ancak Türkiye'de 3D BASKI benzerleri satışta bulunursa listeye girer.

Kontrol: Google Alışveriş (Türkiye, TL) "<Türkçe ad> <ürün tipi> 3d baskı" araması, ürün başına 1 arama;
az ilan çıkarsa Serper ile Trendyol / Hepsiburada / Amazon TR site araması da yapılır (pazar.site_ara).
Sonuç pazar.alisveris_sonuclari ile süzülür (yalnızca 3D baskı, Türk pazar yerleri ve bağımsız 3D baskı
mağazaları; dijital dosya ve yurt dışı pazar yerleri sayılmaz). En az TR_KONTROL_EN_AZ_ILAN satış ilanı
(aynı ürün ya da aynı tipte benzer ürün) varsa "Türkiye'de satılıyor" sayılır.

Sonuç e-ticaret kaydına (market_checks) yazılır: piyasa fiyatı ve bonusu da bundan hesaplanır, panelde
görünür ve TR_KONTROL_YENILEME_GUN gün boyunca tekrar aranmaz. Daha önce yapılmış tam e-ticaret araması
(Lens + Alışveriş) da aynı şekilde kullanılır.

Bütçe: SERPER_KEY varsa Serper ile (SerpApi aylık kotası harcanmaz); yoksa SerpApi'nin o günkü payının
üçte biri. Arama yapılamayan ürün o gün listeye girmez (kontrol şart). Daha önce sattığın ürün kontrolsüz
geçer: Türkiye'de satıldığı zaten belli.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from . import config, kota, pazar


def gerekli_mi(u: dict) -> bool:
    return bool(u.get("genel"))


def ilan_sayisi(o: dict | None) -> int:
    """Kayıttaki Türkiye satış ilanları (sosyal medya hariç; aynı ürün ve aynı tipte benzer ürünler)."""
    return sum(1 for r in (o or {}).get("results") or [] if r.get("kaynak") != "sosyal")


def taze_mi(o: dict | None, simdi: datetime | None = None) -> bool:
    if not pazar.gecerli_mi(o):
        return False
    simdi = simdi or datetime.now(timezone.utc)
    try:
        return pazar._zaman(o["checked_at"]) >= simdi - timedelta(days=config.TR_KONTROL_YENILEME_GUN)
    except (KeyError, TypeError, ValueError):
        return False


def _satildi(u: dict, satis_ozeti: dict | None) -> int:
    return int(((satis_ozeti or {}).get("urun") or {}).get(u.get("id"), 0) or 0)


def aranacaklar(urunler: list[dict], kayitlar: dict[int, dict], adet: int,
                satis_ozeti: dict | None = None, simdi: datetime | None = None) -> list[dict]:
    """Kontrol gereken, taze kaydı olmayan ürünler; en çok indirilen önce, en çok `adet`."""
    adaylar = [u for u in urunler if gerekli_mi(u) and u.get("id") is not None and u.get("name")
               and not _satildi(u, satis_ozeti) and not taze_mi(kayitlar.get(u["id"]), simdi)]
    adaylar.sort(key=lambda u: (u.get("trend_rank") is None, -(u.get("downloads") or 0)))
    return adaylar[:max(0, adet)]


def ara(urun: dict, serper_key: str = "", serpapi_key: str = "",
        client: httpx.Client | None = None) -> tuple[list[dict], str | None]:
    sorgu = pazar.arama_metni(urun.get("name"), None, urun.get("tags"))
    if not sorgu:
        return [], None
    if serper_key:
        yanit = pazar.serper_alisveris(serper_key, {"q": sorgu, "gl": "tr", "hl": "tr"}, client)
    else:
        yanit = pazar.alisveris_ara(serpapi_key, sorgu, client)
    sonuclar = pazar.alisveris_sonuclari(yanit)
    # Alışveriş az ilan bulduysa Trendyol / Hepsiburada / Amazon TR ürün sayfalarında da bakılır (+1 kredi).
    if serper_key and config.PAZAR_SITE_ARAMA and len(sonuclar) < config.TR_KONTROL_EN_AZ_ILAN:
        sonuclar = pazar.birlestir(sonuclar, pazar.site_sonuclari(pazar.site_ara(serper_key, sorgu, client)),
                                   en_fazla=20)
    return sonuclar, sorgu


def butce(ayarlar: config.Ayarlar, bugun: date, client: httpx.Client | None = None) -> tuple[int, str]:
    """(bugün en çok kaç ürün, hangi servis)."""
    if ayarlar.serper_key:
        return config.TR_KONTROL_GUNLUK, "Serper"
    if ayarlar.serpapi_key:
        kalan = pazar.kalan_hak(ayarlar.serpapi_key, client)
        return min(config.TR_KONTROL_GUNLUK, kota.gunluk_arama(kalan, bugun) // 3), "SerpApi"
    return 0, "anahtar yok"


def isaretle(urunler: list[dict], kayitlar: dict[int, dict], satis_ozeti: dict | None = None) -> None:
    """Kontrol gereken ürünlere 'tr_satista' (True/False/None) ve 'tr_kontrol' (açıklama) yazar."""
    for u in urunler:
        if not gerekli_mi(u):
            continue
        adet = _satildi(u, satis_ozeti)
        o = kayitlar.get(u.get("id"))
        if adet:
            u["tr_satista"], u["tr_kontrol"] = True, f"Türkiye'de satılıyor (sen {adet} adet sattın)"
        elif pazar.gecerli_mi(o):
            n = ilan_sayisi(o)
            u["tr_satista"] = n >= config.TR_KONTROL_EN_AZ_ILAN
            u["tr_kontrol"] = (f"Türkiye'de {n} adet 3D baskı satış ilanı var" if u["tr_satista"] else
                               f"Türkiye'de 3D baskı satışı yok/az ({n} ilan); listeye alınmadı")
        else:
            u["tr_satista"], u["tr_kontrol"] = None, "Türkiye pazarı kontrol edilemedi; listeye alınmadı"


def calistir(depo, urunler: list[dict], kayitlar: dict[int, dict], ayarlar: config.Ayarlar, bugun: date,
             satis_ozeti: dict | None = None, client: httpx.Client | None = None) -> dict[int, dict]:
    """Taze kaydı olmayan kategori dışı ürünleri arar, kaydeder, `kayitlar`ı günceller ve ürünleri işaretler.
    Bugün yapılan kayıtları döndürür. Bir arama hata verirse (ör. kredi bitti) o ana kadarkiler kaydedilir."""
    yeni: dict[int, dict] = {}
    gerekenler = [u for u in urunler if gerekli_mi(u)]
    if gerekenler:
        adet, servis = butce(ayarlar, bugun, client)
        hedefler = aranacaklar(urunler, kayitlar, adet, satis_ozeti)
        for u in hedefler:
            try:
                sonuclar, sorgu = ara(u, ayarlar.serper_key, ayarlar.serpapi_key, client)
            except (pazar.PazarHatasi, httpx.HTTPError) as e:
                print(f"UYARI: Türkiye pazar kontrolü durdu ({u.get('name')}): {e}")
                break
            yeni[u["id"]] = pazar.ozetle(u["id"], sonuclar, sorgu, u.get("name") or "")
        if yeni:
            depo.pazar_kaydet(list(yeni.values()))
            kayitlar.update(yeni)
        isaretle(urunler, kayitlar, satis_ozeti)
        gecen = sum(1 for u in gerekenler if u.get("tr_satista"))
        print(f"Türkiye pazar kontrolü ({servis}): kategori dışı {len(gerekenler)} ürün, bugün {len(yeni)} arama; "
              f"{gecen} ürün Türkiye'de satılıyor.")
    return yeni
