"""Gerçek satış verisi: siparişler (panel "Siparişler" sekmesi) ve "Sattım" işaretleri.

- Satılan ürün tekrar listeye gelirse SATILAN_URUN_BONUS; aynı kategoriden satış olduysa
  SATILAN_KATEGORI_BONUS (1-2 satış / 3+ satış) eklenir. Böylece sistem, MakerWorld'ün değil senin
  müşterinin ilgisine göre öneri yapmaya başlar.
- Siparişe gerçek baskı süresi / filament gramı girilirse MakerWorld tahminiyle oranlanır;
  en az KALIBRASYON_EN_AZ örnek varsa maliyet hesabı bu oranlarla düzeltilir (maliyet.DUZELTME).
"""
from __future__ import annotations

import statistics

from . import config


def satis_ozeti(siparisler: list[dict], isaretler: list[dict]) -> dict:
    """{'urun': {product_id: adet}, 'kategori': {kategori: adet}}. İptal edilen siparişler sayılmaz.
    Aynı ürün hem siparişle hem "Sattım" sayacıyla girildiyse büyük olan alınır (çift sayılmasın)."""
    urun: dict[int, int] = {}
    kategori_adi: dict[int, str] = {}
    for s in siparisler:
        if s.get("durum") == "iptal" or not s.get("product_id"):
            continue
        pid = int(s["product_id"])
        urun[pid] = urun.get(pid, 0) + int(s.get("adet") or 1)
        kat = (s.get("products") or {}).get("category")
        if kat:
            kategori_adi[pid] = kat
    for m in isaretler:
        pid, adet = m.get("product_id"), int(m.get("sold_count") or 0)
        if not pid or adet <= 0:
            continue
        urun[int(pid)] = max(urun.get(int(pid), 0), adet)
        kat = (m.get("products") or {}).get("category")
        if kat:
            kategori_adi.setdefault(int(pid), kat)
    kategori: dict[str, int] = {}
    for pid, adet in urun.items():
        if pid in kategori_adi:
            kategori[kategori_adi[pid]] = kategori.get(kategori_adi[pid], 0) + adet
    return {"urun": urun, "kategori": kategori}


def satis_bonusu(u: dict, ozet: dict | None) -> tuple[int, str | None]:
    if not ozet:
        return 0, None
    adet = ozet["urun"].get(u.get("id"), 0)
    if adet:
        return config.SATILAN_URUN_BONUS, f"Bu ürünü {adet} adet sattın"
    kat_adet = ozet["kategori"].get(u.get("category") or "", 0)
    if kat_adet:
        az, cok = config.SATILAN_KATEGORI_BONUS
        return (cok if kat_adet >= 3 else az), f"Bu kategoride {kat_adet} satışın var"
    return 0, None


def kalibrasyon(siparisler: list[dict]) -> dict | None:
    """Gerçek / tahmini oranlarının ortancası: {'sure', 'gram', 'ornek'}. Örnek yetersizse o alan 1.0;
    ikisi de yetersizse None. Oranlar KALIBRASYON_SINIR içinde tutulur."""
    sure, gram = [], []
    for s in siparisler:
        if s.get("durum") == "iptal":
            continue
        p = s.get("products") or {}
        adet = max(1, int(s.get("adet") or 1))
        if s.get("gercek_sure_dk") and p.get("print_time_min"):
            sure.append(s["gercek_sure_dk"] / (p["print_time_min"] * adet))
        if s.get("gercek_gram") and p.get("weight_g"):
            gram.append(s["gercek_gram"] / (p["weight_g"] * adet))
    alt, ust = config.KALIBRASYON_SINIR

    def oran(liste: list[float]) -> float:
        if len(liste) < config.KALIBRASYON_EN_AZ:
            return 1.0
        return round(min(ust, max(alt, statistics.median(liste))), 3)

    sonuc = {"sure": oran(sure), "gram": oran(gram), "ornek": max(len(sure), len(gram))}
    return None if sonuc["sure"] == 1.0 and sonuc["gram"] == 1.0 else sonuc


def yazi(k: dict | None) -> str:
    if not k:
        return "Maliyet düzeltmesi yok (gerçek süre/gram girilmiş en az %d sipariş gerekir)" % config.KALIBRASYON_EN_AZ
    return (f"Maliyet düzeltmesi: süre ×{k['sure']:.2f}, filament ×{k['gram']:.2f} "
            f"({k['ornek']} siparişin gerçek değerlerinden)")
