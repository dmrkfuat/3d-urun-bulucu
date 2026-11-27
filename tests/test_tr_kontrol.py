"""Kategori dışı modeller (anahtar kelimesiz MakerWorld araması) ve Türkiye pazar kontrolü."""
from datetime import date, datetime, timedelta, timezone

import httpx

from urun_bulucu import config, ozet, puanlama, tr_kontrol
from urun_bulucu.kaynaklar.makerworld import MakerWorldKaynak, genel_kategori

from .ornek_veri import mw_tasarim, urun

BUGUN = date(2026, 11, 27)


def _mw_handler(istekler):
    detaylar = {
        1: mw_tasarim(1, "Flexi Gecko", 100, 900),
        2: {**mw_tasarim(2, "Nordic Gnome", 100, 5000),
            "categories": [{"id": 104, "name": "Sculptures", "picUrl": ""},
                           {"id": 100, "name": "Art", "picUrl": "https://x/art.svg"}]},
        3: mw_tasarim(3, "Planter Pot", 100, 4000),
        4: mw_tasarim(4, "Car Hook", 100, 300),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        yol = request.url.path
        if yol.endswith("/search-service/select/design2"):
            terim = request.url.params["keyword"]
            ids = {"flexi": [1], "planter": [], "": [2, 3, 4, 1]}[terim]
            hits = [{"id": i, "title": detaylar[i]["title"], "tags": [], "downloadCount": detaylar[i]["downloadCount"]}
                    for i in ids]
            return httpx.Response(200, json={"hits": hits})
        if "/design-service/design/" in yol:
            return httpx.Response(200, json=detaylar[int(yol.rsplit("/", 1)[1])])
        return httpx.Response(404)
    return handler


def test_kategorisiz_arama_genel_ve_kendi_kategorileri():
    istekler = []
    kaynak = MakerWorldKaynak(httpx.Client(transport=httpx.MockTransport(_mw_handler(istekler))), bekleme_sn=0)
    urunler = kaynak.topla({"Eklemli figür": ["flexi"], "Saksı": ["planter"]}, detay_limiti=10, gun=30,
                           genel_adet=50, genel_detay=1)
    gore = {u["external_id"]: u for u in urunler}
    # Kelime aramasında çıkmayan "Planter Pot" kategorimize uyduğu için o kategoriye girdi (genel değil).
    assert gore["3"]["category"] == "Saksı" and not gore["3"].get("genel")
    assert gore["1"]["category"] == "Eklemli figür" and not gore["1"].get("genel")
    # Uymayanlardan en çok indirilen 1 tanesi MakerWorld'ün ana kategorisiyle; Türkiye kontrolü gerekir.
    assert gore["2"]["category"] == "Diğer · Sanat" and gore["2"]["genel"] is True
    assert "4" not in gore   # genel_detay=1 sınırı


def test_genel_kategori_adi():
    assert genel_kategori({"categories": [{"name": "Gadgets", "picUrl": "x"}]}) == "Diğer · Gadget"
    assert genel_kategori({"categories": [{"name": "Weird"}]}) == "Diğer · Weird"
    assert genel_kategori({}) == "Diğer"


def _kayit(n, gun_once=1):
    t = (datetime.now(timezone.utc) - timedelta(days=gun_once)).isoformat()
    return {"checked_at": t, "results": [{"kaynak": "metin", "site": "Trendyol", "birebir": False}] * n
            + [{"kaynak": "sosyal", "site": "Instagram"}]}


def test_isaretle_ve_secim_disi_birakma():
    gecen = urun(1, "Gnome A", 10, 100, kategori="Diğer · Sanat", genel=True)
    az = urun(2, "Gnome B", 10, 100, kategori="Diğer · Sanat", genel=True)
    yok = urun(3, "Gnome C", 10, 100, kategori="Diğer · Sanat", genel=True)
    satilan = urun(4, "Gnome D", 10, 100, kategori="Diğer · Sanat", genel=True)
    kendi = urun(5, "Fidget", 10, 100)
    urunler = [gecen, az, yok, satilan, kendi]
    tr_kontrol.isaretle(urunler, {1: _kayit(2), 2: _kayit(1)}, {"urun": {4: 3}, "kategori": {}})
    assert gecen["tr_satista"] is True and "2 adet" in gecen["tr_kontrol"]
    assert az["tr_satista"] is False            # sosyal medya ilanı sayılmaz; 1 < TR_KONTROL_EN_AZ_ILAN
    assert yok["tr_satista"] is None            # kontrol edilemedi
    assert satilan["tr_satista"] is True and "sattın" in satilan["tr_kontrol"]
    assert "tr_satista" not in kendi            # kendi kategorilerimiz kontrolsüz

    secilen = {s["product_id"] for s in ozet.sec(puanlama.puanla(urunler, {}, BUGUN))}
    assert secilen == {1, 4, 5}
    s1 = next(s for s in ozet.sec(puanlama.puanla(urunler, {}, BUGUN)) if s["product_id"] == 1)
    assert "3D baskı satış ilanı" in s1["reason"] and s1["urun"]["score_detail"]["turkiye"]


def test_aranacaklar_taze_kayit_ve_satilan_atlanir():
    a = urun(1, "A", 1, 500, genel=True)
    b = urun(2, "B", 1, 900, genel=True)
    c = urun(3, "C", 1, 100, genel=True, trend_rank=4)
    d = urun(4, "D", 1, 9999, genel=True)
    e = urun(5, "E", 1, 9999)
    kayitlar = {1: _kayit(3, gun_once=config.TR_KONTROL_YENILEME_GUN + 2), 2: _kayit(3, gun_once=3)}
    hedef = tr_kontrol.aranacaklar([a, b, c, d, e], kayitlar, 5, {"urun": {4: 1}})
    # b taze; d satıldı; e kendi kategorimiz. Trend olan önce, sonra indirmeye göre.
    assert [u["id"] for u in hedef] == [3, 1]
    assert tr_kontrol.aranacaklar([a, b, c], kayitlar, 1)[0]["id"] == 3


class _Depo:
    def __init__(self):
        self.kaydedilen = []

    def pazar_kaydet(self, satirlar):
        self.kaydedilen.extend(satirlar)


def test_calistir_serper_ile_arar_kaydeder_isaretler():
    istekler = []

    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        assert request.url.host == "google.serper.dev"
        return httpx.Response(200, json={"shopping": [
            {"title": "Cüce Biblo 3D Baskı", "source": "Trendyol", "link": "https://www.trendyol.com/a-p-1",
             "price": "249,90 TL"},
            {"title": "Noel Cücesi 3d baskı PLA", "source": "Hepsiburada", "link": "https://www.hepsiburada.com/b",
             "price": "199 TL"},
            {"title": "Gnome STL dosyası", "source": "Cults3D", "link": "https://cults3d.com/x", "price": "50 TL"},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    g = urun(7, "Nordic Gnome", 10, 100, kategori="Diğer · Sanat", genel=True, tags=["gnome", "christmas"])
    k = urun(8, "Fidget", 10, 100)
    ayarlar = config.Ayarlar(supabase_url="", supabase_key="", veritabani_yolu=None, serper_key="x")
    kayitlar, depo = {}, _Depo()
    yeni = tr_kontrol.calistir(depo, [g, k], kayitlar, ayarlar, BUGUN, client=client)
    assert len(istekler) == 1 and set(yeni) == {7} and 7 in kayitlar
    assert depo.kaydedilen[0]["product_id"] == 7
    assert g["tr_satista"] is True          # dijital dosya sayılmadı, 2 ilan kaldı
    assert "tr_satista" not in k


def test_calistir_anahtarsiz_kimse_gecmez():
    g = urun(7, "Nordic Gnome", 10, 100, genel=True)
    ayarlar = config.Ayarlar(supabase_url="", supabase_key="", veritabani_yolu=None)
    assert tr_kontrol.calistir(_Depo(), [g], {}, ayarlar, BUGUN) == {}
    assert g["tr_satista"] is None


def test_yazici_ve_ilgisiz_ilanlar_turkiye_kontrolunu_gecirmez():
    """2026-11-27: "Gnomo Nordico…" 2 cüce ilanı + 9 yazıcı/reçine ilanıyla "11 ilan" sayılmıştı;
    "Knitted Jesus" gibi yalnızca yazıcı ilanı dönen ürün ise kontrolü geçmemeli."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):                      # site araması: sonuç yok
            return httpx.Response(200, json={"organic": []})
        return httpx.Response(200, json={"shopping": [
            {"title": "Bambu Lab A1 3D Yazıcı", "source": "Robolink Market", "link": "https://robolinkmarket.com/a",
             "price": "17.011,50 TL"},
            {"title": "Anycubic 3D Yazıcı Reçine", "source": "Hepsiburada", "link": "https://www.hepsiburada.com/r",
             "price": "1.125 TL"},
            {"title": "Kartal Dekoratif Duvar Süsü 3D Baskı", "source": "Trendyol", "link": "https://www.trendyol.com/k-p-2",
             "price": "80 TL"},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    g = urun(7, "Knitted Jesus", 10, 100, kategori="Diğer · Sanat", genel=True)
    ayarlar = config.Ayarlar(supabase_url="", supabase_key="", veritabani_yolu=None, serper_key="x")
    kayitlar = {}
    tr_kontrol.calistir(_Depo(), [g], kayitlar, ayarlar, BUGUN, client=client)
    assert tr_kontrol.ilan_sayisi(kayitlar[7]) == 0
    assert g["tr_satista"] is False and "(0 ilan)" in g["tr_kontrol"]
    # ilgisiz işaretli sonuçlar sayılmaz; işareti olmayan eski kayıt eskisi gibi sayılır
    assert tr_kontrol.ilan_sayisi({"results": [{"kaynak": "metin", "ilgili": False}, {"kaynak": "metin", "ilgili": True},
                                               {"kaynak": "metin"}, {"kaynak": "sosyal"}]}) == 2
