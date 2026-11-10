from datetime import date

import httpx

from urun_bulucu import config, kesif
from urun_bulucu.db import SqliteDepo

GUN = date(2026, 11, 10)


def _ilan(baslik, site="Hepsiburada", n=0, fiyat=300.0):
    return {"site": site, "title": baslik, "link": f"https://www.hepsiburada.com/u-{abs(hash(baslik)) % 10**8}-{n}",
            "price": fiyat, "thumbnail": f"https://t.example/{n}.jpg", "pazar_yeri": True, "kaynak": "metin"}


# ------------------------------------------------------------------ kümeleme
def test_kumele_markali_ilanlari_tek_urunde_toplar():
    ilanlar = [
        _ilan("Bezos 3D Baskı Dokunsal Fidget Cetveli - Kabartmalı Stres ve Odaklanma Oyuncağı - Kırmızı", n=1),
        _ilan("3D Baskı Dokunsal Fidget Cetveli - Kabartmalı Stres Ve Odaklanma Oyuncağı - Beyaz", "PttAVM", 2),
        _ilan("Nexora Living 3D Baskı Dokunsal Fidget Cetveli", "n11", 3),
        _ilan("Genel Markalar Sonsuz Küp Infinity Küp – Stres Atıcı, 3D Baskı", "Trendyol", 4),
        _ilan("MODA Sonsuz Küp Infinity Küp – Stres Atıcı, 3D Baskı", "Trendyol", 5),
        _ilan("3D Baskı Fidget Oyuncak", "Trendyol", 6),   # genel başlık: hangi ürün belli değil
    ]
    k = kesif.kumele(ilanlar)
    assert [len(x["ilanlar"]) for x in k] == [3, 2]
    assert k[0]["ad"] == "Dokunsal Fidget Cetveli" and k[0]["anahtar"] == "cetvel dokunsal"
    assert "infinity" in k[1]["anahtar"]                  # "Infinity" ı/i karışmaz
    assert kesif.ingilizce_sorgu(k[1]["kelimeler"]) == "infinity cube"


def test_ingilizce_kelimeler_ve_siki_isim_eslesmesi():
    ayirt, genel = kesif.ingilizce_kelimeler(["dokunsal", "fidget", "cetveli"])
    assert ayirt == ["tactile", "ruler"] and genel == ["fidget"]
    assert kesif.isim_uyar("Tactile Fidget Rulers", ["tactile", "ruler"])
    assert not kesif.isim_uyar("OTF Fidget Knife - Ruler - Comb", ["tactile", "ruler"])
    assert kesif.isim_uyar("Pen Holder Cat", ["pen holder"]) and not kesif.isim_uyar("x", [])


def test_lens_incele_model_sayfasi_ve_ilgili_ilanlar():
    kume = kesif.kumele([_ilan("Bezos 3D Baskı Dokunsal Fidget Cetveli", n=1)])[0]
    yanit = {"visual_matches": [
        {"position": 1, "source": "Çiçeksepeti", "title": "3D Baskı Dokunsal Fidget Cetveli - Kabartmalı",
         "link": "https://www.ciceksepeti.com/3d-baski-dokunsal-fidget-cetveli-kcm1"},
        {"position": 2, "source": "Trendyol", "title": "Pilsan Denge Oyunu",             # ilgisiz
         "link": "https://www.trendyol.com/pilsan/denge-p-1"},
        {"position": 15, "source": "MakerWorld", "title": "Fidget Ruler - Free 3D Print Model - MakerWorld",
         "link": "https://makerworld.com/en/models/1106083-fidget-ruler"},
        {"position": 43, "source": "Printables.com", "title": "Sabunluk - Basit Model / Soap Dish",   # şekil benzeri
         "link": "https://www.printables.com/model/1417151-sabunluk"},
    ]}
    ilanlar, modeller = kesif.lens_incele(yanit, kume)
    assert [i["site"] for i in ilanlar] == ["Çiçeksepeti"]
    assert [(m["site"], m["id"], m["sira"]) for m in modeller] == [("MakerWorld", "1106083", 15)]


# ------------------------------------------------------------------ uçtan uca (sahte SerpApi + MakerWorld)
def _serpapi(cagrilar, kalan=200):
    def handler(request: httpx.Request) -> httpx.Response:
        p = dict(request.url.params)
        cagrilar.append(p.get("engine") or "hesap")
        if request.url.path.endswith("account.json"):
            return httpx.Response(200, json={"total_searches_left": kalan})
        if p["engine"] == "google_shopping":
            if p["q"] != "3d baskı fidget":
                return httpx.Response(200, json={"shopping_results": []})
            return httpx.Response(200, json={"shopping_results": [
                {"title": "Bezos 3D Baskı Dokunsal Fidget Cetveli - Kırmızı", "source": "Hepsiburada",
                 "link": "https://www.hepsiburada.com/bezos-cetvel-p-1", "extracted_price": 338.9,
                 "thumbnail": "https://encrypted-tbn2.gstatic.com/shopping?q=tbn:1"},
                {"title": "3D Baskı Dokunsal Fidget Cetveli - Turuncu", "source": "n11",
                 "link": "https://www.n11.com/urun/cetvel-2", "extracted_price": 299.0},
                {"title": "3D Baskı Dokunsal Fidget Cetveli | Mor", "source": "PttAVM.com",
                 "link": "https://www.pttavm.com/cetvel-3", "extracted_price": 672.0},
            ]})
        if p["engine"] == "google_lens":
            return httpx.Response(200, json={"visual_matches": [
                {"position": 1, "source": "Çiçeksepeti", "title": "3D Baskı Dokunsal Fidget Cetveli",
                 "link": "https://www.ciceksepeti.com/cetvel-kcm9",
                 "price": {"extracted_value": 450, "currency": "₺"}},
                {"position": 9, "source": "MakerWorld", "title": "Fidget Ruler - MakerWorld",
                 "link": "https://makerworld.com/en/models/1106083-fidget-ruler"},
            ]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


class SahteMakerWorld:
    def __init__(self):
        self.aramalar = []

    def ara(self, terim, adet=30, gun=30):
        self.aramalar.append(terim)
        return [{"id": 2131615, "title": "OTF Fidget Knife - Ruler - Comb"},   # sıkı süzgeçte elenir
                {"id": 777, "title": "Tactile Fidget Ruler"}]

    def detay(self, tid):
        ad = {"1106083": "Fidget Ruler", "777": "Tactile Fidget Ruler"}[str(tid)]
        return {"id": int(tid), "title": ad, "designCreator": {"name": "Tasarımcı", "uid": 5},
                "downloadCount": 1000, "likeCount": 100,
                "instances": [{"id": 1, "prediction": 5400, "weight": 25, "isDefault": True}]}


def test_kesfet_kaydeder_eslestirir_ve_lensi_onbellekten_kullanir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KESIF_SORGULARI", ["3d baskı fidget", "3d baskı saksı"])
    monkeypatch.setattr(config, "RAPOR_KLASORU", tmp_path / "raporlar")
    depo = SqliteDepo(tmp_path / "t.db")
    cagrilar, mw = [], SahteMakerWorld()
    ayar = config.Ayarlar("", "", tmp_path / "t.db", serpapi_key="K")
    kumeler, yol = kesif.calistir(depo, ayar, GUN, mw, client=_serpapi(cagrilar))

    assert cagrilar.count("google_lens") == 1
    k = kumeler[0]
    assert k["ad"] == "Dokunsal Fidget Cetveli" and len(k["ilanlar"]) == 4   # 3 alışveriş + 1 Lens
    assert k["fiyat_medyan"] == 394.45
    assert [(e["external_id"], e["eslesme"]) for e in k["eslesmeler"]] == [("1106083", "görsel"), ("777", "isim")]
    e = k["eslesmeler"][0]
    assert e["product_id"] and e["kar_tl"] == round(394.45 - e["cost_tl"])
    satir = depo.kesif_onceki([k["anahtar"]], "2026-11-01")[k["anahtar"]]
    assert satir["ilan_sayisi"] == 4 and satir["lens_yapildi"] and satir["siteler"]["Hepsiburada"] == 1
    assert depo.con.execute("select category from products where external_id='1106083'").fetchone()[0] == kesif.KATEGORI
    md = open(yol, encoding="utf-8").read()
    assert "🎯 görsel eşleşme: [Fidget Ruler]" in md and "4 ilan" in md
    tg = kesif.telegram_mesaji(GUN, kumeler, "https://panel")
    assert "🎯 <a href=\"https://makerworld.com/en/models/1106083\">Fidget Ruler</a>" in tg and len(tg) <= 4096

    # Bir hafta sonra: aynı ürünün Lens sonucu önbellekten (kota harcanmaz).
    cagrilar.clear()
    sonraki = date(2026, 11, 17)
    assert kesif.zamani_geldi(depo, sonraki) and not kesif.zamani_geldi(depo, date(2026, 11, 12))
    kumeler, _ = kesif.calistir(depo, ayar, sonraki, mw, client=_serpapi(cagrilar))
    assert "google_lens" not in cagrilar and len(kumeler[0]["ilanlar"]) == 4


def test_calistir_zamani_gelmediyse_tablo_yoksa_veya_kota_azsa_aramaz(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAPOR_KLASORU", tmp_path / "raporlar")
    ayar = config.Ayarlar("", "", tmp_path / "t.db", serpapi_key="K")
    depo = SqliteDepo(tmp_path / "t.db")
    depo.kesif_kaydet([{"kesif_tarihi": "2026-11-08", "anahtar": "a", "ad": "a"}])
    cagrilar = []
    assert kesif.calistir(depo, ayar, GUN, SahteMakerWorld(), client=_serpapi(cagrilar)) == ([], None)

    class TabloYok(SqliteDepo):
        def kesif_son_tarih(self):
            raise RuntimeError('relation "market_discovery" does not exist')
    assert kesif.calistir(TabloYok(tmp_path / "u.db"), ayar, GUN, SahteMakerWorld(),
                          client=_serpapi(cagrilar)) == ([], None)
    assert kesif.calistir(SqliteDepo(tmp_path / "v.db"), ayar, GUN, SahteMakerWorld(),
                          client=_serpapi(cagrilar, kalan=10)) == ([], None)
    assert cagrilar == ["hesap"]     # yalnızca ücretsiz kota sorgusu


def test_tek_magazanin_cok_urunu_talep_sayilmaz():
    tek = [_ilan(f"3D Baskı Masa Düzenleyici Model {n}", "Pixu3D", n) for n in range(14)]
    cok = [_ilan("Dokunsal Fidget Cetveli", s, n) for n, s in enumerate(["Hepsiburada", "n11", "PttAVM"], 20)]
    assert kesif.talep_puani(tek) == 5 and kesif.talep_puani(cok) == 3
    assert kesif.site_sayisi(tek) == 1 and kesif.site_adi("trendruum.com") == "trendruum"
    # İsimle arama tek ayırt edici kelimeyle yapılmaz (her anahtarlık eşleşirdi).
    assert kesif.ingilizce_kelimeler(["maskot", "anahtarlik"])[0] == ["keychain"]


def test_model_sayfasi_alan_adini_dogrular():
    assert kesif.model_sayfasi("https://makerworld.com/en/models/1106083-fidget-ruler") == ("MakerWorld", "1106083")
    assert kesif.model_sayfasi("https://www.printables.com/model/1786092-star") == ("Printables", "1786092")
    assert kesif.model_sayfasi("https://www.thingiverse.com/thing:12345") == ("Thingiverse", "12345")
    assert kesif.model_sayfasi("https://kotu.example/?x=printables.com/model/1") is None
    assert kesif.model_sayfasi("https://printables.com.kotu.example/model/1") is None
    assert kesif.model_sayfasi("https://kotu.example/makerworld.com/models/1") is None
    assert kesif.model_sayfasi("https://makerworld.com/tr/search/models?keyword=x") is None
