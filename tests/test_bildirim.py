import json
from datetime import date

import httpx
import pytest

from urun_bulucu import bildirim

from .ornek_veri import urun


def _secimler(n=5):
    sonuc = []
    for i in range(1, n + 1):
        u = urun(i, f"Model <{i}>", 10, 100, image_url=f"https://cdn.example/{i}.png" if i != 2 else None,
                 print_time_min=60, weight_g=20, cost_tl=20.6, price_tl=65, trend_rank=3 if i == 1 else None)
        sonuc.append({"rank": i, "score": 90 - i, "urun": u})
    return sonuc


def test_mesajlar_ilk_uc_fotografli_kalan_tek_mesaj():
    m = bildirim.mesajlar(date(2026, 11, 9), _secimler(5), "https://panel.example")
    assert [x["metot"] for x in m] == ["sendPhoto", "sendMessage", "sendPhoto", "sendMessage"]
    ilk = m[0]["veri"]["caption"]
    assert "<b>1. Model &lt;1&gt;</b>" in ilk          # HTML kaçışı
    assert "~21 → 65 TL" in ilk and "trend #3" in ilk and "🎬" in ilk
    son = m[-1]["veri"]["text"]
    assert "4. <a href=" in son and "5. <a href=" in son and "Panel: https://panel.example" in son


def test_gonder_ve_fotograf_hatasinda_metne_doner():
    gelen = []

    def handler(request: httpx.Request) -> httpx.Response:
        govde = json.loads(request.content)
        gelen.append((request.url.path.rsplit("/", 1)[1], govde))
        assert request.url.path.startswith("/botTOKEN/")
        assert govde["chat_id"] == "42" and govde["parse_mode"] == "HTML"
        if request.url.path.endswith("sendPhoto"):
            return httpx.Response(400, json={"ok": False, "description": "wrong file"})
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    istekler = bildirim.mesajlar(date(2026, 11, 9), _secimler(1))
    assert bildirim.gonder("TOKEN", "42", istekler, client) == 2
    assert [g[0] for g in gelen] == ["sendPhoto", "sendMessage", "sendMessage"]


def test_gonder_hata_verir():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})))
    with pytest.raises(bildirim.BildirimHatasi, match="Unauthorized"):
        bildirim.gonder("KOTU", "42", [{"metot": "sendMessage", "veri": {"text": "x"}}], client)
