"""Modele özel kısa video (Reels/TikTok/Shorts) fikri.

Ürünün kendi verisinden üretilir: baskı süresi, filament gramı, renk sayısı, görsel
özellikler, kategori, trend durumu ve MakerWorld etiketleri. Ücretsizdir (yapay zekâ
servisi kullanılmaz); kurallar aşağıdaki fonksiyonlardadır.
"""
from __future__ import annotations

import re

from . import analiz

HAREKETLI = "hareketli parça"
AMS = "çok renkli (AMS)"
SATISFYING = "satisfying"
ISIK = "ışık/şeffaf efekt"

TEMEL_ETIKETLER = ["#3dbaskı", "#3dprinting", "#bambulab", "#p1s"]
OZELLIK_ETIKETLERI = {
    HAREKETLI: "#printinplace",
    AMS: "#multicolor",
    SATISFYING: "#satisfying",
    ISIK: "#lamp",
}
KAPANIS = {
    "Fidget ve oyuncak": "Elde oynatırken bitir; son kare ilk kareye bağlansın (loop).",
    "Eklemli figür": "Figürü elde kıvrılarak hareket ettir; loop olacak şekilde bitir.",
    "Masa ve ofis düzenleyici": "Dağınık masa → düzenli masa geçişiyle bitir (öncesi/sonrası).",
    "Ev dekorasyonu ve saksı": "Bitkiyi/ürünü yerine koyduğun sakin bir son sahne.",
    "Hediyelik": "Paketle ve \"kime hediye edersin?\" yazısıyla bitir (yorum getirir).",
    "Telefon ve kablo aksesuarı": "Günlük kullanım POV: telefonu/kabloyu yerleştirme anı.",
    "Trend / sezonluk": "Sezona uygun ortamda göster (ör. yılbaşı süsleri arasında).",
}
VARSAYILAN_KAPANIS = "Ürünü elde 360° çevirerek bitir."


def _baskili_mi(urun: dict, kelime: str) -> bool:
    metin = " ".join([urun.get("name") or "", *(urun.get("tags") or [])]).lower()
    return kelime in metin


def kancalar(urun: dict) -> list[str]:
    """Videonun ilk 1-2 saniyesinde ekrana yazılacak cümleler, en güçlüsü önce."""
    ozellik = set(urun.get("features") or [])
    dakika = urun.get("print_time_min")
    renk = urun.get("color_count") or 0
    sonuc = []
    if HAREKETLI in ozellik and (_baskili_mi(urun, "print in place") or _baskili_mi(urun, "print-in-place")):
        sonuc.append("Tek parça basıldı, hiç montaj yok 🤯")
    if dakika and dakika <= 60:
        sonuc.append(f"Sadece {dakika} dakikada bastım ⏱️")
    if renk >= 2:
        sonuc.append(f"{renk} renk, tek baskı 🎨")
    if HAREKETLI in ozellik and not sonuc:
        sonuc.append("Bu parçalar baskıdan hareketli çıkıyor 🤯")
    if SATISFYING in ozellik:
        sonuc.append("Bunu elinden bırakamayacaksın 🌀")
    if ISIK in ozellik:
        sonuc.append("Işığı açınca bak 💡")
    sezon_notu = (urun.get("score_detail") or {}).get("sezon")
    if sezon_notu:
        sonuc.append(f"{sezon_notu}, şimdiden hazırla")
    if urun.get("trend_rank"):
        sonuc.append("Şu an MakerWorld'de trend olan model 🔥")
    if urun.get("category") == "Hediyelik":
        sonuc.append("Hediye derdine 3D baskı çözüm 🎁")
    if urun.get("price_tl") and urun.get("cost_tl"):
        sonuc.append(f"Maliyeti {urun['cost_tl']:.0f} TL, bakın ne çıktı")
    if not sonuc:
        sonuc.append("3D yazıcıda böyle basılıyor 👀")
    return sonuc


def cekim_plani(urun: dict) -> list[str]:
    ozellik = set(urun.get("features") or [])
    dakika = urun.get("print_time_min")
    renk = urun.get("color_count") or 0

    if HAREKETLI in ozellik or SATISFYING in ozellik:
        acilis = "Sonucu önce göster: ürünü elde oynatırken başla (0-2 sn)."
    elif renk >= 2:
        acilis = "AMS'in renk değiştirdiği an veya renkli katmanlar yakın çekim (0-2 sn)."
    elif ISIK in ozellik:
        acilis = "Karanlık oda, ışık kapalı; tek hareketle aç (0-2 sn)."
    else:
        acilis = "Bitmiş ürün yakın çekim, yavaş kaydırma (0-2 sn)."

    if dakika and dakika > 6 * 60:
        orta = f"Uzun baskı ({analiz.sure_yazi(dakika)}): yalnızca 4-5 sn'lik hızlı timelapse."
    elif dakika:
        orta = f"{analiz.sure_yazi(dakika)} süren baskının timelapse'i (P1S kamerası veya sabit telefon)."
    else:
        orta = "Baskının timelapse'i (P1S kamerası veya sabit telefon)."
    if renk >= 2:
        orta += " Renk geçişlerini kesmeden göster."

    sezon_notu = (urun.get("score_detail") or {}).get("sezon")
    if sezon_notu:
        kapanis = f"Sezona uygun ortamda göster ({sezon_notu.split(':')[0]} süsleri/hediye paketi arasında)."
    else:
        kapanis = KAPANIS.get(urun.get("category"), VARSAYILAN_KAPANIS)
    return [acilis, orta, kapanis]


def sure_onerisi(urun: dict) -> str:
    ozellik = set(urun.get("features") or [])
    if ozellik & {HAREKETLI, SATISFYING}:
        return "7-12 sn (loop)"
    return "15-20 sn"


def aciklama(urun: dict) -> str:
    parcalar = [urun.get("name") or "Model"]
    if urun.get("print_time_min"):
        parcalar.append(f"{analiz.sure_yazi(urun['print_time_min']).lstrip('~')} baskı")
    if urun.get("weight_g"):
        parcalar.append(f"{urun['weight_g']} g filament")
    parcalar.append("Bambu Lab P1S")
    tasarimci = urun.get("creator")
    metin = " · ".join(parcalar)
    if tasarimci:
        metin += f" | Tasarım: {tasarimci} (MakerWorld)"
    return metin


def _etiket(ham: str) -> str | None:
    temiz = re.sub(r"[^0-9a-zçğıöşü]", "", ham.lower())
    return f"#{temiz}" if 3 <= len(temiz) <= 25 else None


def etiketler(urun: dict, en_fazla: int = 8) -> list[str]:
    sonuc = list(TEMEL_ETIKETLER)
    for ozellik in urun.get("features") or []:
        e = OZELLIK_ETIKETLERI.get(ozellik)
        if e and e not in sonuc:
            sonuc.append(e)
    for ham in urun.get("tags") or []:
        e = _etiket(str(ham))
        if e and e not in sonuc:
            sonuc.append(e)
        if len(sonuc) >= en_fazla:
            break
    return sonuc[:en_fazla]


def fikir(urun: dict) -> dict:
    return {
        "kanca": kancalar(urun)[0],
        "alternatif_kanca": (kancalar(urun)[1:2] or [None])[0],
        "sure": sure_onerisi(urun),
        "plan": cekim_plani(urun),
        "aciklama": aciklama(urun),
        "etiketler": etiketler(urun),
    }


def metin(f: dict) -> str:
    """Veritabanına (weekly_picks.video_idea) ve rapora yazılan çok satırlı hâli."""
    satirlar = [f"Kanca: \"{f['kanca']}\"" + (f" (alternatif: \"{f['alternatif_kanca']}\")"
                                               if f.get("alternatif_kanca") else "")]
    satirlar.append(f"Süre: {f['sure']}")
    satirlar += [f"{i}) {adim}" for i, adim in enumerate(f["plan"], start=1)]
    satirlar.append(f"Açıklama: {f['aciklama']}")
    satirlar.append("Etiketler: " + " ".join(f["etiketler"]))
    return "\n".join(satirlar)
