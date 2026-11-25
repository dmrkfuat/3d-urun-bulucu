"""Görsel doğrulama: e-ticaret ilanının fotoğrafı MakerWorld modeliyle AYNI ürünü mü gösteriyor?

Kelime kuralı (pazar.ayni_urun_mu) başlığa bakar; başlığı eksik ama fotoğrafı birebir aynı olan ilanları
kaçırır ("Örgü Dokulu Yılbaşı Geyik Figürü" başlıklı Noel Baba gibi), aynı kelimeleri taşıyan farklı
tasarımları da ayıramaz. Burada MakerWorld kapak görseli ile adayların küçük görselleri tek istekte
Claude'a gösterilir (resmi Anthropic API, ANTHROPIC_API_KEY); her aday için "aynı / farklı / belirsiz"
kararı JSON olarak döner. Karar verilemezse (anahtar yok, görsel inmedi, hata) kelime kuralı geçerli kalır.

Görseller bu program tarafından indirilip gönderilir (base64): inmeyen aday atlanır, istek bozulmaz.
Maliyet: ürün başına tek istek (referans + en çok GORSEL_EN_FAZLA_ADAY küçük görsel); kullanılan token ve
tahmini ücret her çalışmada yazdırılır. Bir çalışmada en çok GORSEL_CALISMA_SINIRI ürün kontrol edilir.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from . import config

KABUL_EDILEN = {"image/jpeg", "image/png", "image/gif", "image/webp"}
EN_BUYUK_BAYT = 3_700_000      # base64 sonrası API'nin görsel başına 5 MB sınırının altında kalsın
SONUC_SEMASI = {
    "type": "object",
    "properties": {
        "sonuclar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "karar": {"type": "string", "enum": ["ayni", "farkli", "belirsiz"]},
                    "neden": {"type": "string"},
                },
                "required": ["no", "karar", "neden"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sonuclar"],
    "additionalProperties": False,
}
TALIMAT = """Sen bir 3D baskı ürün karşılaştırıcısısın. İlk görsel (REFERANS) MakerWorld'deki bir 3D modelin \
kapak görselidir: "{ad}". Sonraki numaralı görseller Türk e-ticaret sitelerindeki ilanların küçük görselleridir.

Her aday için yalnızca görsele bakarak karar ver:
- "ayni": aynı 3D modelin (aynı tasarımın) baskısı. Renk, filament, fotoğraf açısı, arka plan, ölçek veya \
set adedi farklı olabilir; şekil ve tasarım ayrıntıları aynı olmalı.
- "farkli": başka bir tasarım. Aynı kategori, aynı tema ya da aynı karakter olması yetmez (ör. başka bir \
geyik figürü, başka bir Grinch modeli, başka bir fidget oyuncağı "farkli"dır).
- "belirsiz": görsel çok küçük, bulanık ya da ürün seçilemiyor.
İlan başlığı yalnızca bağlam içindir; başlık ile görsel çelişirse görsele güven. Emin değilsen "ayni" deme.
Her aday için tek satırlık Türkçe "neden" yaz."""


class GorselHatasi(RuntimeError):
    pass


def indir(url: str | None, client: httpx.Client) -> dict | None:
    """Görseli indirir → API görsel bloğu (base64); uygun değilse None."""
    if not url or not url.startswith("https://"):
        return None
    try:
        yanit = client.get(url, headers={"User-Agent": config.TRENDYOL_UA}, follow_redirects=True)
    except httpx.HTTPError:
        return None
    tur = (yanit.headers.get("content-type") or "").split(";")[0].strip().lower()
    if yanit.status_code != 200 or tur not in KABUL_EDILEN or not yanit.content or len(yanit.content) > EN_BUYUK_BAYT:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": tur,
                                        "data": base64.standard_b64encode(yanit.content).decode("ascii")}}


def kucuk_adres(url: str | None) -> str | None:
    """MakerWorld görsel sunucusu (Aliyun OSS) küçültme parametresini destekler: 4 MB'lık PNG kapak
    ~1024 px genişlikte birkaç on KB olur (API sınırı aşılmaz, yükleme küçülür)."""
    if url and urlsplit(url).hostname == "makerworld.bblmw.com" and "?" not in url:
        return url + "?x-oss-process=image/resize,w_1024"
    return url


def _icerik(ad: str, referans: dict, adaylar: list[tuple[int, str, dict]]) -> list[dict]:
    icerik: list[dict] = [{"type": "text", "text": "REFERANS (MakerWorld modeli):"}, referans]
    for no, baslik, blok in adaylar:
        icerik += [{"type": "text", "text": f"Aday {no} — ilan başlığı: {baslik[:120]}"}, blok]
    icerik.append({"type": "text", "text": TALIMAT.format(ad=ad[:120])})
    return icerik


@dataclass
class Dogrulayici:
    """Bir çalışma boyunca görsel doğrulama: istemciler, ürün sınırı ve harcama toplamı."""
    api_key: str
    sinir: int = config.GORSEL_CALISMA_SINIRI
    istemci: object | None = None            # testlerde sahte istemci verilir
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=30))
    kontrol_edilen: int = 0
    girdi_token: int = 0
    cikti_token: int = 0

    def _claude(self):
        if self.istemci is None:
            import anthropic   # yalnızca görsel doğrulama açıkken yüklenir

            self.istemci = anthropic.Anthropic(api_key=self.api_key)
        return self.istemci

    @property
    def hakki_var(self) -> bool:
        return self.kontrol_edilen < self.sinir

    def maliyet_usd(self) -> float:
        return (self.girdi_token * config.GORSEL_GIRDI_USD_M + self.cikti_token * config.GORSEL_CIKTI_USD_M) / 1e6

    def karsilastir(self, ad: str, referans_url: str, adaylar: list[tuple[str, str]]) -> dict[int, tuple[str, str]]:
        """adaylar: [(başlık, görsel adresi)] → {aday sırası (0'dan): (karar, neden)}. Görseli inmeyen aday
        sonuçta yer almaz. Referans inmezse veya API hata verirse GorselHatasi."""
        referans = indir(kucuk_adres(referans_url), self.http) or indir(referans_url, self.http)
        if referans is None:
            raise GorselHatasi("MakerWorld görseli indirilemedi")
        bloklar = []
        for i, (baslik, url) in enumerate(adaylar[: config.GORSEL_EN_FAZLA_ADAY]):
            blok = indir(url, self.http)
            if blok:
                bloklar.append((i, baslik or "", blok))
        if not bloklar:
            return {}
        self.kontrol_edilen += 1
        numara = {n: i for n, (i, _, _) in enumerate(bloklar, start=1)}   # istekteki no → aday sırası
        import anthropic

        try:
            yanit = self._claude().beta.messages.create(
                model=config.GORSEL_MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",   # güvenlik sınıflandırıcısı reddederse sunucu başka modelle dener
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SONUC_SEMASI}},
                messages=[{"role": "user", "content": _icerik(
                    ad, referans, [(n, b, k) for n, (_, b, k) in enumerate(bloklar, start=1)])}],
            )
        except anthropic.APIError as e:
            # Hesap sorunu (anahtar geçersiz/yetkisiz, kredi bitti): o çalışmada başka ürün denenmez.
            hesap = (isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError))
                     or "credit balance" in str(e).lower())
            if hesap:
                self.sinir = 0
            raise GorselHatasi(("Anthropic hesabı kullanılamıyor (anahtar veya kredi); bu çalışmada görsel "
                                "doğrulama kapatıldı. " if hesap else "") + f"Claude API: {str(e)[:300]}") from e
        kullanim = getattr(yanit, "usage", None)
        self.girdi_token += int(getattr(kullanim, "input_tokens", 0) or 0)
        self.cikti_token += int(getattr(kullanim, "output_tokens", 0) or 0)
        if yanit.stop_reason == "refusal":
            raise GorselHatasi("Claude isteği reddetti")
        metin = next((b.text for b in yanit.content if getattr(b, "type", None) == "text"), "")
        try:
            veri = json.loads(metin)
        except ValueError as e:
            raise GorselHatasi("Claude yanıtı JSON değil") from e
        sonuc: dict[int, tuple[str, str]] = {}
        for s in veri.get("sonuclar") or []:
            if s.get("no") in numara and s.get("karar") in ("ayni", "farkli", "belirsiz"):
                sonuc[numara[s["no"]]] = (s["karar"], str(s.get("neden") or "")[:200])
        return sonuc
