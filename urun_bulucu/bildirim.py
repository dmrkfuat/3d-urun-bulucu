"""Günlük özeti Telegram'a gönderir (ücretsiz Telegram Bot API).

.env / GitHub Secrets: TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID. İkisi de yoksa hiçbir şey
gönderilmez. Gönderim hatası analizi durdurmaz; yalnızca uyarı yazılır.
"""
from __future__ import annotations

import html
from datetime import date

import httpx

from . import analiz, pazar, sezon, video

API = "https://api.telegram.org"
FOTOGRAFLI_ADET = 3  # ilk kaç ürün kapak görseliyle gönderilsin


class BildirimHatasi(RuntimeError):
    pass


def _e(metin: object) -> str:
    return html.escape(str(metin), quote=False)


def _fiyat(u: dict) -> str:
    if u.get("cost_tl") is None:
        return ""
    return f" · ~{u['cost_tl']:.0f} → {u['price_tl']:.0f} TL"


def satis_link_html(y: dict) -> str:
    """Bir satış yeri: <a href="...">Trendyol</a> 135 TL (bağımsız mağaza ise işaretli)."""
    fiyat = f" {y['price']:.0f} TL" if y.get("price") is not None else ""
    etiket = "" if y.get("pazar_yeri", True) else " (mağaza)"
    return f"<a href=\"{_e(y['link'])}\">{_e(y['site'])}</a>{fiyat}{etiket}"


def urun_yazisi(s: dict, pazar_ozeti: dict | None = None, sinir: int = 1024) -> str:
    """Bir ürünün Telegram metni (HTML). Fotoğraf altı en fazla 1024 karakter; sığmazsa
    satış bağlantıları azaltılır (HTML etiketi yarıda kesilmez)."""
    u = s["urun"]
    bas = [
        f"<b>{s['rank']}. {_e(u['name'])}</b> — {s['score']} puan",
        f"⏱ {_e(analiz.sure_yazi(u.get('print_time_min')))}"
        + (f" · {u['weight_g']} g" if u.get("weight_g") else "") + _e(_fiyat(u)),
    ]
    if u.get("trend_rank"):
        bas.append(f"🔥 MakerWorld trend #{u['trend_rank']}")
    sezon_notu = (u.get("score_detail") or {}).get("sezon")
    if sezon_notu:
        bas.append(_e(sezon_notu))
    if pazar_ozeti is not None:
        bas.append(f"🛒 {_e(pazar.fiyat_yazi(pazar_ozeti, u.get('price_tl')))}")
    son = [f"🎬 {_e(video.kancalar(u)[0])}", f"🔗 MakerWorld: {_e(u['url'])}"]
    yerler = [f"   ↳ {satis_link_html(y)}" for y in pazar.satis_yerleri(pazar_ozeti)]
    while True:
        metin = "\n".join(bas + yerler + son)
        if len(metin) <= sinir or not yerler:
            return metin if len(metin) <= sinir else "\n".join(bas[:2] + son)[:sinir]
        yerler.pop()


def mesajlar(gun: date, secimler: list[dict], panel_url: str | None = None, *,
             pazar_sonuclari: dict[int, dict] | None = None, yeni_modeller: list[dict] | None = None,
             yeni_takip: list[str] | None = None) -> list[dict]:
    """Gönderilecek Telegram istekleri: ilk 3 ürün fotoğraflı, kalanlar tek mesajda,
    varsa takip edilen tasarımcıların yeni modelleri ayrı mesajda."""
    pazar_sonuclari = pazar_sonuclari or {}
    sonuc: list[dict] = []
    for s in secimler[:FOTOGRAFLI_ADET]:
        yazi = urun_yazisi(s, pazar_sonuclari.get(s["product_id"]))
        if s["urun"].get("image_url"):
            sonuc.append({"metot": "sendPhoto", "veri": {"photo": s["urun"]["image_url"], "caption": yazi}})
        else:
            sonuc.append({"metot": "sendMessage", "veri": {"text": yazi}})
    kalan = []
    for s in secimler[FOTOGRAFLI_ADET:]:
        satir = f"{s['rank']}. <a href=\"{_e(s['urun']['url'])}\">{_e(s['urun']['name'])}</a> — {s['score']}"
        yerler = pazar.satis_yerleri(pazar_sonuclari.get(s["product_id"]), en_fazla=2)
        if yerler:
            satir += "\n   🛒 " + " · ".join(satis_link_html(y) for y in yerler)
        kalan.append(satir)
    ozet = [f"<b>3D Ürün Özeti — {gun.isoformat()}</b>"]
    aktif = sezon.aktif_sezonlar(gun)
    if aktif:
        ozet.append(_e(" · ".join(sezon.yazi(sz, k) for sz, k in aktif)))
    if kalan:
        ozet += ["", *kalan]
    if yeni_takip:
        ozet += ["", f"👤 Takibe alındı: {_e(', '.join(yeni_takip))}"]
    if panel_url:
        ozet += ["", f"📊 Panel: {_e(panel_url)}"]
    sonuc.append({"metot": "sendMessage", "veri": {"text": "\n".join(ozet), "disable_web_page_preview": True}})

    if yeni_modeller:
        satirlar = ["<b>🆕 Takip ettiğin tasarımcılardan yeni modeller</b>", ""]
        satirlar += [f"• {_e(m['tasarimci'])}: <a href=\"{_e(m['url'])}\">{_e(m['ad'])}</a>"
                     for m in yeni_modeller[:15]]
        sonuc.append({"metot": "sendMessage", "veri": {"text": "\n".join(satirlar),
                                                       "disable_web_page_preview": True}})
    return sonuc


def gonder(token: str, chat_id: str, istekler: list[dict], client: httpx.Client | None = None) -> int:
    client = client or httpx.Client(timeout=30)
    gonderilen = 0
    for istek in istekler:
        veri = {"chat_id": chat_id, "parse_mode": "HTML", **istek["veri"]}
        yanit = client.post(f"{API}/bot{token}/{istek['metot']}", json=veri)
        if yanit.status_code != 200 and istek["metot"] == "sendPhoto":
            # Görsel alınamadıysa (ör. GIF/boyut sınırı) metin olarak gönder.
            veri = {"chat_id": chat_id, "parse_mode": "HTML", "text": istek["veri"]["caption"]}
            yanit = client.post(f"{API}/bot{token}/sendMessage", json=veri)
        if yanit.status_code != 200:
            try:
                aciklama = yanit.json().get("description")
            except ValueError:
                aciklama = yanit.text[:200]
            raise BildirimHatasi(f"Telegram {yanit.status_code}: {aciklama}")
        gonderilen += 1
    return gonderilen
