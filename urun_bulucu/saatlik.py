"""Saatlik Telegram testi: Supabase'teki en son günlük özeti tek mesaj olarak gönderir.

Dış sitelere (MakerWorld, SerpApi) istek atmaz; yalnızca kayıtlı veriyi okur. Telegram
bağlantısının ve mesaj biçiminin çalıştığını görmek içindir.
Çalıştırma: python -m urun_bulucu.saatlik
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import httpx

from . import bildirim, config, pazar
from .bildirim import _e, _href

TR_SAATI = timezone(timedelta(hours=3))  # Türkiye yaz saati uygulamıyor (UTC+3)


def son_ozet(sb) -> tuple[str | None, list[dict]]:
    """En son özet günü ve o günün seçimleri (ürün bilgisiyle), sıra numarasına göre."""
    son = sb.table("weekly_picks").select("pick_date").order("pick_date", desc=True).limit(1).execute().data
    if not son:
        return None, []
    gun = son[0]["pick_date"]
    satirlar = (sb.table("weekly_picks")
                .select("rank, score, product_id, products(name, url, print_time_min, cost_tl, price_tl, trend_rank)")
                .eq("pick_date", gun).order("rank").execute().data)
    return gun, [s for s in satirlar if s.get("products")]


def pazar_kayitlari(sb, secimler: list[dict]) -> dict[int, dict]:
    ids = [s["product_id"] for s in secimler]
    if not ids:
        return {}
    satirlar = sb.table("market_checks").select("*").in_("product_id", ids).execute().data
    return {r["product_id"]: r for r in satirlar if pazar.gecerli_mi(r)}


def mesaj(gun: str | None, secimler: list[dict], panel_url: str | None, simdi: datetime | None = None,
          pazar_sonuclari: dict[int, dict] | None = None) -> str:
    pazar_sonuclari = pazar_sonuclari or {}
    simdi = (simdi or datetime.now(timezone.utc)).astimezone(TR_SAATI)
    satirlar = [f"🧪 <b>Saatlik test</b> — {simdi:%d.%m.%Y %H:%M}", "Sistem çalışıyor; Telegram bağlantısı tamam."]
    if not gun:
        satirlar.append("Henüz kayıtlı özet yok.")
    else:
        satirlar += ["", f"Son özet: <b>{_e(gun)}</b>"]
        for s in secimler[:5]:
            p = s["products"]
            fiyat = f" · {p['cost_tl']:.0f}→{p['price_tl']:.0f} TL" if p.get("cost_tl") is not None else ""
            satirlar.append(f"{s['rank']}. <a href=\"{_href(p['url'])}\">{_e(p['name'])}</a> — {s['score']}"
                            + ("🔥" if p.get("trend_rank") else "") + _e(fiyat))
            yerler = pazar.satis_yerleri(pazar_sonuclari.get(s["product_id"]), en_fazla=3)
            if yerler:
                satirlar.append("   🛒 " + " · ".join(bildirim.satis_link_html(y) for y in yerler))
    if panel_url:
        satirlar += ["", f"📊 Panel: {_e(panel_url)}"]
    return "\n".join(satirlar)


def calistir() -> int:
    ayarlar = config.ayarlari_oku()
    if not (ayarlar.telegram_token and ayarlar.telegram_chat_id):
        print("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID yok.")
        return 2
    gun, secimler, pazar_sonuclari = None, [], {}
    if ayarlar.supabase_var:
        from supabase import create_client
        sb = create_client(ayarlar.supabase_url, ayarlar.supabase_key)
        gun, secimler = son_ozet(sb)
        try:
            pazar_sonuclari = pazar_kayitlari(sb, secimler)
        except Exception as e:  # noqa: BLE001 — tablo yoksa mesaj yine gitsin
            print(f"UYARI: e-ticaret sonuçları okunamadı: {e}")
    metin = mesaj(gun, secimler, ayarlar.panel_url or None, pazar_sonuclari=pazar_sonuclari)
    try:
        bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id,
                        [{"metot": "sendMessage", "veri": {"text": metin, "disable_web_page_preview": True}}])
    except (bildirim.BildirimHatasi, httpx.HTTPError) as e:
        print(f"HATA: Telegram mesajı gönderilemedi: {e}")
        return 1
    print(f"Saatlik test mesajı gönderildi (son özet: {gun}).")
    return 0


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(calistir())
