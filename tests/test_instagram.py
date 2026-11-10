from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from urun_bulucu import bildirim, config, instagram, ozet
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

SIMDI = datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _duzenleme_kapali(monkeypatch):
    """Paylaşım testleri ffmpeg'e bağlı olmasın; düzenleme testleri kendisi açar."""
    monkeypatch.setattr(config, "INSTAGRAM_VIDEO_DUZENLE", False)


def _urun(**ek):
    return urun(1, "Impossible Thread Fidget", 10, 100, print_time_min=59, color_count=2, creator="Tasarımcı",
                tags=["navidad", "fidget toy", "mini"], features=["hareketli parça"], **ek)


# ------------------------------------------------------------------ açıklama metni
def test_gonderi_metni_turkce_ve_sinirlar_icinde():
    m = instagram.gonderi_metni(_urun())
    assert "✨ İmkansız vida" in m                        # Türkçe ad, büyük İ
    assert "59 dk baskı" in m and "2 renk" in m
    assert "DM" in m and "Tasarım: Tasarımcı (MakerWorld)" in m
    etiketler = [k for k in m.split() if k.startswith("#")]
    assert "#3dbaskı" in etiketler and "#yılbaşı" in etiketler   # navidad → yılbaşı
    assert "#navidad" not in etiketler and "#mini" not in etiketler
    assert len(etiketler) <= config.INSTAGRAM_ETIKET_ADET and len(set(etiketler)) == len(etiketler)
    assert instagram.metni_dogrula(m) is None


def test_metni_dogrula_sinirlar():
    assert "2200" in instagram.metni_dogrula("a" * 2201)
    assert "30" in instagram.metni_dogrula(" ".join(f"#e{i}" for i in range(31)))
    assert instagram.metni_dogrula("kısa #tek") is None


def test_ozet_secimlerinde_aciklama_var_ve_sqlite_kaydeder(tmp_path):
    u = _urun(score=80, score_detail={"populerlik": 0.5, "artis": 0.5, "sure": 0.5})
    secim = ozet.sec([u])[0]
    assert secim["instagram_caption"].startswith(instagram.video.kancalar(u)[0])
    depo = SqliteDepo(tmp_path / "t.db")
    depo.urunleri_kaydet([u])
    secim["product_id"] = depo.con.execute("select id from products").fetchone()[0]
    depo.secimleri_kaydet(date(2026, 11, 10), [secim])
    kayit = depo.con.execute("select instagram_caption from weekly_picks").fetchone()[0]
    assert kayit == secim["instagram_caption"]


def test_telegram_instagram_mesaji_kacisli_ve_sigar():
    secimler = [{"rank": i, "urun": {"name": f"M<{i}>"}, "instagram_caption": "a & b " + "x" * 1500}
                for i in range(1, 4)]
    m = bildirim.instagram_mesaji(secimler)
    assert "<b>1. M&lt;1&gt;</b>" in m and "<pre>a &amp; b" in m
    assert len(m) <= 4096 and "3. M" not in m           # üçüncüsü sığmadı, atlandı
    assert bildirim.instagram_mesaji([{"rank": 1, "urun": {"name": "x"}}]) is None


# ------------------------------------------------------------------ paylaşım
class SahteDepo:
    def __init__(self, gonderiler=None, gizli=None):
        self.gonderiler = {g["id"]: g for g in (gonderiler or [])}
        self.gizli = gizli or {}
        self.isaretlenen, self.silinen = [], []

    def gizli_oku(self, anahtar):
        return self.gizli.get(anahtar)

    def gizli_yaz(self, anahtar, deger, kaynak, yenilendi):
        self.gizli[anahtar] = {"deger": deger, "kaynak": kaynak, "yenilendi": yenilendi}

    def zamani_gelenler(self, simdi, limit):
        return [dict(g) for g in self.gonderiler.values()
                if g["status"] == "bekliyor" and g["scheduled_at"] <= simdi][:limit]

    def islenenler(self):
        return [dict(g) for g in self.gonderiler.values() if g["status"] == "isleniyor"]

    def guncelle(self, gid, alanlar):
        self.gonderiler[gid].update(alanlar)

    def imzali_url(self, yol, saniye):
        return f"https://depo.example/{yol}?token=imza"

    def video_sil(self, yollar):
        self.silinen.extend(yollar)

    def video_isaretle(self, urun_id):
        self.isaretlenen.append(urun_id)

    def urun_adi(self, urun_id):
        return "Ürün <A>"


def _gonderi(**ek):
    g = {"id": 1, "product_id": 7, "video_path": "7/1.mp4", "caption": "Merhaba #3dbaskı",
         "scheduled_at": "2026-11-10T16:00:00+00:00", "status": "bekliyor", "attempts": 0,
         "updated_at": "2026-11-09T10:00:00+00:00"}
    g.update(ek)
    return g


def _api(durumlar, hesap_hatasi=False):
    """Sahte Instagram API; çağrıları kaydeder. durumlar: kap_durumu yanıtları sırayla."""
    cagrilar = []

    def handler(request: httpx.Request) -> httpx.Response:
        yol = request.url.path
        cagrilar.append((request.method, yol, dict(request.url.params),
                         request.content.decode() if request.method == "POST" else ""))
        assert request.url.params.get("access_token") == "TOKEN"
        if yol.endswith("/me"):
            if hesap_hatasi:
                return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})
            return httpx.Response(200, json={"user_id": "1784", "username": "fuat3d"})
        if yol.endswith("/1784/media"):
            return httpx.Response(200, json={"id": "KAP1"})
        if yol.endswith("/KAP1"):
            kod = durumlar.pop(0)
            return httpx.Response(200, json={"status_code": kod, "status": "Error: bad video" if kod == "ERROR" else ""})
        if yol.endswith("/1784/media_publish"):
            return httpx.Response(200, json={"id": "MEDYA9"})
        if yol.endswith("/MEDYA9"):
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        return httpx.Response(404, json={"error": {"message": "yok"}})

    return httpx.Client(transport=httpx.MockTransport(handler)), cagrilar


def test_isle_reels_olusturur_bekler_yayinlar_ve_isaretler():
    depo = SahteDepo([_gonderi(), _gonderi(id=2, scheduled_at="2026-11-11T16:00:00+00:00")])
    client, cagrilar = _api(["IN_PROGRESS", "FINISHED"])
    beklenen = []
    bildirimler = instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI, bekle=beklenen.append)

    olustur = next(c for c in cagrilar if c[1].endswith("/1784/media"))
    assert "media_type=REELS" in olustur[3] and "share_to_feed=true" in olustur[3]
    assert "video_url=https%3A%2F%2Fdepo.example%2F7%2F1.mp4" in olustur[3]
    assert beklenen == [config.INSTAGRAM_KONTROL_ARALIGI_SN]
    g = depo.gonderiler[1]
    assert g["status"] == "paylasildi" and g["media_id"] == "MEDYA9" and g["attempts"] == 1
    assert g["permalink"] == "https://www.instagram.com/reel/abc/"
    assert depo.isaretlenen == [7] and depo.silinen == ["7/1.mp4", "7/1_hazir.mp4"]
    assert depo.gonderiler[2]["status"] == "bekliyor"     # saati gelmedi
    assert len(bildirimler) == 1 and "✅" in bildirimler[0] and "Ürün &lt;A&gt;" in bildirimler[0]


def test_isle_islenmeyi_bitiremezse_sonraki_calismaya_birakir(monkeypatch):
    monkeypatch.setattr(config, "INSTAGRAM_BEKLEME_SN", 0)
    depo = SahteDepo([_gonderi()])
    client, _ = _api(["IN_PROGRESS"])
    assert instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI, bekle=lambda s: None) == []
    g = depo.gonderiler[1]
    assert g["status"] == "isleniyor" and g["container_id"] == "KAP1"

    # Sonraki çalışma: işlenmiş, yayınlanır.
    client, cagrilar = _api(["FINISHED"])
    instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI + timedelta(minutes=15))
    assert depo.gonderiler[1]["status"] == "paylasildi"
    assert not any(c[1].endswith("/1784/media") for c in cagrilar)   # yeni kap açılmadı


def test_isle_video_hatasi_ve_hesap_hatasi():
    depo = SahteDepo([_gonderi()])
    client, _ = _api(["ERROR"])
    b = instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI)
    assert depo.gonderiler[1]["status"] == "hata" and "bad video" in depo.gonderiler[1]["error"]
    assert "⚠️" in b[0] and depo.silinen == []           # hatalıda video silinmez (tekrar denenebilir)

    depo = SahteDepo([_gonderi()])
    client, cagrilar = _api([], hesap_hatasi=True)
    instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI)
    assert depo.gonderiler[1]["status"] == "hata" and "token" in depo.gonderiler[1]["error"]
    assert not any(c[1].endswith("/media") for c in cagrilar)


def test_isle_cok_uzun_aciklamayi_gondermez():
    depo = SahteDepo([_gonderi(caption="a" * 2300)])
    client, cagrilar = _api([])
    instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI)
    assert depo.gonderiler[1]["status"] == "hata" and "2200" in depo.gonderiler[1]["error"]
    assert not any(c[1].endswith("/media") for c in cagrilar)


def test_isle_gonderi_yoksa_instagrama_istek_atmaz():
    client, cagrilar = _api([])
    assert instagram.isle(SahteDepo(), instagram.InstagramIstemci("TOKEN", client), SIMDI) == []
    assert cagrilar == []


# ------------------------------------------------------------------ token
def _token_api(basarili=True):
    cagrilar = []

    def handler(request: httpx.Request) -> httpx.Response:
        cagrilar.append(dict(request.url.params))
        assert request.url.path.endswith("/refresh_access_token")
        if not basarili:
            return httpx.Response(400, json={"error": {"message": "too new"}})
        return httpx.Response(200, json={"access_token": "YENI", "token_type": "bearer", "expires_in": 5184000})

    return httpx.Client(transport=httpx.MockTransport(handler)), cagrilar


def test_token_ilk_kez_kaydedilir_ve_yenilenmez():
    depo = SahteDepo()
    client, cagrilar = _token_api()
    assert instagram.token_hazirla(depo, "ESKI", SIMDI, client) == "ESKI"
    assert depo.gizli["instagram_token"]["deger"] == "ESKI" and cagrilar == []
    assert "ESKI" not in depo.gizli["instagram_token"]["kaynak"]


def test_token_suresi_gelince_yenilenir_github_degisince_sifirlanir(capsys):
    kaynak = instagram._ozet("ESKI")
    eski = (SIMDI - timedelta(days=8)).isoformat()
    depo = SahteDepo(gizli={"instagram_token": {"deger": "DEPODAKI", "kaynak": kaynak, "yenilendi": eski}})
    client, cagrilar = _token_api()
    assert instagram.token_hazirla(depo, "ESKI", SIMDI, client) == "YENI"
    assert cagrilar[0] == {"grant_type": "ig_refresh_token", "access_token": "DEPODAKI"}
    assert depo.gizli["instagram_token"]["deger"] == "YENI"
    assert "YENI" not in capsys.readouterr().out          # token yazdırılmaz

    # GitHub'daki token değiştirildi: depodaki yerine yenisi kullanılır.
    assert instagram.token_hazirla(depo, "BAMBASKA", SIMDI, client) == "BAMBASKA"


def test_token_yenilenemezse_eskisiyle_devam(capsys):
    depo = SahteDepo(gizli={"instagram_token": {"deger": "D", "kaynak": instagram._ozet("E"),
                                                "yenilendi": (SIMDI - timedelta(days=10)).isoformat()}})
    client, _ = _token_api(basarili=False)
    assert instagram.token_hazirla(depo, "E", SIMDI, client) == "D"
    assert "50 gün" in capsys.readouterr().out


# ------------------------------------------------------------------ video hazırlama
class VideoDepo(SahteDepo):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.indirilen, self.yuklenen = [], {}

    def video_indir(self, yol, hedef):
        self.indirilen.append(yol)
        Path(hedef).write_bytes(b"ham")

    def video_yukle(self, yol, dosya):
        self.yuklenen[yol] = Path(dosya).read_bytes()


def _sahte_duzenle(giris, cikis, aciklama):
    Path(cikis).write_bytes(b"hazir:" + Path(giris).read_bytes() + aciklama.encode()[:5])
    return {}


def test_video_hazirla_duzenler_yukler_ve_kapatilabilir(monkeypatch):
    monkeypatch.setattr(config, "INSTAGRAM_VIDEO_DUZENLE", True)
    monkeypatch.setattr(instagram.video_duzenle, "ffmpeg_yolu", lambda: "ffmpeg")
    depo = VideoDepo()
    yol, notu = instagram.video_hazirla(depo, _gonderi(video_path="7/1.mov"), _sahte_duzenle)
    assert (yol, notu) == ("7/1_hazir.mp4", None)
    assert depo.indirilen == ["7/1.mov"] and depo.yuklenen["7/1_hazir.mp4"] == b"hazir:hamMerha"

    depo = VideoDepo()   # panelde kutu kaldırıldı
    assert instagram.video_hazirla(depo, _gonderi(video_edit=False), _sahte_duzenle) == ("7/1.mp4", None)
    assert depo.indirilen == []


def test_video_hazirla_basarisizsa_ozgun_videoyla_devam(monkeypatch):
    monkeypatch.setattr(config, "INSTAGRAM_VIDEO_DUZENLE", True)
    monkeypatch.setattr(instagram.video_duzenle, "ffmpeg_yolu", lambda: None)
    assert instagram.video_hazirla(VideoDepo(), _gonderi(), _sahte_duzenle) == (
        "7/1.mp4", "ffmpeg bulunamadı; video düzenlenmeden paylaşıldı")

    monkeypatch.setattr(instagram.video_duzenle, "ffmpeg_yolu", lambda: "ffmpeg")

    def bozuk(giris, cikis, aciklama):
        raise instagram.video_duzenle.VideoDuzenlemeHatasi("video çok kısa")

    yol, notu = instagram.video_hazirla(VideoDepo(), _gonderi(), bozuk)
    assert yol == "7/1.mp4" and "video çok kısa" in notu


def test_isle_duzenlenmis_videoyu_paylasir_notu_bildirir():
    depo = SahteDepo([_gonderi()])
    client, cagrilar = _api(["FINISHED"])
    b = instagram.isle(depo, instagram.InstagramIstemci("TOKEN", client), SIMDI,
                       hazirla=lambda d, g: ("7/1_hazir.mp4", "deneme notu"))
    olustur = next(c for c in cagrilar if c[1].endswith("/1784/media"))
    assert "1_hazir.mp4" in olustur[3]
    assert depo.gonderiler[1]["status"] == "paylasildi" and "ℹ️ deneme notu" in b[0]


def test_video_duzenle_metin_yardimcilari():
    vd = instagram.video_duzenle
    ac = "Tek parça basıldı, hiç montaj yok 🤯\n\n✨ İmkansız vida\n#3dbaskı"
    assert vd.kanca_metni(ac) == "Tek parça basıldı, hiç montaj yok"
    assert vd.kanca_metni("🤯\n#a #b") == ""
    assert vd.tr_buyuk("hiç ışık") == "HİÇ IŞIK"
    assert vd.satirlara_bol("TEK PARÇA BASILDI, HİÇ MONTAJ YOK") == ["TEK PARÇA BASILDI,", "HİÇ MONTAJ YOK"]
    assert len(vd.satirlara_bol("kelime " * 30)) == 4
    assert vd.hazir_yolu("7/1731.mov") == "7/1731_hazir.mp4"
    f, kanca_sn = vd.filtre(["A", "B"], ["DM"], 10.0, ses_var=False)
    assert "k1.txt" in f and "s0.txt" in f and "tpad=stop_mode=clone" in f and "[0:a]" not in f
    assert "gte(t,10.000)" in f and kanca_sn == config.INSTAGRAM_KANCA_SN
    f, _ = vd.filtre([], [], 4.0, ses_var=True)
    assert "drawtext" not in f and "apad" in f


@pytest.mark.skipif(not instagram.video_duzenle.ffmpeg_yolu() or not instagram.video_duzenle.font_bul(),
                    reason="ffmpeg yok (FFMPEG_YOLU ile gösterilebilir)")
def test_video_duzenle_gercek_ffmpeg(tmp_path):
    import subprocess
    vd = instagram.video_duzenle
    ff = vd.ffmpeg_yolu()
    giris = tmp_path / "ham.mp4"
    subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "4", "-c:v", "libx264", str(giris)], check=True)
    r = vd.duzenle(giris, tmp_path / "hazir.mp4", "%20 indirim: tek parça 🤯\n#etiket")
    sure, ses = vd.bilgi(ff, tmp_path / "hazir.mp4")
    assert abs(sure - (4 + config.INSTAGRAM_SON_KART_SN)) < 0.3 and ses   # sessize ses kanalı eklendi
    assert r["kanca"] == ["%20 İNDİRİM: TEK", "PARÇA"]


def test_video_hazirla_beklenmeyen_dosya_adini_duzenlemez(monkeypatch):
    monkeypatch.setattr(config, "INSTAGRAM_VIDEO_DUZENLE", True)
    monkeypatch.setattr(instagram.video_duzenle, "ffmpeg_yolu", lambda: "ffmpeg")
    depo = VideoDepo()
    for yol in ["7/1.m3u8", "../x/1.mp4", "7/1.mp4/../a.txt"]:
        yol2, notu = instagram.video_hazirla(depo, _gonderi(video_path=yol), _sahte_duzenle)
        assert yol2 == yol and "biçimde değil" in notu
    assert depo.indirilen == []


@pytest.mark.skipif(not instagram.video_duzenle.ffmpeg_yolu() or not instagram.video_duzenle.font_bul(),
                    reason="ffmpeg yok (FFMPEG_YOLU ile gösterilebilir)")
def test_video_duzenle_mp4_kiliginda_liste_dosyasini_reddeder(tmp_path):
    gizli = tmp_path / "gizli.txt"
    gizli.write_text("SIR")
    sahte = tmp_path / "giris.mp4"     # aslında HLS listesi: yerel dosyayı okutmaya çalışır
    sahte.write_text(f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\nfile://{gizli.as_posix()}\n#EXT-X-ENDLIST\n")
    with pytest.raises(instagram.video_duzenle.VideoDuzenlemeHatasi):
        instagram.video_duzenle.duzenle(sahte, tmp_path / "c.mp4", "deneme")
    assert not (tmp_path / "c.mp4").exists()
