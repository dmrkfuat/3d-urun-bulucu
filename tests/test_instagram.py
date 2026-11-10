from datetime import date, datetime, timedelta, timezone

import httpx

from urun_bulucu import bildirim, config, instagram, ozet
from urun_bulucu.db import SqliteDepo

from .ornek_veri import urun

SIMDI = datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)


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

    def video_sil(self, yol):
        self.silinen.append(yol)

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
    assert depo.isaretlenen == [7] and depo.silinen == ["7/1.mp4"]
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
