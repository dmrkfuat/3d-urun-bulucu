"""E-ticaret araştırması testleri. Yanıt biçimleri 2026-11-09'da alınan gerçek SerpApi
yanıtlarından sadeleştirilmiştir (Google Lens ve Google Alışveriş, Türkiye)."""
from datetime import date, datetime, timezone

import httpx
import pytest

from urun_bulucu import bildirim, config, ozet, pazar, puanlama
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

LENS = {"visual_matches": [
    {"title": "Print Forge 3D Baskı Katlanabilir Yüzük", "link": "https://www.trendyol.com/x/y-p-1",
     "source": "Trendyol"},
    {"title": "Dumpling Squishy", "link": "https://www.trendyol.com/x/z-p-2", "source": "Trendyol",   # 3D değil
     "price": {"value": "₺1.200*", "extracted_value": 1200.0, "currency": "₺"}},
    {"title": "3D Printed Flexy Ring", "link": "https://www.reddit.com/r/x", "source": "Reddit"},     # pazar yeri değil
    {"title": "3D Printed Flexi Ring", "link": "https://www.etsy.com/listing/9", "source": "Etsy",
     "price": {"value": "$12*", "extracted_value": 12.0, "currency": "$"}},                         # TL değil
    {"title": "3D printed ring", "link": "https://www.amazon.com/dp/1", "source": "Amazon"},          # TR değil
]}
ALISVERIS = {"shopping_results": [
    {"title": "Fidget Parmak Yüzüğü 3D Baski", "source": "Trendyol", "price": "₺134,99", "extracted_price": 134.99,
     "product_link": "https://www.google.com/search?prds=1"},
    {"title": "Fidget Yüzük 3D Baskı", "source": "Pixu3D", "price": "₺179,00", "extracted_price": 179.0,
     "product_link": "https://www.google.com/search?prds=2"},
    {"title": "Fidget Yüzük", "source": "Pixu3D", "price": "₺229,00",                              # satıcı adı 3D
     "product_link": "https://www.google.com/search?prds=3"},
    {"title": "Manyetik Stres Yüzüğü", "source": "trendyol.com", "price": "₺542,23", "extracted_price": 542.23,
     "product_link": "https://www.google.com/search?prds=4"},                                        # 3D değil
    {"title": "Fidget Rings 3D Baskı Modeli — Fidget Oyuncak", "source": "3D Yazdıralım", "price": "₺1,00",
     "extracted_price": 1.0, "product_link": "https://www.google.com/search?prds=5"},                # dijital dosya
    {"title": "Gyro Ring 3D Baskı", "source": "Atölye", "price": "₺10,00", "extracted_price": 10.0,
     "product_link": "https://www.google.com/search?prds=6"},                                        # 20 TL altı
    {"title": "Jiro Fidget 3D Baskı", "source": "Pixu3D", "price": "₺65.918,87", "extracted_price": 65918.87,
     "product_link": "https://www.google.com/search?prds=7"},                                        # uç değer
    {"title": "PLA Fidget Yıldızı", "source": "hepsiburada.com", "price": "₺279,00", "extracted_price": 279.0,
     "product_link": "https://www.google.com/search?prds=8"},
]}


def test_site_suzgeci():
    assert pazar.site_bul("https://www.trendyol.com/a-p-1", "Trendyol") == "Trendyol"
    assert pazar.site_bul("https://www.google.com/search?prds=2",
                          "Amazon.com.tr - Amazon.com.tr – pazaryeri") == "Amazon TR"
    assert pazar.site_bul("https://www.google.com/search?prds=1", "trendyol.com") == "Trendyol"
    assert pazar.site_bul(None, "Trendyol") is None   # bağlantısız sonuç kabul edilmez
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
    zararli = {"visual_matches": [{"title": "3D baskı", "link": "javascript:alert(1)", "source": "Trendyol"}]}
    assert pazar.lens_sonuclari(zararli) == []


def test_bagimsiz_magaza_etiketi_ve_baslik_temizligi(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_BAGIMSIZ_MAGAZALAR", True)
    assert pazar.bagimsiz_etiket("Pixu3D") == "Pixu3D"
    assert pazar.bagimsiz_etiket("3D Yazdıralım") == "3D Yazdıralım"
    assert pazar.bagimsiz_etiket("[Tıkla](https://x.example) **mağaza**") == "Tıklahttpsx.example mağaza"
    # Pazar yeri adına benzeyen bağımsız mağaza pazar yeri gibi görünemez
    assert pazar.bagimsiz_etiket("Trendyol") == "Trendyol (bağımsız)"
    assert pazar.bagimsiz_etiket("Trendyol Store 3D") == "Trendyol Store 3D (bağımsız)"
    assert pazar.bagimsiz_etiket("!!!") is None
    assert pazar.temiz_baslik("Yüzük ](javascript:x) **3D**\nBaskı") == "Yüzük javascript:x 3D Baskı"
    # Google'ın Trendyol dışı bir satıcıyı alan adı eşleşmesi olmadan "Trendyol" diye vermesi:
    sahte = {"shopping_results": [{"title": "Yüzük 3D Baskı", "source": "Trendyol Resmi Mağaza",
                                   "extracted_price": 100.0, "product_link": "https://shop.example/1"}]}
    [r] = pazar.alisveris_sonuclari(sahte)
    assert (r["site"], r["pazar_yeri"]) == ("Trendyol Resmi Mağaza (bağımsız)", False)


def test_uc_d_sarti():
    assert pazar.uc_d_mi("Fidget Yüzük 3D Baskı")
    assert pazar.uc_d_mi("Fidget Parmak Yuzugu 3D Baski")
    assert pazar.uc_d_mi("3D Printed Flexi Dragon")
    assert pazar.uc_d_mi("3 Boyutlu Yazıcı ile Basılmış Vazo")
    assert pazar.uc_d_mi("PLA Kalemlik")
    assert pazar.uc_d_mi("Fidget Yüzük", "Pixu3D")            # satıcı 3D baskı mağazası
    assert not pazar.uc_d_mi("Manyetik Stres Yüzüğü", "Trendyol")
    assert not pazar.uc_d_mi("Fidget Rings 3D Baskı Modeli — Fidget Oyuncak", "3D Yazdıralım")
    assert not pazar.uc_d_mi("Flexi Dragon STL dosyası")
    assert not pazar.uc_d_mi("3D puzzle ahşap")                # "3D" tek başına yetmez
    assert pazar.uc_d_mi("İndirimli 3D Baskı Vazo")            # "indirim" dijital sayılmaz


def test_fiyat_metinden():
    assert pazar._fiyat_metinden("₺2.348,59") == 2348.59
    assert pazar._fiyat_metinden("₺1.200*") == 1200.0
    assert pazar._fiyat_metinden("₺599") == 599.0
    assert pazar._fiyat_metinden(None) is None


def test_ayikla_ve_ozetle(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_BAGIMSIZ_MAGAZALAR", True)
    g = pazar.lens_sonuclari(LENS)
    assert [(r["site"], r["price"]) for r in g] == [("Trendyol", None), ("Etsy", None)]
    m = pazar.alisveris_sonuclari(ALISVERIS)
    assert [(r["site"], r["price"], r["pazar_yeri"]) for r in m] == [
        ("Trendyol", 134.99, True), ("Pixu3D", 179.0, False), ("Pixu3D", 229.0, False),
        ("Pixu3D", 65918.87, False), ("Hepsiburada", 279.0, True)]
    o = pazar.ozetle(5, pazar.birlestir(g, m), "fidget yüzük 3d baskı")
    # 65.918 TL uç değer istatistikten atılır (ortancanın 5 katından fazla)
    assert (o["min_price"], o["max_price"], o["currency"]) == (134.99, 279.0, "TL")
    assert pazar.medyan(o) == 204.0
    assert o["results"][0]["sorgu"] == "fidget yüzük 3d baskı"
    assert pazar.fiyat_yazi(o, 65) == ("3D baskı benzeri: Pixu3D 3, Trendyol 2, Etsy 1, Hepsiburada 1 · "
                                       "135–279 TL (ortanca 204 TL) · senin önerilen fiyatın 65 TL")
    assert pazar.fiyat_yazi(pazar.ozetle(5, [])) == "3D baskı benzeri satışta bulunamadı"


def test_yalniz_pazar_yerleri_ayari(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_BAGIMSIZ_MAGAZALAR", False)
    assert [r["site"] for r in pazar.alisveris_sonuclari(ALISVERIS)] == ["Trendyol", "Hepsiburada"]


def test_turkce_sorgu():
    assert pazar.sorgu_olustur("Ultra Satisfying Fidget Flexy Ring! (NO TPU!)") == "fidget yüzük"
    assert pazar.sorgu_olustur("Impossible Thread - Print-in-Place Fidget (no AMS)") == "imkansız vida fidget"
    assert pazar.sorgu_olustur("Custom Text Embosser | Print-in-Place Hinged Press") == "yazı kabartma pres"
    assert pazar.sorgu_olustur("MYLITOS MINI GRINCH") == "grinch"            # marka adı atılır
    assert pazar.sorgu_olustur("Gnomo Nordico Natalizio Stile Maglia NO AMS") == "cüce"
    assert pazar.sorgu_olustur("Zorblax Thing") == "zorblax thing"           # sözlükte yoksa ilk 2 kelime
    assert pazar.sorgu_olustur("ZORBLAX") is None                            # tamamı büyük harf: marka sayılır
    assert pazar.sorgu_olustur("Christmas Cable Car") == "teleferik yılbaşı"
    assert pazar.sorgu_olustur("Desk Organizer with Pen Holder") == "kalemlik masa düzenleyici"
    assert pazar.sorgu_olustur("Zorblax") == "zorblax"
    assert pazar.sorgu_olustur("") is None


def test_secilecekler_ve_eski_kural(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_YENILEME_GUN", 14)
    monkeypatch.setattr(config, "PAZAR_KURAL_TARIHI", "2026-11-09T17:30:00+00:00")
    simdi = datetime(2026, 11, 12, tzinfo=timezone.utc)
    secimler = [{"rank": i, "product_id": i, "urun": urun(i, f"M{i}", 1, 1, image_url=f"u{i}",
                                                          trend_rank=(9 if i == 4 else None))}
                for i in range(1, 6)]
    secimler[1]["urun"]["image_url"] = None
    tarihler = {1: "2026-11-10T00:00:00+00:00",      # yeni kuralla arandı → atlanır
                3: "2026-11-09T17:05:00+00:00"}      # eski kuralla arandı → yeniden aranır
    assert [s["product_id"] for s in pazar.secilecekler(secimler, tarihler, simdi, adet=3)] == [3, 4, 5]   # sıraya göre; 1 yakında arandı, 2 görselsiz


def test_calistir_iki_arama_ve_tekrar_aranmaz(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PAZAR_KURAL_TARIHI", "2026-01-01T00:00:00+00:00")
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
            assert (p["type"], p["q"]) == ("visual_matches", "fidget yüzük 3d baskı")   # görsel + metin
            return httpx.Response(200, json=LENS)
        assert (p["q"], p["gl"]) == ("fidget yüzük 3d baskı", "tr")
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
        pazar.lens_ara("X", "u", client=kotu)
    bos = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"error": "Google Shopping hasn't returned any results for this query."})))
    assert pazar.alisveris_ara("K", "q", bos) == {}


def test_rapor_ve_telegram():
    u = urun(1, "Ring", 10, 100, image_url="https://cdn.example/1.png", price_tl=65)
    secimler = ozet.sec(puanlama.puanla([u], {}, date(2026, 11, 9)))
    o = {secimler[0]["product_id"]: pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS),
                                                                    pazar.alisveris_sonuclari(ALISVERIS)))}
    md = ozet.markdown(date(2026, 11, 9), secimler, 1, "SQLite", o)
    assert "**Türkiye'de satışta:** 3D baskı benzeri: Pixu3D 3" in md and "senin önerilen fiyatın 65 TL" in md
    assert "  - Trendyol: [Print Forge Studio 3D Baskı Katlanabilir Yüzük](https://www.trendyol.com/x/y-p-1)" \
           " (görsel eşleşme)" in md or "  - Trendyol: [Print Forge 3D Baskı Katlanabilir Yüzük]" in md
    m = bildirim.mesajlar(date(2026, 11, 9), secimler, pazar_sonuclari=o)
    assert "🛒 3D baskı benzeri: Pixu3D 3" in m[0]["veri"]["caption"]


# ---------------------------------------------------------------- satış bağlantıları
def test_satis_linki_ve_yerleri():
    dogrudan = {"site": "Trendyol", "pazar_yeri": True, "title": "Yüzük 3D Baskı",
                "link": "https://www.trendyol.com/x/y-p-1", "price": None}
    assert pazar.satis_linki(dogrudan) == "https://www.trendyol.com/x/y-p-1"
    google = {"site": "Hepsiburada", "pazar_yeri": True, "title": "Fidget Yüzük 3D Baskı & Set",
              "link": "https://www.google.com/search?prds=1", "price": 279.0}
    assert pazar.satis_linki(google) == "https://www.hepsiburada.com/ara?q=Fidget+Y%C3%BCz%C3%BCk+3D+Bask%C4%B1+%26+Set"
    magaza = {"site": "Pixu3D", "pazar_yeri": False, "title": "Yüzük",
              "link": "https://www.google.com/search?prds=2", "price": 179.0}
    assert pazar.satis_linki(magaza) == "https://www.google.com/search?prds=2"

    o = {"results": [magaza, google, dogrudan,
                     {**google, "price": 199.0, "title": "Başka"},                     # aynı site: tek bağlantı
                     {"site": "Etsy", "pazar_yeri": True, "title": "Ring", "price": 150.0,
                      "link": "https://www.etsy.com/listing/5"}]}
    yerler = pazar.satis_yerleri(o)
    # önce pazar yerleri (fiyatlı ucuzdan pahalıya, fiyatsız sonra), her siteden bir tane, en fazla 3
    assert [(y["site"], y["price"]) for y in yerler] == [("Etsy", 150.0), ("Hepsiburada", 199.0), ("Trendyol", None)]
    assert pazar.satis_yerleri(None) == []


def test_telegram_satis_baglantilari_ve_uzunluk():
    o = pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS), pazar.alisveris_sonuclari(ALISVERIS)))
    s = {"rank": 1, "score": 90, "product_id": 1,
         "urun": urun(1, "Ring", 1, 1, image_url="https://cdn.example/1.png", price_tl=65)}
    yazi = bildirim.urun_yazisi(s, o)
    assert "   ↳ <a href=\"https://www.hepsiburada.com/ara?q=PLA+Fidget+Y%C4%B1ld%C4%B1z%C4%B1\">Hepsiburada</a> 279 TL" in yazi
    assert "🔗 MakerWorld: " in yazi
    # Sığmazsa satış bağlantıları azaltılır, HTML yarıda kesilmez
    kisa = bildirim.urun_yazisi(s, o, sinir=len(yazi) - 10)
    assert kisa.count("↳") == yazi.count("↳") - 1 and kisa.count("<a ") == kisa.count("</a>")

    kalan = [{"rank": i, "score": 80, "product_id": i, "urun": urun(i, f"M{i}", 1, 1)} for i in range(2, 6)]
    m = bildirim.mesajlar(date(2026, 11, 9), [s] + kalan, pazar_sonuclari={4: o})
    ozet_metni = m[-1]["veri"]["text"]
    assert "4. <a href" in ozet_metni and "\n   🛒 <a href=" in ozet_metni
    assert "(mağaza)" in ozet_metni or ozet_metni.count("🛒") == 1


def test_gecerli_mi(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_KURAL_TARIHI", "2026-11-09T17:10:00+00:00")
    assert pazar.gecerli_mi({"checked_at": "2026-11-09T18:00:00+00:00"})
    assert not pazar.gecerli_mi({"checked_at": "2026-11-09T14:33:34+00:00"})
    assert not pazar.gecerli_mi({})
    assert not pazar.gecerli_mi(None)


def test_dijital_dosya_siteleri_elenir():
    assert pazar.dijital_site_mi("https://cults3d.com/en/3d-model/x", None)
    assert pazar.dijital_site_mi(None, "cults3d.com")
    assert pazar.dijital_site_mi(None, "Creality Cloud")
    assert not pazar.dijital_site_mi("https://www.trendyol.com/x", "Trendyol")
    yanit = {"shopping_results": [
        {"title": "Grinch 3D Baskı", "source": "cults3d.com", "extracted_price": 90.0,
         "product_link": "https://www.google.com/search?prds=1"},
        {"title": "Grinch 3D Baskı", "source": "Deniz 3D Studio", "extracted_price": 65.0,
         "product_link": "https://www.google.com/search?prds=2"}]}
    assert [r["site"] for r in pazar.alisveris_sonuclari(yanit)] == ["Deniz 3D Studio"]
    # Eski kayıtta kalmış dijital site bağlantı olarak gösterilmez
    eski = {"results": [{"site": "cults3d.com", "pazar_yeri": False, "title": "x", "price": 90.0,
                         "link": "https://www.google.com/search?prds=1"}]}
    assert pazar.satis_yerleri(eski) == []



# ---------------------------------------------------------------- görselden kelime + sosyal medya
LENS_TR = {"visual_matches": [
    {"title": "Katlanabilir Stres Yüzüğü 3D Baskı", "link": "https://www.trendyol.com/a/b-p-1", "source": "Trendyol"},
    {"title": "3D Baskı Katlanabilir Stres Halkası", "link": "https://www.hepsiburada.com/c-p-2",
     "source": "Hepsiburada"},
    {"title": "Markaadı Fidget 3D Baskı", "link": "https://www.n11.com/urun/d-3", "source": "n11"},
    {"title": "Squishy Dumpling", "link": "https://www.trendyol.com/e-p-4", "source": "Trendyol"},   # 3D değil
    {"title": "Fidget yüzük 3D baskı 🌀 sipariş için DM", "link": "https://www.instagram.com/p/abc/",
     "source": "Instagram"},
    {"title": "3D Printed Flexy Fidget Ring | TikTok", "link": "https://www.tiktok.com/@x/video/1",
     "source": "TikTok"},
    {"title": "Satisfying 3D print", "link": "https://www.facebook.com/x/posts/1", "source": "Facebook"},
    {"title": "YouTube", "link": "https://www.youtube.com/watch?v=1", "source": "YouTube"},          # genel
    {"title": "zararlı", "link": "javascript:alert(1)", "source": "Instagram"},
]}


def test_lens_kelimeleri_ve_arama_metni():
    # "katlanabilir" ve "stres" iki Türkçe 3D baskı başlığında geçiyor; tek başlıktaki "markaadı" kullanılmaz
    assert pazar.lens_kelimeleri(LENS_TR) == ["katlanabilir", "stres"]
    assert pazar.arama_metni("Ultra Satisfying Fidget Flexy Ring", LENS_TR) ==         "fidget yüzük katlanabilir stres 3d baskı"
    assert pazar.arama_metni("Ultra Satisfying Fidget Flexy Ring", {}) == "fidget yüzük 3d baskı"
    assert pazar.arama_metni("", {}) is None


def test_sosyal_medya_sonuclari():
    s = pazar.sosyal_sonuclari(LENS_TR)
    assert [(r["site"], r["tr"], r["satis"]) for r in s] == [
        ("Instagram", True, True), ("TikTok", False, False), ("Facebook", False, False)]
    assert all(r["kaynak"] == "sosyal" and r["price"] is None for r in s)
    o = pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS_TR), []) + s)
    assert o["found_count"] == 3                       # sosyal medya satış sitesi sayılmaz
    assert pazar.sosyal_yazi(o) == "Sosyal medyada: Facebook 1, Instagram 1, TikTok 1 (1 Türkçe, 1 satış belirtili)"
    assert "Instagram" not in pazar.fiyat_yazi(o)
    assert all(y["site"] != "Instagram" for y in pazar.satis_yerleri(o))
    assert pazar.sosyal_etiket(s[0]) == " (Türkçe, satış)"
    # "Satisfying" satış belirtisi sayılmaz (Türkçe ı/i büyük-küçük harf tuzağı)
    assert not pazar.SATIS_IZI.search("Satisfying ring") and not pazar.TR_KELIME.search("Satisfying ring")


def test_telegram_ve_rapor_sosyal():
    o = pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS_TR), []) + pazar.sosyal_sonuclari(LENS_TR))
    s = {"rank": 1, "score": 90, "product_id": 1,
         "urun": urun(1, "Ring", 1, 1, image_url="https://cdn.example/1.png", price_tl=65)}
    yazi = bildirim.urun_yazisi(s, o)
    assert "📱 <a href=\"https://www.instagram.com/p/abc/\">Instagram</a> (Türkçe, satış)" in yazi
    md = ozet.markdown(date(2026, 11, 9), ozet.sec(puanlama.puanla([s["urun"]], {}, date(2026, 11, 9))), 1,
                       "SQLite", {s["urun"]["id"]: o})
    assert "- **Sosyal medyada: Facebook 1, Instagram 1, TikTok 1" in md
    assert "  - Instagram: [Fidget yüzük 3D baskı 🌀 sipariş için DM](https://www.instagram.com/p/abc/)"            " (Türkçe, satış)" in md



def test_sosyal_ilgi_suzgeci():
    lens = {"visual_matches": [
        {"title": "Yeni nesil magnetik fidget slider", "link": "https://www.instagram.com/p/1/"},
        {"title": "ORJİNAL BİREBİR EZME ANTIFAR STOKLARIMIZDA", "link": "https://www.instagram.com/p/2/"},
        {"title": "Modeling complex springs in Plasticity", "link": "https://www.youtube.com/watch?v=3"},
        {"title": "Grumpy Christmas Grinch 3D model for download", "link": "https://www.facebook.com/x/4"},
        {"title": "Satisfying donut 3D printed ASMR", "link": "https://www.tiktok.com/@a/video/5"},
    ]}
    anahtarlar = pazar.anahtar_kelimeler("Ultra Satisfying Fidget Flexy Ring", "fidget yüzük 3d baskı")
    assert "ring" in anahtarlar and "satisfying" not in anahtarlar
    basliklar = [r["title"] for r in pazar.sosyal_sonuclari(lens, anahtarlar)]
    # "springs" içindeki "ring" eşleşmez; ilgisiz antifar ve dosya indirme sayfası elenir
    assert basliklar == ["Yeni nesil magnetik fidget slider", "Satisfying donut 3D printed ASMR"]


def test_markdown_icin_parantezli_link():
    assert pazar.guvenli_link("https://shop.example/a_(b)[c]") == "https://shop.example/a_%28b%29%5Bc%5D"


def test_lens_ilgisiz_benzer_urunu_ve_yabanci_pazari_atar():
    yanit = {"visual_matches": [
        {"title": "3D Baskı Fidget Yüzük", "link": "https://www.trendyol.com/a/b-p-1", "source": "Trendyol"},
        {"title": "3D Baskı Katlanabilir Stres Yıldızı", "link": "https://www.trendyol.com/a/c-p-2",
         "source": "Trendyol"},
    ]}
    anahtar = pazar.anahtar_kelimeler("Fidget Flexy Ring", "fidget yüzük 3d baskı")
    assert [r["title"] for r in pazar.lens_sonuclari(yanit, anahtar)] == ["3D Baskı Fidget Yüzük"]
    assert len(pazar.lens_sonuclari(yanit)) == 2          # anahtar verilmezse eski davranış
    alis = {"shopping_results": [
        {"title": "3D Baskılı Stres Oyuncağı", "source": "Temu", "link": "https://www.temu.com/x",
         "extracted_price": 90},
        {"title": "3D Baskı Fidget Yüzük", "source": "Atölye3D", "link": "https://atolye3d.com/y",
         "extracted_price": 120},
    ]}
    assert [r["site"] for r in pazar.alisveris_sonuclari(alis)] == ["Atölye3D"]


def test_dosya_satisi_elenir():
    assert not pazar.uc_d_mi("3D Print File - Extra Spiky Fidget Spinner: Sensory Stim Toy")
    assert not pazar.uc_d_mi("Fidget Ring 3D Printer Files STL")
    assert pazar.uc_d_mi("3D Printed Spiral Fidget Toy")
