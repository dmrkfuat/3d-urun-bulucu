from datetime import date

from urun_bulucu import ozet, puanlama, talep
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

BUGUN = date(2026, 11, 9)


def test_kisa_baski_ve_gorsellik_puani_artirir():
    a = urun(1, "Sade parça", 100, 1000, print_time_min=900)
    b = urun(2, "Flexi parça", 100, 1000, print_time_min=90, features=["hareketli parça"])
    sirali = puanlama.puanla([a, b], {}, BUGUN)
    assert sirali[0]["id"] == 2
    assert sirali[0]["score"] > sirali[1]["score"]
    assert 0 <= sirali[1]["score"] <= 100


def test_yedi_gunluk_artis_onceki_anliktan_hesaplanir():
    hizli = urun(1, "Hızlı", 100, 5000)
    yavas = urun(2, "Yavaş", 100, 5000)
    onceki = {1: {"snap_date": "2026-11-02", "downloads": 1000, "likes": 50},
              2: {"snap_date": "2026-11-02", "downloads": 4990, "likes": 100}}
    sirali = puanlama.puanla([hizli, yavas], onceki, BUGUN)
    assert sirali[0]["id"] == 1
    assert sirali[0]["score_detail"]["artis_tipi"] == "son 7 gün"


def test_etsy_talep_bonusu(tmp_path):
    csv = tmp_path / "etsy.csv"
    csv.write_text("anahtar_kelime,ulke,not\narticulated dragon,US,ornek\n", encoding="utf-8")
    talepler = talep.oku(csv)
    a = urun(1, "Articulated Dragon", 100, 1000)
    b = urun(2, "Articulated Snake", 100, 1000)
    sirali = puanlama.puanla([a, b], {}, BUGUN, talepler)
    assert sirali[0]["id"] == 1
    assert sirali[0]["score_detail"]["etsy_talep"] == "articulated dragon"


def test_ozet_kategori_siniri_ve_icerik():
    urunler = [urun(i, f"Fidget {i}", 1000 - i, 10000) for i in range(1, 8)]
    urunler += [urun(100 + i, f"Saksı {i}", 50, 500, kategori="Ev dekorasyonu ve saksı",
                     license_flag="nc_sadece_icerik") for i in range(1, 8)]
    secimler = ozet.sec(puanlama.puanla(urunler, {}, BUGUN))
    assert len(secimler) == 8  # 4 fidget + 4 saksı (kategori sınırı)
    metin = ozet.markdown(BUGUN, secimler, len(urunler), "SQLite")
    assert "Satılamaz (NC)" in metin
    assert "Video fikri" in metin and "Neden seçildi" in metin


def test_sqlite_ayni_model_tekrar_eklenmez(tmp_path):
    depo = SqliteDepo(tmp_path / "t.db")
    u = urun(None, "Model", 10, 100)
    idler1 = depo.urunleri_kaydet([u])
    u2 = {**u, "likes": 20}
    idler2 = depo.urunleri_kaydet([u2])
    assert idler1 == idler2
    satir = depo.con.execute("select count(*) c, max(likes) l from products").fetchone()
    assert (satir["c"], satir["l"]) == (1, 20)

    pid = idler1[("thingiverse", u["external_id"])]
    u2["id"] = pid
    depo.anliklari_kaydet(date(2026, 11, 2), [{**u2, "downloads": 50}])
    depo.anliklari_kaydet(BUGUN, [u2])
    onceki = depo.onceki_anliklar([pid], en_gec=date(2026, 11, 3), en_erken=date(2026, 10, 26))
    assert onceki[pid]["downloads"] == 50

    puanli = puanlama.puanla([u2], onceki, BUGUN)
    depo.puanlari_kaydet(puanli)
    secimler = ozet.sec(puanli)
    depo.secimleri_kaydet(BUGUN, secimler)
    depo.secimleri_kaydet(BUGUN, secimler)  # aynı gün tekrar çalışınca çoğalmaz
    assert depo.con.execute("select count(*) from weekly_picks").fetchone()[0] == 1
