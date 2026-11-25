import json
from types import SimpleNamespace

import pytest

from urun_bulucu import aciklama, config, instagram

from .ornek_veri import urun


@pytest.fixture(autouse=True)
def _gorsel_yok(monkeypatch):
    monkeypatch.setattr(aciklama.gorsel, "indir", lambda url, client: None)


class SahteClaude:
    def __init__(self, veri, stop="end_turn"):
        self.veri, self.stop, self.istekler = veri, stop, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **k):
        self.istekler.append(k)
        return SimpleNamespace(
            stop_reason=self.stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
            content=[SimpleNamespace(type="text", text=json.dumps(self.veri))])


def _secimler():
    u1 = urun(1, "Impossible Thread Fidget", 1, 1, creator="Usta Tasarımcı", print_time_min=59,
              tags=["fidget"], features=["hareketli parça"], image_url="https://cdn.example/1.png")
    u2 = urun(2, "Mini Grinch", 1, 1, category="Hediyelik", creator="mylitos")
    return [{"urun": u, "instagram_caption": instagram.gonderi_metni(u)} for u in (u1, u2)]


def test_claude_metni_kanca_govde_ve_etiketlerle_yazilir():
    s = _secimler()
    eski2 = s[1]["instagram_caption"]
    claude = SahteClaude({"aciklamalar": [
        {"no": 1, "kanca": "Bu vida hiç bitmiyor 🌀", "metin": "Elinde döndürdükçe rahatlatan bir oyuncak.\n\nDM'den yaz!"},
        {"no": 2, "kanca": "Grinch masana geldi", "metin": "Usta işi, 45 dakikada bastım."},   # süre geçti → şablon
        {"no": 9, "kanca": "x", "metin": "y"},
    ]})
    k = aciklama.claude_ile_yaz(s, "KEY", istemci=claude)
    m = s[0]["instagram_caption"]
    assert m.startswith("Bu vida hiç bitmiyor 🌀\n\nElinde döndürdükçe")
    assert "#3dbaskı" in m and "#bambulab" not in m and instagram.metni_dogrula(m) is None
    assert s[1]["instagram_caption"] == eski2
    assert k["yazilan"] == 1 and k["maliyet_usd"] > 0
    istek = claude.istekler[0]
    gonderilen = json.dumps(istek["messages"], ensure_ascii=False)
    # Yasak bilgiler Claude'a hiç verilmez
    assert "Usta Tasarımcı" not in gonderilen and "mylitos" not in gonderilen and "59" not in gonderilen
    assert istek["model"] == config.INSTAGRAM_ACIKLAMA_MODEL and istek["fallbacks"] == "default"


def test_yasak_bilgi_veya_tasarimci_gecerse_sablon_kalir():
    u = _secimler()[1]["urun"]
    assert aciklama._birlestir(u, "Selam", "Bambu Lab ile bastım") is None
    assert aciklama._birlestir(u, "Selam", "Tasarım: mylitos") is None
    assert aciklama._birlestir(u, "Selam", "Fiyatı 50 TL") is None
    assert aciklama._birlestir(u, "Selam", "#grinch") is None
    assert aciklama._birlestir(u, "", "metin") is None
    assert aciklama._birlestir(u, "Selam 🎄", "Güzel bir hediye.\n\n\n\nDM at.").startswith(
        "Selam 🎄\n\nGüzel bir hediye.\n\nDM at.\n\n#")


def test_claude_etiketleri_temizlenir():
    u = _secimler()[1]["urun"]   # tasarımcı: mylitos
    e = aciklama.temiz_etiketler(u, ["#Grinch", "yılbaşı hediyesi", "#grinch", "#BambuLab", "#p1s",
                                     "#christmastree20", "#mylitosdesign", "#a b!", "#İstanbul", "#3dprinting"])
    assert e == ["#3dbaskı", "#3dyazıcı", "#grinch", "#yılbaşıhediyesi", "#istanbul", "#3dprinting"]
    # Yetersiz öneri → şablon etiketleri
    assert aciklama.temiz_etiketler(u, ["#bambu", "#x1"]) == instagram.etiketler(u)
    m = aciklama._birlestir(u, "Selam", "Güzel bir hediye.", ["#grinch", "#yılbaşı", "#hediye"])
    assert m.endswith("\n\n#3dbaskı #3dyazıcı #grinch #yılbaşı #hediye")


def test_sablon_etiketlerinde_sayili_ve_anlamsiz_yok():
    u = urun(3, "Tree", 1, 1, tags=["christmastree20", "adorno0", "NoAMS", "multipart", "Christmas", "xmax2026"])
    e = instagram.etiketler(u)
    assert "#yılbaşı" in e and not any(x.lower() in ("#christmastree20", "#adorno0", "#noams", "#multipart",
                                                     "#xmax2026") for x in e)


def test_ret_ve_bozuk_yanit_hata_verir():
    with pytest.raises(aciklama.AciklamaHatasi, match="reddetti"):
        aciklama.claude_ile_yaz(_secimler(), "KEY", istemci=SahteClaude({}, stop="refusal"))
    bozuk = SahteClaude({})
    bozuk.beta.messages.create = lambda **k: SimpleNamespace(
        stop_reason="end_turn", usage=None, content=[SimpleNamespace(type="text", text="metin")])
    with pytest.raises(aciklama.AciklamaHatasi, match="JSON"):
        aciklama.claude_ile_yaz(_secimler(), "KEY", istemci=bozuk)
