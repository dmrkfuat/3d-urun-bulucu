"""Instagram: gönderi açıklaması (Türkçe metin + etiketler) ve zamanlanmış Reels paylaşımı.

Yalnızca resmi Instagram API'si (Instagram Login ile) kullanılır; şifreyle giriş, tarayıcı
otomasyonu veya resmi olmayan kütüphane yoktur.

Akış:
1. Günlük analiz ilk 10 ürünün her biri için açıklama metni üretir (weekly_picks.instagram_caption);
   Telegram'a ve panele gelir. Bunun için anahtar gerekmez.
2. Sen ürünü basıp videosunu çekersin; panelden videoyu yükleyip saat seçersin
   (Supabase Storage 'instagram' alanı + instagram_posts tablosu).
3. GitHub Actions 15 dakikada bir `python -m urun_bulucu.instagram` çalıştırır: saati gelen video
   için Reels oluşturulur, Instagram videoyu işleyince yayınlanır, ürüne "video" işareti konur ve
   Telegram'a bağlantı gönderilir.

Token (INSTAGRAM_TOKEN, 60 gün geçerli) haftada bir otomatik yenilenir; yenisi Supabase'teki
kapalı gizli_ayarlar tablosunda tutulur (panel ve dışarısı göremez).
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import httpx

from . import analiz, bildirim, config, pazar, video

# --------------------------------------------------------------------------- açıklama metni
TEMEL_ETIKETLER = ["#3dbaskı", "#3dyazıcı", "#3dprinting", "#bambulab", "#elyapımı"]
KATEGORI_ETIKETLERI = {
    "Fidget ve oyuncak": ["#fidget", "#stresoyuncağı", "#oyuncak"],
    "Eklemli figür": ["#figür", "#eklemlifigür", "#koleksiyon"],
    "Masa ve ofis düzenleyici": ["#masadüzeni", "#ofisdekorasyonu", "#düzenleyici"],
    "Ev dekorasyonu ve saksı": ["#evdekorasyonu", "#dekorasyon", "#saksı"],
    "Hediyelik": ["#hediye", "#hediyelik", "#kişiyeözel"],
    "Telefon ve kablo aksesuarı": ["#telefontutucu", "#masaüstü", "#aksesuar"],
}
# Tek başına anlamsız/çok genel MakerWorld etiketleri.
ETIKET_GURULTU = {"mini", "little", "small", "tiny", "cute", "new", "test", "holiday", "3d", "print",
                  "3d print", "3d printing", "papa noel", "santa claus", "micro", "bad", "good",
                  "collection", "model", "design", "toy"}
KATEGORI_CUMLESI = {
    "Fidget ve oyuncak": "🌀 Elinden bırakamayacağın bir stres oyuncağı.",
    "Eklemli figür": "🦎 Her parçası hareketli, masanın yeni maskotu.",
    "Masa ve ofis düzenleyici": "🗂️ Masanı toparlamanın en şık yolu.",
    "Ev dekorasyonu ve saksı": "🏡 Evine küçük ama fark edilen bir dokunuş.",
    "Hediyelik": "🎁 Sevdiklerine farklı bir hediye.",
    "Telefon ve kablo aksesuarı": "📱 Günlük kullanımda hep elinin altında.",
}


def _bas_harf(metin: str) -> str:
    """Türkçe büyük harf: 'imkansız vida' → 'İmkansız vida' (str.capitalize 'I' yapar)."""
    if not metin:
        return metin
    ilk = {"i": "İ", "ı": "I"}.get(metin[0], metin[0].upper())
    return ilk + metin[1:]


def baslik(urun: dict) -> str:
    """Türkçe ürün adı + ürün tipi (e-ticaret aramasıyla aynı sözlük, ör. 'Grinch mini figür');
    çevrilemezse modelin kendi adı."""
    ad = (urun.get("name") or "").strip()
    tr = pazar.arama_metni(ad, None, urun.get("tags"))
    tr = re.sub(r"\s*3d baskı$", "", tr or "").strip()
    return _bas_harf(tr) if tr else (ad or "3D baskı model")


def _turkce_etiketler(urun: dict) -> list[str]:
    """MakerWorld etiketleri; sözlükte karşılığı olan yabancı kelimeler Türkçeye çevrilir
    (navidad/xmas/christmas → yılbaşı)."""
    sonuc = []
    for ham in urun.get("tags") or []:
        k = str(ham).strip().lower()
        if k in ETIKET_GURULTU:
            continue
        tr = pazar.CEVIRI.get(k) or pazar.CEVIRI.get(k.rstrip("s"))
        sonuc.append(tr.replace(" ", "") if tr else str(ham))
    return sonuc


def etiketler(urun: dict, en_fazla: int | None = None) -> list[str]:
    en_fazla = min(en_fazla or config.INSTAGRAM_ETIKET_ADET, 30)
    sonuc: list[str] = []
    for e in [*TEMEL_ETIKETLER, *KATEGORI_ETIKETLERI.get(urun.get("category"), []),
              *video.etiketler({**urun, "tags": _turkce_etiketler(urun)}, en_fazla=30)]:
        if e.lower() not in {x.lower() for x in sonuc}:
            sonuc.append(e)
    return sonuc[:en_fazla]


def gonderi_metni(urun: dict) -> str:
    """Instagram açıklaması: kanca, Türkçe ad, baskı bilgisi, satış çağrısı, tasarımcı, etiketler."""
    satirlar = [video.kancalar(urun)[0], "", f"✨ {baslik(urun)}"]
    bilgi = []
    if urun.get("print_time_min"):
        bilgi.append(f"⏱ {analiz.sure_yazi(urun['print_time_min']).lstrip('~')} baskı")
    if (urun.get("color_count") or 0) >= 2:
        bilgi.append(f"🎨 {urun['color_count']} renk")
    bilgi.append("Bambu Lab P1S")
    satirlar.append(" · ".join(bilgi))
    sezon_notu = (urun.get("score_detail") or {}).get("sezon")
    if sezon_notu:
        satirlar.append(f"{sezon_notu.split(':')[0]} için şimdiden sipariş ver.")
    elif urun.get("category") in KATEGORI_CUMLESI:
        satirlar.append(KATEGORI_CUMLESI[urun["category"]])
    satirlar += ["", "🎨 İstediğin renkte basabilirim.", "📩 Sipariş ve fiyat için DM at!"]
    if urun.get("creator"):
        satirlar.append(f"Tasarım: {urun['creator']} (MakerWorld)")
    etiket = " ".join(etiketler(urun))
    govde = "\n".join(satirlar)
    sinir = config.INSTAGRAM_ACIKLAMA_SINIRI - len(etiket) - 2
    return f"{govde[:sinir]}\n\n{etiket}"


def metni_dogrula(metin: str) -> str | None:
    """Instagram sınırlarını aşan açıklama için hata yazısı; uygunsa None."""
    if len(metin) > config.INSTAGRAM_ACIKLAMA_SINIRI:
        return f"açıklama {len(metin)} karakter (en fazla {config.INSTAGRAM_ACIKLAMA_SINIRI})"
    if len(re.findall(r"#\w", metin)) > 30:
        return "açıklamada 30'dan fazla etiket var"
    if len(re.findall(r"@\w", metin)) > 20:
        return "açıklamada 20'den fazla @ var"
    return None


# --------------------------------------------------------------------------- Instagram API
class InstagramHatasi(RuntimeError):
    pass


class InstagramIstemci:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token
        self.client = client or httpx.Client(timeout=60)

    def _yanit(self, yanit: httpx.Response) -> dict:
        try:
            veri = yanit.json()
        except ValueError:
            veri = {}
        if yanit.status_code != 200 or "error" in veri:
            h = veri.get("error") or {}
            mesaj = h.get("error_user_msg") or h.get("message") or yanit.text[:200]
            raise InstagramHatasi(f"Instagram {yanit.status_code}: {mesaj}")
        return veri

    def _get(self, yol: str, **params) -> dict:
        return self._yanit(self.client.get(f"{config.INSTAGRAM_API}/{yol}",
                                           params={**params, "access_token": self.token}))

    def _post(self, yol: str, **veri) -> dict:
        return self._yanit(self.client.post(f"{config.INSTAGRAM_API}/{yol}",
                                            params={"access_token": self.token}, data=veri))

    def hesap(self) -> dict:
        """{'user_id', 'username'}: paylaşımda kullanılan profesyonel hesap kimliği."""
        veri = self._get("me", fields="user_id,username")
        if isinstance(veri.get("data"), list) and veri["data"]:
            veri = veri["data"][0]
        if not veri.get("user_id"):
            raise InstagramHatasi("Hesap kimliği alınamadı (profesyonel hesap mı?)")
        return veri

    def reels_olustur(self, ig_id: str, video_url: str, aciklama: str) -> str:
        veri = self._post(f"{ig_id}/media", media_type="REELS", video_url=video_url,
                          caption=aciklama, share_to_feed="true")
        return str(veri["id"])

    def kap_durumu(self, kap_id: str) -> tuple[str, str]:
        """(status_code, status): FINISHED, IN_PROGRESS, ERROR, EXPIRED veya PUBLISHED."""
        veri = self._get(kap_id, fields="status_code,status")
        return veri.get("status_code") or "", veri.get("status") or ""

    def yayinla(self, ig_id: str, kap_id: str) -> str:
        return str(self._post(f"{ig_id}/media_publish", creation_id=kap_id)["id"])

    def kalici_baglanti(self, medya_id: str) -> str | None:
        try:
            return self._get(medya_id, fields="permalink").get("permalink")
        except InstagramHatasi:
            return None

    def token_yenile(self) -> tuple[str, int]:
        """Uzun ömürlü token'ı yeniler (en az 24 saatlik olmalı). (yeni token, saniye)."""
        veri = self._yanit(self.client.get(config.INSTAGRAM_TOKEN_API, params={
            "grant_type": "ig_refresh_token", "access_token": self.token}))
        return veri["access_token"], int(veri.get("expires_in") or 0)


# --------------------------------------------------------------------------- depo
class InstagramDepo(Protocol):
    def gizli_oku(self, anahtar: str) -> dict | None: ...
    def gizli_yaz(self, anahtar: str, deger: str, kaynak: str, yenilendi: str) -> None: ...
    def zamani_gelenler(self, simdi: str, limit: int) -> list[dict]: ...
    def islenenler(self) -> list[dict]: ...
    def guncelle(self, gonderi_id: int, alanlar: dict) -> None: ...
    def imzali_url(self, yol: str, saniye: int) -> str: ...
    def video_sil(self, yol: str) -> None: ...
    def video_isaretle(self, urun_id: int) -> None: ...
    def urun_adi(self, urun_id: int | None) -> str | None: ...


class SupabaseInstagramDepo:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self.sb = create_client(url, key)

    def gizli_oku(self, anahtar: str) -> dict | None:
        yanit = self.sb.table("gizli_ayarlar").select("*").eq("anahtar", anahtar).execute()
        return yanit.data[0] if yanit.data else None

    def gizli_yaz(self, anahtar: str, deger: str, kaynak: str, yenilendi: str) -> None:
        self.sb.table("gizli_ayarlar").upsert({"anahtar": anahtar, "deger": deger, "kaynak": kaynak,
                                               "yenilendi": yenilendi}, on_conflict="anahtar").execute()

    def zamani_gelenler(self, simdi: str, limit: int) -> list[dict]:
        return list(self.sb.table("instagram_posts").select("*").eq("status", "bekliyor")
                    .lte("scheduled_at", simdi).order("scheduled_at").limit(limit).execute().data)

    def islenenler(self) -> list[dict]:
        return list(self.sb.table("instagram_posts").select("*").eq("status", "isleniyor")
                    .order("scheduled_at").execute().data)

    def guncelle(self, gonderi_id: int, alanlar: dict) -> None:
        self.sb.table("instagram_posts").update({**alanlar, "updated_at": _simdi()}).eq("id", gonderi_id).execute()

    def imzali_url(self, yol: str, saniye: int) -> str:
        yanit = self.sb.storage.from_(config.INSTAGRAM_DEPO).create_signed_url(yol, saniye)
        adres = yanit.get("signedURL") or yanit.get("signedUrl") or yanit.get("signed_url")
        if not adres:
            raise InstagramHatasi(f"Video bağlantısı oluşturulamadı: {yol}")
        return adres

    def video_sil(self, yol: str) -> None:
        self.sb.storage.from_(config.INSTAGRAM_DEPO).remove([yol])

    def video_isaretle(self, urun_id: int) -> None:
        var = self.sb.table("product_marks").select("product_id").eq("product_id", urun_id).execute().data
        if var:
            self.sb.table("product_marks").update({"video": True, "updated_at": _simdi()}).eq("product_id", urun_id).execute()
        else:
            self.sb.table("product_marks").insert({"product_id": urun_id, "video": True}).execute()

    def urun_adi(self, urun_id: int | None) -> str | None:
        if not urun_id:
            return None
        veri = self.sb.table("products").select("name").eq("id", urun_id).execute().data
        return veri[0]["name"] if veri else None


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _zaman(metin: str | None) -> datetime | None:
    if not metin:
        return None
    try:
        return datetime.fromisoformat(str(metin).replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- token
def _ozet(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def token_hazirla(depo: InstagramDepo, ortam_token: str, simdi: datetime,
                  client: httpx.Client | None = None) -> str:
    """Kullanılacak token: GitHub'daki token değişmediyse depodaki (yenilenmiş) token.
    Son yenilemeden INSTAGRAM_TOKEN_YENILEME_GUN geçtiyse yeniler. Token hiç yazdırılmaz."""
    kaynak = _ozet(ortam_token)
    kayit = depo.gizli_oku("instagram_token")
    if kayit and kayit.get("kaynak") == kaynak and kayit.get("deger"):
        token, yenilendi = kayit["deger"], _zaman(kayit.get("yenilendi")) or simdi
    else:
        # Yeni (veya GitHub'da değiştirilmiş) token: yaşı bilinmiyor, bugünden sayılır.
        token, yenilendi = ortam_token, simdi
        depo.gizli_yaz("instagram_token", token, kaynak, simdi.isoformat(timespec="seconds"))
    if simdi - yenilendi >= timedelta(days=config.INSTAGRAM_TOKEN_YENILEME_GUN):
        try:
            yeni, sure = InstagramIstemci(token, client).token_yenile()
            depo.gizli_yaz("instagram_token", yeni, kaynak, simdi.isoformat(timespec="seconds"))
            print(f"Instagram token yenilendi ({sure // 86400} gün geçerli).")
            token = yeni
        except (InstagramHatasi, httpx.HTTPError, KeyError) as e:
            kalan = 60 - (simdi - yenilendi).days
            print(f"UYARI: Instagram token yenilenemedi ({e}); yaklaşık {kalan} gün içinde süresi dolar.")
    return token


# --------------------------------------------------------------------------- paylaşım
def _bildir(ayarlar: config.Ayarlar, metinler: list[str]) -> None:
    if not (metinler and ayarlar.telegram_token and ayarlar.telegram_chat_id):
        return
    try:
        bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id,
                        [{"metot": "sendMessage", "veri": {"text": m, "disable_web_page_preview": True}}
                         for m in metinler])
    except (bildirim.BildirimHatasi, httpx.HTTPError) as e:
        print(f"UYARI: Telegram bildirimi gönderilemedi: {e}")


def _ad(depo: InstagramDepo, g: dict) -> str:
    try:
        return depo.urun_adi(g.get("product_id")) or f"gönderi #{g['id']}"
    except Exception:  # noqa: BLE001 — yalnızca bildirim metni için
        return f"gönderi #{g['id']}"


def isle(depo: InstagramDepo, ig: InstagramIstemci, simdi: datetime,
         bekle: Callable[[float], None] = time.sleep) -> list[str]:
    """Saati gelen gönderileri başlatır, işlenenleri yayınlar. Telegram metinlerini (HTML) döndürür."""
    bildirimler: list[str] = []
    gelenler = depo.zamani_gelenler(simdi.isoformat(timespec="seconds"), config.INSTAGRAM_CALISMA_BASINA_EN_FAZLA)
    islenen = depo.islenenler()
    if not gelenler and not islenen:
        return bildirimler

    def hata(g: dict, mesaj: str) -> None:
        depo.guncelle(g["id"], {"status": "hata", "error": mesaj[:500]})
        bildirimler.append(f"⚠️ Instagram paylaşımı başarısız: <b>{bildirim._e(_ad(depo, g))}</b>\n"
                           f"{bildirim._e(mesaj[:300])}\nPanelde Instagram sekmesinden tekrar deneyebilirsin.")

    try:
        ig_id = str(ig.hesap()["user_id"])
    except (InstagramHatasi, httpx.HTTPError) as e:
        # Token/hesap sorunu: gönderiler hataya alınır ki her 15 dakikada tekrar denenip uyarı yağmasın.
        for g in [*gelenler, *islenen]:
            hata(g, f"Instagram hesabına erişilemedi (token geçersiz veya süresi dolmuş olabilir): {e}")
        return bildirimler

    for g in gelenler:
        sorun = metni_dogrula(g.get("caption") or "")
        if sorun:
            hata(g, sorun)
            continue
        try:
            adres = depo.imzali_url(g["video_path"], config.INSTAGRAM_IMZALI_URL_SN)
            kap = ig.reels_olustur(ig_id, adres, g.get("caption") or "")
        except (InstagramHatasi, httpx.HTTPError) as e:
            hata(g, str(e))
            continue
        except Exception as e:  # noqa: BLE001 — depolama hatası vb.; diğer gönderiler sürsün
            hata(g, f"Video bağlantısı oluşturulamadı: {e}")
            continue
        g.update(status="isleniyor", container_id=kap, attempts=(g.get("attempts") or 0) + 1,
                 updated_at=simdi.isoformat(timespec="seconds"))  # 23 saat sınırı buradan sayılır
        depo.guncelle(g["id"], {"status": "isleniyor", "container_id": kap, "error": None,
                                "attempts": g["attempts"]})
        islenen.append(g)

    bitis = time.monotonic() + config.INSTAGRAM_BEKLEME_SN
    bekleyen = list(islenen)
    while bekleyen:
        sonraki = []
        for g in bekleyen:
            try:
                kod, aciklama = ig.kap_durumu(g["container_id"])
                if kod in ("FINISHED", "PUBLISHED"):
                    medya = ig.yayinla(ig_id, g["container_id"]) if kod == "FINISHED" else g.get("media_id")
                    baglanti = ig.kalici_baglanti(medya) if medya else None
                    depo.guncelle(g["id"], {"status": "paylasildi", "media_id": medya, "permalink": baglanti,
                                            "published_at": _simdi(), "error": None})
                    _paylasim_sonrasi(depo, g)
                    bildirimler.append(f"✅ Instagram'da paylaşıldı: <b>{bildirim._e(_ad(depo, g))}</b>"
                                       + (f"\n{bildirim._e(baglanti)}" if baglanti else ""))
                elif kod in ("ERROR", "EXPIRED"):
                    hata(g, f"Instagram videoyu işleyemedi ({kod}): {aciklama or 'video biçimini kontrol et'}")
                else:
                    olusturma = _zaman(g.get("updated_at")) or simdi
                    if simdi - olusturma > timedelta(hours=23):
                        hata(g, "Instagram videoyu 23 saatte işleyemedi")
                    else:
                        sonraki.append(g)
            except (InstagramHatasi, httpx.HTTPError) as e:
                hata(g, str(e))
        bekleyen = sonraki
        if bekleyen:
            if time.monotonic() + config.INSTAGRAM_KONTROL_ARALIGI_SN > bitis:
                print(f"{len(bekleyen)} video hâlâ işleniyor; sonraki çalışmada kontrol edilecek.")
                break
            bekle(config.INSTAGRAM_KONTROL_ARALIGI_SN)
    return bildirimler


def _paylasim_sonrasi(depo: InstagramDepo, g: dict) -> None:
    """Ürüne 'videosunu çektim' işareti; depolamadaki video silinir. Hata paylaşımı bozmaz."""
    try:
        if g.get("product_id"):
            depo.video_isaretle(g["product_id"])
    except Exception as e:  # noqa: BLE001
        print(f"UYARI: Video işareti konamadı: {e}")
    if config.INSTAGRAM_PAYLASINCA_VIDEOYU_SIL:
        try:
            depo.video_sil(g["video_path"])
        except Exception as e:  # noqa: BLE001
            print(f"UYARI: Video depodan silinemedi: {e}")


def calistir() -> int:
    ayarlar = config.ayarlari_oku()
    if not ayarlar.instagram_token:
        print("INSTAGRAM_TOKEN yok; Instagram paylaşımı kapalı.")
        return 0
    if not ayarlar.supabase_var:
        print("Instagram paylaşımı için Supabase gerekir (video depolama ve gönderi listesi).")
        return 0
    depo = SupabaseInstagramDepo(ayarlar.supabase_url, ayarlar.supabase_key)
    simdi = datetime.now(timezone.utc)
    try:
        token = token_hazirla(depo, ayarlar.instagram_token, simdi)
        bildirimler = isle(depo, InstagramIstemci(token), simdi)
    except (InstagramHatasi, httpx.HTTPError) as e:
        print(f"HATA: {e}")
        _bildir(ayarlar, [f"⚠️ Instagram görevi çalışmadı: {bildirim._e(str(e)[:300])}"])
        return 1
    except Exception as e:  # noqa: BLE001 — çoğunlukla SQL güncellemesi çalıştırılmamıştır
        print(f"HATA: {e}\nSupabase'te supabase/guncelleme_2026-11-10_instagram.sql çalıştırıldı mı?")
        return 1
    for m in bildirimler:
        print(re.sub(r"<[^>]+>", "", m))
    _bildir(ayarlar, bildirimler)
    if not bildirimler:
        print("Saati gelen Instagram gönderisi yok.")
    return 0


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(calistir())
