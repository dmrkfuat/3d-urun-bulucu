"""Testler için UYDURMA örnek veriler (gerçek modeller değildir)."""
from __future__ import annotations


def urun(id_, ad, begeni, indirme, kategori="Fidget ve oyuncak", **ek):
    u = {
        "id": id_, "source_id": "makerworld", "external_id": str(id_), "name": ad,
        "url": f"https://makerworld.com/en/models/{id_}", "category": kategori, "creator": "x",
        "downloads": indirme, "likes": begeni, "makes": 0, "views": 0,
        "published_at": "2026-10-01T00:00:00+00:00", "license": "Creative Commons - Attribution",
        "license_flag": "ticari_serbest", "print_time_min": None, "material": None,
        "image_url": None, "tags": [], "features": [],
    }
    u.update(ek)
    return u


def mw_tasarim(id_, ad, begeni, indirme, lisans="Standard Digital File License", profiller=None,
               aciklama="<p>Print in place.</p>", olusturma="2026-10-20T10:00:00Z"):
    """MakerWorld /design-service/design/{id} yanıtının sadeleştirilmiş taklidi."""
    profiller = profiller if profiller is not None else [{"id": 1, "yazici": "P1S", "sure_sn": 5400}]
    instances = []
    for p in profiller:
        renk = p.get("renk", 1)
        instances.append({
            "id": p["id"],
            "isDefault": p["id"] == profiller[0]["id"],
            "prediction": p.get("sure_sn", 3600),
            "weight": 20,
            "materialCnt": renk,
            "materialColorCnt": renk,
            "needAms": p.get("ams", renk > 1),
            "instanceFilaments": [{"type": t} for t in p.get("filament", ["PLA"])],
            "extention": {"modelInfo": {"compatibility": {"devProductName": p.get("yazici", "P1S")}}},
        })
    return {
        "id": id_,
        "title": ad,
        "summary": aciklama,
        "tags": ["test"],
        "license": lisans,
        "likeCount": begeni,
        "downloadCount": indirme,
        "printCount": begeni // 3,
        "readCount": 0,
        "createTime": olusturma,
        "coverUrl": f"https://cdn.example/mw{id_}.png",
        "designCreator": {"name": f"mw_tasarimci{id_}"},
        "nsfw": False,
        "isPrintable": True,
        "paidSetting": {"isPaid": False},
        "defaultInstanceId": profiller[0]["id"] if profiller else None,
        "instances": instances,
    }
