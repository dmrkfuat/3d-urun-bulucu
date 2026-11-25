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


def test_tabla_adedi_profil_adindan():
    from urun_bulucu.kaynaklar.makerworld import tabla_adedi
    assert tabla_adedi("PIES ESTABLES X 60 0.2mm layer, 3 walls, 10% infill") == 60
    assert tabla_adedi("GORRO ROJO X78 0.2mm layer") == 78
    assert tabla_adedi("MONOCROMO X01 0.2mm layer") == 1
    assert tabla_adedi("Full plate 4x keychains") == 4
    assert tabla_adedi("10 pcs per plate") == 10 and tabla_adedi("Set of 6 coasters") == 6
    # Yazıcı adları, ölçüler ve katman kalınlığı adet değildir
    assert tabla_adedi("X2D specific - PETG / PLA - 0.2mm layer") == 1
    assert tabla_adedi("X1C 0.16mm, 256 x 256 plate") == 1
    assert tabla_adedi("0.2mm layer, 2 walls, 15% infill") == 1 and tabla_adedi(None) == 1


def test_cok_adetli_tabla_parca_basina_hesaplanir():
    # Mini Grinch (2026-11-25): seçilen profil 60 adetlik tablaydı (645 dk, 171 g) ve tek ürün sayılıyordu
    t = mw_tasarim(1, "MYLITOS MINI GRINCH", 1, 1, profiller=[
        {"id": 1, "baslik": "PIES ESTABLES X 60 0.2mm layer", "sure_sn": 38688, "gram": 171}])
    t["instances"][0]["instanceFilaments"] = [{"type": "PLA", "color": "#61c680", "usedG": "99"}]
    u = urune_cevir(t, "Hediyelik")
    assert (u["print_time_min"], u["weight_g"], u["tabla_adedi"]) == (11, 3, 60)
    assert (u["tabla_suresi_dk"], u["tabla_gram"]) == (645, 171)
    assert u["filaments"] == [{"type": "PLA", "color": "#61C680", "grams": 1.6}]
    assert u["cost_tl"] < 5 and u["price_tl"] == 50                     # tabla için 183 → 550 TL'ydi
    from urun_bulucu import maliyet
    assert "bir tablada 60 adet basar (~10 sa 45 dk, 171 g)" in maliyet.yazi(u)
    # Tek parçalık profilde değişiklik yok
    tek = urune_cevir(mw_tasarim(2, "Vase", 1, 1, profiller=[{"id": 1, "sure_sn": 3600, "gram": 40}]), "Ev")
    assert (tek["print_time_min"], tek["weight_g"], tek["tabla_adedi"]) == (60, 40, 1)
    assert "tablada" not in maliyet.yazi(tek)


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
