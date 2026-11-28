"""SerpApi bütçesi + Serper yedeği, Trendyol fiyat düşüşü, siparişler, Instagram performansı,
hikâye/carousel paylaşımı ve Etsy talebi."""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from urun_bulucu import config, etsy, instagram, istatistik, kota, maliyet, pazar, puanlama, siparis, trendyol

from .ornek_veri import urun
from .test_instagram import SIMDI, VideoDepo, _gonderi


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    monkeypatch.setattr(config, "INSTAGRAM_VIDEO_DUZENLE", False)
    monkeypatch.setattr(maliyet, "DUZELTME", {"sure": 1.0, "gram": 1.0})
    monkeypatch.setattr(kota, "YENILEME", None)
    pazar.yedek_ayarla("")
    yield
    pazar.yedek_ayarla("")


# ------------------------------------------------------------------ SerpApi bütçesi
def test_kota_kalan_hak_ayin_kalan_gunlerine_bolunur(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_YENILEME_GUNU", 1)
    assert kota.sonraki_yenileme(date(2026, 11, 26)) == date(2026, 12, 1)
    assert kota.sonraki_yenileme(date(2026, 12, 1)) == date(2027, 1, 1)
    assert kota.kalan_gun(date(2026, 11, 26)) == 5
    assert kota.gunluk_arama(9, date(2026, 11, 26)) == 1          # 9 hak / 5 gün
    assert kota.gunluk_urun(9, date(2026, 11, 26)) == 0           # ürün başına 2 arama gerekir
    assert kota.gunluk_urun(250, date(2026, 11, 1)) == config.PAZAR_GUNLUK_ADET
    assert kota.gunluk_urun(None, date(2026, 11, 1)) == 0
    monkeypatch.setattr(config, "SERPAPI_YENILEME_GUNU", 31)      # 30 çeken ayda ayın son günü
    assert kota.sonraki_yenileme(date(2026, 11, 26)) == date(2026, 11, 30)


def test_yenileme_tarihi_serpapi_hesabindan_okunur():
    def handler(r):
        return httpx.Response(200, json={"total_searches_left": 9, "plan_renewal_date": "2026-12-09"})

    assert pazar.kalan_hak("KEY", httpx.Client(transport=httpx.MockTransport(handler))) == 9
    assert kota.sonraki_yenileme(date(2026, 11, 26)) == date(2026, 12, 9)
    assert kota.kalan_gun(date(2026, 11, 26)) == 13 and kota.gunluk_arama(9, date(2026, 11, 26)) == 0
    assert kota.sonraki_yenileme(date(2026, 12, 10)) == date(2027, 1, 1)   # tarih geçtiyse ayardaki gün
    kota.yenileme_ayarla("bozuk")
    assert kota.YENILEME is None


def test_kesif_ancak_sonrasina_hak_kalirsa(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_YENILEME_GUNU", 1)
    # 1 Kasım: 30 gün kaldı → keşiften sonra 29 × 2 = 58 hak kalmalı
    assert kota.buyuk_is_izinli(250, date(2026, 11, 1))
    assert not kota.buyuk_is_izinli(80, date(2026, 11, 1))
    assert kota.buyuk_is_izinli(40, date(2026, 11, 28))
    assert not kota.buyuk_is_izinli(None, date(2026, 11, 28))


def test_serpapi_hakki_bitince_alisveris_serperdan(monkeypatch):
    istekler = []

    def handler(r: httpx.Request) -> httpx.Response:
        istekler.append(r)
        if r.url.host == "serpapi.com":
            return httpx.Response(429, json={"error": "Your account has run out of searches."})
        assert r.url.host == "google.serper.dev" and r.headers["X-API-KEY"] == "YEDEK"
        assert json.loads(r.content) == {"q": "grinch 3d baskı", "gl": "tr", "hl": "tr"}
        return httpx.Response(200, json={"shopping": [
            {"title": "3D Baskı Grinch Figür", "source": "Trendyol", "link": "https://www.trendyol.com/x/grinch-p-1",
             "price": "149,90 TL", "imageUrl": "https://img/x.jpg"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(pazar.PazarHatasi):                       # yedek yoksa hata
        pazar.alisveris_ara("KEY", "grinch 3d baskı", client)
    pazar.yedek_ayarla("YEDEK")
    sonuc = pazar.alisveris_sonuclari(pazar.alisveris_ara("KEY", "grinch 3d baskı", client))
    assert sonuc and sonuc[0]["site"] == "Trendyol" and sonuc[0]["price"] == 149.9
    # Lens'in yedeği yoktur
    with pytest.raises(pazar.PazarHatasi):
        pazar.lens_ara("KEY", "https://img/x.jpg", None, client)


class _PazarDepo:
    def __init__(self):
        self.kaydedilen = []

    def pazar_kayitlari(self, ids):
        return {}

    def pazar_kaydet(self, satirlar):
        self.kaydedilen += satirlar


def test_pazar_butceye_uyar_ve_hata_olunca_aranani_kaydeder(monkeypatch):
    secimler = [{"product_id": i, "rank": i, "urun": urun(i, f"Model {i}", 1, 1, image_url="https://img/x.jpg")}
                for i in (1, 2, 3)]
    cagri = []

    def sahte_ara(api_key, u, client=None):
        cagri.append(u["id"])
        if len(cagri) == 2:
            raise pazar.PazarHatasi("SerpApi: run out of searches")
        return [], "sorgu"

    monkeypatch.setattr(pazar, "urun_ara", sahte_ara)
    depo = _PazarDepo()
    assert pazar.calistir(depo, secimler, "KEY", adet=0) == {} and cagri == []
    ozet = pazar.calistir(depo, secimler, "KEY", adet=3)
    assert list(ozet) == [1] and cagri == [1, 2] and len(depo.kaydedilen) == 1


# ------------------------------------------------------------------ Trendyol fiyat düşüşü
def test_trendyol_fiyat_dusen_rakipler():
    gecmis = [{"tarih": "2026-11-12", "urun_id": 1, "degerlendirme": 10, "favori": 100, "fiyat": 300},
              {"tarih": "2026-11-12", "urun_id": 2, "degerlendirme": 5, "favori": 10, "fiyat": 100}]
    urunler = [{"urun_id": 1, "degerlendirme": 12, "favori": 110, "fiyat": 240, "ad": "Kalemlik", "url": "https://t/1",
                "magaza": "MYE"},
               {"urun_id": 2, "degerlendirme": 5, "favori": 10, "fiyat": 95, "ad": "Küp", "url": "https://t/2"}]
    trendyol.hiz_ekle(urunler, gecmis, date(2026, 11, 19))
    dusen = trendyol.fiyat_dususleri(urunler)
    assert [u["urun_id"] for u in dusen] == [1] and dusen[0]["dusus"] == 0.2
    md = trendyol.markdown(date(2026, 11, 19), urunler, [], 2, None)
    assert "Fiyatı düşenler" in md and "300 → 240 TL (−%20)" in md
    tg = trendyol.telegram_mesaji(date(2026, 11, 19), urunler, [])
    assert "Fiyatı düşen rakipler" in tg


# ------------------------------------------------------------------ siparişler
def _siparisler():
    p = {"category": "Hediyelik", "print_time_min": 60, "weight_g": 20}
    return [
        {"product_id": 1, "adet": 2, "durum": "teslim", "gercek_sure_dk": 150, "gercek_gram": 44, "products": p},
        {"product_id": 1, "adet": 1, "durum": "yeni", "gercek_sure_dk": 72, "gercek_gram": 21, "products": p},
        {"product_id": 2, "adet": 1, "durum": "teslim", "gercek_sure_dk": 66, "gercek_gram": 22, "products": p},
        {"product_id": 3, "adet": 5, "durum": "iptal", "gercek_sure_dk": 10, "products": p},
    ]


def test_satis_ozeti_ve_bonus():
    isaretler = [{"product_id": 1, "sold_count": 2, "products": {"category": "Hediyelik"}},     # siparişten az
                 {"product_id": 9, "sold_count": 4, "products": {"category": "Eklemli figür"}}]
    ozet = siparis.satis_ozeti(_siparisler(), isaretler)
    assert ozet["urun"] == {1: 3, 2: 1, 9: 4}          # iptal sayılmaz; çift sayım yok
    assert ozet["kategori"] == {"Hediyelik": 4, "Eklemli figür": 4}
    assert siparis.satis_bonusu({"id": 1, "category": "Hediyelik"}, ozet)[0] == config.SATILAN_URUN_BONUS
    assert siparis.satis_bonusu({"id": 5, "category": "Hediyelik"}, ozet) == (2, "Bu kategoride 4 satışın var")
    assert siparis.satis_bonusu({"id": 5, "category": "Saksı"}, ozet) == (0, None)


def test_kalibrasyon_gercek_degerlerden_maliyeti_duzeltir():
    k = siparis.kalibrasyon(_siparisler())
    assert k == {"sure": 1.2, "gram": 1.1, "ornek": 3}
    assert siparis.kalibrasyon(_siparisler()[:2]) is None           # 3 örnekten az
    once = maliyet.hesapla(20, 60)
    maliyet.DUZELTME.update(sure=k["sure"], gram=k["gram"])
    sonra = maliyet.hesapla(20, 60)
    assert sonra["maliyet_tl"] > once["maliyet_tl"]
    assert "×1.20" in siparis.yazi(k)


# ------------------------------------------------------------------ Instagram performansı
def _ig(id_, kat, reach, saved=0, shares=0, likes=0, saat=20, gun=1, tur="REELS"):
    t = (SIMDI - timedelta(days=gun)).replace(hour=saat - 3)   # Türkiye saati = UTC+3
    return {"id": id_, "media_id": f"M{id_}", "media_type": tur, "published_at": t.isoformat(),
            "permalink": f"https://instagram.com/reel/{id_}", "products": {"name": f"Ürün {id_}", "category": kat},
            "insights": {"reach": reach, "saved": saved, "shares": shares, "likes": likes, "comments": 0}}


def test_instagram_kategori_bonusu_ve_haftalik_ozet():
    g = [_ig(1, "Fidget", 100, saved=10, shares=5, likes=20), _ig(2, "Fidget", 100, saved=8, shares=6, likes=10),
         _ig(3, "Saksı", 100, likes=5, saat=11), _ig(4, "Saksı", 100, likes=3, saat=11),
         _ig(5, "Hediyelik", 100, saved=2, likes=10), _ig(6, "Hediyelik", 100, saved=1, likes=12, tur="STORIES")]
    bonus = istatistik.kategori_bonuslari(g)
    assert bonus["Fidget"][0] == 4 and bonus["Saksı"][0] == -2 and "Hediyelik" not in bonus   # hikâye sayılmaz
    assert istatistik.kategori_bonuslari(g[:3]) == {}                                          # veri az
    metin = istatistik.haftalik_ozet(g, SIMDI.date())
    assert "Instagram haftalık özet" in metin and "Ürün 1" in metin and "🟢 Fidget: +4" in metin
    assert istatistik.en_iyi_saat(g)[0] == 18
    assert istatistik.haftalik_ozet([], SIMDI.date()) is None


class _IstatistikDepo:
    def __init__(self, gonderiler):
        self.g = gonderiler
        self.yazilan = {}

    def paylasilanlar(self, en_erken):
        return self.g

    def guncelle(self, gid, alanlar):
        self.yazilan[gid] = alanlar


def test_istatistik_guncelleme_desteklenmeyen_metrikte_azaltir():
    istenen = []

    def handler(r: httpx.Request) -> httpx.Response:
        m = r.url.params["metric"]
        istenen.append(m)
        if "views" in m:
            return httpx.Response(400, json={"error": {"message": "metric not supported"}})
        return httpx.Response(200, json={"data": [{"name": "reach", "values": [{"value": 120}]},
                                                  {"name": "saved", "total_value": {"value": 7}}]})

    ig = instagram.InstagramIstemci("TOKEN", httpx.Client(transport=httpx.MockTransport(handler)))
    depo = _IstatistikDepo([{"id": 1, "media_id": "M1"}, {"id": 2, "media_id": "M2", "insights_at": SIMDI.isoformat()},
                            {"id": 3, "media_id": None}])
    assert istatistik.istatistikleri_guncelle(depo, ig, SIMDI) == 1      # 2: bugün güncellendi, 3: medya yok
    assert depo.yazilan[1]["insights"] == {"reach": 120, "saved": 7} and len(istenen) == 2


def test_puanlama_yeni_sinyaller():
    a = urun(1, "Dragon", 10, 10, category="Fidget ve oyuncak", etsy_favori=25000)
    b = urun(2, "Dragon", 10, 10, category="Fidget ve oyuncak")
    c = urun(3, "Dragon", 10, 10, category="Ev dekorasyonu ve saksı")
    sirali = puanlama.puanla([a, b, c], {}, date(2026, 11, 26),
                             ig_bonuslari={"Ev dekorasyonu ve saksı": (4, "IG iyi")},
                             satis_ozeti={"urun": {2: 3}, "kategori": {}})
    p = {u["id"]: u for u in sirali}
    taban = p[1]["score"] - 5
    assert p[1]["score_detail"]["etsy_bonusu"] == 5 and p[2]["score"] == pytest.approx(taban + 3)
    assert p[3]["score"] == pytest.approx(taban + 4) and p[3]["score_detail"]["instagram"] == "IG iyi"


# ------------------------------------------------------------------ hikâye ve carousel
def _api_tur():
    cagrilar = []

    def handler(r: httpx.Request) -> httpx.Response:
        yol, govde = r.url.path, r.content.decode() if r.method == "POST" else ""
        cagrilar.append((yol, govde))
        if yol.endswith("/me"):
            return httpx.Response(200, json={"user_id": "1784"})
        if yol.endswith("/1784/media"):
            n = sum(1 for y, _ in cagrilar if y.endswith("/1784/media"))
            return httpx.Response(200, json={"id": f"KAP{n}"})
        if "/KAP" in yol:
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if yol.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "MEDYA9"})
        return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/x/"})

    return httpx.Client(transport=httpx.MockTransport(handler)), cagrilar


class _TurDepo(VideoDepo):
    def yol_kullaniliyor(self, yol, haric_id):
        return any(g["video_path"] == yol and g["id"] != haric_id and g["status"] in ("bekliyor", "isleniyor")
                   for g in self.gonderiler.values())


def test_reels_ve_hikaye_ayni_video_son_paylasilinca_silinir():
    depo = _TurDepo([_gonderi(), _gonderi(id=2, caption="", media_type="STORIES")])
    client, cagrilar = _api_tur()
    gonderilen = []
    bildirimler = instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI, bekle=lambda s: None,
                                 video_gonder=lambda d, m: gonderilen.append(m))
    olustur = [g for y, g in cagrilar if y.endswith("/1784/media")]
    assert "media_type=REELS" in olustur[0] and "media_type=STORIES" in olustur[1]
    assert all(depo.gonderiler[i]["status"] == "paylasildi" for i in (1, 2))
    assert depo.silinen == ["7/1.mp4", "7/1_hazir.mp4"]                # yalnızca bir kez, sonuncusunda
    assert len(gonderilen) == 1                                          # Telegram'a yalnız Reels videosu
    assert any("hikâye olarak" in b for b in bildirimler)


def test_carousel_fotograflarla_paylasilir_ve_silinir():
    depo = _TurDepo([_gonderi(video_path=None, media_type="CAROUSEL", image_paths=["7/a.jpg", "7/b.jpg"]),
                     _gonderi(id=2, video_path=None, media_type="CAROUSEL", image_paths=["7/c.jpg"])])
    client, cagrilar = _api_tur()
    instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI, bekle=lambda s: None)
    olustur = [g for y, g in cagrilar if y.endswith("/1784/media")]
    assert sum("is_carousel_item=true" in g for g in olustur) == 2
    assert "media_type=CAROUSEL" in olustur[2] and "children=KAP1%2CKAP2" in olustur[2]
    assert depo.gonderiler[1]["status"] == "paylasildi" and depo.silinen == ["7/a.jpg", "7/b.jpg"]
    assert depo.gonderiler[2]["status"] == "hata" and "2-10" in depo.gonderiler[2]["error"]
    assert not instagram.duzenlenecek_mi({"media_type": "CAROUSEL", "video_path": None})


# ------------------------------------------------------------------ Etsy
def test_etsy_sorgu_bonus_ve_arama():
    assert etsy.sorgu("MYLITOS Articulated Dragon - print in place V2") == "articulated dragon"
    assert etsy.bonus(25000) == 5 and etsy.bonus(1200) == 1 and etsy.bonus(None) == 0
    istekler = []

    def handler(r: httpx.Request) -> httpx.Response:
        istekler.append(r)
        assert r.headers["x-api-key"] == "K:S" and r.url.path.endswith("/listings/active")
        return httpx.Response(200, json={"count": 2, "results": [{"title": "a", "num_favorers": 900, "url": "u"},
                                                                 {"title": "b", "num_favorers": 300}]})

    urunler = [urun(1, "Articulated Dragon", 1, 1), urun(2, "articulated dragon v2", 1, 1), urun(3, "V2", 1, 1)]
    adet = etsy.isle(urunler, "K:S", httpx.Client(transport=httpx.MockTransport(handler)), bekle=lambda s: None)
    assert adet == 1 and len(istekler) == 1                              # aynı sorgu önbellekten
    assert urunler[0]["etsy_favori"] == urunler[1]["etsy_favori"] == 1200 and "etsy_favori" not in urunler[2]
    assert etsy.isle(urunler, "") == 0
