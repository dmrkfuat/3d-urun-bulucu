"""Yazıcı köprüsü: rapor birleştirme, özet, kamera paketi, SD kart, istek işleme ve baskı bitişi."""
import ftplib
import io
from datetime import datetime, timezone
import os
import shutil
import ssl
import struct
import subprocess

import pytest

from urun_bulucu import kopru, video_duzenle

AYAR = kopru.KopruAyar(ip="192.0.2.10", erisim_kodu="12345678", seri="TESTSERI", ad="Bambu P1S")
JPEG = b"\xff\xd8" + b"x" * 50 + b"\xff\xd9"


def test_birlestir_ic_ice_ve_liste_degisir():
    eski = {"print": {"mc_percent": 10, "ams": {"ams": [1]}, "nozzle_temper": 200}}
    yeni = {"print": {"mc_percent": 20, "ams": {"ams": [2]}}}
    sonuc = kopru.birlestir(eski, yeni)
    assert sonuc == {"print": {"mc_percent": 20, "ams": {"ams": [2]}, "nozzle_temper": 200}}
    assert eski["print"]["mc_percent"] == 10  # eski değişmez


def test_ozet_alanlari_ve_ams():
    rapor = {"print": {"gcode_state": "RUNNING", "mc_percent": 37, "mc_remaining_time": 258, "layer_num": 42,
                       "total_layer_num": 120, "nozzle_temper": 219.6, "nozzle_target_temper": 220, "bed_temper": 64.9,
                       "bed_target_temper": 65, "subtask_name": "Skull Planter",
                       "ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PETG", "tray_color": "000000FF", "remain": 62},
                                                            {"id": "1", "tray_type": "", "remain": -1},
                                                            {"id": "2", "tray_type": "PLA", "tray_color": "FFFFFFFF", "remain": -1}]}]}}}
    oz = kopru.ozet(rapor)
    assert oz["durum"] == "RUNNING" and oz["yuzde"] == 37 and oz["kalan_dk"] == 258
    assert (oz["katman"], oz["toplam_katman"]) == (42, 120)
    assert (oz["nozul"], oz["tabla"]) == (220, 65)
    assert oz["ams"] == [{"yuva": "1-1", "tur": "PETG", "renk": "000000", "kalan": 62},
                         {"yuva": "1-3", "tur": "PLA", "renk": "FFFFFF", "kalan": None}]
    assert kopru.ozet({})["durum"] is None


def test_bitti_mi():
    assert kopru.bitti_mi("RUNNING", "FINISH")
    assert kopru.bitti_mi("PAUSE", "FAILED")
    assert not kopru.bitti_mi("FINISH", "FINISH")
    assert not kopru.bitti_mi(None, "FINISH")      # köprü açıldığında zaten bitmiş baskı tetiklemez
    assert not kopru.bitti_mi("RUNNING", "RUNNING")


def test_kamera_kimlik_paketi():
    paket = kopru.kamera_kimlik_paketi("12345678")
    assert len(paket) == 80
    assert struct.unpack("<IIII", paket[:16]) == (0x40, 0x3000, 0, 0)
    assert paket[16:20] == b"bblp" and paket[48:56] == b"12345678"


class SahteSoket:
    def __init__(self, veri: bytes, iz: bytes = b"sertifika"):
        self.akis, self.iz = io.BytesIO(veri), iz

    def recv(self, n):
        return self.akis.read(min(n, 7))   # parça parça okuma da çalışmalı

    def getpeercert(self, binary_form=False):
        return self.iz


def _kare(veri: bytes) -> bytes:
    return struct.pack("<IIII", len(veri), 0, 1, 0) + veri


def test_kare_oku_gecerli_gecersiz_ve_kopuk():
    sok = SahteSoket(_kare(JPEG) + _kare(b"jpeg-degil"))
    assert kopru.kare_oku(sok) == JPEG
    assert kopru.kare_oku(sok) is None
    with pytest.raises(ConnectionError):
        kopru.kare_oku(SahteSoket(_kare(JPEG)[:20]))
    with pytest.raises(ConnectionError):
        kopru.kare_oku(SahteSoket(struct.pack("<IIII", 0, 0, 0, 0)))


def test_parmak_izi():
    import hashlib
    iz = hashlib.sha256(b"sertifika").hexdigest().upper()
    assert kopru.parmak_izi_bicim(iz.lower()[:8] + ":" + iz.lower()[8:]) == iz
    kopru.parmak_izi_dogrula(SahteSoket(b""), iz)            # eşleşiyor
    with pytest.raises(ssl.SSLError):
        kopru.parmak_izi_dogrula(SahteSoket(b""), "")        # ayarlanmamış: kapalı varsayılan, reddedilir
    with pytest.raises(ssl.SSLError):
        kopru.parmak_izi_dogrula(SahteSoket(b"", iz=b"baska"), iz)


def test_parmak_izi_yoksa_kopru_baslamaz(monkeypatch, capsys):
    monkeypatch.setenv("YAZICI_IP", "192.0.2.5")
    monkeypatch.setenv("YAZICI_ERISIM_KODU", "abc")
    monkeypatch.setenv("YAZICI_SERI", "S1")
    monkeypatch.setenv("YAZICI_PARMAK_IZI", "")
    assert kopru.main([]) == 2
    assert "YAZICI_PARMAK_IZI" in capsys.readouterr().out


def test_guvenli_ad():
    assert kopru.guvenli_ad("video_2026-11-26_17-45-12.avi") == "video_2026-11-26_17-45-12.avi"
    for kotu in ("../.env", "/timelapse/x.avi", "a\\b.avi", "", "foto.jpg", "..", "C:x.avi", "c:..avi",
                 "x.avi\r\nDELE y.avi", "a b.avi", "..x.avi", None, 5):
        with pytest.raises(ValueError):
            kopru.guvenli_ad(kotu)


def test_mqtt_parmak_izi_pahonun_kendi_soketinde_denetlenir():
    import hashlib
    pytest.importorskip("paho.mqtt.client")
    iz = hashlib.sha256(b"sertifika").hexdigest().upper()
    m = kopru.MqttIstemci(kopru.KopruAyar(ip="192.0.2.10", erisim_kodu="x", seri="S", parmak_izi=iz), lambda r: None)
    assert m.istemci.on_socket_open == m._soket_denetim   # CONNECT (şifre) gönderilmeden önce çağrılır

    class Kapanan(SahteSoket):
        kapandi = False

        def close(self):
            self.kapandi = True
    dogru, yanlis = Kapanan(b""), Kapanan(b"", iz=b"saldirgan")
    m._soket_denetim(None, None, dogru)
    assert not dogru.kapandi
    with pytest.raises(ssl.SSLError):
        m._soket_denetim(None, None, yanlis)
    assert yanlis.kapandi


class SahteFTP:
    def __init__(self, dosyalar, mlsd_var=True):
        self.dosyalar, self.mlsd_var = dosyalar, mlsd_var
        self.indirilen = []

    def mlsd(self, yol, facts=None):
        if not self.mlsd_var:
            raise ftplib.error_perm("500 MLSD desteklenmiyor")
        yield "thumbnail", {"type": "dir"}
        for ad, boy, tarih in self.dosyalar:
            yield ad, {"type": "file", "size": str(boy), "modify": tarih}

    def nlst(self, yol):
        return [f"{yol}/{ad}" for ad, _, _ in self.dosyalar] + [f"{yol}/thumbnail"]

    def size(self, yol):
        return next(b for a, b, _ in self.dosyalar if yol.endswith(a))

    def sendcmd(self, komut):
        return "213 " + next(t for a, _, t in self.dosyalar if komut.endswith(a))

    def retrbinary(self, komut, yaz):
        self.indirilen.append(komut)
        yaz(b"avi-verisi")

    def quit(self):
        pass


DOSYALAR = [("video_eski.avi", 1000, "20261125100000"), ("video_yeni.avi", 2000, "20261126170000"), ("not.txt", 5, "20261126170000")]


@pytest.mark.parametrize("mlsd_var", [True, False])
def test_sd_listele_mlsd_ve_yedek(mlsd_var):
    liste = kopru.sd_listele(SahteFTP(DOSYALAR, mlsd_var))
    assert [d["ad"] for d in liste] == ["video_yeni.avi", "video_eski.avi"]
    assert liste[0]["boyut"] == 2000
    # Yazıcı saati yerel saattir; bilgisayarın saat dilimiyle UTC'ye çevrilir
    beklenen = datetime(2026, 11, 26, 17, 0, 0).astimezone(timezone.utc).isoformat()
    assert liste[0]["tarih"] == beklenen


class SahteDepo:
    def __init__(self, istekler=None, aktif=None):
        self.durumlar, self.guncellemeler, self.yuklenen, self.eklenen = [], [], [], []
        self.istekler, self.aktif = list(istekler or []), aktif

    def durum_yaz(self, ad, model, durum):
        self.durumlar.append((ad, durum))

    def bekleyen_istekler(self, ad):
        istekler, self.istekler = self.istekler, []
        return istekler

    def istek_guncelle(self, istek_id, **alanlar):
        self.guncellemeler.append((istek_id, alanlar))

    def aktif_siparis(self, ad):
        return self.aktif

    def video_yukle(self, yol, veri):
        self.yuklenen.append((yol, len(veri)))

    def medya_ekle(self, siparis_id, oge):
        self.eklenen.append((siparis_id, oge))


class Saat:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _sahte_ffmpeg(monkeypatch):
    def kareden(ffmpeg, kareler, sure, cikti):
        if len(kareler) < 2:
            raise RuntimeError("Kamera görüntüsü yok")
        open(cikti, "wb").write(b"mp4" * len(kareler))

    def cevir(ffmpeg, girdi, cikti):
        shutil.copy(girdi, cikti)
    monkeypatch.setattr(kopru, "kareden_mp4", kareden)
    monkeypatch.setattr(kopru, "mp4ye_cevir", cevir)


def test_adim_durum_yazar_ve_klip_istegini_isler(monkeypatch):
    _sahte_ffmpeg(monkeypatch)
    saat = Saat()
    depo = SahteDepo(istekler=[{"id": 7, "tur": "klip", "siparis_id": 41, "saniye": 30},
                               {"id": 8, "tur": "klip", "siparis_id": None, "saniye": 30}])
    kayitlar = []

    def kamera(saniye):                      # istek anında bağlanıp `saniye` kaydeder
        kayitlar.append(saniye)
        return [JPEG] * 22, 30.2
    k = kopru.Kopru(AYAR, depo, "ffmpeg", saat=saat, kamera=kamera)
    k.rapor_al({"print": {"gcode_state": "RUNNING", "mc_percent": 50}})
    k.adim()
    assert depo.durumlar[0][0] == "Bambu P1S" and depo.durumlar[0][1]["yuzde"] == 50
    assert depo.durumlar[0][1]["kamera"] is True and depo.durumlar[0][1]["kamera_mod"] == "istek"
    assert kayitlar == [30]                  # yalnızca geçerli istek için, bir kez bağlandı
    assert depo.guncellemeler[0] == (7, {"durum": "isleniyor"})
    sonuc = depo.guncellemeler[1][1]
    assert sonuc["durum"] == "tamam" and sonuc["sonuc"]["kare"] == 22 and sonuc["sonuc"]["sure"] == 30.2
    assert depo.guncellemeler[3][1]["durum"] == "hata" and "Sipariş" in depo.guncellemeler[3][1]["hata"]
    siparis_id, oge = depo.eklenen[0]
    assert siparis_id == 41 and oge["tur"] == "klip" and oge["yol"].startswith("41/") and oge["yol"].endswith(".mp4")
    assert depo.yuklenen[0][0] == oge["yol"]


def test_durum_her_adimda_yazilmaz():
    saat = Saat()
    depo = SahteDepo()
    k = kopru.Kopru(AYAR, depo, None, saat=saat)
    k.rapor_al({"print": {"gcode_state": "RUNNING", "nozzle_temper": 200}})
    k.adim()
    k.rapor_al({"print": {"nozzle_temper": 201}})
    saat.t += 3
    k.adim()                                  # yalnızca sıcaklık değişti, 10 sn dolmadı
    assert len(depo.durumlar) == 1
    k.rapor_al({"print": {"gcode_state": "PAUSE"}})
    saat.t += 3
    k.adim()                                  # durum değişti: hemen yazılır
    saat.t += 11
    k.adim()                                  # süre doldu
    assert [d[1]["durum"] for d in depo.durumlar] == ["RUNNING", "PAUSE", "PAUSE"]


def test_sd_aktar_ve_klip_icin_ffmpeg_yoksa_hata():
    depo = SahteDepo(istekler=[{"id": 1, "tur": "klip", "siparis_id": 5, "saniye": 15}])
    baglandi = []
    k = kopru.Kopru(AYAR, depo, None, saat=Saat(), kamera=lambda s: baglandi.append(s) or ([JPEG] * 5, 15))
    k.adim()
    assert depo.guncellemeler[-1][1]["durum"] == "hata" and "ffmpeg" in depo.guncellemeler[-1][1]["hata"]
    assert baglandi == []                    # ffmpeg yokken kameraya boşuna bağlanılmaz


def test_kameraya_baglanilamazsa_panele_bildirilir(monkeypatch):
    _sahte_ffmpeg(monkeypatch)
    saat = Saat()
    depo = SahteDepo(istekler=[{"id": 1, "tur": "klip", "siparis_id": 5, "saniye": 15}])

    def kamera(_s):
        raise ConnectionError("kamera bağlantısı kapandı")
    k = kopru.Kopru(AYAR, depo, "ffmpeg", saat=saat, kamera=kamera)
    k.adim()
    assert depo.guncellemeler[-1][1]["durum"] == "hata" and "Kameraya bağlanılamadı" in depo.guncellemeler[-1][1]["hata"]
    saat.t += kopru.DURUM_ARALIGI
    k.adim()
    assert depo.durumlar[-1][1]["kamera"] is False and "kapandı" in depo.durumlar[-1][1]["kamera_hatasi"]


def test_uzun_is_arka_planda_durum_yazimini_durdurmaz(monkeypatch):
    import threading
    _sahte_ffmpeg(monkeypatch)
    saat = Saat()
    serbest, basladi = threading.Event(), threading.Event()

    def kamera(saniye):                      # 60 sn'lik kayıt gibi uzun süren iş
        basladi.set()
        serbest.wait(5)
        return [JPEG] * 10, saniye
    depo = SahteDepo(istekler=[{"id": 3, "tur": "klip", "siparis_id": 5, "saniye": 60}])
    k = kopru.Kopru(AYAR, depo, "ffmpeg", saat=saat, kamera=kamera, arka_planda=True)
    k.rapor_al({"print": {"gcode_state": "RUNNING"}})
    k.adim()                                  # iş kuyruğa alındı, adim beklemeden döndü
    assert basladi.wait(2)
    yazim = len(depo.durumlar)
    saat.t += kopru.DURUM_ARALIGI
    k.adim()                                  # kayıt sürerken durum yazılmaya devam eder
    assert len(depo.durumlar) == yazim + 1
    assert depo.guncellemeler[0] == (3, {"durum": "isleniyor"})
    assert all(a["durum"] != "tamam" for _, a in depo.guncellemeler)
    serbest.set()
    for _ in range(50):
        if any(a["durum"] == "tamam" for _, a in depo.guncellemeler):
            break
        threading.Event().wait(0.05)
    assert any(a["durum"] == "tamam" for _, a in depo.guncellemeler)


def test_kamera_kaydet_ilk_kareden_itibaren_sure_kadar_kaydeder(monkeypatch):
    saat = Saat(0.0)
    kareler = [_kare(JPEG)] * 30

    class Sok(SahteSoket):
        def __init__(self):
            super().__init__(b"".join(kareler))
            self.gonderilen = b""

        def recv(self, n):
            saat.t += 0.2                     # her okuma zaman ilerletir (7 baytlık parçalar: ~kare başına 2,2 sn)
            return super().recv(n)

        def sendall(self, b):
            self.gonderilen += b

        def settimeout(self, _):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.kapandi = True
    sok = Sok()
    monkeypatch.setattr(kopru, "tls_ac", lambda ayar, port, **k: sok)
    alinan, sure = kopru.kamera_kaydet(AYAR, 10, saat=saat)
    assert sok.gonderilen == kopru.kamera_kimlik_paketi(AYAR.erisim_kodu)
    assert 10 <= sure < 12.5 and 5 <= len(alinan) <= 7 and getattr(sok, "kapandi", False)


def test_sd_listele_ve_aktar_istekleri(monkeypatch):
    _sahte_ffmpeg(monkeypatch)
    ftp = SahteFTP(DOSYALAR)
    depo = SahteDepo(istekler=[{"id": 1, "tur": "sd_listele"},
                               {"id": 2, "tur": "sd_aktar", "siparis_id": 9, "dosya": "video_yeni.avi"},
                               {"id": 3, "tur": "sd_aktar", "siparis_id": 9, "dosya": "../.env"}])
    k = kopru.Kopru(AYAR, depo, "ffmpeg", ftp_ac=lambda: ftp, saat=Saat())
    k.adim()
    sonuclar = {i: a for i, a in depo.guncellemeler if a["durum"] != "isleniyor"}
    assert [d["ad"] for d in sonuclar[1]["sonuc"]["dosyalar"]] == ["video_yeni.avi", "video_eski.avi"]
    assert sonuclar[2]["durum"] == "tamam"
    assert sonuclar[3]["durum"] == "hata"
    assert ftp.indirilen == ["RETR /timelapse/video_yeni.avi"]
    _, oge = depo.eklenen[0]
    assert oge["tur"] == "timelapse" and oge["kaynak"] == "video_yeni.avi" and oge["ad"] == "video_yeni.mp4"


def test_baski_bitince_timelapse_eklenir_ve_bildirilir(monkeypatch):
    _sahte_ffmpeg(monkeypatch)
    saat, mesajlar = Saat(), []
    ftp = SahteFTP(DOSYALAR)
    # Baskı yerel saatle 16:00'da başladı: 17:00'deki dosya dahil, önceki günün dosyası hariç
    baslangic = datetime(2026, 11, 26, 16, 0).astimezone(timezone.utc).isoformat()
    aktif = {"id": 41, "urun_adi": "Skull Planter", "medya": [], "baski_baslangic": baslangic}
    depo = SahteDepo(aktif=aktif)
    k = kopru.Kopru(AYAR, depo, "ffmpeg", ftp_ac=lambda: ftp, saat=saat, bildir=mesajlar.append)
    k.rapor_al({"print": {"gcode_state": "RUNNING", "subtask_name": "Skull"}})
    k.adim()
    k.rapor_al({"print": {"gcode_state": "FINISH"}})
    k.adim()
    assert not depo.eklenen                   # dosyanın yazılması beklenir
    saat.t += kopru.TIMELAPSE_BEKLEME + 1
    k.adim()
    assert len(depo.eklenen) == 1 and depo.eklenen[0][0] == 41
    assert depo.eklenen[0][1]["kaynak"] == "video_yeni.avi"   # baskı başlangıcından önceki eski dosya değil
    assert "Baskı bitti" in mesajlar[0] and "#SIP-41" in mesajlar[0] and "Timelapse" in mesajlar[0]
    # Aynı dosya ikinci kez eklenmez
    aktif["medya"] = [depo.eklenen[0][1]]
    assert k.timelapse_ekle(aktif) is None


def test_basarisiz_baski_bildirimi():
    mesajlar = []
    depo = SahteDepo()
    saat = Saat()
    k = kopru.Kopru(AYAR, depo, None, ftp_ac=lambda: SahteFTP([]), saat=saat, bildir=mesajlar.append)
    k.rapor_al({"print": {"gcode_state": "RUNNING", "subtask_name": "<Vazo>"}})
    k.adim()
    k.rapor_al({"print": {"gcode_state": "FAILED"}})
    k.adim()
    saat.t += kopru.TIMELAPSE_BEKLEME + 1
    k.adim()
    assert "başarısız" in mesajlar[0] and "&lt;Vazo&gt;" in mesajlar[0]


def test_seri_sorunu_mac_ve_bicim():
    assert "MAC" in kopru.seri_sorunu("AA:BB:CC:11:22:33")
    assert "MAC" in kopru.seri_sorunu("aa-bb-cc-11-22-33")
    assert kopru.seri_sorunu("01p00a123456789") is not None     # küçük harf
    assert kopru.seri_sorunu("01P 00A1") is not None
    assert kopru.seri_sorunu("01P00A123456789") is None


def test_ayarlar_eksikse_none(monkeypatch):
    for k in ("YAZICI_IP", "YAZICI_ERISIM_KODU", "YAZICI_SERI", "YAZICI_ADI", "YAZICI_PARMAK_IZI"):
        monkeypatch.delenv(k, raising=False)
    assert kopru.kopru_ayarlari() is None
    monkeypatch.setenv("YAZICI_IP", "192.0.2.5")
    monkeypatch.setenv("YAZICI_ERISIM_KODU", "abc")
    monkeypatch.setenv("YAZICI_SERI", "S1")
    monkeypatch.setenv("YAZICI_PARMAK_IZI", "aa:bb")
    a = kopru.kopru_ayarlari()
    assert a.ad == "Bambu P1S" and a.parmak_izi == "AABB"


FFMPEG = video_duzenle.ffmpeg_yolu()


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg yok")
def test_gercek_ffmpeg_kare_ve_avi_donusumu(tmp_path):
    kare = subprocess.run([FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48", "-frames:v", "1",
                           "-f", "image2", "-c:v", "mjpeg", "pipe:1"], capture_output=True, check=True).stdout
    assert kare[:2] == b"\xff\xd8"
    klip = tmp_path / "klip.mp4"
    kopru.kareden_mp4(FFMPEG, [kare] * 10, 10, str(klip))
    assert klip.stat().st_size > 0 and b"ftyp" in klip.read_bytes()[:64]
    # P1S gibi saniyede ~0,7 kare: 30 sn'lik istek 22 kareyle gelir, klip yine ~30 sn sürmeli
    ffprobe = os.path.join(os.path.dirname(FFMPEG), "ffprobe" + os.path.splitext(FFMPEG)[1])
    if os.path.isfile(ffprobe):
        yavas = tmp_path / "yavas.mp4"
        kopru.kareden_mp4(FFMPEG, [kare] * 22, 30, str(yavas))
        sure = float(subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(yavas)],
                                    capture_output=True, text=True, check=True).stdout)
        assert 28 <= sure <= 31
    avi = tmp_path / "t.avi"
    subprocess.run([FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=5", "-t", "2",
                    "-c:v", "mjpeg", str(avi)], check=True)
    mp4 = tmp_path / "t.mp4"
    kopru.mp4ye_cevir(FFMPEG, str(avi), str(mp4))
    assert mp4.stat().st_size > 0 and b"ftyp" in mp4.read_bytes()[:64]
    with pytest.raises(RuntimeError):
        kopru.kareden_mp4(FFMPEG, [kare], 10, str(tmp_path / "bos.mp4"))
