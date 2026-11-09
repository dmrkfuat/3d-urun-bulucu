from urun_bulucu import analiz, lisans


def test_lisans_siniflandirma():
    assert lisans.siniflandir("Creative Commons - Attribution") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("Creative Commons - Attribution - Share Alike") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("Creative Commons - Public Domain Dedication") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("GNU - GPL") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("Creative Commons - Attribution - Non-Commercial") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("CC BY-NC-SA 4.0") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("Attribution - Non-Commercial - No Derivatives") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("All Rights Reserved") == lisans.KONTROL_ET
    # MakerWorld lisansları
    assert lisans.siniflandir("Standard Digital File License") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("MakerWorld Exclusive License") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("BY") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("BY-SA") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("CC0") == lisans.TICARI_SERBEST
    assert lisans.siniflandir("BY-NC-SA") == lisans.NC_SADECE_ICERIK
    assert lisans.siniflandir("Bypass") == lisans.KONTROL_ET
    assert lisans.siniflandir("") == lisans.KONTROL_ET
    assert lisans.siniflandir(None) == lisans.KONTROL_ET


def test_baski_suresi():
    assert analiz.baski_suresi_dk("Print time: 2h 30m on a P1S") == 150
    assert analiz.baski_suresi_dk("Printing time approx. 1.5 hours") == 90
    assert analiz.baski_suresi_dk("print time - 45 min") == 45
    assert analiz.baski_suresi_dk("Baskı süresi: 3 saat 10 dk") == 190
    assert analiz.baski_suresi_dk("Layer height 0.2, 15% infill") is None


def test_malzeme_ve_gorsel():
    metin = "Printed in Silk PLA and PETG, print in place, multicolor with AMS"
    assert analiz.malzeme_bul(metin) == "Silk PLA, PETG"
    oz = analiz.gorsel_ozellikler("Flexi Dragon", "articulated fidget", metin)
    assert "hareketli parça" in oz and "çok renkli (AMS)" in oz and "satisfying" in oz
    assert analiz.gorsel_puan(oz) == 1.0
    # kelime sınırı: "lightweight" ışık efekti sayılmaz, "gears" hareketli sayılır
    assert analiz.gorsel_ozellikler("lightweight bracket") == []
    assert analiz.gorsel_ozellikler("planetary gears") == ["hareketli parça"]
    # olumsuz ifadeler sayılmaz
    assert analiz.gorsel_ozellikler("Watch Stand [no supports, no AMS]") == []
    assert analiz.gorsel_ozellikler("works without AMS too", "multicolor version") == ["çok renkli (AMS)"]
    assert analiz.gorsel_ozellikler("- Multi-material/AMS: not required\n- Supports: none") == []
    assert analiz.gorsel_ozellikler("holder-no-supports-no-ams") == []


def test_html_temizleme_ve_sure_yazi():
    assert analiz.temiz_metin("<p>Print time: 2h</p>", None) .strip() == "Print time: 2h"
    assert analiz.sure_yazi(150) == "~2 sa 30 dk"
    assert analiz.sure_yazi(None).startswith("bilinmiyor")
