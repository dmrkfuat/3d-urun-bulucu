"""Tasarımcı takibi.

1) Günlük ilk 10'a giren her modelin tasarımcısı için "kaç farklı gün ilk 10'a girdi" sayılır.
   TAKIP_ESIGI güne ulaşan tasarımcı otomatik takibe alınır (panelden kapatılabilir; bir kez
   kapatılan tekrar otomatik açılmaz).
2) Takip edilen tasarımcıların son modellerine bakılır; daha önce bildirilmemiş yeni modeller
   Telegram'da "yeni model" olarak bildirilir. İlk kontrolde geçmiş modeller bildirilmez.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .kaynaklar.makerworld import KAYNAK_ID, SITE, MakerWorldKaynak

TAKIP_ESIGI = 2          # bu kadar farklı gün ilk 10'a giren tasarımcı otomatik takip edilir
GUNLUK_KONTROL = 10      # her gün en fazla kaç takip edilen tasarımcıya bakılsın
YENI_MODEL_ARAMA = 5     # her tasarımcının son kaç modeline bakılsın


def isabetleri_isle(depo, gun: date, secimler: list[dict]) -> list[str]:
    """İlk 10'daki tasarımcıların gün sayısını artırır. Yeni otomatik takip edilenlerin adlarını döndürür."""
    tasarimcilar: dict[int, dict] = {}
    for s in secimler:
        u = s["urun"]
        if u.get("source_id") == KAYNAK_ID and u.get("creator_uid"):
            tasarimcilar.setdefault(int(u["creator_uid"]), u)
    if not tasarimcilar:
        return []
    mevcut = depo.tasarimcilar(KAYNAK_ID, list(tasarimcilar))
    gun_yazi = gun.isoformat()
    satirlar, yeni_takip = [], []
    for uid, u in tasarimcilar.items():
        t = dict(mevcut.get(uid) or {"source_id": KAYNAK_ID, "uid": uid, "hit_days": 0,
                                     "followed": False, "auto_followed": False})
        t["name"] = u.get("creator") or t.get("name")
        t["handle"] = u.get("creator_handle") or t.get("handle")
        if str(t.get("last_hit_date") or "")[:10] != gun_yazi:
            t["hit_days"] = int(t.get("hit_days") or 0) + 1
            t["last_hit_date"] = gun_yazi
        if t["hit_days"] >= TAKIP_ESIGI and not t.get("followed") and not t.get("auto_followed"):
            t["followed"] = True
            t["auto_followed"] = True
            yeni_takip.append(t["name"] or str(uid))
        satirlar.append(t)
    depo.tasarimcilari_kaydet(satirlar)
    return yeni_takip


def yeni_modelleri_bul(depo, kaynak: MakerWorldKaynak) -> list[dict]:
    """Takip edilen tasarımcıların bildirilmemiş yeni modelleri: [{tasarimci, ad, url, kapak}]"""
    bulunan: list[dict] = []
    satirlar = []
    for t in depo.takip_edilenler(GUNLUK_KONTROL):
        modeller = kaynak.tasarimci_modelleri(t["uid"], YENI_MODEL_ARAMA)
        en_yeni = max((int(m["id"]) for m in modeller), default=None)
        onceki = t.get("last_design_id")
        if onceki is not None:
            for m in modeller:
                if int(m["id"]) > int(onceki):
                    bulunan.append({"tasarimci": t.get("name") or t.get("handle") or str(t["uid"]),
                                    "ad": (m.get("title") or "").strip(), "url": f"{SITE}/{m['id']}",
                                    "kapak": m.get("coverUrl") or m.get("cover")})
        t = dict(t)
        t["last_design_id"] = max(int(onceki or 0), en_yeni or 0) or None
        t["last_checked"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        satirlar.append(t)
    depo.tasarimcilari_kaydet(satirlar)
    return bulunan
