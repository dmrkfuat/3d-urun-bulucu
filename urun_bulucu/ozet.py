"""Özet: en iyi ürünleri seçer, neden seçildiğini ve video fikrini yazar."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import analiz, instagram, lisans, maliyet, pazar, sezon, video
from .config import KATEGORI_BASINA_EN_FAZLA, MAKERWORLD_HEPSI_SATILABILIR, OZET_ADET, YAZICI


def _kisa_sayi(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} milyon"
    if n >= 1000:
        return f"{n / 1000:.1f} bin"
    return str(n)


def video_fikri(urun: dict) -> str:
    return video.metin(video.fikir(urun))


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
    if urun.get("trend_rank"):
        nedenler.append(f"MakerWorld trend listesinde #{urun['trend_rank']}")
    if d.get("sezon"):
        nedenler.append(f"sezon ürünü ({d['sezon']})")
    if d.get("piyasa") and (d.get("piyasa_bonusu") or 0) > 0:
        nedenler.append(d["piyasa"])
    if (urun.get("hourly_profit_tl") or 0) >= 50:
        nedenler.append(f"saat başına ~{urun['hourly_profit_tl']:.0f} TL kazanç")
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
         "video_idea": video_fikri(u), "instagram_caption": instagram.gonderi_metni(u), "urun": u}
        for i, u in enumerate(secilen, start=1)
    ]


def markdown(gun: date, secimler: list[dict], toplam: int, depo_adi: str,
             pazar_sonuclari: dict[int, dict] | None = None) -> str:
    pazar_sonuclari = pazar_sonuclari or {}
    satirlar = [
        f"# 3D Ürün Özeti — {gun.isoformat()}",
        "",
        f"Yazıcı: {YAZICI} · İncelenen model: {toplam} · Kaynak: MakerWorld · Veritabanı: {depo_adi}",
        "",
    ]
    aktif = sezon.aktif_sezonlar(gun)
    if aktif:
        satirlar += ["**Yaklaşan sezon:** " + " · ".join(sezon.yazi(s, k) for s, k in aktif)
                     + f" (temaya uyan modeller +{sezon.SEZON_BONUS} puan)", ""]
    satirlar += [
        "Lisans işaretleri: 🟢 satılabilir · 🟡 NC / kişisel kullanım: satılamaz, içerikte gösterilebilir · "
        "🔴 kontrol et. (Bilgilendirme amaçlıdır, hukuki görüş değildir.)",
        "",
        "Maliyet ve fiyat kaba tahmindir (config.py: filament TL/kg, saat maliyeti, fiyat çarpanı).",
        "",
        "| # | Ürün | Puan | Baskı süresi | Maliyet → Fiyat | Lisans |",
        "|---|------|-----:|--------------|-----------------|--------|",
    ]
    for s in secimler:
        u = s["urun"]
        fiyat = (f"~{u['cost_tl']:.0f} → {u['price_tl']:.0f} TL" if u.get("cost_tl") is not None else "-")
        satirlar.append(
            f"| {s['rank']} | [{u['name'].replace('|', '/')}]({u['url']}) | {s['score']} | "
            f"{analiz.sure_yazi(u.get('print_time_min'))} | {fiyat} | "
            f"{lisans.ETIKET[u['license_flag']].split(' ')[0]} |"
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
            f"- **Maliyet:** {maliyet.yazi(u)}",
            *([f"- **Türkiye'de satışta:** {pazar.fiyat_yazi(pazar_sonuclari[s['product_id']], u.get('price_tl'))}"]
              + [f"  - {r['site']}: [{(r.get('title') or 'ürün')[:60].replace(']', ')')}]({pazar.satis_linki(r) or '#'})"
                 + (f" — {r['price']:.0f} TL" if r.get("price") is not None else "")
                 + (" (bağımsız mağaza)" if r.get("pazar_yeri") is False else "")
                 + (" (görsel eşleşme)" if r.get("kaynak") == "görsel" else "")
                 for r in [x for x in pazar_sonuclari[s["product_id"]]["results"]
                           if x.get("kaynak") != "sosyal"][:6]]
              if s["product_id"] in pazar_sonuclari else []),
            *([f"- **{pazar.sosyal_yazi(pazar_sonuclari[s['product_id']])}**"]
              + [f"  - {r['site']}: [{(r.get('title') or 'gönderi')[:60]}]({r['link']}){pazar.sosyal_etiket(r)}"
                 for r in pazar.sosyal_yerler(pazar_sonuclari[s["product_id"]], en_fazla=4)]
              if pazar.sosyal_yazi(pazar_sonuclari.get(s["product_id"])) else []),
            f"- **Lisans:** {u.get('license') or 'belirtilmemiş'} → {lisans.ETIKET[u['license_flag']]}"
            + (" (ayar: MakerWorld modelleri satılabilir sayılıyor)" if MAKERWORLD_HEPSI_SATILABILIR else ""),
            "- **Video fikri:**",
            *[f"  - {satir}" for satir in s["video_idea"].splitlines()],
            "",
        ]
    return "\n".join(satirlar)


def rapor_yaz(klasor: Path, gun: date, icerik: str) -> Path:
    klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"{gun.isoformat()}.md"
    yol.write_text(icerik, encoding="utf-8")
    return yol
