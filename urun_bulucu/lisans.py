"""Lisans metnini içerik/satış açısından sınıflandırır.

Bu sınıflandırma bilgilendirme amaçlıdır, hukuki görüş değildir.
"""
from __future__ import annotations

import re

TICARI_SERBEST = "ticari_serbest"
NC_SADECE_ICERIK = "nc_sadece_icerik"
KONTROL_ET = "kontrol_et"

ETIKET = {
    TICARI_SERBEST: "🟢 Satılabilir (atıf gerekebilir)",
    NC_SADECE_ICERIK: "🟡 Satılamaz (NC / kişisel kullanım) — içerikte gösterilebilir",
    KONTROL_ET: "🔴 Kontrol et — lisans belirsiz",
}

_NC = re.compile(r"non[\s-]?commercial|\bnc\b", re.I)
# MakerWorld'ün kendi lisansları: dosya ve baskı satışı yasak (Standard Digital File License
# metni: "shall not ... sell ... the digital or 3D printed versions"). Exclusive modellerin
# baskısını satmak için tasarımcıdan ücretli ticari lisans gerekir.
_KISISEL = re.compile(r"standard digital file license|makerworld exclusive", re.I)
_SERBEST = re.compile(
    r"creative commons|\bcc[\s-]?(by|0)\b|public domain|\bgnu\b|\bgpl\b|\blgpl\b|\bbsd\b"
    r"|\bmit\b|cern|open hardware|apache",
    re.I,
)
# MakerWorld CC lisanslarını kısaltma olarak yazar: "BY", "BY-SA", "BY-ND", "CC0".
_CC_KISA = re.compile(r"^(?:cc[\s-]?)?(?:by(?:[\s-](?:sa|nd))?|0)(?:\s*\d\.\d)?$", re.I)


def siniflandir(lisans: str | None) -> str:
    metin = (lisans or "").strip()
    if not metin:
        return KONTROL_ET
    if _NC.search(metin) or _KISISEL.search(metin):
        return NC_SADECE_ICERIK
    if _SERBEST.search(metin) or _CC_KISA.match(metin):
        return TICARI_SERBEST
    return KONTROL_ET
