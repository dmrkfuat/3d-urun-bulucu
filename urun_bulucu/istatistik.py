"""Instagram performansı: paylaşılan gönderilerin istatistikleri puanlamaya ve haftalık özete girer.

Günlük analizde (INSTAGRAM_TOKEN ve Supabase varsa):
1. Son IG_ISTATISTIK_GUN günde paylaşılan gönderilerin erişim, beğeni, yorum, kaydetme, paylaşım ve
   izlenme sayıları resmi Instagram API'sinden alınıp instagram_posts.insights'a yazılır.
2. Her gönderinin etkileşim oranı = (3×kaydetme + 3×paylaşım + 2×yorum + beğeni) / erişim. Kaydetme
   ve paylaşım satın alma niyetine en yakın işaret olduğundan ağır sayılır.
3. Kategorinin ortalama oranı genel ortalamanın 1,5 katıysa +4, 1,15 katıysa +2; 0,6 katının altındaysa
   −2 (o kategorideki ürünlere). Veri azsa (IG_EN_AZ_GONDERI / IG_KATEGORI_EN_AZ) bonus verilmez.
4. Haftada bir (IG_HAFTALIK_OZET_GUNU) Telegram'a özet: haftanın en iyi gönderileri ve en iyi saat.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

from . import bildirim, config

TR = timezone(timedelta(hours=3))
METRIKLER = ["reach", "likes", "comments", "saved", "shares", "views", "total_interactions"]
YEDEK_METRIKLER = ["reach", "likes", "comments", "saved", "shares"]   # bazıları desteklenmezse


def _zaman(t: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")) if t else None
    except ValueError:
        return None


def etkilesim(ins: dict | None) -> float | None:
    """Ağırlıklı etkileşim / erişim; erişim yoksa None."""
    if not ins or not ins.get("reach"):
        return None
    puan = (3 * (ins.get("saved") or 0) + 3 * (ins.get("shares") or 0)
            + 2 * (ins.get("comments") or 0) + (ins.get("likes") or 0))
    return puan / ins["reach"]


def istatistikleri_guncelle(depo, ig, simdi: datetime | None = None) -> int:
    """Güncellenmesi gereken gönderilerin istatistiklerini alır ve yazar; güncellenen sayısı.
    Instagram verileri 48 saate kadar gecikebildiği için her gönderi günde en çok bir kez sorulur."""
    simdi = simdi or datetime.now(timezone.utc)
    en_erken = (simdi - timedelta(days=config.IG_ISTATISTIK_GUN)).isoformat(timespec="seconds")
    adet = 0
    for g in depo.paylasilanlar(en_erken):
        son = _zaman(g.get("insights_at"))
        if not g.get("media_id") or (son and simdi - son < timedelta(hours=20)):
            continue
        try:
            ins = ig.istatistik(g["media_id"], METRIKLER)
        except Exception:  # noqa: BLE001 — bazı metrikler bu medya türünde yoksa daha az metrikle
            try:
                ins = ig.istatistik(g["media_id"], YEDEK_METRIKLER)
            except Exception as e:  # noqa: BLE001
                print(f"UYARI: Instagram istatistiği alınamadı (gönderi #{g['id']}): {str(e)[:150]}")
                continue
        depo.guncelle(g["id"], {"insights": ins, "insights_at": simdi.isoformat(timespec="seconds")})
        g["insights"] = ins
        adet += 1
    return adet


def _kategori(g: dict) -> str | None:
    return (g.get("products") or {}).get("category")


def kategori_bonuslari(gonderiler: list[dict]) -> dict[str, tuple[int, str]]:
    """{kategori: (bonus, açıklama)}; hikâyeler sayılmaz (24 saatlik, erişimleri farklı)."""
    oranlar = [(g, etkilesim(g.get("insights"))) for g in gonderiler if g.get("media_type") != "STORIES"]
    oranlar = [(g, o) for g, o in oranlar if o is not None]
    if len(oranlar) < config.IG_EN_AZ_GONDERI:
        return {}
    genel = statistics.mean(o for _, o in oranlar) or 0
    if genel <= 0:
        return {}
    kategoriler: dict[str, list[float]] = {}
    for g, o in oranlar:
        if _kategori(g):
            kategoriler.setdefault(_kategori(g), []).append(o)
    sonuc = {}
    for kat, liste in kategoriler.items():
        if len(liste) < config.IG_KATEGORI_EN_AZ:
            continue
        kat_oran = statistics.mean(liste) / genel
        bonus = 4 if kat_oran >= 1.5 else 2 if kat_oran >= 1.15 else -2 if kat_oran <= 0.6 else 0
        if bonus:
            sonuc[kat] = (bonus, f"Instagram'da bu kategori ortalamanın {kat_oran:.1f} katı etkileşim alıyor "
                                 f"({len(liste)} gönderi)")
    return sonuc


def en_iyi_saat(gonderiler: list[dict]) -> tuple[int, float] | None:
    """(Türkiye saatiyle 3 saatlik dilimin başı, ortalama erişim): en az 5 gönderi ve dilimde en az 2."""
    dilimler: dict[int, list[int]] = {}
    for g in gonderiler:
        t, ins = _zaman(g.get("published_at")), g.get("insights") or {}
        if t and ins.get("reach") and g.get("media_type") != "STORIES":
            dilimler.setdefault(t.astimezone(TR).hour // 3 * 3, []).append(ins["reach"])
    if sum(len(v) for v in dilimler.values()) < 5:
        return None
    adaylar = [(s, statistics.mean(v)) for s, v in dilimler.items() if len(v) >= 2]
    return max(adaylar, key=lambda x: x[1]) if adaylar else None


def haftalik_ozet(gonderiler: list[dict], bugun: date, panel_url: str | None = None) -> str | None:
    """Son 7 günün gönderileri için Telegram metni (HTML); hiç gönderi yoksa None."""
    bas = datetime.combine(bugun - timedelta(days=7), datetime.min.time(), TR)
    hafta = [g for g in gonderiler if (_zaman(g.get("published_at")) or bas) > bas and g.get("insights")]
    if not hafta:
        return None
    e_ = bildirim._e
    toplam = {k: sum((g["insights"].get(k) or 0) for g in hafta) for k in ("reach", "likes", "saved", "shares", "comments")}
    s = [f"<b>📈 Instagram haftalık özet</b> ({bugun.isoformat()})",
         f"{len(hafta)} gönderi · {toplam['reach']} erişim · {toplam['likes']} beğeni · {toplam['saved']} kaydetme · "
         f"{toplam['shares']} paylaşım · {toplam['comments']} yorum", "", "<b>En iyi gönderiler</b>"]
    sirali = sorted(hafta, key=lambda g: etkilesim(g["insights"]) or 0, reverse=True)
    for n, g in enumerate(sirali[:3], 1):
        ad = (g.get("products") or {}).get("name") or f"gönderi #{g['id']}"
        ins = g["insights"]
        isim = (f"<a href=\"{bildirim._href(g['permalink'])}\">{e_(ad[:50])}</a>" if g.get("permalink")
                else e_(ad[:50]))
        s.append(f"{n}. {isim} — {ins.get('reach', 0)} erişim, {ins.get('saved', 0)} kaydetme, "
                 f"{ins.get('shares', 0)} paylaşım")
    saat = en_iyi_saat(gonderiler)
    if saat:
        s += ["", f"⏰ En çok erişim alan saat: {saat[0]:02d}:00–{saat[0] + 3:02d}:00 (ortalama {saat[1]:.0f} erişim)"]
    bonus = kategori_bonuslari(gonderiler)
    if bonus:
        s += ["", "<b>Kategori etkisi (puanlamada)</b>"] + [
            f"{'🟢' if b > 0 else '🔴'} {e_(k)}: {b:+d}" for k, (b, _) in sorted(bonus.items(), key=lambda x: -x[1][0])]
    if panel_url:
        s += ["", f"📊 {e_(panel_url)}"]
    return "\n".join(s)


def calistir(ayarlar: config.Ayarlar, bugun: date) -> tuple[dict[str, tuple[int, str]], str | None]:
    """(kategori bonusları, haftalık özet metni veya None). Token/Supabase yoksa ({}, None)."""
    if not (ayarlar.instagram_token and ayarlar.supabase_var):
        return {}, None
    from . import instagram

    depo = instagram.SupabaseInstagramDepo(ayarlar.supabase_url, ayarlar.supabase_key)
    try:
        token = instagram.token_hazirla(depo, ayarlar.instagram_token, datetime.now(timezone.utc))
        ig = instagram.InstagramIstemci(token, hesap_id=ayarlar.instagram_hesap_id)
        adet = istatistikleri_guncelle(depo, ig)
        print(f"Instagram istatistikleri: {adet} gönderi güncellendi.")
    except Exception as e:  # noqa: BLE001 — kayıtlı istatistiklerle devam
        print(f"UYARI: Instagram istatistikleri güncellenemedi: {str(e)[:200]}")
    en_erken = (datetime.now(timezone.utc) - timedelta(days=config.IG_ISTATISTIK_GUN)).isoformat(timespec="seconds")
    gonderiler = depo.paylasilanlar(en_erken)
    ozet = haftalik_ozet(gonderiler, bugun, ayarlar.panel_url or None) if bugun.weekday() == config.IG_HAFTALIK_OZET_GUNU else None
    return kategori_bonuslari(gonderiler), ozet
