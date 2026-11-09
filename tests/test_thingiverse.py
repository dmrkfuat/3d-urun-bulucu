import httpx
import pytest

from urun_bulucu.kaynaklar.thingiverse import ThingiverseHatasi, ThingiverseKaynak

from .ornek_veri import thing

DETAYLAR = {
    1: thing(1, "Flexi Test Dragon", 900, 20000, aciklama="Print in place. Print time: 3h 20m. PLA"),
    2: thing(2, "Test Desk Organizer", 300, 5000, lisans="Creative Commons - Attribution - Non-Commercial"),
    3: {**thing(3, "Gizli", 999, 99999), "is_nsfw": True},
}


def _handler(istekler):
    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        assert request.headers["Authorization"] == "Bearer deneme-token"
        yol = request.url.path
        if yol.startswith("/search/"):
            assert request.url.params["sort"] == "popular"
            assert request.url.params["posted_after"] == "now-30d"
            hits = [{"id": i, "like_count": DETAYLAR[i]["like_count"], "is_nsfw": DETAYLAR[i]["is_nsfw"]}
                    for i in DETAYLAR]
            return httpx.Response(200, json={"total": len(hits), "hits": hits})
        if yol.startswith("/things/"):
            return httpx.Response(200, json=DETAYLAR[int(yol.rsplit("/", 1)[1])])
        return httpx.Response(404)
    return handler


def test_topla_ve_donustur():
    istekler = []
    kaynak = ThingiverseKaynak("deneme-token", httpx.Client(transport=httpx.MockTransport(_handler(istekler))),
                               bekleme_sn=0)
    urunler = kaynak.topla({"Eklemli figür": ["flexi"], "Masa": ["desk organizer"]}, detay_limiti=10,
                           donem="now-30d")

    assert [u["external_id"] for u in urunler] == ["1", "2"]  # NSFW elendi, tekrar yok
    ejder = urunler[0]
    assert ejder["category"] == "Eklemli figür"
    assert ejder["print_time_min"] == 200
    assert ejder["material"] == "PLA"
    assert "hareketli parça" in ejder["features"]
    assert ejder["license_flag"] == "ticari_serbest"
    assert ejder["image_url"].endswith("1_large.jpg")
    assert urunler[1]["license_flag"] == "nc_sadece_icerik"
    # 2 arama + 2 detay isteği (NSFW için detay çekilmez)
    assert len(istekler) == 4


def test_gecersiz_token():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    kaynak = ThingiverseKaynak("kotu", client, bekleme_sn=0)
    with pytest.raises(ThingiverseHatasi, match="geçersiz"):
        kaynak.ara("fidget")


def test_bos_token():
    with pytest.raises(ThingiverseHatasi):
        ThingiverseKaynak("")
