"""Instagram açıklamalarını Claude'a yazdırır (ANTHROPIC_API_KEY varsa; yoksa şablon metin kalır).

Günlük analizde ilk 10 ürün için tek istek atılır: her ürünün Türkçe adı, kategorisi, özellikleri ve
MakerWorld kapak görseli verilir; Claude her biri için kısa bir kanca (ilk satır; videoda da yazı olarak
çıkar) ve doğal bir Türkçe gövde yazar. Etiketler (#) kodla eklenir, Instagram sınırları kodla denetlenir.

Metinde tasarımcı adı, baskı süresi, yazıcı/makine adı, fiyat ve maliyet olmaz: bu bilgiler Claude'a hiç
verilmez, yine de geçerse o ürünün metni şablona döner. Hata olursa (anahtar, kredi, ağ) şablon metinler
kalır; analiz durmaz.
"""
from __future__ import annotations

import json
import re

import httpx

from . import config, gorsel, instagram

SEMA = {
    "type": "object",
    "properties": {
        "aciklamalar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "kanca": {"type": "string"},
                    "metin": {"type": "string"},
                    "etiketler": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["no", "kanca", "metin", "etiketler"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["aciklamalar"],
    "additionalProperties": False,
}

TALIMAT = """Türkiye'de 3D baskı ürünler satan küçük bir Instagram hesabı (@nozzlelabb) için Reels açıklamaları \
yazıyorsun. Videolarda ürün 3D yazıcıda basılırken ya da elde gösterilirken görünüyor. Yukarıda numaralı \
ürünlerin bilgileri ve varsa görselleri var. Her ürün için:

- "kanca": açıklamanın ilk satırı. Videonun ilk saniyelerinde ekranda da büyük yazı olarak çıkacak; kaydırmayı \
durduracak, merak uyandıran, en fazla 40 karakterlik tek cümle. En fazla bir emoji.
- "metin": kancadan sonraki gövde, 2-4 kısa paragraf (toplam en fazla 450 karakter). Ürünün ne olduğunu, \
neden hoş olduğunu ve kime/nereye yakıştığını samimi, doğal bir Türkçeyle anlat; görseldeki gerçek \
ayrıntılardan yararlan. Sonda istenen renkte basılabileceğini ve sipariş/fiyat için DM'den yazılmasını \
söyle. Emojiyi ölçülü kullan.
- "etiketler": 8-12 hashtag ("#" ile). Çoğu Türkiye'de gerçekten aranan Türkçe etiketler olsun (Türkçe \
karakterlerle, boşluksuz: #yılbaşıhediyesi, #masaüstüdekor); birkaç tane de yaygın İngilizce etiket \
(#3dprinting gibi). Ürünün kendisini, kullanım yerini, kime hediye olduğunu ve varsa sezonu anlatsın. \
"Model etiketleri" yalnızca ipucudur; oradaki yabancı, sayılı veya anlamsız etiketleri kopyalama.

Kurallar:
- Tasarımcı adı, baskı süresi, yazıcı veya makine adı/markası, fiyat, maliyet ve MakerWorld yazma \
(etiketlerde de).
- Kanca ve metinde # ve @ kullanma.
- Verilmeyen bir özelliği uydurma (ör. ölçü, malzeme, ışık, hareket); emin değilsen genel kal.
- Her ürünün metni farklı olsun; aynı kalıp cümleleri tekrarlama.
- Abartılı ve reklam kokan dilden kaçın ("kaçırma", "inanılmaz fırsat" gibi)."""

# Metne girmemesi gerekenler; geçerse o ürün şablona döner.
YASAK = re.compile(r"bambu|p1s|makerworld|\b\d+(?:[.,]\d+)?\s*(dk|dakika|sa\b|saat)|\bTL\b|#|@", re.IGNORECASE)


class AciklamaHatasi(RuntimeError):
    pass


def _bilgi(no: int, u: dict) -> str:
    satirlar = [f"Ürün {no}: {instagram.baslik(u)} (MakerWorld adı: {u.get('name')})",
                f"Kategori: {u.get('category') or '-'}"]
    if u.get("features"):
        satirlar.append("Özellikler: " + ", ".join(u["features"]))
    if (u.get("color_count") or 0) >= 2:
        satirlar.append(f"Renk sayısı: {u['color_count']}")
    etiket = [str(t) for t in (u.get("tags") or [])][:12]
    if etiket:
        satirlar.append("Model etiketleri: " + ", ".join(etiket))
    sezon_notu = (u.get("score_detail") or {}).get("sezon")
    if sezon_notu:
        satirlar.append(f"Sezon: {sezon_notu.split(':')[0]}")
    return "\n".join(satirlar)


ETIKET = re.compile(r"#[0-9a-zçğıöşüâîû_]*[a-zçğıöşüâîû][0-9a-zçğıöşüâîû_]*")


def temiz_etiketler(urun: dict, onerilen: list | None) -> list[str]:
    """Claude'un etiketleri: biçimi bozuk, sayıyla biten, marka/yazıcı, tasarımcı veya tekrar olanlar
    atılır; başa temel 3D baskı etiketleri eklenir. 3'ten az geçerli öneri varsa şablon etiketleri."""
    yaratici = re.sub(r"\W", "", (urun.get("creator") or "").lower())
    secilen: list[str] = []
    for ham in onerilen or []:
        e = "#" + re.sub(r"\s+", "", str(ham)).lstrip("#").lower().replace("i̇", "i")
        if (not ETIKET.fullmatch(e) or len(e) > 30 or re.search(r"\d$", e)
                or instagram.MAKINE_ETIKETI.search(e) or (len(yaratici) >= 3 and yaratici in e)):
            continue
        if e not in secilen:
            secilen.append(e)
    if len(secilen) < 3:
        return instagram.etiketler(urun)
    sonuc = [e for e in instagram.TEMEL_ETIKETLER[:2] if e not in secilen] + secilen
    return sonuc[: config.INSTAGRAM_ETIKET_ADET]


def _birlestir(urun: dict, kanca: str, metin: str, etiketler: list | None = None) -> str | None:
    """Kanca + gövde + etiketler; kurala veya Instagram sınırlarına uymazsa None."""
    kanca = " ".join((kanca or "").split())
    govde = "\n".join(s.rstrip() for s in (metin or "").strip().splitlines())
    govde = re.sub(r"\n{3,}", "\n\n", govde)
    if not kanca or not govde or len(kanca) > 60:
        return None
    yaratici = (urun.get("creator") or "").strip().lower()
    hepsi = f"{kanca}\n{govde}"
    if YASAK.search(hepsi) or (len(yaratici) >= 3 and yaratici in hepsi.lower()):
        return None
    etiket = " ".join(temiz_etiketler(urun, etiketler))
    sonuc = f"{kanca}\n\n{govde}\n\n{etiket}"
    return None if instagram.metni_dogrula(sonuc) else sonuc


def claude_ile_yaz(secimler: list[dict], api_key: str, istemci=None,
                   http: httpx.Client | None = None) -> dict:
    """secimler[*]['instagram_caption'] alanını Claude'un metniyle değiştirir (uymayanlar şablonda kalır).
    {'yazilan', 'girdi_token', 'cikti_token', 'maliyet_usd'} döndürür; istek başarısızsa AciklamaHatasi."""
    if not secimler:
        return {"yazilan": 0, "girdi_token": 0, "cikti_token": 0, "maliyet_usd": 0.0}
    import anthropic   # yalnızca bu özellik açıkken yüklenir

    http = http or httpx.Client(timeout=30)
    icerik: list[dict] = []
    for no, s in enumerate(secimler, start=1):
        u = s["urun"]
        icerik.append({"type": "text", "text": _bilgi(no, u)})
        url = u.get("image_url")
        blok = gorsel.indir(gorsel.kucuk_adres(url), http) or gorsel.indir(url, http) if url else None
        if blok:
            icerik.append(blok)
    icerik.append({"type": "text", "text": TALIMAT})

    istemci = istemci or anthropic.Anthropic(api_key=api_key)
    try:
        yanit = istemci.beta.messages.create(
            model=config.INSTAGRAM_ACIKLAMA_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SEMA}},
            messages=[{"role": "user", "content": icerik}],
        )
    except anthropic.APIError as e:
        raise AciklamaHatasi(f"Claude API: {str(e)[:300]}") from e
    kullanim = getattr(yanit, "usage", None)
    girdi = int(getattr(kullanim, "input_tokens", 0) or 0)
    cikti = int(getattr(kullanim, "output_tokens", 0) or 0)
    if yanit.stop_reason == "refusal":
        raise AciklamaHatasi("Claude isteği reddetti")
    metin = next((b.text for b in yanit.content if getattr(b, "type", None) == "text"), "")
    try:
        veri = json.loads(metin)
    except ValueError as e:
        raise AciklamaHatasi("Claude yanıtı JSON değil") from e

    yazilan = 0
    for a in veri.get("aciklamalar") or []:
        no = a.get("no")
        if not isinstance(no, int) or not 1 <= no <= len(secimler):
            continue
        s = secimler[no - 1]
        yeni = _birlestir(s["urun"], a.get("kanca"), a.get("metin"), a.get("etiketler"))
        if yeni:
            s["instagram_caption"] = yeni
            yazilan += 1
    maliyet = (girdi * config.GORSEL_GIRDI_USD_M + cikti * config.GORSEL_CIKTI_USD_M) / 1e6
    return {"yazilan": yazilan, "girdi_token": girdi, "cikti_token": cikti, "maliyet_usd": maliyet}
