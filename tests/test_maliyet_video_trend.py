from datetime import date

import httpx

from urun_bulucu import config, maliyet, ozet, puanlama, video
from urun_bulucu.db import SqliteDepo
from urun_bulucu.kaynaklar.makerworld import TREND_KATEGORI, MakerWorldKaynak, kategori_bul, urune_cevir

from .ornek_veri import mw_tasarim, urun

BUGUN = date(2026, 11, 9)


# ---------------------------------------------------------------- maliyet
def test_maliyet_hesabi(monkeypatch):
    monkeypatch.setattr(config, "FILAMENT_TL_KG", 800)
    monkeypatch.setattr(config, "SAAT_MALIYETI_TL", 3)
    monkeypatch.setattr(config, "FIRE_ORANI", 0.10)
    monkeypatch.setattr(config, "FIYAT_CARPANI", 3)
    monkeypatch.setattr(config, "EN_DUSUK_FIYAT_TL", 50)
    # 100 g, 2 saat: filament 100*1.1*0.8 = 88 TL, makine 6 TL → 94 TL; fiyat 282 → 285
    s = maliyet.hesapla(100, 120)
    assert s == {"maliyet_tl": 94.0, "fiyat_tl": 285, "saatlik_kazanc_tl": 95.5}
    # Küçük parça: fiyat en düşük sınıra çekilir
    assert maliyet.hesapla(5, 20)["fiyat_tl"] == 50
    assert maliyet.hesapla(None, 60) is None
    assert maliyet.hesapla(20, None) is None


def test_urunde_gram_renk_ve_maliyet():
    t = mw_tasarim(1, "Vase", 1, 1, profiller=[{"id": 1, "sure_sn": 7200, "renk": 3}])
    t["instances"][0]["weight"] = 100
    u = urune_cevir(t, "Ev")
    assert (u["weight_g"], u["color_count"], u["print_time_min"]) == (100, 3, 120)
    assert u["cost_tl"] is not None and u["price_tl"] >= u["cost_tl"]
    assert "maliyet" in maliyet.yazi(u)
    # Profil yoksa maliyet hesaplanmaz
    bos = urune_cevir(mw_tasarim(2, "X", 1, 1, profiller=[]), "Ev")
    assert bos["cost_tl"] is None and "hesaplanamadı" in maliyet.yazi(bos)


# ---------------------------------------------------------------- trend
def test_trend_kategori_bulma():
    kategoriler = {"Fidget ve oyuncak": ["fidget"], "Ev": ["planter", "vase"]}
    assert kategori_bul({"title": "Spiral Vase", "tags": []}, kategoriler) == "Ev"
    assert kategori_bul({"title": "X", "tags": ["Fidget Toy"]}, kategoriler) == "Fidget ve oyuncak"
    assert kategori_bul({"title": "Christmas Train", "tags": []}, kategoriler) == TREND_KATEGORI


def test_topla_trend_ve_arama_birlikte():
    trend = {21: mw_tasarim(21, "Christmas Train", 10, 500), 22: {**mw_tasarim(22, "Gizli", 1, 1), "nsfw": True},
             23: mw_tasarim(23, "Flexi Fidget Snake", 10, 400)}
    arama = {23: trend[23], 24: mw_tasarim(24, "Fidget Cube", 5, 300)}
    detaylar = {**trend, **arama}
    istekler = []

    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request.url.path)
        yol = request.url.path
        if yol.endswith("/select/design/nav"):
            assert request.url.params["navKey"] == "Trending"
            return httpx.Response(200, json={"hits": [{k: v for k, v in trend[i].items() if k != "instances"}
                                                      for i in (21, 22, 23)]})
        if yol.endswith("/select/design2"):
            return httpx.Response(200, json={"hits": [{"id": i, "downloadCount": arama[i]["downloadCount"]}
                                                      for i in arama]})
        return httpx.Response(200, json=detaylar[int(yol.rsplit("/", 1)[1])])

    kaynak = MakerWorldKaynak(httpx.Client(transport=httpx.MockTransport(handler)), bekleme_sn=0)
    urunler = kaynak.topla({"Fidget ve oyuncak": ["fidget"]}, detay_limiti=10, gun=30, trend_adet=5)

    sonuc = {u["external_id"]: u for u in urunler}
    assert set(sonuc) == {"21", "23", "24"}           # NSFW elendi, 23 iki kez çekilmedi
    assert sonuc["21"]["trend_rank"] == 1 and sonuc["21"]["category"] == TREND_KATEGORI
    assert sonuc["23"]["trend_rank"] == 3 and sonuc["23"]["category"] == "Fidget ve oyuncak"
    assert sonuc["24"]["trend_rank"] is None
    assert sum("/design-service/design/" in y for y in istekler) == 3


def test_trend_bonusu_ve_nedeni():
    a = urun(1, "A", 100, 1000)
    b = urun(2, "B", 100, 1000, trend_rank=4)
    puanli = {u["id"]: u for u in puanlama.puanla([a, b], {}, BUGUN)}
    assert puanli[2]["score"] - puanli[1]["score"] == config.TREND_BONUS
    assert "trend listesinde #4" in ozet.neden(puanli[2])


# ---------------------------------------------------------------- video
def test_video_fikri_modele_ozel():
    u = urun(1, "Flexi Gecko", 10, 100, features=["hareketli parça", "çok renkli (AMS)"],
             tags=["print in place", "Gecko Toy"], print_time_min=45, color_count=3, weight_g=30,
             creator="Ayse", category="Eklemli figür")
    f = video.fikir(u)
    assert f["kanca"] == "Tek parça basıldı, hiç montaj yok 🤯"
    assert f["alternatif_kanca"] == "Sadece 45 dakikada bastım ⏱️"
    assert f["sure"] == "7-12 sn (loop)"
    assert "Renk geçişlerini" in f["plan"][1]
    assert "loop" in f["plan"][2]
    assert "30 g filament" in f["aciklama"] and "Tasarım: Ayse" in f["aciklama"]
    assert f["etiketler"][:4] == video.TEMEL_ETIKETLER
    assert "#printinplace" in f["etiketler"] and "#geckotoy" in f["etiketler"]
    assert len(f["etiketler"]) <= 8

    metin = video.metin(f)
    assert metin.startswith("Kanca:") and "\n1) " in metin and "Etiketler: #3dbaskı" in metin


def test_video_fikri_uzun_baski_ve_varsayilan():
    u = urun(1, "Big Lamp", 1, 1, print_time_min=9 * 60, category="Bilinmeyen")
    f = video.fikir(u)
    assert f["kanca"] == "3D yazıcıda böyle basılıyor 👀"
    assert "4-5 sn" in f["plan"][1]
    assert f["plan"][2] == video.VARSAYILAN_KAPANIS


def test_raporda_video_ve_maliyet():
    u = urun(1, "Ring", 10, 100, print_time_min=60, weight_g=20, cost_tl=20.6, price_tl=65,
             hourly_profit_tl=44.4, features=["satisfying"])
    secimler = ozet.sec(puanlama.puanla([u], {}, BUGUN))
    md = ozet.markdown(BUGUN, secimler, 1, "SQLite")
    assert "~21 → 65 TL" in md
    assert "- **Maliyet:** ~21 TL maliyet (20 g filament)" in md
    assert "  - Kanca: " in md and "  - Etiketler: " in md


# ---------------------------------------------------------------- db
def test_sqlite_yeni_sutunlar_ve_eski_dosya(tmp_path):
    import sqlite3
    yol = tmp_path / "eski.db"
    # Yeni sütunları olmayan eski bir veritabanı
    con = sqlite3.connect(yol)
    con.executescript("create table products (id integer primary key autoincrement, source_id text, "
                      "external_id text, name text, url text, first_seen text, last_seen text, "
                      "unique (source_id, external_id));")
    con.close()
    depo = SqliteDepo(yol)
    sutunlar = {r["name"] for r in depo.con.execute("pragma table_info(products)")}
    assert {"weight_g", "cost_tl", "price_tl", "trend_rank"} <= sutunlar


# ---------------------------------------------------------------- piyasaya göre fiyat ve satış puanı
def _pazar_kaydi(fiyatlar, satis=None):
    return {"found_count": satis if satis is not None else len(fiyatlar),
            "results": [{"site": "Trendyol", "price": f, "kaynak": "metin"} for f in fiyatlar]}


def test_piyasaya_gore_fiyat():
    u = urun(1, "Ring", 10, 100, print_time_min=60, weight_g=20, cost_tl=20.6, price_tl=65, hourly_profit_tl=44.4)
    guncel = maliyet.piyasaya_uygula([u], {1: _pazar_kaydi([300, 380, 400, 450])})
    assert guncel == [u]
    assert u["price_tl"] == 355 and u["maliyet_fiyati"] == 65          # ortanca 390 × 0,9 = 351 → 5'e yukarı 355
    assert u["piyasa"] == {"medyan": 390, "fiyatli": 4, "satis_sonucu": 4}
    assert u["hourly_profit_tl"] == round(355 - 20.6, 1)
    assert "ortancası 390 TL'ye göre; maliyete göre 65 TL olurdu" in maliyet.yazi(u)
    # İki kez uygulanınca maliyet fiyatı korunur
    maliyet.piyasaya_uygula([u], {1: _pazar_kaydi([300, 380, 400, 450])})
    assert u["maliyet_fiyati"] == 65


def test_piyasa_fiyati_maliyetin_altina_inmez_ve_az_veride_uygulanmaz():
    u = urun(1, "Vazo", 10, 100, print_time_min=600, weight_g=400, cost_tl=380.0, price_tl=1140, hourly_profit_tl=76)
    maliyet.piyasaya_uygula([u], {1: _pazar_kaydi([200, 250, 300])})
    assert u["price_tl"] == 570                                          # 380 × 1,5
    v = urun(2, "X", 10, 100, print_time_min=60, weight_g=20, cost_tl=20.6, price_tl=65, hourly_profit_tl=44.4)
    assert maliyet.piyasaya_uygula([v], {2: _pazar_kaydi([300, 400])}) == [] and v["price_tl"] == 65


def test_satis_puani_ve_piyasa_bonusu():
    hizli = urun(1, "A", 10, 100, cost_tl=20, price_tl=200, hourly_profit_tl=120)
    agir = urun(2, "B", 10, 100, cost_tl=380, price_tl=1150, hourly_profit_tl=80)
    assert puanlama.satis_puani(hizli) == 1.0
    assert puanlama.satis_puani(agir) < 0.75                            # pahalı: zor satar
    assert puanlama.satis_puani(urun(3, "C", 10, 100)) == 0.5           # maliyet bilinmiyor
    assert puanlama.piyasa_bonusu(hizli) == (0, None)
    hizli["piyasa"] = {"medyan": 380, "fiyatli": 5, "satis_sonucu": 13}
    bonus, metin = puanlama.piyasa_bonusu(hizli)
    assert bonus == 3 and "ortanca 380 TL (maliyetin 19 katı); pazar kalabalık" in metin
    agir["piyasa"] = {"medyan": 450, "fiyatli": 4, "satis_sonucu": 4}
    assert puanlama.piyasa_bonusu(agir)[0] == -3                        # piyasa maliyeti karşılamıyor


def test_piyasa_bonusu_puana_ve_nedene_yansir():
    a = urun(1, "A", 100, 1000, print_time_min=60, weight_g=20, cost_tl=20, price_tl=60, hourly_profit_tl=40)
    b = urun(2, "B", 100, 1000, print_time_min=60, weight_g=20, cost_tl=20, price_tl=60, hourly_profit_tl=40,
             piyasa={"medyan": 300, "fiyatli": 5, "satis_sonucu": 5})
    puanli = {u["id"]: u for u in puanlama.puanla([a, b], {}, BUGUN)}
    assert puanli[2]["score"] - puanli[1]["score"] == 5
    assert puanli[2]["score_detail"]["fiyat_kaynagi"] == "piyasa"
    assert "ortanca 300 TL" in ozet.neden(puanli[2])
