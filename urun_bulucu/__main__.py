"""Çalıştırma: python -m urun_bulucu"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

from . import (aciklama, bildirim, config, etsy, gorsel, istatistik, kesif, kota, maliyet, ozet, pazar,
               puanlama, siparis, talep, tasarimci)
from .db import depo_olustur, satis_verisi
from .kaynaklar.makerworld import MakerWorldHatasi, MakerWorldKaynak


def calistir(bugun: date | None = None) -> int:
    bugun = bugun or date.today()
    ayarlar = config.ayarlari_oku()

    depo = depo_olustur(ayarlar)
    print(f"Veritabanı: {depo.ad}")

    # Gerçek satışlar: satılan ürün/kategori puanda öne çıkar; gerçek süre/gram girildiyse maliyet düzelir
    # (maliyet MakerWorld verisi okunurken hesaplandığı için önce ayarlanır).
    satis_ozeti = None
    try:
        siparisler, isaretler = satis_verisi(depo)
        satis_ozeti = siparis.satis_ozeti(siparisler, isaretler)
        duzeltme = siparis.kalibrasyon(siparisler)
        if duzeltme:
            maliyet.DUZELTME.update(sure=duzeltme["sure"], gram=duzeltme["gram"])
        print(f"Satış geçmişi: {len(satis_ozeti['urun'])} ürün satılmış. {siparis.yazi(duzeltme)}")
    except Exception as e:  # noqa: BLE001 — isteğe bağlı
        print(f"UYARI: Satış verisi okunamadı: {e}")

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
        kayitlar = pazar.kayitlari_oku(depo, urunler)   # yalnızca aynı ürün sayılan sonuçların fiyatı
        print(f"Piyasaya göre fiyat: {len(maliyet.piyasaya_uygula(urunler, kayitlar))} ürün")
    except Exception as e:  # noqa: BLE001 — fiyat maliyetten kalır
        print(f"UYARI: Piyasa fiyatları okunamadı: {e}")

    talepler = talep.oku(config.TALEP_DOSYASI)
    if ayarlar.etsy_key:
        try:
            print(f"Etsy: {etsy.isle(urunler, ayarlar.etsy_key)} arama")
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: Etsy araması atlandı: {e}")
    ig_bonuslari, ig_ozeti = {}, None
    try:
        ig_bonuslari, ig_ozeti = istatistik.calistir(ayarlar, bugun)
        if ig_bonuslari:
            print("Instagram kategori etkisi: " + ", ".join(f"{k} {b:+d}" for k, (b, _) in ig_bonuslari.items()))
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Instagram performansı okunamadı: {e}")
    puanli = puanlama.puanla(urunler, onceki, bugun, talepler, ig_bonuslari=ig_bonuslari, satis_ozeti=satis_ozeti)
    depo.puanlari_kaydet(puanli)

    secimler = ozet.sec(puanli)
    if ayarlar.anthropic_key and config.INSTAGRAM_LLM_ACIKLAMA:
        try:
            k = aciklama.claude_ile_yaz(secimler, ayarlar.anthropic_key)
            print(f"Instagram açıklamaları (Claude): {k['yazilan']}/{len(secimler)} ürün, {k['girdi_token']} girdi + "
                  f"{k['cikti_token']} çıktı token (~${k['maliyet_usd']:.3f})")
        except Exception as e:  # noqa: BLE001 — şablon metinler kalır
            print(f"UYARI: Instagram açıklamaları Claude ile yazılamadı, şablon kullanıldı: {e}")
    depo.secimleri_kaydet(bugun, secimler)

    # --- İsteğe bağlı ekler: biri hata verirse uyarı yazılır, analiz durmaz ---
    yeni_takip, yeni_modeller, pazar_sonuclari = [], [], {}
    # İlan fotoğrafları MakerWorld görseliyle karşılaştırılır (ANTHROPIC_API_KEY varsa); önce bugün aranan
    # ürünler, sonra ilk 10'un kayıtlı ilanları (sıraya göre, GORSEL_CALISMA_SINIRI ürüne kadar).
    dogrulayici = (gorsel.Dogrulayici(ayarlar.anthropic_key)
                   if ayarlar.anthropic_key and config.GORSEL_DOGRULAMA else None)
    try:
        yeni_takip = tasarimci.isabetleri_isle(depo, bugun, secimler)
        yeni_modeller = tasarimci.yeni_modelleri_bul(depo, kaynak)
        print(f"Tasarımcı takibi: {len(yeni_modeller)} yeni model"
              + (f"; yeni takip: {', '.join(yeni_takip)}" if yeni_takip else ""))
    except Exception as e:  # noqa: BLE001 — isteğe bağlı özellik
        print(f"UYARI: Tasarımcı takibi atlandı: {e}")
    if ayarlar.serpapi_key:
        try:
            # Aylık bütçe: kalan hak, yenilemeye kalan günlere bölünür (ay ortasında bitmesin).
            pazar.yedek_ayarla(ayarlar.serper_key)
            kalan = pazar.kalan_hak(ayarlar.serpapi_key)
            adet = kota.gunluk_urun(kalan, bugun)
            print(kota.yazi(kalan, bugun))
            aranan = pazar.calistir(depo, secimler, ayarlar.serpapi_key, dogrulayici=dogrulayici, adet=adet)
            print(f"E-ticaret araması: {len(aranan)} ürün arandı (bütçe {adet}).")
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: E-ticaret araması atlandı: {e}")
    try:
        # Rapor ve Telegram için bugünkü ilk 10'un kayıtlı tüm arama sonuçları (önceki günlerde
        # aranmış olanlar dahil); yalnızca 3D şartıyla yapılmış aramalar.
        pazar_sonuclari = pazar.kayitlari_oku(depo, [s["urun"] for s in secimler], dogrulayici)
        if dogrulayici and dogrulayici.kontrol_edilen:
            print(f"Görsel doğrulama: {dogrulayici.kontrol_edilen} ürün, {dogrulayici.girdi_token} girdi + "
                  f"{dogrulayici.cikti_token} çıktı token (~${dogrulayici.maliyet_usd():.3f})")
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
    kesif_trendyol = None
    try:
        kesif_kumeleri, _, kesif_trendyol = kesif.calistir(depo, ayarlar, bugun, kaynak)
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
            kesif_mesaji = kesif.telegram_mesaji(bugun, kesif_kumeleri, ayarlar.panel_url or None,
                                                 trendyol=kesif_trendyol)
            if kesif_mesaji:
                istekler.append({"metot": "sendMessage",
                                 "veri": {"text": kesif_mesaji, "disable_web_page_preview": True}})
            if ig_ozeti:
                istekler.append({"metot": "sendMessage",
                                 "veri": {"text": ig_ozeti, "disable_web_page_preview": True}})
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
