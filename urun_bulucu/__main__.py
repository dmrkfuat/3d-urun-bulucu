"""Çalıştırma: python -m urun_bulucu"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

from . import bildirim, config, ozet, puanlama, talep
from .db import depo_olustur
from .kaynaklar.makerworld import MakerWorldHatasi, MakerWorldKaynak


def calistir(bugun: date | None = None) -> int:
    bugun = bugun or date.today()
    ayarlar = config.ayarlari_oku()

    depo = depo_olustur(ayarlar)
    print(f"Veritabanı: {depo.ad}")

    kaynak = MakerWorldKaynak()
    print("MakerWorld'den son 30 günün modelleri toplanıyor (yavaş ve az istekle, birkaç dakika sürebilir)...")
    try:
        # Toplam detay isteği MAKERWORLD_DETAY_LIMITI civarında kalsın: önce trend, kalanı aramadan.
        urunler = kaynak.topla(config.KATEGORILER, config.ARAMA_ADET,
                               config.MAKERWORLD_DETAY_LIMITI - config.MAKERWORLD_TREND_ADET,
                               config.MAKERWORLD_GUN, trend_adet=config.MAKERWORLD_TREND_ADET)
    except (MakerWorldHatasi, httpx.HTTPError) as e:
        print(f"HATA: MakerWorld'den veri alınamadı: {e}")
        return 1
    print(f"{len(urunler)} model alındı ({kaynak.istek_sayisi} istek).")
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
                         ozet.markdown(bugun, secimler, len(urunler), depo.ad))
    print(f"Özet hazır: {yol}")
    for s in secimler:
        print(f"  {s['rank']:>2}. {s['score']:>5}  {s['urun']['name']}")

    if ayarlar.telegram_token and ayarlar.telegram_chat_id:
        try:
            adet = bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id,
                                   bildirim.mesajlar(bugun, secimler, ayarlar.panel_url or None))
            print(f"Telegram'a {adet} mesaj gönderildi.")
        except (bildirim.BildirimHatasi, httpx.HTTPError) as e:
            print(f"UYARI: Telegram bildirimi gönderilemedi: {e}")
    return 0


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler için
        except AttributeError:
            pass
    sys.exit(calistir())
