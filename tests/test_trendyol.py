import json
from datetime import date

import httpx
import pytest

from urun_bulucu import config, trendyol
from urun_bulucu.db import SqliteDepo

ROBOTS = """
User-agent: *
User-agent: Googlebot
Disallow: /sr?
Disallow: /*?sst=
Disallow: /*/*-p-*/saticilar
Disallow: /kapali/
Allow: /kapali/acik-p-9

User-agent: KotuBot
Disallow: /
"""


def _sayfa(ad, marka="WORK3D", magaza_id=895933, magaza="Çınar3D Store", deg=10, fav=100, benzer=(),
           fiyat=199.9, stok=True):
    ld = {"@context": "https://schema.org", "@type": "Product", "name": ad,
          "brand": {"@type": "Brand", "name": marka}, "image": ["https://cdn.dsmcdn.com/u.jpg"],
          "offers": {"@type": "Offer", "price": str(fiyat),
                     "availability": f"https://schema.org/{'InStock' if stok else 'OutOfStock'}"},
          "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.5, "ratingCount": deg,
                              "reviewCount": deg // 2}}
    durum = ('{"merchantListing":{"merchant":{"id":%d,"name":"%s","officialName":"GİZLİ KİŞİ",'
             '"registeredEmailAddress":"gizli@ornek.com","taxNumber":"1234567890"}},"favoriteCount":%d,'
             '"category":{"id":1,"name":"Askılık","hierarchy":"Ev \\u002FAskılık"}}' % (magaza_id, magaza, fav))
    linkler = "".join(f'<a href="{b}?boutiqueId=1">x</a>' for b in benzer)
    return (f'<html><script type="application/ld+json">{json.dumps(ld)}</script>'
            f"<script>window.__D__={durum}</script>{linkler}</html>")


SAYFALAR = {
    "/work3d/top-askisi-3d-baski-p-1": _sayfa("WORK3D Top Askısı 3D Baskı", deg=17, fav=331,
                                              benzer=["/dersan3d/sapka-askisi-p-2", "/lefty/ahsap-raf-p-3",
                                                      "/genel-markalar/kartal-3d-baski-p-4",
                                                      "/work3d/top-askisi-3d-baski-p-1"]),
    "/dersan3d/sapka-askisi-p-2": _sayfa("dersan3d Şapka Askısı", "dersan3d", 1131175, "Dersan3D", 31, 944,
                                         benzer=["/work3d/kartal-aplik-p-5"]),
    "/lefty/ahsap-raf-p-3": _sayfa("Ahşap Raf", "Lefty", 7, "Lefty Ev", 500, 9000),
    "/genel-markalar/kartal-3d-baski-p-4": _sayfa("Kartal 3D Baskı Lamba", "Genel Markalar"),
    "/work3d/kartal-aplik-p-5": _sayfa("WORK3D Kartal Aplik", deg=4, fav=277, stok=False),
}


def _trendyol(okunan, durum=None):
    def handler(request: httpx.Request) -> httpx.Response:
        yol = request.url.path
        okunan.append(yol)
        assert request.headers["User-Agent"] == config.TRENDYOL_UA   # kimlik gizlenmez
        if durum and yol in durum:
            return durum[yol]
        if yol == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if yol in SAYFALAR:
            return httpx.Response(200, text=SAYFALAR[yol])
        return httpx.Response(404)
    return trendyol.Okuyucu(httpx.Client(transport=httpx.MockTransport(handler)), bekleme_sn=0)


def test_robots_gruplari_en_uzun_eslesme_ve_yildiz():
    r = trendyol.Robots(ROBOTS)
    assert r.izinli("/work3d/x-p-1")
    assert not r.izinli("/sr?mid=895933&os=1")
    assert not r.izinli("/magaza/cinar3d-store-m-895933?sst=0")
    assert not r.izinli("/work3d/x-p-1/saticilar")
    assert not r.izinli("/kapali/baska-p-8") and r.izinli("/kapali/acik-p-9")   # daha uzun Allow kazanır
    assert len(r.kurallar) == 5   # KotuBot grubunun "Disallow: /" kuralı bize uygulanmaz


def test_yol_al_yalnizca_trendyol_urun_adresi():
    assert trendyol.yol_al("https://www.trendyol.com/work3d/top-p-871801614?boutiqueId=61") == "/work3d/top-p-871801614"
    assert trendyol.yol_al("https://trendyol.com/a/b-p-1#x") == "/a/b-p-1"
    for link in ["http://www.trendyol.com/a/b-p-1", "https://www.trendyol.com.kotu.site/a/b-p-1",
                 "https://www.trendyol.com/sr?mid=1", "https://www.trendyol.com/magaza/x-m-1", None, ""]:
        assert trendyol.yol_al(link) is None


def test_urun_ayikla_kisisel_bilgi_almaz():
    u = trendyol.urun_ayikla(SAYFALAR["/work3d/top-askisi-3d-baski-p-1"], "/work3d/top-askisi-3d-baski-p-1")
    assert (u["urun_id"], u["magaza_id"], u["magaza"], u["marka"]) == (1, 895933, "Çınar3D Store", "WORK3D")
    assert (u["degerlendirme"], u["yorum"], u["favori"], u["fiyat"], u["puan"]) == (17, 8, 331, 199.9, 4.5)
    assert u["kategori"] == "Ev /Askılık" and u["stokta"] and u["gorsel"] == "https://cdn.dsmcdn.com/u.jpg"
    assert "/dersan3d/sapka-askisi-p-2" in u["benzer"] and "/work3d/top-askisi-3d-baski-p-1" not in u["benzer"]
    metin = json.dumps(u, ensure_ascii=False)
    assert "GİZLİ" not in metin and "gizli@" not in metin and "1234567890" not in metin
    assert trendyol.urun_ayikla("<html>doğrulama</html>", "/a/b-p-1") is None


def test_aday_mi_adresten_3d_tahmini():
    assert trendyol.aday_mi("/dersan3d/sapka-p-2", set())                 # markada 3d
    assert trendyol.aday_mi("/lefty/kartal-3d-baski-lamba-p-3", set())    # adında 3d baskı
    assert not trendyol.aday_mi("/lefty/ahsap-raf-p-3", set())
    assert trendyol.aday_mi("/lefty/ahsap-raf-p-3", {"lefty"})            # bilinen 3D mağaza markası
    assert not trendyol.aday_mi("/genel-markalar/kartal-3d-baski-p-4", set())
    # "3 boyutlu" tek başına 3D baskı değil (manyetik yapı blokları)
    assert not trendyol.aday_mi("/magly/manyetik-yapi-bloklari-renkli-3-boyutlu-72-parca-p-876839630", set())
    assert trendyol.aday_mi("/x/3-boyutlu-baski-kartal-p-1", set())


def test_uc_d_mi_manyetik_blok_degil():
    u = {"ad": "Magly Manyetik Yapı Blokları – Renkli 3 Boyutlu 72 Parça", "marka": "Magly", "magaza": "Magly",
         "yol": "/magly/manyetik-yapi-bloklari-renkli-3-boyutlu-72-parca-p-876839630"}
    assert not trendyol.uc_d_mi(u)
    assert trendyol.uc_d_mi({**u, "marka": "BASKIMARKETİM"})                       # 3D baskı mağazası
    assert trendyol.uc_d_mi({**u, "ad": "Kartal 3D Baskı Lamba", "marka": "X", "magaza": "Y"})
    assert not trendyol.uc_d_mi({**u, "ad": "Kartal 3D baskı STL dosyası", "marka": "3D Dosya"})


def test_tara_kurallara_uyar_ve_benzerlerden_3d_magazalara_ulasir():
    okunan = []
    oku = _trendyol(okunan)
    urunler, neden = trendyol.tara(oku, [], ["/work3d/top-askisi-3d-baski-p-1"], set(), sinir=10)
    assert neden is None
    assert {u["urun_id"] for u in urunler} == {1, 2, 5}
    assert "/lefty/ahsap-raf-p-3" not in okunan                 # 3D değil: açılmaz
    assert "/genel-markalar/kartal-3d-baski-p-4" not in okunan  # temkinli: açılmaz
    assert okunan[0] == "/robots.txt" and okunan.count("/work3d/top-askisi-3d-baski-p-1") == 1


def test_robotsta_kapali_adres_acilmaz():
    okunan = []
    oku = _trendyol(okunan)
    assert oku.urun("/kapali/baska-p-8") is None and "/kapali/baska-p-8" not in okunan
    assert oku.urun("/sr?q=3d") is None


@pytest.mark.parametrize("yanit", [httpx.Response(403), httpx.Response(429),
                                   httpx.Response(200, text="<html>Lütfen robot olmadığınızı doğrulayın</html>")])
def test_engel_gorulunce_durur(yanit):
    okunan = []
    oku = _trendyol(okunan, {"/dersan3d/sapka-askisi-p-2": yanit})
    urunler, neden = trendyol.tara(oku, [], ["/work3d/top-askisi-3d-baski-p-1"], set(), sinir=10)
    assert neden and [u["urun_id"] for u in urunler] == [1]
    assert "/work3d/kartal-aplik-p-5" not in okunan


def test_yonlendirme_izlenmez():
    okunan = []
    oku = _trendyol(okunan, {"/work3d/top-askisi-3d-baski-p-1": httpx.Response(
        301, headers={"Location": "https://www.trendyol.com/sr?mid=1"})})
    assert oku.urun("/work3d/top-askisi-3d-baski-p-1") is None
    assert "/sr" not in okunan


def test_sayfa_siniri():
    okunan = []
    urunler, _ = trendyol.tara(_trendyol(okunan), [], ["/work3d/top-askisi-3d-baski-p-1"], set(), sinir=2)
    assert len([y for y in okunan if y != "/robots.txt"]) == 2


class SahteMakerWorld:
    def ara(self, terim, adet=30, gun=30):
        return [{"id": 42, "title": "Hat Hanger Rack"}]

    def detay(self, tid):
        return {"id": int(tid), "title": "Hat Hanger Rack", "designCreator": {"name": "T", "uid": 5},
                "downloadCount": 10, "likeCount": 1,
                "instances": [{"id": 1, "prediction": 3600, "weight": 30, "isDefault": True}]}


def test_calistir_kaydeder_siralar_ve_haftalik_hizi_hesaplar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAPOR_KLASORU", tmp_path / "raporlar")
    monkeypatch.setattr(config, "TRENDYOL_TOHUMLAR", ["https://www.trendyol.com/work3d/top-askisi-3d-baski-p-1"])
    monkeypatch.setattr(config, "TRENDYOL_LENS_ADET", 0)
    depo = SqliteDepo(tmp_path / "t.db")
    ayar = config.Ayarlar("", "", tmp_path / "t.db")
    gun1 = date(2026, 11, 12)
    s = trendyol.calistir(depo, ayar, gun1, SahteMakerWorld(), okuyucu=_trendyol([]))
    assert [u["urun_id"] for u in s["urunler"]] == [2, 1, 5]      # toplam değerlendirme + favori/10
    assert s["magazalar"][0]["magaza"] == "Dersan3D" and s["magazalar"][1]["urun"] == 2
    assert depo.ty_son_tarih() == "2026-11-12" and len(depo.ty_gecmis("2026-11-01")) == 3
    md = open(s["yol"], encoding="utf-8").read()
    assert "İlk okuma" in md and "Dersan3D" in md and "stokta yok" in md
    assert "Hat Hanger Rack" in md                                   # isimle MakerWorld eşleşmesi
    assert not trendyol.zamani_geldi(depo, date(2026, 11, 15)) and trendyol.zamani_geldi(depo, date(2026, 11, 19))

    # Bir hafta sonra: top askısı hızlandı (+14 değerlendirme), Dersan3D yerinde saydı.
    SAYFALAR_2 = dict(SAYFALAR)
    SAYFALAR_2["/work3d/top-askisi-3d-baski-p-1"] = _sayfa(
        "WORK3D Top Askısı 3D Baskı", deg=31, fav=361, benzer=["/dersan3d/sapka-askisi-p-2"])
    durum = {y: httpx.Response(200, text=t) for y, t in SAYFALAR_2.items()}
    s = trendyol.calistir(depo, ayar, date(2026, 11, 19), SahteMakerWorld(), okuyucu=_trendyol([], durum))
    ilk = s["urunler"][0]
    assert ilk["urun_id"] == 1 and ilk["artis_degerlendirme"] == 14 and ilk["artis_favori"] == 30
    assert ilk["haftalik"] == 17.0
    assert "bu haftaki değerlendirme artışı" in open(s["yol"], encoding="utf-8").read()
    tg = trendyol.telegram_mesaji(date(2026, 11, 19), s["urunler"], s["magazalar"], "https://panel")
    assert "bu hafta +14 değ." in tg and "Çınar3D Store" in tg and len(tg) <= 4096


def test_tablo_yoksa_atlar(tmp_path, capsys):
    class Bozuk:
        def ty_son_tarih(self):
            raise RuntimeError("relation trendyol_products does not exist")
    ayar = config.Ayarlar("", "", tmp_path / "t.db")
    assert trendyol.calistir(Bozuk(), ayar, date(2026, 11, 12), okuyucu=_trendyol([])) is None
    assert "guncelleme_2026-11-11_trendyol.sql" in capsys.readouterr().out


def test_robots_okunamazsa_hic_sayfa_acilmaz(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAPOR_KLASORU", tmp_path / "raporlar")
    monkeypatch.setattr(config, "TRENDYOL_LENS_ADET", 0)
    okunan = []
    oku = _trendyol(okunan, {"/robots.txt": httpx.Response(503)})
    s = trendyol.calistir(SqliteDepo(tmp_path / "t.db"), config.Ayarlar("", "", tmp_path / "t.db"),
                          date(2026, 11, 12), SahteMakerWorld(), okuyucu=oku)
    assert okunan == ["/robots.txt"] and s["urunler"] == [] and "robots.txt" in s["neden"]
    assert "Okuma yapılamadı" in trendyol.telegram_mesaji(date(2026, 11, 12), [], [], neden=s["neden"])
