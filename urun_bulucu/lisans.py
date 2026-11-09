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
    NC_SADECE_ICERIK: "🟡 Satılamaz (NC) — içerikte gösterilebilir",
    KONTROL_ET: "🔴 Kontrol et — lisans belirsiz",
}

_NC = re.compile(r"non[\s-]?commercial|\bnc\b", re.I)
_SERBEST = re.compile(
    r"creative commons|\bcc[\s-]?(by|0)\b|public domain|\bgnu\b|\bgpl\b|\blgpl\b|\bbsd\b"
    r"|\bmit\b|cern|open hardware|apache",
    re.I,
)


def siniflandir(lisans: str | None) -> str:
    metin = (lisans or "").strip()
    if not metin:
        return KONTROL_ET
    if _NC.search(metin):
        return NC_SADECE_ICERIK
    if _SERBEST.search(metin):
        return TICARI_SERBEST
    return KONTROL_ET
