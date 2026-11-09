"""Testler için UYDURMA örnek veriler (gerçek modeller değildir)."""
from __future__ import annotations


def thing(id_, ad, begeni, indirme, lisans="Creative Commons - Attribution", aciklama="", eklendi="2026-10-01T10:00:00+00:00"):
    return {
        "id": id_,
        "name": ad,
        "public_url": f"https://www.thingiverse.com/thing:{id_}",
        "creator": {"name": f"tasarimci{id_}"},
        "like_count": begeni,
        "download_count": indirme,
        "make_count": begeni // 20,
        "view_count": indirme * 5,
        "added": eklendi,
        "license": lisans,
        "description": aciklama,
        "instructions": "",
        "details": "",
        "tags": [{"name": "test"}],
        "default_image": {"url": f"https://cdn.example/{id_}.jpg",
                          "sizes": [{"type": "display", "size": "large", "url": f"https://cdn.example/{id_}_large.jpg"}]},
        "is_nsfw": False,
    }


def urun(id_, ad, begeni, indirme, kategori="Fidget ve oyuncak", **ek):
    u = {
        "id": id_, "source_id": "thingiverse", "external_id": str(id_), "name": ad,
        "url": f"https://www.thingiverse.com/thing:{id_}", "category": kategori, "creator": "x",
        "downloads": indirme, "likes": begeni, "makes": 0, "views": 0,
        "published_at": "2026-10-01T00:00:00+00:00", "license": "Creative Commons - Attribution",
        "license_flag": "ticari_serbest", "print_time_min": None, "material": None,
        "image_url": None, "tags": [], "features": [],
    }
    u.update(ek)
    return u
