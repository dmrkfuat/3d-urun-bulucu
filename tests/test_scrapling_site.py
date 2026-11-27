"""Scrapling ayrıştırıcısıyla Trendyol ürün sayfası ve Serper site bazlı arama (Trendyol/Hepsiburada/Amazon TR)."""
import json

import httpx

from urun_bulucu import pazar, tr_kontrol, trendyol

from .ornek_veri import urun

YOL = "/atolye3d/hareketli-ejderha-3d-baski-p-123"


def _sayfa(ld=True, ek=""):
    veri = {"@type": "Product", "name": "Hareketli Ejderha 3D Baskı", "brand": {"name": "Atolye3D"},
            "offers": {"price": "249.90"}, "aggregateRating": {"ratingCount": 12, "ratingValue": 4.5}}
    blok = f'<script type="application/ld+json">{json.dumps(veri)}</script>' if ld else ""
    return (f'<html><head>{blok}<meta property="og:title" content="Ejderha Figür 3D Baskı">'
            f'<meta property="product:price:amount" content="199"></head><body>'
            f'<a href="https://www.trendyol.com/baska3d/fidget-ahtapot-p-456?boutiqueId=1">x</a>'
            f'<a href="/atolye3d/hareketli-ejderha-3d-baski-p-123">kendisi</a>'
            f'<a href="/sr?q=ejderha">arama</a>{ek}'
            '<script>window.__S={"favoriteCount":340,"merchant":{"id":77,"name":"Atolye 3D"}}</script>'
            '</body></html>')


def test_trendyol_scrapling_ile_ayiklar():
    u = trendyol.urun_ayikla(_sayfa(), YOL)
    assert u["ad"] == "Hareketli Ejderha 3D Baskı" and u["fiyat"] == 249.9 and u["degerlendirme"] == 12
    assert u["favori"] == 340 and u["magaza"] == "Atolye 3D" and u["magaza_id"] == 77
    # <a href> bağlantıları ayrıştırıcıdan: sorgu atılır, kendisi ve arama sayfası alınmaz.
    assert u["benzer"] == ["/baska3d/fidget-ahtapot-p-456"]


def test_trendyol_json_ld_yoksa_open_graph():
    u = trendyol.urun_ayikla(_sayfa(ld=False), YOL)
    assert u["ad"] == "Ejderha Figür 3D Baskı" and u["fiyat"] == 199.0


def test_dogrulama_sayfasi_urun_sayilmaz():
    assert trendyol.urun_ayikla(_sayfa(ld=False, ek="<p>Lütfen robot olmadığınızı doğrulayın captcha</p>"), YOL) is None
    assert trendyol.urun_ayikla(_sayfa(), "/sr?q=x") is None


ORGANIK = {"organic": [
    {"title": "3D Baskı Hareketli Örümcek", "link": "https://www.trendyol.com/a/orumcek-3d-baski-p-1",
     "displayedLink": "https://www.trendyol.com › a", "snippet": "Esnek fidget, 189,90 TL"},
    {"title": "Örümcek Clicker Anahtarlık", "link": "https://www.google.com/goto?url=CAES",
     "displayedLink": "https://www.hepsiburada.com › ... › Figür", "snippet": "3D baskı mekanik fidget ₺149"},
    {"title": "3D Baskılı Örümcek Oyuncak", "link": "https://www.amazon.com.tr/dp/B0X",
     "displayedLink": "https://www.amazon.com.tr › Baskili", "snippet": "9,4 inç uzunluk"},
    {"title": "Plastik Örümcek Oyuncak", "link": "https://www.trendyol.com/b/orumcek-p-2",
     "displayedLink": "https://www.trendyol.com › b", "snippet": "Fabrika üretimi"},
    {"title": "Örümcek STL dosyası 3D baskı", "link": "https://www.trendyol.com/c/stl-p-3",
     "displayedLink": "https://www.trendyol.com › c", "snippet": "dijital"},
    {"title": "3D baskı örümcek", "link": "https://www.n11.com/urun/x",
     "displayedLink": "https://www.n11.com › urun", "snippet": ""},
]}


def test_site_sonuclari():
    s = pazar.site_sonuclari(ORGANIK)
    assert [(r["site"], r["price"]) for r in s] == [("Trendyol", 189.9), ("Hepsiburada", 149.0), ("Amazon TR", None)]
    assert all(r["kaynak"] == "site" and r["pazar_yeri"] for r in s)
    # Google yönlendirmeli bağlantıda tıklanacak adres sitenin kendi araması olur.
    assert pazar.satis_linki(s[1]).startswith("https://www.hepsiburada.com/ara?q=")


def test_tr_kontrol_az_ilan_cikinca_site_aramasi():
    istekler = []

    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request.url.path)
        govde = json.loads(request.content)
        if request.url.path == "/shopping":
            return httpx.Response(200, json={"shopping": []})
        assert "site:trendyol.com OR site:hepsiburada.com OR site:amazon.com.tr" in govde["q"]
        return httpx.Response(200, json=ORGANIK)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sonuc, sorgu = tr_kontrol.ara(urun(1, "Flexi Spider", 1, 1, tags=["spider"]), serper_key="x", client=client)
    assert istekler == ["/shopping", "/search"] and len(sonuc) == 3 and sorgu


def test_serpapi_hakki_yokken_serper_ile_arar():
    istekler = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "google.serper.dev"   # SerpApi'ye (Lens) hiç gidilmez
        istekler.append(request.url.path)
        if request.url.path == "/shopping":
            return httpx.Response(200, json={"shopping": [
                {"title": "Örümcek Fidget 3D Baskı", "source": "n11", "link": "https://www.n11.com/urun/x",
                 "price": "175 TL"}]})
        return httpx.Response(200, json=ORGANIK)

    class Depo:
        kaydedilen = []

        def pazar_kontrol_tarihleri(self, ids):
            return {}

        def pazar_kaydet(self, satirlar):
            self.kaydedilen.extend(satirlar)

    u = urun(5, "Flexi Spider", 1, 1, tags=["spider"], image_url="https://x/k.jpg")
    secim = {"rank": 1, "product_id": 5, "urun": u}
    depo = Depo()
    sonuc = pazar.calistir(depo, [secim], "", client=httpx.Client(transport=httpx.MockTransport(handler)),
                           adet=3, serper_key="x")
    assert istekler == ["/shopping", "/search"]
    siteler = {r["site"] for r in sonuc[5]["results"]}
    assert siteler == {"n11", "Trendyol", "Hepsiburada", "Amazon TR"} and depo.kaydedilen[0]["product_id"] == 5
