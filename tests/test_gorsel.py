"""Görsel doğrulama testleri: Claude istemcisi ve görsel indirme sahtedir (ağa ve API'ye istek atılmaz)."""
import json
from types import SimpleNamespace

import httpx
import pytest

from urun_bulucu import config, gorsel, pazar
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPEG = b"\xff\xd8\xff" + b"0" * 100


def _http():
    def handler(request: httpx.Request) -> httpx.Response:
        yol = request.url.path
        if yol.endswith(".png"):
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if yol.endswith(".jpg"):
            return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg; charset=binary"})
        if yol.endswith(".html"):
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


class SahteClaude:
    """client.beta.messages.create(...) taklidi: istekleri kaydeder, verilen yanıtı döndürür."""

    def __init__(self, sonuclar=None, stop_reason="end_turn"):
        self.istekler = []
        self.sonuclar, self.stop_reason = sonuclar or [], stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.istekler.append(kw)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=json.dumps({"sonuclar": self.sonuclar}))],
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=500))


def _dogrulayici(claude, sinir=10):
    return gorsel.Dogrulayici("anahtar", sinir=sinir, istemci=claude, http=_http())


def _gorseller(istek):
    return [b for b in istek["messages"][0]["content"] if b["type"] == "image"]


def test_karsilastir_istek_ve_eslestirme():
    claude = SahteClaude([{"no": 1, "karar": "ayni", "neden": "aynı örgü desenli Noel Baba"},
                          {"no": 2, "karar": "farkli", "neden": "başka tasarım"}])
    d = _dogrulayici(claude)
    sonuc = d.karsilastir("Knitted Santa", "https://cdn.example/ref.png",
                          [("Örgü Dokulu Figür", "https://t.example/a.jpg"),
                           ("İnmeyen", "https://t.example/yok.jpg.404"),       # 404: atlanır
                           ("Görsel değil", "https://t.example/b.html"),        # text/html: atlanır
                           ("Mini Noel Baba", "https://t.example/c.png")])
    # İstekte 1 ve 2 numaralı adaylar 0. ve 3. sıradaki ilanlardır
    assert sonuc == {0: ("ayni", "aynı örgü desenli Noel Baba"), 3: ("farkli", "başka tasarım")}
    [istek] = claude.istekler
    assert istek["model"] == config.GORSEL_MODEL == "claude-opus-5-5"
    assert (istek["fallbacks"], istek["betas"]) == ("default", ["server-side-fallback-2026-07-01"])
    assert istek["output_config"]["format"]["schema"] == gorsel.SONUC_SEMASI
    assert "thinking" not in istek and "temperature" not in istek
    gorseller = _gorseller(istek)
    assert len(gorseller) == 3 and gorseller[0]["source"]["media_type"] == "image/png"
    assert gorseller[1]["source"]["media_type"] == "image/jpeg"
    metin = " ".join(b["text"] for b in istek["messages"][0]["content"] if b["type"] == "text")
    assert "Aday 1 — ilan başlığı: Örgü Dokulu Figür" in metin and "Aday 2 — ilan başlığı: Mini Noel Baba" in metin
    assert (d.kontrol_edilen, d.girdi_token, d.cikti_token) == (1, 3000, 500)
    assert d.maliyet_usd() == pytest.approx(0.022)


def test_karsilastir_hatalar():
    with pytest.raises(gorsel.GorselHatasi, match="MakerWorld görseli"):
        _dogrulayici(SahteClaude()).karsilastir("x", "https://cdn.example/yok", [("a", "https://t.example/a.jpg")])
    with pytest.raises(gorsel.GorselHatasi, match="reddetti"):
        _dogrulayici(SahteClaude(stop_reason="refusal")).karsilastir(
            "x", "https://cdn.example/ref.png", [("a", "https://t.example/a.jpg")])
    # Hiçbir aday görseli inmezse istek atılmaz
    claude = SahteClaude()
    assert _dogrulayici(claude).karsilastir("x", "https://cdn.example/ref.png", [("a", "http://t.example/a.jpg")]) == {}
    assert claude.istekler == []


def test_hesap_hatasinda_dogrulama_kapanir():
    import anthropic

    class KrediYok(SahteClaude):
        def _create(self, **kw):
            self.istekler.append(kw)
            raise anthropic.BadRequestError(
                "Your credit balance is too low to access the Anthropic API.",
                response=httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
                body=None)

    claude = KrediYok()
    d = _dogrulayici(claude)
    with pytest.raises(gorsel.GorselHatasi, match="kapatıldı"):
        d.karsilastir("x", "https://cdn.example/ref.png", [("a", "https://t.example/a.jpg")])
    assert not d.hakki_var                                                  # sonraki ürünler denenmez
    u = {"name": "Grinch", "image_url": "https://cdn.example/ref.png"}
    s = [_ilan("Grinch 3D Baskı", thumbnail="https://t.example/1.jpg")]
    assert pazar.gorselle_kontrol(s, u, d) == (s, False) and len(claude.istekler) == 1


def test_makerworld_gorseli_kucultulur():
    url = "https://makerworld.bblmw.com/makerworld/model/US1/design/a.png"
    assert gorsel.kucuk_adres(url) == url + "?x-oss-process=image/resize,w_1024"
    assert gorsel.kucuk_adres("https://t.example/a.png") == "https://t.example/a.png"
    assert gorsel.kucuk_adres(url + "?x=1") == url + "?x=1"


def _ilan(title, kaynak="görsel", price=None, thumbnail=None):
    return {"site": "Trendyol", "title": title, "kaynak": kaynak, "price": price, "pazar_yeri": True,
            "link": "https://www.trendyol.com/x/y-p-1", "thumbnail": thumbnail}


def test_gorsel_karar_kelime_kuralindan_once_gelir():
    u = {"name": "Knitted Santa Claus - No AMS, No Glue", "image_url": "https://cdn.example/ref.png"}
    sonuclar = [
        _ilan("Örgü Dokulu Yılbaşı Geyik Figürü 3D Baskı", price=300.0, thumbnail="https://t.example/1.jpg"),
        _ilan("3D Baskı Örgü Dokulu Noel Baba Figürü", price=720.0, thumbnail="https://t.example/2.jpg"),
        _ilan("3D Baskı Örgü Noel Baba", price=310.0, thumbnail="https://t.example/3.jpg"),
        _ilan("Örgü Noel Baba 3D Baskı", "metin", 320.0),                    # görseli yok: kelime kuralı
        {"site": "Instagram", "title": "x", "kaynak": "sosyal", "link": "https://www.instagram.com/p/1/",
         "thumbnail": "https://t.example/4.jpg"},                             # sosyal: sorulmaz
    ]
    claude = SahteClaude([{"no": 1, "karar": "ayni", "neden": "aynı model"},
                          {"no": 2, "karar": "farkli", "neden": "başka Noel Baba"},
                          {"no": 3, "karar": "belirsiz", "neden": "görsel küçük"}])
    yeni, degisti = pazar.gorselle_kontrol(sonuclar, u, _dogrulayici(claude))
    assert degisti and len(_gorseller(claude.istekler[0])) == 4             # referans + 3 ilan
    o = pazar.ozetle(1, yeni, "örgü noel baba 3d baskı", u["name"])
    # 1: başlık yetmiyordu ama fotoğraf aynı → aynı ürün; 2: başlık uyuyor ama fotoğraf farklı → değil;
    # 3: belirsiz → kelime kuralı (örgü + noel baba) → aynı; 4: görseli yok → kelime kuralı → aynı
    assert [r.get("birebir") for r in o["results"]] == [True, False, True, True, None]
    assert (o["found_count"], o["min_price"], o["max_price"]) == (3, 300.0, 320.0)
    assert yeni[0]["gorsel_neden"] == "aynı model" and "gorsel_karar" not in yeni[4]
    # Kararı verilmiş ilanlar bir daha sorulmaz
    assert pazar.gorselle_kontrol(yeni, u, _dogrulayici(claude)) == (yeni, False) and len(claude.istekler) == 1


def test_gorsel_dogrulama_siniri_ve_hata():
    u = {"name": "Grinch", "image_url": "https://cdn.example/ref.png"}
    s = [_ilan("Grinch 3D Baskı", thumbnail="https://t.example/1.jpg")]
    claude = SahteClaude([{"no": 1, "karar": "ayni", "neden": "-"}])
    d = _dogrulayici(claude, sinir=1)
    assert pazar.gorselle_kontrol(s, u, d)[1] is True
    assert pazar.gorselle_kontrol(s, u, d) == (s, False)                     # sınır doldu
    assert pazar.gorselle_kontrol(s, u, None) == (s, False)                  # anahtar yok
    # Hata: sonuçlar olduğu gibi kalır (kelime kuralı), sonraki çalışmada yeniden denenir
    bozuk = _dogrulayici(SahteClaude(stop_reason="refusal"))
    assert pazar.gorselle_kontrol(s, u, bozuk) == (s, False)


def test_kayitlari_oku_gorsel_kararlari_kaydeder(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    u = urun(None, "Knitted Santa Claus", 1, 1, image_url="https://cdn.example/ref.png")
    pid = depo.urunleri_kaydet([u])[("makerworld", u["external_id"])]
    depo.pazar_kaydet([{"product_id": pid, "checked_at": "2026-11-20T10:00:00+00:00", "found_count": 0,
                        "results": [_ilan("Örgü Dokulu Yılbaşı Geyik Figürü", price=300.0,
                                          thumbnail="https://t.example/1.jpg")]}])
    claude = SahteClaude([{"no": 1, "karar": "ayni", "neden": "aynı model"}])
    o = pazar.kayitlari_oku(depo, [{**u, "id": pid}], _dogrulayici(claude))[pid]
    assert o["found_count"] == 1 and o["results"][0]["birebir"] is True
    kayit = depo.pazar_kayitlari([pid])[pid]
    assert kayit["results"][0]["gorsel_karar"] == "ayni"                    # panel ve sonraki günler için
    assert pazar.kayitlari_oku(depo, [{**u, "id": pid}], _dogrulayici(claude))[pid]["found_count"] == 1
    assert len(claude.istekler) == 1                                         # tekrar sorulmadı
