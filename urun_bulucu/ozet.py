"""Özet: en iyi ürünleri seçer, neden seçildiğini ve video fikrini yazar."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import analiz, lisans
from .config import KATEGORI_BASINA_EN_FAZLA, MAKERWORLD_HEPSI_SATILABILIR, OZET_ADET, YAZICI

# Özelliğe göre hazır video/paylaşım fikirleri (sıra önemli: ilk eşleşen kullanılır).
VIDEO_SABLONLARI: list[tuple[str, str]] = [
    ("hareketli parça",
     "Tabladan tek parça çıkarıp ilk kez hareket ettirdiğin an — yakın çekim, sesli. "
     "Kanca yazısı: \"Bu tek parça basıldı 🤯\""),
    ("çok renkli (AMS)",
     "AMS renk değişimlerinin hızlandırılmış timelapse'i, sonunda ürünün 360° dönüşü. "
     "Kanca: \"4 renk, tek baskı\""),
    ("satisfying",
     "10-15 sn'lik sessiz \"satisfying\" döngü: ürünü elde tekrar tekrar oynat, "
     "sonu başına bağlansın (loop)."),
    ("ışık/şeffaf efekt",
     "Karanlık oda: ışık yanınca ortaya çıkan efekt. Önce kapalı, sonra açık — tek geçiş."),
]
KATEGORI_SABLONLARI = {
    "Masa ve ofis düzenleyici": "Öncesi/sonrası: dağınık masa → düzenli masa, 15 sn, hızlı kesmeler.",
    "Ev dekorasyonu ve saksı": "Timelapse + bitkiyi/ürünü yerine koyduğun sakin bir son sahne.",
    "Telefon ve kablo aksesuarı": "Günlük kullanım POV: telefonu/kabloyu yerleştirme anı, \"bunu bilmiyordum\" tadında.",
    "Hediyelik": "\"Sevgiliye/arkadaşa 3D baskı hediye\" kurgusu: baskı → paketleme → veriliş.",
}
VARSAYILAN_VIDEO = "Baskı timelapse'i + elde gösterim; açıklamaya baskı süresi ve filament miktarını yaz."


def _kisa_sayi(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} milyon"
    if n >= 1000:
        return f"{n / 1000:.1f} bin"
    return str(n)


def video_fikri(urun: dict) -> str:
    ozellikler = urun.get("features") or []
    for ozellik, fikir in VIDEO_SABLONLARI:
        if ozellik in ozellikler:
            return fikir
    return KATEGORI_SABLONLARI.get(urun.get("category"), VARSAYILAN_VIDEO)


def neden(urun: dict) -> str:
    d = urun["score_detail"]
    nedenler = []
    if d["populerlik"] >= 0.6:
        nedenler.append(f"çok popüler ({_kisa_sayi(urun['likes'])} beğeni, "
                        f"{_kisa_sayi(urun['downloads'])} indirme)")
    if d["artis"] >= 0.6:
        nedenler.append(f"ilgi hızla artıyor (günde ~{_kisa_sayi(int(d['gunluk_ilgi_artisi']))} etkileşim, "
                        f"{d['artis_tipi']})")
    if urun.get("features"):
        nedenler.append("görsel olarak ilgi çekici: " + ", ".join(urun["features"]))
    if urun.get("print_time_min") is not None and d["sure"] >= 0.85:
        nedenler.append(f"kısa baskı ({analiz.sure_yazi(urun['print_time_min'])})")
    if d.get("etsy_talep"):
        nedenler.append(f"Etsy talep listenizle eşleşiyor (\"{d['etsy_talep']}\")")
    if not nedenler:
        nedenler.append("puan bileşenlerinin dengeli toplamı yüksek")
    metin = "; ".join(nedenler)
    return metin[:1].upper() + metin[1:] + "."  # capitalize() "AMS"i "ams" yapıyordu


def sec(puanli_urunler: list[dict], adet: int = OZET_ADET) -> list[dict]:
    """Puan sırasıyla seçer; aynı kategoriden en fazla KATEGORI_BASINA_EN_FAZLA ürün."""
    secilen, sayac = [], {}
    for u in puanli_urunler:
        k = u.get("category")
        if sayac.get(k, 0) >= KATEGORI_BASINA_EN_FAZLA:
            continue
        sayac[k] = sayac.get(k, 0) + 1
        secilen.append(u)
        if len(secilen) == adet:
            break
    return [
        {"rank": i, "product_id": u["id"], "score": u["score"], "reason": neden(u),
         "video_idea": video_fikri(u), "urun": u}
        for i, u in enumerate(secilen, start=1)
    ]


def markdown(gun: date, secimler: list[dict], toplam: int, depo_adi: str) -> str:
    satirlar = [
        f"# 3D Ürün Özeti — {gun.isoformat()}",
        "",
        f"Yazıcı: {YAZICI} · İncelenen model: {toplam} · Kaynak: MakerWorld · Veritabanı: {depo_adi}",
        "",
        "Lisans işaretleri: 🟢 satılabilir · 🟡 NC / kişisel kullanım: satılamaz, içerikte gösterilebilir · "
        "🔴 kontrol et. (Bilgilendirme amaçlıdır, hukuki görüş değildir.)",
        "",
        "| # | Ürün | Puan | Baskı süresi | Lisans |",
        "|---|------|-----:|--------------|--------|",
    ]
    for s in secimler:
        u = s["urun"]
        satirlar.append(
            f"| {s['rank']} | [{u['name'].replace('|', '/')}]({u['url']}) | {s['score']} | "
            f"{analiz.sure_yazi(u.get('print_time_min'))} | {lisans.ETIKET[u['license_flag']].split(' ')[0]} |"
        )
    satirlar.append("")
    for s in secimler:
        u = s["urun"]
        satirlar += [
            f"## {s['rank']}. {u['name']} — {s['score']} puan",
            "",
        ]
        if u.get("image_url"):
            satirlar += [f"![{u['name']}]({u['image_url']})", ""]
        satirlar += [
            f"- **Link:** {u['url']}",
            f"- **Kategori:** {u.get('category') or '-'} · **Tasarımcı:** {u.get('creator') or '-'}",
            f"- **Neden seçildi:** {s['reason']}",
            f"- **Tahmini baskı süresi:** {analiz.sure_yazi(u.get('print_time_min'))}"
            + (f" · **Malzeme:** {u['material']}" if u.get("material") else ""),
            f"- **Lisans:** {u.get('license') or 'belirtilmemiş'} → {lisans.ETIKET[u['license_flag']]}"
            + (" (ayar: MakerWorld modelleri satılabilir sayılıyor)" if MAKERWORLD_HEPSI_SATILABILIR else ""),
            f"- **Video fikri:** {s['video_idea']}",
            "",
        ]
    return "\n".join(satirlar)


def rapor_yaz(klasor: Path, gun: date, icerik: str) -> Path:
    klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"{gun.isoformat()}.md"
    yol.write_text(icerik, encoding="utf-8")
    return yol
