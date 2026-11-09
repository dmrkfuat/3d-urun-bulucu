"""Çalıştırma: python -m urun_bulucu"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

from . import config, ozet, puanlama, talep
from .db import depo_olustur
from .kaynaklar.makerworld import MakerWorldHatasi, MakerWorldKaynak
from .kaynaklar.thingiverse import ThingiverseHatasi, ThingiverseKaynak


def _thingiverse(ayarlar: config.Ayarlar) -> list[dict] | None:
    if not ayarlar.thingiverse_token:
        print("UYARI: THINGIVERSE_TOKEN yok; Thingiverse atlandı. README.md > 'Thingiverse anahtarı'.")
        return None
    kaynak = ThingiverseKaynak(ayarlar.thingiverse_token)
    print("Thingiverse'ten popüler modeller toplanıyor (yavaş ve az istekle, birkaç dakika sürebilir)...")
    try:
        urunler = kaynak.topla(config.KATEGORILER, config.ARAMA_ADET, config.DETAY_LIMITI,
                               config.ARAMA_DONEMI)
    except (ThingiverseHatasi, httpx.HTTPError) as e:
        print(f"UYARI: Thingiverse atlandı: {e}")
        return None
    print(f"  Thingiverse: {len(urunler)} model ({kaynak.istek_sayisi} istek).")
    return urunler


def _makerworld() -> list[dict] | None:
    if not config.MAKERWORLD_AKTIF:
        return None
    kaynak = MakerWorldKaynak()
    print("MakerWorld'den son 30 günün modelleri toplanıyor...")
    try:
        urunler = kaynak.topla(config.KATEGORILER, config.ARAMA_ADET, config.MAKERWORLD_DETAY_LIMITI,
                               config.MAKERWORLD_GUN)
    except (MakerWorldHatasi, httpx.HTTPError) as e:
        print(f"UYARI: MakerWorld atlandı: {e}")
        return None
    print(f"  MakerWorld: {len(urunler)} model ({kaynak.istek_sayisi} istek).")
    return urunler


def calistir(bugun: date | None = None) -> int:
    bugun = bugun or date.today()
    ayarlar = config.ayarlari_oku()

    depo = depo_olustur(ayarlar)
    print(f"Veritabanı: {depo.ad}")

    urunler: list[dict] = []
    kullanilan: list[str] = []
    for ad, sonuc in (("Thingiverse", _thingiverse(ayarlar)), ("MakerWorld", _makerworld())):
        if sonuc:
            urunler += sonuc
            kullanilan.append(ad)
    print(f"Toplam {len(urunler)} model alındı.")
    if not urunler:
        print("Hiç model gelmedi; özet yazılmadı.")
        return 1

    idler = depo.urunleri_kaydet(urunler)
    for u in urunler:
        u["id"] = idler[(u["source_id"], u["external_id"])]
    depo.anliklari_kaydet(bugun, urunler)
    onceki = depo.onceki_anliklar([u["id"] for u in urunler],
                                  en_gec=bugun - timedelta(days=6), en_erken=bugun - timedelta(days=14))

    talepler = talep.oku(config.TALEP_DOSYASI)
    puanli = puanlama.puanla(urunler, onceki, bugun, talepler)
    depo.puanlari_kaydet(puanli)

    secimler = ozet.sec(puanli)
    depo.secimleri_kaydet(bugun, secimler)
    yol = ozet.rapor_yaz(config.RAPOR_KLASORU, bugun,
                         ozet.markdown(bugun, secimler, len(urunler), depo.ad, kullanilan))
    print(f"Özet hazır: {yol}")
    for s in secimler:
        print(f"  {s['rank']:>2}. {s['score']:>5}  [{ozet._kaynak(s['urun'])}] {s['urun']['name']}")
    return 0


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler için
        except AttributeError:
            pass
    sys.exit(calistir())
