from datetime import date, datetime, timezone

import httpx
import pytest

from urun_bulucu import bildirim, ozet, pazar, puanlama, sezon, tasarimci
from urun_bulucu.db import SqliteDepo
from urun_bulucu.kaynaklar.makerworld import MakerWorldKaynak, filament_listesi

from .ornek_veri import urun


# ---------------------------------------------------------------- sezon
def test_aktif_sezonlar_ve_tarihler():
    adlar = lambda g: [s.ad for s, _ in sezon.aktif_sezonlar(g)]  # noqa: E731
    assert adlar(date(2026, 11, 9)) == ["Öğretmenler Günü", "Yılbaşı"]
    assert dict((s.ad, k) for s, k in sezon.aktif_sezonlar(date(2026, 11, 9)))["Yılbaşı"] == 52
    assert adlar(date(2027, 4, 20)) == ["Anneler Günü", "Kurban Bayramı"]   # 2. pazar: 9 Mayıs 2027
    assert adlar(date(2026, 7, 1)) == []
    assert sezon._ninci_pazar(2027, 5, 2) == date(2027, 5, 9)
    assert sezon._ninci_pazar(2027, 6, 3) == date(2027, 6, 20)


def test_sezon_eslesme_bonus_ve_yazi():
    gun = date(2026, 11, 9)
    a = urun(1, "Christmas Tree Ornament", 100, 1000)
    b = urun(2, "Desk Organizer", 100, 1000)
    c = urun(3, "Apple Watch Stand", 100, 1000)  # "apple" Öğretmenler Günü kelimesi değil
    puanli = {u["id"]: u for u in puanlama.puanla([a, b, c], {}, gun)}
    assert puanli[1]["score"] - puanli[2]["score"] == sezon.SEZON_BONUS
    assert puanli[1]["score_detail"]["sezon"] == "🎄 Yılbaşı: 52 gün kaldı"
    assert puanli[3]["score_detail"]["sezon"] is None
    assert "sezon ürünü (🎄 Yılbaşı: 52 gün kaldı)" in ozet.neden(puanli[1])
    md = ozet.markdown(gun, ozet.sec(list(puanli.values())), 3, "SQLite")
    assert "**Yaklaşan sezon:** 🍎 Öğretmenler Günü: 15 gün kaldı · 🎄 Yılbaşı: 52 gün kaldı" in md
    # Kelime sınırı: "elf" kelimesi "shelf" içinde eşleşmemeli
    assert sezon.eslesen({"name": "Wall Shelf", "tags": []}, sezon.aktif_sezonlar(gun)) is None


# ---------------------------------------------------------------- filament listesi
def test_filament_listesi():
    profil = {"instanceFilaments": [{"type": "PLA", "color": "#5e43b7", "usedG": "21.04"},
                                    {"type": "PETG", "color": None, "usedG": None}]}
    assert filament_listesi(profil) == [{"type": "PLA", "color": "#5E43B7", "grams": 21.0},
                                        {"type": "PETG", "color": None, "grams": 0.0}]
    assert filament_listesi(None) == []


# ---------------------------------------------------------------- tasarımcı
def _secim(pid, uid, ad):
    return {"rank": pid, "score": 80, "product_id": pid,
            "urun": urun(pid, f"Model {pid}", 1, 1, creator=ad, creator_uid=uid, creator_handle=ad.lower())}


def test_tasarimci_iki_gunde_otomatik_takip(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    g1, g2 = date(2026, 11, 9), date(2026, 11, 10)
    assert tasarimci.isabetleri_isle(depo, g1, [_secim(1, 7, "Ayse"), _secim(2, 7, "Ayse")]) == []
    # Aynı gün tekrar çalışırsa gün sayısı artmaz
    assert tasarimci.isabetleri_isle(depo, g1, [_secim(1, 7, "Ayse")]) == []
    assert depo.tasarimcilar("makerworld", [7])[7]["hit_days"] == 1
    assert tasarimci.isabetleri_isle(depo, g2, [_secim(3, 7, "Ayse")]) == ["Ayse"]
    t = depo.tasarimcilar("makerworld", [7])[7]
    assert (t["hit_days"], t["followed"], t["auto_followed"]) == (2, True, True)
    # Kullanıcı takibi kapatırsa tekrar otomatik açılmaz
    depo.tasarimcilari_kaydet([{**t, "followed": False}])
    assert tasarimci.isabetleri_isle(depo, date(2026, 11, 11), [_secim(4, 7, "Ayse")]) == []
    assert depo.tasarimcilar("makerworld", [7])[7]["followed"] is False


def test_yeni_modeller_ilk_kontrolde_bildirilmez(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    depo.tasarimcilari_kaydet([{"source_id": "makerworld", "uid": 7, "name": "Ayse", "hit_days": 2,
                                "followed": True, "auto_followed": True}])
    modeller = {"ilk": [{"id": 100, "title": "Eski"}], "sonra": [{"id": 101, "title": "Yeni <b>"},
                                                                 {"id": 100, "title": "Eski"}]}
    asama = {"ad": "ilk"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/design-service/published/7/design")
        return httpx.Response(200, json={"hits": modeller[asama["ad"]]})

    kaynak = MakerWorldKaynak(httpx.Client(transport=httpx.MockTransport(handler)), bekleme_sn=0)
    assert tasarimci.yeni_modelleri_bul(depo, kaynak) == []
    asama["ad"] = "sonra"
    yeni = tasarimci.yeni_modelleri_bul(depo, kaynak)
    assert yeni == [{"tasarimci": "Ayse", "ad": "Yeni <b>", "url": "https://makerworld.com/en/models/101",
                     "kapak": None}]
    assert tasarimci.yeni_modelleri_bul(depo, kaynak) == []  # tekrar bildirilmez

    m = bildirim.mesajlar(date(2026, 11, 9), [], yeni_modeller=yeni, yeni_takip=["Ayse"])
    assert "Takibe alındı: Ayse" in m[0]["veri"]["text"]
    assert "Yeni &lt;b&gt;" in m[-1]["veri"]["text"]


