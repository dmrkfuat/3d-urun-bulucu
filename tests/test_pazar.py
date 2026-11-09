"""E-ticaret araştırması testleri. Yanıt biçimleri 2026-11-09'da alınan gerçek SerpApi
yanıtlarından sadeleştirilmiştir (Google Lens ve Google Alışveriş, Türkiye)."""
from datetime import date, datetime, timezone

import httpx
import pytest

from urun_bulucu import bildirim, config, ozet, pazar, puanlama
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

LENS = {"visual_matches": [
    {"title": "Print Forge 3D Baskı Yüzük", "link": "https://www.trendyol.com/x/y-p-1", "source": "Trendyol"},
    {"title": "Squishy", "link": "https://www.trendyol.com/x/z-p-2", "source": "Trendyol",
     "price": {"value": "₺1.200*", "extracted_value": 1200.0, "currency": "₺"}},
    {"title": "Reddit", "link": "https://www.reddit.com/r/x", "source": "Reddit"},
    {"title": "Etsy US", "link": "https://www.etsy.com/listing/9", "source": "Etsy",
     "price": {"value": "$12*", "extracted_value": 12.0, "currency": "$"}},           # TL değil: fiyat alınmaz
    {"title": "Amazon US", "link": "https://www.amazon.com/dp/1", "source": "Amazon"},   # TR değil: elenir
    {"title": "Hepsiburada", "link": "https://www.hepsiburada.com/a-p-3", "source": "Hepsiburada"},
]}
ALISVERIS = {"shopping_results": [
    {"title": "Manyetik Stres Yüzüğü", "source": "Trendyol", "price": "₺599,00", "extracted_price": 599.0,
     "product_link": "https://www.google.com/search?ibp=oshop&prds=productid:1"},
    {"title": "Fidget Yüzük", "source": "Amazon.com.tr - Amazon.com.tr – pazaryeri", "price": "₺499,00",
     "extracted_price": 499.0, "product_link": "https://www.google.com/search?prds=2"},
    {"title": "Fidget Set", "source": "hepsiburada.com", "price": "₺2.348,59",
     "product_link": "https://www.google.com/search?prds=3"},                            # extracted_price yok
    {"title": "Yurt dışı", "source": "Stress zéro", "price": "₺300,00", "extracted_price": 300.0},
    {"title": "Print Forge 3D Baskı Yüzük", "source": "Trendyol", "price": "₺350", "extracted_price": 350.0,
     "product_link": "https://www.google.com/search?prds=5"},
]}


def test_site_suzgeci():
    assert pazar.site_bul("https://www.trendyol.com/a-p-1", "Trendyol") == "Trendyol"
    assert pazar.site_bul("https://www.google.com/search?prds=2",
                          "Amazon.com.tr - Amazon.com.tr – pazaryeri") == "Amazon TR"
    assert pazar.site_bul(None, "Trendyol") is None   # bağlantısız sonuç kabul edilmez
    assert pazar.site_bul("https://www.google.com/search?prds=1", "trendyol.com") == "Trendyol"
    assert pazar.site_bul("https://www.amazon.com/dp/1", "Amazon") is None
    assert pazar.site_bul("https://www.reddit.com/r/x", "Reddit") is None
    # Sahte alan adları ve başka sitedeki "Trendyol" yazısı kabul edilmez
    assert pazar.site_bul("https://trendyol.com.evil.example/x", "Trendyol") is None
    assert pazar.site_bul("https://eviltrendyol.com/x", "Trendyol") is None
    assert pazar.site_bul("https://shop.example/x", "Trendyol") is None


def test_guvenli_link():
    assert pazar.guvenli_link("https://www.trendyol.com/a-p-1") == "https://www.trendyol.com/a-p-1"
    assert pazar.guvenli_link("javascript:alert(1)") is None
    assert pazar.guvenli_link("http://www.trendyol.com/a") is None
    assert pazar.guvenli_link("data:text/html,x") is None
    assert pazar.guvenli_link(None) is None
    assert pazar.guvenli_link("https://www.google.com/search?q=teleferik yılbaşı") == \
        "https://www.google.com/search?q=teleferik%20yılbaşı"
    zararli = {"visual_matches": [{"title": "x", "link": "javascript:alert(1)", "source": "Trendyol"}]}
    assert pazar.lens_sonuclari(zararli) == []   # alan adı yok → site eşleşmez → elenir


def test_fiyat_metinden():
    assert pazar._fiyat_metinden("₺2.348,59") == 2348.59
    assert pazar._fiyat_metinden("₺1.200*") == 1200.0
    assert pazar._fiyat_metinden("₺599") == 599.0
    assert pazar._fiyat_metinden(None) is None


def test_ayikla_birlestir_ozetle():
    g = pazar.lens_sonuclari(LENS)
    m = pazar.alisveris_sonuclari(ALISVERIS)
    assert [(r["site"], r["price"]) for r in g] == [("Trendyol", None), ("Trendyol", 1200.0), ("Etsy", None),
                                                    ("Hepsiburada", None)]
    assert [(r["site"], r["price"]) for r in m] == [("Trendyol", 599.0), ("Amazon TR", 499.0),
                                                    ("Hepsiburada", 2348.59), ("Trendyol", 350.0)]
    b = pazar.birlestir(g, m)
    assert len(b) == 7          # "Print Forge 3D Baskı Yüzük" iki aramada da geldi, bir kez sayılır
    o = pazar.ozetle(5, b, "fidget yüzük")
    # Fiyat istatistiği metin (Alışveriş) sonuçlarından: 499, 599, 2348.59 (350'li tekrar görsel tarafta kaldı)
    assert (o["min_price"], o["max_price"], o["currency"]) == (499.0, 2348.59, "TL")
    assert pazar.medyan(o) == 599.0
    assert o["results"][0]["sorgu"] == "fidget yüzük"
    assert pazar.fiyat_yazi(o, 65) == ("Trendyol 3, Hepsiburada 2, Etsy 1, Amazon TR 1 · 499–2349 TL "
                                       "(ortanca 599 TL) · senin önerilen fiyatın 65 TL")
    assert pazar.fiyat_yazi(pazar.ozetle(5, [])) == "Türk pazar yerlerinde benzeri bulunamadı"


def test_turkce_sorgu():
    assert pazar.sorgu_olustur("Ultra Satisfying Fidget Flexy Ring! (NO TPU!)") == "fidget yüzük"
    assert pazar.sorgu_olustur("Christmas Cable Car") == "teleferik yılbaşı"
    assert pazar.sorgu_olustur("Desk Organizer with Pen Holder") == "kalemlik masa düzenleyici"
    assert pazar.sorgu_olustur("Zorblax") == "zorblax"
    assert pazar.sorgu_olustur("") is None


def test_secilecekler(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_YENILEME_GUN", 14)
    simdi = datetime(2026, 11, 9, tzinfo=timezone.utc)
    secimler = [{"rank": i, "product_id": i, "urun": urun(i, f"M{i}", 1, 1, image_url=f"u{i}",
                                                          trend_rank=(9 if i == 4 else None))}
                for i in range(1, 6)]
    secimler[1]["urun"]["image_url"] = None
    tarihler = {1: "2026-11-01T00:00:00+00:00", 3: "2026-10-01T00:00:00+00:00"}
    assert [s["product_id"] for s in pazar.secilecekler(secimler, tarihler, simdi, adet=3)] == [4, 3, 5]


def test_calistir_iki_arama_ve_tekrar_aranmaz(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    u = urun(None, "Fidget Flexy Ring", 1, 1, image_url="https://cdn.example/r.png")
    pid = depo.urunleri_kaydet([u])[("makerworld", u["external_id"])]
    secimler = [{"rank": 1, "product_id": pid, "urun": {**u, "id": pid}}]
    istekler = []

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        istekler.append(p["engine"])
        assert p["api_key"] == "K"
        if p["engine"] == "google_lens":
            assert (p["url"], p["country"]) == (u["image_url"], "tr")
            return httpx.Response(200, json=LENS)
        assert (p["q"], p["gl"]) == ("fidget yüzük", "tr")
        return httpx.Response(200, json=ALISVERIS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sonuc = pazar.calistir(depo, secimler, "K", client)
    assert istekler == ["google_lens", "google_shopping"]
    assert sonuc[pid]["found_count"] == 7
    assert pazar.calistir(depo, secimler, "K", client) == {}   # 14 gün içinde tekrar aranmaz
    assert len(istekler) == 2


def test_hata_ve_bos_sonuc():
    kotu = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": "Invalid API key."})))
    with pytest.raises(pazar.PazarHatasi, match="Invalid API key"):
        pazar.lens_ara("X", "u", kotu)
    bos = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"error": "Google Shopping hasn't returned any results for this query."})))
    assert pazar.alisveris_ara("K", "q", bos) == {}


def test_rapor_ve_telegram():
    u = urun(1, "Ring", 10, 100, image_url="https://cdn.example/1.png", price_tl=65)
    secimler = ozet.sec(puanlama.puanla([u], {}, date(2026, 11, 9)))
    o = {secimler[0]["product_id"]: pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS),
                                                                    pazar.alisveris_sonuclari(ALISVERIS)))}
    md = ozet.markdown(date(2026, 11, 9), secimler, 1, "SQLite", o)
    assert "**Türk pazar yerlerinde:** Trendyol 3" in md and "senin önerilen fiyatın 65 TL" in md
    assert "  - Trendyol: [Squishy](https://www.trendyol.com/x/z-p-2) — 1200 TL (görsel eşleşme)" in md
    m = bildirim.mesajlar(date(2026, 11, 9), secimler, pazar_sonuclari=o)
    assert "🛒 Trendyol 3" in m[0]["veri"]["caption"]
