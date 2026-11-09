"""Günlük özeti Telegram'a gönderir (ücretsiz Telegram Bot API).

.env / GitHub Secrets: TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID. İkisi de yoksa hiçbir şey
gönderilmez. Gönderim hatası analizi durdurmaz; yalnızca uyarı yazılır.
"""
from __future__ import annotations

import html
from datetime import date

import httpx

from . import analiz, video

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


def urun_yazisi(s: dict) -> str:
    """Bir ürünün Telegram metni (HTML). Fotoğraf altı sınırı 1024 karakter."""
    u = s["urun"]
    satirlar = [
        f"<b>{s['rank']}. {_e(u['name'])}</b> — {s['score']} puan",
        f"⏱ {_e(analiz.sure_yazi(u.get('print_time_min')))}"
        + (f" · {u['weight_g']} g" if u.get("weight_g") else "") + _e(_fiyat(u)),
    ]
    if u.get("trend_rank"):
        satirlar.append(f"🔥 MakerWorld trend #{u['trend_rank']}")
    satirlar.append(f"🎬 {_e(video.kancalar(u)[0])}")
    satirlar.append(f"🔗 {_e(u['url'])}")
    return "\n".join(satirlar)[:1024]


def mesajlar(gun: date, secimler: list[dict], panel_url: str | None = None) -> list[dict]:
    """Gönderilecek Telegram istekleri: ilk 3 ürün fotoğraflı, kalanlar tek mesajda."""
    sonuc: list[dict] = []
    for s in secimler[:FOTOGRAFLI_ADET]:
        yazi = urun_yazisi(s)
        if s["urun"].get("image_url"):
            sonuc.append({"metot": "sendPhoto", "veri": {"photo": s["urun"]["image_url"], "caption": yazi}})
        else:
            sonuc.append({"metot": "sendMessage", "veri": {"text": yazi}})
    kalan = [f"{s['rank']}. <a href=\"{_e(s['urun']['url'])}\">{_e(s['urun']['name'])}</a> — {s['score']}"
             for s in secimler[FOTOGRAFLI_ADET:]]
    ozet = [f"<b>3D Ürün Özeti — {gun.isoformat()}</b>"]
    if kalan:
        ozet += ["", *kalan]
    if panel_url:
        ozet += ["", f"📊 Panel: {_e(panel_url)}"]
    sonuc.append({"metot": "sendMessage", "veri": {"text": "\n".join(ozet), "disable_web_page_preview": True}})
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
