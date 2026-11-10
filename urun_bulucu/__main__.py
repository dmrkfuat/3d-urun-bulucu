"""Çalıştırma: python -m urun_bulucu"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

from . import bildirim, config, kesif, maliyet, ozet, pazar, puanlama, talep, tasarimci
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

    # Daha önce e-ticarette aranmış ürünlerde fiyat piyasaya göre önerilir (puanlamadan önce).
    try:
        kayitlar = {pid: o for pid, o in depo.pazar_kayitlari([u["id"] for u in urunler]).items()
                    if pazar.gecerli_mi(o)}
        print(f"Piyasaya göre fiyat: {len(maliyet.piyasaya_uygula(urunler, kayitlar))} ürün")
    except Exception as e:  # noqa: BLE001 — fiyat maliyetten kalır
        print(f"UYARI: Piyasa fiyatları okunamadı: {e}")

    talepler = talep.oku(config.TALEP_DOSYASI)
    puanli = puanlama.puanla(urunler, onceki, bugun, talepler)
    depo.puanlari_kaydet(puanli)

    secimler = ozet.sec(puanli)
    depo.secimleri_kaydet(bugun, secimler)

    # --- İsteğe bağlı ekler: biri hata verirse uyarı yazılır, analiz durmaz ---
    yeni_takip, yeni_modeller, pazar_sonuclari = [], [], {}
    try:
        yeni_takip = tasarimci.isabetleri_isle(depo, bugun, secimler)
        yeni_modeller = tasarimci.yeni_modelleri_bul(depo, kaynak)
        print(f"Tasarımcı takibi: {len(yeni_modeller)} yeni model"
              + (f"; yeni takip: {', '.join(yeni_takip)}" if yeni_takip else ""))
    except Exception as e:  # noqa: BLE001 — isteğe bağlı özellik
        print(f"UYARI: Tasarımcı takibi atlandı: {e}")
    if ayarlar.serpapi_key:
        try:
            aranan = pazar.calistir(depo, secimler, ayarlar.serpapi_key)
            print(f"E-ticaret araması: {len(aranan)} ürün arandı.")
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: E-ticaret araması atlandı: {e}")
    try:
        # Rapor ve Telegram için bugünkü ilk 10'un kayıtlı tüm arama sonuçları (önceki günlerde
        # aranmış olanlar dahil); yalnızca 3D şartıyla yapılmış aramalar.
        pazar_sonuclari = {pid: o for pid, o in depo.pazar_kayitlari([s["product_id"] for s in secimler]).items()
                           if pazar.gecerli_mi(o)}
        # Bugün ilk kez aranan ürünlerin fiyatı da piyasaya göre güncellenir (puan yarın etkilenir).
        guncel = maliyet.piyasaya_uygula([s["urun"] for s in secimler], pazar_sonuclari)
        for u in guncel:
            u["score_detail"].update(puanlama.fiyat_ayrintisi(u))
        if guncel:
            depo.puanlari_kaydet(guncel)
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Kayıtlı e-ticaret sonuçları okunamadı: {e}")

    # Haftalık pazar keşfi: Türkiye'de çok satan 3D baskılar → MakerWorld'deki modeli.
    kesif_kumeleri: list[dict] = []
    try:
        kesif_kumeleri, _ = kesif.calistir(depo, ayarlar, bugun, kaynak)
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Pazar keşfi atlandı: {e}")

    yol = ozet.rapor_yaz(config.RAPOR_KLASORU, bugun,
                         ozet.markdown(bugun, secimler, len(urunler), depo.ad, pazar_sonuclari))
    print(f"Özet hazır: {yol}")
    for s in secimler:
        print(f"  {s['rank']:>2}. {s['score']:>5}  {s['urun']['name']}")

    if ayarlar.telegram_token and ayarlar.telegram_chat_id:
        try:
            istekler = bildirim.mesajlar(bugun, secimler, ayarlar.panel_url or None,
                                         pazar_sonuclari=pazar_sonuclari, yeni_modeller=yeni_modeller,
                                         yeni_takip=yeni_takip)
            kesif_mesaji = kesif.telegram_mesaji(bugun, kesif_kumeleri, ayarlar.panel_url or None)
            if kesif_mesaji:
                istekler.append({"metot": "sendMessage",
                                 "veri": {"text": kesif_mesaji, "disable_web_page_preview": True}})
            adet = bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id, istekler)
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
