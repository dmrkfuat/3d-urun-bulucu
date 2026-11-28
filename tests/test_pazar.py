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
    # İşaretlenmemiş (aynı ürün olduğu doğrulanmamış) sonuçlar fiyata katılmaz
    o = pazar.ozetle(5, pazar.birlestir(g, m), "fidget yüzük 3d baskı")
    assert (o["found_count"], o["min_price"], pazar.medyan(o)) == (0, None, None)
    assert pazar.fiyat_yazi(o, 65) == ("Aynı ürün Türkiye'de satışta bulunamadı "
                                       "(aynı kategoride 7 farklı ürün; fiyata katılmadı)")
    # Aynı ürün sayılanlar: 65.918 TL uç değer istatistikten atılır (ortancanın 5 katından fazla)
    o = pazar.ozetle(5, [{**r, "birebir": True} for r in pazar.birlestir(g, m)], "fidget yüzük 3d baskı")
    assert (o["found_count"], o["min_price"], o["max_price"], o["currency"]) == (7, 134.99, 279.0, "TL")
    assert pazar.medyan(o) == 204.0
    assert o["results"][0]["sorgu"] == "fidget yüzük 3d baskı"
    assert pazar.fiyat_yazi(o, 65) == ("Aynı ürün satışta: Pixu3D 3, Trendyol 2, Etsy 1, Hepsiburada 1 · "
                                       "135–279 TL (ortanca 204 TL) · senin önerilen fiyatın 65 TL")
    assert pazar.fiyat_yazi(pazar.ozetle(5, [])) == "Aynı ürün Türkiye'de satışta bulunamadı"


# ---------------------------------------------------------------- aynı ürün mü? (Kasım 2026 gerçek örnekleri)
def _s(title, kaynak="metin", price=None):
    return {"site": "Trendyol", "title": title, "kaynak": kaynak, "price": price, "pazar_yeri": True}


def test_kavramlar():
    k = lambda ad: [sorted(x) for x in pazar.kavramlar(ad)]   # noqa: E731
    assert k("Personalized Reindeer Sweater Ornament") == [["geyik", "reindeer"], ["kazak", "sweater"]]
    assert k("MYLITOS MINI GRINCH") == [["grinch"]]                       # büyük harf marka atılır
    assert k("Thermoformed Christmas gift box") == [["thermoformed"]]     # sezon/tür kelimeleri genel
    assert k("Knitted Santa Claus - No AMS, No Glue") == [["noel baba", "santa claus"], ["knitted", "orgu"]]
    assert k("The Dark Spin - Batarang Fidget Spinner") == [["spin"], ["batarang"]]
    assert k("Fidget Toy") == []


def test_ayni_urun_metin_aramasi_iki_kavram_ister():
    ad = "Personalized Reindeer Sweater Ornament"
    o = pazar.ozetle(1, [_s("Geyik Duvar Dekorasyonu 3D Baskı", price=319.0),
                         _s("Geometrik Geyik Figür Seti – 2'li 20 cm 3D Yazıcı Baskı", price=719.0),
                         _s("Geyik Desenli Kazaklı Yılbaşı Süsü 3D Baskı", price=150.0)], None, ad)
    assert [r["birebir"] for r in o["results"]] == [False, False, True]   # "geyik" tek başına yetmez
    assert (o["found_count"], o["min_price"]) == (1, 150.0)
    # Tek kavramlı modelde metin araması hiçbir zaman aynı ürün sayılmaz (görsel doğrulama yok)
    o = pazar.ozetle(1, [_s("Hivhestin Fidget Grinch Figür 3D Baskı", price=599.0)], None, "MYLITOS MINI GRINCH")
    assert o["found_count"] == 0


def test_ayni_urun_gorsel_eslesme():
    ad = "MYLITOS MINI GRINCH"
    o = pazar.ozetle(1, [_s("YAMAN3D 20'li Mini Grinch Figür Seti – Noel Şapkalı", "görsel", 200.0),
                         _s("Anka Atolye Sevimli Yılbaşı Canavarı Monitör Figürü 3D Baskı", "görsel", 261.0)],
                     None, ad)
    assert [r["birebir"] for r in o["results"]] == [True, False]
    # Görsel eşleşmede de iki kavramlı modelde iki kavram gerekir (yalnızca "noel baba" farklı üründür)
    o = pazar.ozetle(1, [_s("3D Baskı Mini Noel Baba Figürü", "görsel", 719.0),
                         _s("3D Baskı Örgü Dokulu Noel Baba Figürü", "görsel", 299.0)],
                     None, "Knitted Santa Claus - No AMS, No Glue")
    assert [r["birebir"] for r in o["results"]] == [False, True]


def test_ayni_urun_kelime_iki_kavrama_sayilmaz_ve_parca_ilanlari():
    ad = "The Dark Spin - Batarang Fidget Spinner"
    assert not pazar.ayni_urun_mu(_s("Jiroskopik Fidget Spinner 3D Baskı"), pazar.kavramlar(ad))  # spin ⊂ spinner
    # Klavye switch'i ve yazıcı parçası 3D baskı ürün değildir
    assert not pazar.uc_d_mi("Clicker Blue Switch 3D Baskı İçin 1000 adet")
    assert not pazar.uc_d_mi("Mavi Clicker Switch, 3D Projeler için - 10 Adet")
    assert pazar.uc_d_mi("3D Baskı Clicker Fidget Oyuncak")


def test_kayitlari_oku_yeniden_isaretler_ve_yazar(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    u = urun(None, "Personalized Reindeer Sweater Ornament", 1, 1)
    pid = depo.urunleri_kaydet([u])[("makerworld", u["external_id"])]
    eski = {"product_id": pid, "checked_at": "2026-11-20T10:00:00+00:00", "found_count": 1,
            "min_price": 319.0, "max_price": 319.0, "currency": "TL",
            "results": [{**_s("Geyik Duvar Dekorasyonu 3D Baskı", price=319.0), "sorgu": "geyik kazak süs 3d baskı"}]}
    depo.pazar_kaydet([eski])
    o = pazar.kayitlari_oku(depo, [{**u, "id": pid}])[pid]
    assert (o["found_count"], o["min_price"], o["checked_at"]) == (0, None, "2026-11-20T10:00:00+00:00")
    assert o["results"][0]["sorgu"] == "geyik kazak süs 3d baskı" and o["results"][0]["birebir"] is False
    kayit = depo.pazar_kayitlari([pid])[pid]                 # panel de aynı işareti görsün
    assert (kayit["found_count"], kayit["results"][0]["birebir"]) == (0, False)


def test_yalniz_pazar_yerleri_ayari(monkeypatch):
    monkeypatch.setattr(config, "PAZAR_BAGIMSIZ_MAGAZALAR", False)
    assert [r["site"] for r in pazar.alisveris_sonuclari(ALISVERIS)] == ["Trendyol", "Hepsiburada"]


def test_turkce_sorgu():
    assert pazar.sorgu_olustur("Ultra Satisfying Fidget Flexy Ring! (NO TPU!)") == "fidget yüzük"
    assert pazar.sorgu_olustur("Impossible Thread - Print-in-Place Fidget (no AMS)") == "imkansız vida fidget"
    assert pazar.sorgu_olustur("Custom Text Embosser | Print-in-Place Hinged Press") == "kabartma mühür pres"
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
    # 7 satış sonucu kaydedilir ama hiçbiri "Flexy" + "yüzük" içermediği için aynı ürün sayılmaz
    assert len(sonuc[pid]["results"]) == 7 and sonuc[pid]["found_count"] == 0
    assert all(r["birebir"] is False for r in sonuc[pid]["results"])
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
    sonuclar = pazar.birlestir(pazar.lens_sonuclari(LENS), pazar.alisveris_sonuclari(ALISVERIS))
    sonuclar = [{**r, "birebir": r["site"] != "Hepsiburada"} for r in sonuclar]   # biri farklı ürün
    o = {secimler[0]["product_id"]: pazar.ozetle(1, sonuclar)}
    md = ozet.markdown(date(2026, 11, 9), secimler, 1, "SQLite", o)
    assert "**Türkiye'de satışta:** Aynı ürün satışta: Pixu3D 3" in md and "senin önerilen fiyatın 65 TL" in md
    assert "(aynı kategoride 1 farklı ürün; fiyata katılmadı)" in md
    assert "  - Trendyol: [Print Forge 3D Baskı Katlanabilir Yüzük]" in md
    assert "PLA Fidget Yıldızı" not in md                    # farklı ürün bağlantı olarak listelenmez
    m = bildirim.mesajlar(date(2026, 11, 9), secimler, pazar_sonuclari=o)
    assert "🛒 Aynı ürün satışta: Pixu3D 3" in m[0]["veri"]["caption"]


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

    o = {"results": [{**r, "birebir": True} for r in [
        magaza, google, dogrudan,
        {**google, "price": 199.0, "title": "Başka"},                     # aynı site: tek bağlantı
        {"site": "Etsy", "pazar_yeri": True, "title": "Ring", "price": 150.0, "link": "https://www.etsy.com/listing/5"}]]
        + [{"site": "n11", "pazar_yeri": True, "title": "Farklı ürün", "price": 20.0,   # aynı ürün değil: gösterilmez
            "link": "https://www.n11.com/urun/1", "birebir": False}]}
    yerler = pazar.satis_yerleri(o)
    # önce pazar yerleri (fiyatlı ucuzdan pahalıya, fiyatsız sonra), her siteden bir tane, en fazla 3
    assert [(y["site"], y["price"]) for y in yerler] == [("Etsy", 150.0), ("Hepsiburada", 199.0), ("Trendyol", None)]
    assert pazar.satis_yerleri(None) == []


def test_telegram_satis_baglantilari_ve_uzunluk():
    o = pazar.ozetle(1, [{**r, "birebir": True} for r in
                         pazar.birlestir(pazar.lens_sonuclari(LENS), pazar.alisveris_sonuclari(ALISVERIS))])
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
    o = pazar.ozetle(1, pazar.birlestir(pazar.lens_sonuclari(LENS_TR), []) + s, None, "Ring")
    assert o["found_count"] == 1                       # yalnızca "Yüzüğü"; sosyal medya satış sitesi sayılmaz
    assert all("birebir" not in r for r in o["results"] if r["kaynak"] == "sosyal")
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


def test_urun_tipi_ve_etiketler():
    assert pazar.arama_metni("MYLITOS MINI GRINCH", None, ["grinch", "christmas", "decoration", "toy"]) \
        == "grinch mini figür 3d baskı"                      # karakter + mini → mini figür (süs değil)
    assert pazar.arama_metni("Christmas Cable Car", None, ["cable car", "decoration"]) \
        == "teleferik yılbaşı süsü 3d baskı"
    assert pazar.arama_metni("Fidget Flexy Ring", None, ["fidget", "decoration"]) == "fidget yüzük 3d baskı"  # tip zaten var
    assert pazar.arama_metni("Custom Text Embosser | Hinged Press") == "kabartma mühür pres 3d baskı"
    assert pazar.arama_metni("XQZW", None, ["keychain", "dragon"]) == "anahtarlık ejderha 3d baskı"   # addan çıkmazsa etiketlerden


def test_genis_metin():
    assert pazar.genis_metin("fidget yüzük 3d baskı") == "stres oyuncağı yüzük 3d baskı"
    assert pazar.genis_metin("noel baba tutucu 3d baskı") is None          # "noel baba" bölünmez
    assert pazar.genis_metin("minik kablo tutucu 3d baskı") == "kablo tutucu 3d baskı"
    assert pazar.genis_metin(None) is None


def _yedek_istemci(kalan: int, istekler: list):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("account.json"):
            istekler.append("hesap")
            return httpx.Response(200, json={"total_searches_left": kalan})
        p = request.url.params
        istekler.append((p["engine"], p.get("q")))
        return httpx.Response(200, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_az_sonucta_genis_arama_kota_varsa():
    u = {"name": "Fidget Flexy Ring", "image_url": "https://cdn.example/r.png", "tags": []}
    istekler = []
    _, sorgu = pazar.urun_ara("K", u, _yedek_istemci(200, istekler))
    assert istekler[-2:] == ["hesap", ("google_shopping", "stres oyuncağı yüzük 3d baskı")]
    assert sorgu == "fidget yüzük 3d baskı · stres oyuncağı yüzük 3d baskı"
    istekler = []
    pazar.urun_ara("K", u, _yedek_istemci(10, istekler))            # kota azsa ek arama yok
    assert [i for i in istekler if i != "hesap"] == [("google_lens", "fidget yüzük 3d baskı"),
                                                     ("google_shopping", "fidget yüzük 3d baskı")]


def test_yazici_ve_sarf_malzemesi_urun_sayilmaz():
    """2026-11-27 kayıtları: zayıf arama metni ("örgü 3d baskı", "cüce 3d baskı") 3D yazıcı ve reçine
    ilanları döndürdü; bunlar "3D Yazıcı" yazdığı için 3D baskı ürün sayılıyordu."""
    for baslik in ("ZAXE X4 3D Yazıcı", "Bambu Lab A1 Combo 3d Yazıcı Materyal Ve Gelişmiş Özellikler",
                   "Anycubic Tough 3D Yazıcı Reçine", "Dental 4K LCD 3D Yazıcı RF-3024D Platform B",
                   "3D Yazıcı: Bir Sonraki Seviye", "eSun PLA+ Filament 1.75 mm 1 kg Siyah"):
        assert pazar.makine_mi(baslik) and not pazar.uc_d_mi(baslik), baslik
    for baslik in ("3D Yazıcı Baskı Dekoratif Geyik Figürü", "Yılbaşı Temalı 3D Yazıcı Üretimi Basmalı Noel Baba",
                   "3 Boyutlu Yazıcı ile Basılmış Vazo", "PLA filament ile üretilmiş vazo 3D baskı",
                   # pazar yerinin kestiği uzun başlık "… 3D Yazıcı" ile bitse de basılmış üründür
                   "Geometrik Geyik Figür Seti – 20 cm 3D Yazıcı Baskı PLA Malzeme - Geometrik Geyik Seti 3D Yazıcı "):
        assert not pazar.makine_mi(baslik) and pazar.uc_d_mi(baslik), baslik


def test_ilgisiz_ilan_benzer_urun_sayilmaz():
    ad, sorgu = "Knitted Reindeer", "örgü geyik 3d baskı"
    assert pazar.ilanla_ilgili("Minimalist 3D Baskı Geyik Figürü", ad, sorgu)
    assert pazar.ilanla_ilgili("Alternatif Yılbaşı Geyiği Süsü 3D Baskı", ad, sorgu)       # Türkçe ek: geyik → geyiği
    assert pazar.ilanla_ilgili("3D Printed Knitted Reindeer Ornament", ad, sorgu)          # model adındaki kelime
    assert not pazar.ilanla_ilgili("Creeper Figürü", ad, sorgu)
    assert not pazar.ilanla_ilgili("Bambu Lab A1 3D Yazıcı", ad, sorgu)
    assert not pazar.ilanla_ilgili("Clicker Blue Switch 3D Baskı İçin 10 adet", "Clicky Clicker", "clicker 3d baskı")
    assert pazar.ilanla_ilgili("Herhangi bir ilan 3D Baskı", None, None)                   # ne arandığı bilinmiyor
    # Kayıtlı arama metni eski olsa da model adının bugünkü Türkçe karşılığı sayılır.
    assert pazar.ilanla_ilgili("3D Baskı Kurabiye Adam Yılbaşı Maketi", "Gingerbread House Kit Card", "ev süs 3d baskı")

    sonuclar = [
        {"site": "Pixu3D", "title": "Geyik Duvar Dekorasyonu 3D Baskı", "price": 319.0, "kaynak": "metin"},
        {"site": "Filamentsan", "title": "Anycubic 3D Yazıcı Reçine", "price": 719.0, "kaynak": "metin"},
        {"site": "3DŞehri", "title": "Creeper Figürü", "price": 130.0, "kaynak": "metin"},
        {"site": "Trendyol", "title": "Örgü Geyik Süsü 3D Baskı", "price": 250.0, "kaynak": "metin"},
        {"site": "Instagram", "title": "geyik", "kaynak": "sosyal"},
    ]
    o = pazar.ozetle(1, sonuclar, sorgu, ad)
    assert [r.get("ilgili") for r in o["results"]] == [True, False, False, True, None]
    assert o["found_count"] == 1 and [r["title"] for r in pazar.ayni_urunler(o)] == ["Örgü Geyik Süsü 3D Baskı"]
    assert [r["title"] for r in pazar.benzer_urunler(o)] == ["Geyik Duvar Dekorasyonu 3D Baskı"]
    assert "aynı kategoride 1 farklı ürün" in pazar.fiyat_yazi(o)
    assert pazar.ilgili_sayisi(sonuclar, ad, sorgu) == 2
    # Eski kayıt (ilgili işareti yok) yeniden işaretlenince aynı sonuca varır; işaretsiz kayıt eskisi gibi sayılır.
    eski = {**o, "results": [{k: v for k, v in r.items() if k != "ilgili"} for r in o["results"]]}
    assert len(pazar.benzer_urunler(eski)) == 3
    assert len(pazar.benzer_urunler(pazar.yeniden_ozetle(eski, ad))) == 1


def test_genel_kelime_tek_basina_ilgili_saymaz():
    """28 Kasım 2026 günlük çalışması: arama metni zayıf kalınca tek bir genel kelimeyle ("sevimli",
    "yılbaşı", "stand") eşleşen alakasız ilanlar benzer ürün sayılıyor, ürün Türkiye kontrolünü geçiyordu."""
    ilgili = pazar.ilanla_ilgili
    # tema / sıfat tek başına yetmez
    ad, sorgu = "Renna Natalizia a Maglia: Cute Edition NO AMS", "sevimli 3d baskı"
    assert not ilgili("3D Baskı Sevimli Ayıcık Biblo – Kalpli Dekoratif Hediyelik Fiyatı", ad, sorgu)
    assert not ilgili("lina hobby 1 Adet 3D Baskı Sevimli Ahtapot Anahtarlık", ad, sorgu)
    # geniş tip tek başına yetmez
    ad, sorgu = "GTA 6 (GTA VI) PS5 DualSense Controller Stand", "stand 3d baskı"
    assert not ilgili("3D Baskı Takı Standı – Küpe, Kolye ve Yüzük Organizeri", ad, sorgu)
    assert ilgili("PS5 DualSense Stand 3D Baskı", ad, sorgu)                               # ayırt edici kelime
    # belirli tip yeter; tema + tema yetmez
    ad, sorgu = "Christmas Light Slinky • Christmas Fidget • No AMS", "yılbaşı lamba fidget 3d baskı"
    assert ilgili("Tetra's 3D Baskı Zincirli Fidget Spinner Stres Oyuncağı Fiyatı", ad, sorgu)
    assert not ilgili("Yılbaşı Tombala Fiyatı, Taksit Seçenekleri ile Satın Al", ad, sorgu)
    assert not ilgili("Antilop 3'lü 3D Baskı Noel Baba Yılbaşı Masaüstü Dekoratif", ad, sorgu)
    assert ilgili("Pitbull Anahtarlık 3D Baskı", "Mini Sliding Photo Book Keychain - 2×3 & 3×4 cm", "anahtarlık 3d baskı")
    # geniş tip, yanında ikinci bir genel kavramla yeter
    ad, sorgu = "Cute Christmas Snoopy - Multi-Part (No AMS Needed)", "sevimli yılbaşı süsü 3d baskı"
    assert ilgili("3D Baskı Sevimli Yılbaşı Süsü", ad, sorgu)
    assert not ilgili("Sevimli Bacaklı 3D Baskı Yılbaşı Ağacı Figürleri", ad, sorgu)
    # çok kelimeli kavramda genel kelime aranmaz; iyelik eki ve İngilizce çoğul serbest
    ad, sorgu = "Christmas Tree Cake Holder Hype Chain Locket", "yılbaşı ağacı tutucu 3d baskı"
    assert ilgili("Noel Ağacı 3D Baskı", ad, sorgu) and ilgili("Minimal 3’lü Yılbaşı Ağaç Dekor Seti", ad, sorgu)
    assert not ilgili("Evrensel Yılbaşı Süs Askısı 3D Baskı", ad, sorgu)
    assert ilgili("Yıldız Tealight Mum Tutucu Seti", "Winter Windowsill Village for LED Tealights", "köy tealight mumluk 3d baskı")
    assert ilgili("Kardan Adam Figürü", "Goofy series – SNOWMAN", "kardan adam figür 3d baskı")
    assert not ilgili("Kurabiye Adam Figürü", "Goofy series – SNOWMAN", "kardan adam figür 3d baskı")
    # ürünün bilinen tek kavramı genelse o kavram yeter
    assert ilgili("Dekoratif Süs 3D Baskı", "Ornament", "süs 3d baskı")
    assert not ilgili("Dekoratif Biblo 3D Baskı", "Ornament", "süs 3d baskı")
    # pazar yerinin kategori / arama sayfası ilan değildir
    assert not ilgili("Sayfa 40 – yılbaşı geyiği", "Knitted Reindeer", "örgü geyik 3d baskı")
    assert not ilgili("3D Hediyelikler 🎁 - Sevdiklerinizi Mutlu Edin - Sayfa 8", "Knitted Reindeer", "örgü geyik 3d baskı")
