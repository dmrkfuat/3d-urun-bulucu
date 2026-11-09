from datetime import date

import httpx
import pytest

from urun_bulucu import puanlama
from urun_bulucu.kaynaklar.makerworld import MakerWorldHatasi, MakerWorldKaynak, urune_cevir

from .ornek_veri import mw_tasarim, urun

DETAYLAR = {
    11: mw_tasarim(11, "Flexi Test Gecko", 2000, 9000, lisans="BY",
                   profiller=[{"id": 1, "yazici": "A1", "sure_sn": 9000},
                              {"id": 2, "yazici": "P1S", "sure_sn": 3600, "renk": 4, "ams": True,
                               "filament": ["PLA", "PETG"]}]),
    12: mw_tasarim(12, "Test Planter", 500, 3000),
    13: {**mw_tasarim(13, "Gizli", 9999, 99999), "nsfw": True},
    14: {**mw_tasarim(14, "Ucretli", 9999, 99999), "paidSetting": {"isPaid": True}},
}


def _handler(istekler):
    def handler(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        assert "3d-urun-bulucu" in request.headers["User-Agent"]
        yol = request.url.path
        if yol.endswith("/search-service/select/design2"):
            assert request.url.params["designCreateSince"] == "30"
            assert request.url.params["orderBy"] == "downloadCount"
            hits = [{k: DETAYLAR[i][k] for k in ("id", "downloadCount", "nsfw", "paidSetting")}
                    for i in DETAYLAR]
            return httpx.Response(200, json={"total": len(hits), "hits": hits})
        if "/design-service/design/" in yol:
            return httpx.Response(200, json=DETAYLAR[int(yol.rsplit("/", 1)[1])])
        return httpx.Response(404)
    return handler


def test_topla_ve_donustur():
    istekler = []
    kaynak = MakerWorldKaynak(httpx.Client(transport=httpx.MockTransport(_handler(istekler))), bekleme_sn=0)
    urunler = kaynak.topla({"Eklemli figür": ["flexi"], "Ev": ["planter"]}, detay_limiti=10, gun=30)

    assert [u["external_id"] for u in urunler] == ["11", "12"]  # NSFW ve ücretli elendi
    gecko = urunler[0]
    assert gecko["source_id"] == "makerworld"
    assert gecko["url"] == "https://makerworld.com/en/models/11"
    assert gecko["print_time_min"] == 60          # A1 değil P1S profili seçildi
    assert gecko["material"] == "PLA, PETG"
    assert "çok renkli (AMS)" in gecko["features"]
    assert "hareketli parça" in gecko["features"]
    assert gecko["license_flag"] == "ticari_serbest"
    assert gecko["makes"] == 2000 // 3
    # Varsayılan ayar: MakerWorld modellerinin hepsi satılabilir sayılır, asıl lisans metni korunur.
    assert urunler[1]["license_flag"] == "ticari_serbest"
    assert urunler[1]["license"] == "Standard Digital File License"
    # 2 arama + 2 detay
    assert len(istekler) == 4


def test_lisans_ayari_kapaliyken_lisansa_gore(monkeypatch):
    from urun_bulucu import config
    monkeypatch.setattr(config, "MAKERWORLD_HEPSI_SATILABILIR", False)
    assert urune_cevir(mw_tasarim(1, "X", 1, 1), "Ev")["license_flag"] == "nc_sadece_icerik"
    assert urune_cevir(mw_tasarim(2, "X", 1, 1, lisans="BY"), "Ev")["license_flag"] == "ticari_serbest"


def test_ams_metinden_degil_profilden():
    # Başlık "multicolor" dese de profil tek renkse AMS etiketi verilmez (ve tersi).
    tek = urune_cevir(mw_tasarim(1, "Multicolor Vase", 1, 1, profiller=[{"id": 1, "renk": 1}]), "Ev")
    assert "çok renkli (AMS)" not in tek["features"]
    cok = urune_cevir(mw_tasarim(2, "Vase", 1, 1, profiller=[{"id": 1, "renk": 3}]), "Ev")
    assert "çok renkli (AMS)" in cok["features"]


def test_engelleme_hata_verir():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="<html>")))
    with pytest.raises(MakerWorldHatasi, match="403"):
        MakerWorldKaynak(client, bekleme_sn=0).ara("fidget")


def test_bicim_degisirse_hata_verir():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"x": 1})))
    with pytest.raises(MakerWorldHatasi, match="biçimi"):
        MakerWorldKaynak(client, bekleme_sn=0).ara("fidget")


def test_populerlik_kaynak_icinde_olceklenir():
    # Sayıları çok büyük bir kaynak, küçük bir kaynağın en iyisini ezmemeli.
    urunler = [
        urun(1, "Küçük kaynak en iyi", 100, 1000, source_id="baska"),
        urun(2, "MW en iyi", 50000, 500000),
        urun(3, "MW orta", 500, 5000),
    ]
    puanli = {u["id"]: u for u in puanlama.puanla(urunler, {}, date(2026, 11, 9))}
    assert puanli[1]["score_detail"]["populerlik"] == 1.0
    assert puanli[2]["score_detail"]["populerlik"] == 1.0
    assert puanli[3]["score_detail"]["populerlik"] < 1.0


def test_gif_kapak_yerine_gercek_fotograf():
    from urun_bulucu.kaynaklar.makerworld import kapak_sec
    d = {"coverUrl": "https://x/a.gif", "designExtension": {"real_pictures": [
        {"url": "https://x/b.GIF"}, {"url": "https://x/c.jpeg"}]}, "instances": [{"cover": "https://x/d.png"}]}
    assert kapak_sec(d) == "https://x/c.jpeg"
    assert kapak_sec({"coverUrl": "https://x/a.png"}) == "https://x/a.png"
    assert kapak_sec({"coverUrl": "https://x/a.gif", "instances": [{"cover": "https://x/d.png"}]}) == "https://x/d.png"
    assert kapak_sec({"coverUrl": "https://x/a.gif"}) == "https://x/a.gif"   # başka görsel yoksa
