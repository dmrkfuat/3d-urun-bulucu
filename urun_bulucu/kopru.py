"""Yazıcı köprüsü: Bambu Lab P1 serisi yazıcıyı (yerel ağ) panele bağlar.

Panel bir web sayfasıdır; yazıcının MQTT, kamera ve SD kart (FTPS) bağlantılarına tarayıcıdan erişilemez.
Bu program evdeki bir bilgisayarda (yazıcıyla aynı ağda) çalışır ve:

- MQTT (8883, TLS) ile yazıcının durumunu okur (ilerleme, katman, kalan süre, sıcaklıklar, AMS) ve
  ~10 saniyede bir Supabase'teki ``yazici_durum`` tablosuna yazar,
- kameranın (6000, TLS; P1/A1 JPEG akışı) son ``KAMERA_TAMPON_SN`` saniyesini bellekte tutar; panelden
  "Son 30 sn" istenince bu karelerden MP4 klip yapıp siparişin video arşivine ekler,
- SD karttaki timelapse dosyalarını (FTPS 990) listeler / siparişe aktarır (AVI → MP4, ffmpeg),
- baskı bitince timelapse'i otomatik olarak o siparişe ekler ve (ayarlıysa) Telegram'a haber verir.

Yalnızca OKUR: yazıcıya baskı başlatma/durdurma gibi komut göndermez (yalnızca tam durum isteği "pushall").

Ayarlar (.env, yalnızca bu bilgisayarda): YAZICI_IP, YAZICI_ERISIM_KODU (yazıcı ekranındaki LAN erişim kodu),
YAZICI_SERI (seri numarası), isteğe bağlı YAZICI_ADI (panelde siparişe yazılan ad; varsayılan "Bambu P1S").
Çalıştırma:  python -m urun_bulucu.kopru          (sürekli çalışır)
             python -m urun_bulucu.kopru --dene   (bağlantıları bir kez dener ve çıkar)
"""
from __future__ import annotations

import collections
import ftplib
import html
import json
import logging
import os
import posixpath
import re
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config, video_duzenle

log = logging.getLogger("kopru")

KULLANICI = "bblp"
MQTT_PORT, KAMERA_PORT, FTPS_PORT = 8883, 6000, 990
TIMELAPSE_KLASORU = "/timelapse"
VIDEO_UZANTILARI = (".avi", ".mp4", ".mov")
SIP_DEPO = "siparis"
EN_BUYUK_BAYT = 50 * 1024 * 1024          # panel ve depolama sınırı
DURUM_ARALIGI = 10                         # sn: Supabase'e durum yazma sıklığı
ISTEK_ARALIGI = 3                          # sn: panel isteklerini kontrol etme sıklığı
PUSHALL_ARALIGI = 300                      # sn: tam durum isteği (P1 serisi yalnızca değişenleri gönderir)
KAMERA_TAMPON_SN = 120                     # bellekte tutulan kamera süresi
TIMELAPSE_BEKLEME = 90                     # sn: baskı bitince timelapse dosyasının yazılmasını bekle
CALISAN = ("PREPARE", "RUNNING", "PAUSE", "SLICING")
BITEN = ("FINISH", "FAILED")


@dataclass(frozen=True)
class KopruAyar:
    ip: str
    erisim_kodu: str
    seri: str
    ad: str = "Bambu P1S"
    model: str = "P1S"
    parmak_izi: str = ""   # yazıcı sertifikasının SHA-256 izi (boşsa denetlenmez; --dene gösterir)


def seri_sorunu(seri: str) -> str | None:
    """Sık yapılan hata: seri yerine MAC adresi. Yanlış seriyle yazıcı MQTT bağlantısını hemen kapatır."""
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", seri or ""):
        return ("YAZICI_SERI bir MAC adresi (AA:BB:CC:…); yazıcının SERİ NUMARASINI yaz: P1S'te 01P ile başlar, "
                "15 karakterdir (yazıcı ekranı: Ayarlar → Cihaz; Bambu Studio: Cihaz sekmesi; ya da arkadaki etiket)")
    if not re.fullmatch(r"[0-9A-Z]{8,20}", seri or ""):
        return "YAZICI_SERI yalnızca büyük harf ve rakamdan oluşmalı (P1S: 01P ile başlar, 15 karakter)"
    return None


def kopru_ayarlari() -> KopruAyar | None:
    ip, kod, seri = (os.getenv(k, "").strip() for k in ("YAZICI_IP", "YAZICI_ERISIM_KODU", "YAZICI_SERI"))
    if not (ip and kod and seri):
        return None
    return KopruAyar(ip=ip, erisim_kodu=kod, seri=seri,
                     ad=os.getenv("YAZICI_ADI", "").strip()[:60] or "Bambu P1S",
                     model=os.getenv("YAZICI_MODEL", "").strip()[:60] or "P1S",
                     parmak_izi=parmak_izi_bicim(os.getenv("YAZICI_PARMAK_IZI", "")))


# ------------------------------------------------------------------ TLS: sertifika parmak izi sabitleme
# Bambu yazıcıların sertifikası kendinden imzalıdır; klasik doğrulama yapılamaz. Bunun yerine sertifikanın
# SHA-256 izi .env'e yazılırsa (YAZICI_PARMAK_IZI), erişim kodu gönderilmeden ÖNCE her bağlantıda karşılaştırılır.

def parmak_izi_bicim(iz: str) -> str:
    return "".join(c for c in (iz or "").upper() if c in "0123456789ABCDEF")


def tls_baglami() -> ssl.SSLContext:
    baglam = ssl.create_default_context()
    baglam.check_hostname = False
    baglam.verify_mode = ssl.CERT_NONE   # yerine parmak izi denetimi (parmak_izi_dogrula)
    return baglam


def sertifika_izi(sok: ssl.SSLSocket) -> str:
    import hashlib
    return hashlib.sha256(sok.getpeercert(binary_form=True) or b"").hexdigest().upper()


def parmak_izi_dogrula(sok: ssl.SSLSocket, beklenen: str) -> None:
    """Kapalı varsayılan: iz ayarlı değilse de bağlantı reddedilir (erişim kodu doğrulanmamış uca gitmesin)."""
    if not beklenen:
        raise ssl.SSLError("YAZICI_PARMAK_IZI ayarlı değil; önce --dene ile yazıcının sertifika izini alıp .env'e ekle")
    if sertifika_izi(sok) != beklenen:
        raise ssl.SSLError("Yazıcı sertifikası beklenen parmak iziyle eşleşmiyor; bağlantı kesildi "
                           "(IP değiştiyse ya da yazıcı sıfırlandıysa --dene ile yeni izi al)")


def tls_ac(ayar: KopruAyar, port: int, zaman_asimi: float = 15, dogrula: bool = True) -> ssl.SSLSocket:
    """TLS bağlantısı açar ve parmak izini doğrular; kimlik bilgisi göndermez.
    dogrula=False yalnızca --dene'de, kimlik bilgisi gönderilmeden izi OKUMAK için kullanılır."""
    ham = socket.create_connection((ayar.ip, port), timeout=zaman_asimi)
    try:
        sok = tls_baglami().wrap_socket(ham, server_hostname=ayar.ip)
        if dogrula:
            parmak_izi_dogrula(sok, ayar.parmak_izi)
        return sok
    except Exception:
        ham.close()
        raise


# ------------------------------------------------------------------ yazıcı raporu (MQTT)

def birlestir(eski: dict, yeni: dict) -> dict:
    """P1 serisi raporları parça parça gelir; sözlükleri iç içe birleştirir (listeler yenisiyle değişir)."""
    sonuc = dict(eski)
    for k, v in yeni.items():
        sonuc[k] = birlestir(sonuc[k], v) if isinstance(v, dict) and isinstance(sonuc.get(k), dict) else v
    return sonuc


def _sayi(v, ondalik: bool = False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 1) if ondalik else int(round(x))


def ozet(rapor: dict) -> dict:
    """Panelde gösterilecek alanlar (yazici_durum.durum)."""
    p = rapor.get("print") or {}
    ams = []
    for a in (p.get("ams") or {}).get("ams") or []:
        for t in a.get("tray") or []:
            if not t.get("tray_type"):
                continue
            kalan = _sayi(t.get("remain"))
            ams.append({"yuva": f"{(_sayi(a.get('id')) or 0) + 1}-{(_sayi(t.get('id')) or 0) + 1}",
                        "tur": str(t.get("tray_type"))[:20], "renk": str(t.get("tray_color") or "")[:6],
                        "kalan": kalan if kalan is not None and 0 <= kalan <= 100 else None})
    return {
        "durum": p.get("gcode_state"),
        "yuzde": _sayi(p.get("mc_percent")),
        "kalan_dk": _sayi(p.get("mc_remaining_time")),
        "katman": _sayi(p.get("layer_num")),
        "toplam_katman": _sayi(p.get("total_layer_num")),
        "nozul": _sayi(p.get("nozzle_temper")), "nozul_hedef": _sayi(p.get("nozzle_target_temper")),
        "tabla": _sayi(p.get("bed_temper")), "tabla_hedef": _sayi(p.get("bed_target_temper")),
        "dosya": (str(p.get("subtask_name"))[:120] if p.get("subtask_name") else None),
        "hiz": _sayi(p.get("spd_lvl")),
        "hata_kodu": p.get("print_error") or None,
        "ams": ams,
    }


def bitti_mi(onceki: str | None, simdiki: str | None) -> bool:
    return onceki in CALISAN and simdiki in BITEN


class MqttIstemci:
    """paho-mqtt ile yazıcıya bağlanır; gelen raporları geri çağırma ile iletir. Kendiliğinden yeniden bağlanır."""

    def __init__(self, ayar: KopruAyar, rapor_geldi):
        import paho.mqtt.client as mqtt  # yalnızca köprüde gerekir (requirements-kopru.txt)
        self.ayar, self.rapor_geldi = ayar, rapor_geldi
        self.istemci = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"panel-kopru-{os.getpid()}")
        self.istemci.username_pw_set(KULLANICI, ayar.erisim_kodu)
        self.istemci.tls_set_context(tls_baglami())
        # paho, TLS el sıkışmasından SONRA ve şifreli CONNECT paketinden ÖNCE on_socket_open'ı çağırır:
        # parmak izi paho'nun kullandığı aynı sokette denetlenir. Eşleşmezse soket kapanır ve SSLError (OSError)
        # yükselir; paho bunu bağlantı hatası sayar, erişim kodunu göndermeden bekleyip yeniden dener.
        self.istemci.on_socket_open = self._soket_denetim
        self.istemci.on_connect = self._baglandi
        self.istemci.on_disconnect = self._koptu
        self.istemci.on_subscribe = self._abone_olundu
        self.son_kopma: str | None = None
        self.kopma_sayisi = 0
        self.istemci.on_message = self._mesaj
        self.bagli = False
        self.son_pushall = 0.0

    def _soket_denetim(self, _istemci, _v, sok):
        try:
            parmak_izi_dogrula(sok, self.ayar.parmak_izi)
        except ssl.SSLError as e:
            log.error("MQTT: %s", e)
            try:
                sok.close()
            except OSError:
                pass
            raise

    def _baglandi(self, istemci, _v, _b, kod, _p=None):
        self.bagli = not getattr(kod, "is_failure", bool(kod))
        if not self.bagli:
            log.warning("MQTT bağlantısı reddedildi: %s (erişim kodu / LAN modu?)", kod)
            return
        log.info("MQTT bağlandı")
        istemci.subscribe(f"device/{self.ayar.seri}/report")
        self.pushall()

    def _koptu(self, _istemci, _v, _bayrak, kod, _p=None):
        self.bagli = False
        self.kopma_sayisi += 1
        self.son_kopma = str(kod)
        log.warning("MQTT bağlantısı koptu: %s", kod)

    def _abone_olundu(self, _istemci, _v, _mid, kodlar, _p=None):
        if any(getattr(k, "is_failure", False) for k in kodlar or []):
            log.error("MQTT aboneliği reddedildi (%s): YAZICI_SERI yazıcının seri numarası mı?", ", ".join(map(str, kodlar)))

    def _mesaj(self, _istemci, _v, mesaj):
        try:
            self.rapor_geldi(json.loads(mesaj.payload))
        except (ValueError, TypeError):
            pass

    def pushall(self):
        self.son_pushall = time.time()
        self.istemci.publish(f"device/{self.ayar.seri}/request",
                             json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))

    def baslat(self):
        self.istemci.connect_async(self.ayar.ip, MQTT_PORT, keepalive=60)
        self.istemci.loop_start()

    def durdur(self):
        self.istemci.loop_stop()
        self.istemci.disconnect()


# ------------------------------------------------------------------ kamera (P1/A1: TLS üzerinden JPEG kareleri)

def kamera_kimlik_paketi(erisim_kodu: str) -> bytes:
    return (struct.pack("<IIII", 0x40, 0x3000, 0, 0)
            + KULLANICI.encode().ljust(32, b"\0") + erisim_kodu.encode()[:32].ljust(32, b"\0"))


def _tam_oku(sok, n: int) -> bytes:
    veri = bytearray()
    while len(veri) < n:
        parca = sok.recv(n - len(veri))
        if not parca:
            raise ConnectionError("kamera bağlantısı kapandı")
        veri += parca
    return bytes(veri)


def kare_oku(sok) -> bytes | None:
    """16 baytlık başlık (ilk 4 bayt: kare boyu) + JPEG. Geçersiz kare için None."""
    baslik = _tam_oku(sok, 16)
    boy = struct.unpack("<I", baslik[:4])[0]
    if not 0 < boy < 10 * 1024 * 1024:
        raise ConnectionError(f"geçersiz kare boyu: {boy}")
    kare = _tam_oku(sok, boy)
    return kare if kare[:2] == b"\xff\xd8" and kare[-2:] == b"\xff\xd9" else None


class Kamera(threading.Thread):
    def __init__(self, ayar: KopruAyar, kare_geldi):
        super().__init__(daemon=True, name="kamera")
        self.ayar, self.kare_geldi = ayar, kare_geldi
        self.calis = True
        self.son_kare = 0.0

    def run(self):
        bekle = 5
        while self.calis:
            try:
                with tls_ac(self.ayar, KAMERA_PORT) as sok:
                    sok.sendall(kamera_kimlik_paketi(self.ayar.erisim_kodu))
                    log.info("Kamera bağlandı")
                    bekle = 5
                    while self.calis:
                        kare = kare_oku(sok)
                        if kare:
                            self.son_kare = time.time()
                            self.kare_geldi(kare)
            except (OSError, ConnectionError, ssl.SSLError) as e:
                log.warning("Kamera: %s; %d sn sonra yeniden denenecek", e, bekle)
                time.sleep(bekle)
                bekle = min(bekle * 2, 120)


# ------------------------------------------------------------------ SD kart (FTPS, örtük TLS)

class _OrtukFTPS(ftplib.FTP_TLS):
    """Bambu yazıcılar 990 portunda örtük (implicit) TLS kullanır ve veri bağlantısında TLS oturumunun
    yeniden kullanılmasını ister; standart ftplib ikisini de yapmaz."""

    beklenen_iz = ""

    def connect(self, host="", port=FTPS_PORT, timeout=30, source_address=None):
        self.host, self.port, self.timeout = host, port, timeout
        ham = socket.create_connection((host, port), timeout)
        self.af = ham.family
        self.sock = self.context.wrap_socket(ham, server_hostname=host)
        try:
            parmak_izi_dogrula(self.sock, self.beklenen_iz)   # login (erişim kodu) öncesi
        except ssl.SSLError:
            self.sock.close()
            raise
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        baglanti, boy = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            baglanti = self.context.wrap_socket(baglanti, server_hostname=self.host, session=self.sock.session)
        return baglanti, boy


def ftps_ac(ayar: KopruAyar) -> ftplib.FTP_TLS:
    ftp = _OrtukFTPS(context=tls_baglami())
    ftp.beklenen_iz = ayar.parmak_izi
    ftp.connect(ayar.ip, FTPS_PORT)
    ftp.login(KULLANICI, ayar.erisim_kodu)
    ftp.prot_p()
    return ftp


def yazici_saati(damga: str) -> str:
    """Yazıcının dosya saati (YYYYMMDDHHMMSS) yazıcının yerel saatiyle gelir (dosya adındaki saatle aynı);
    köprü aynı evde çalıştığı için bilgisayarın saat dilimiyle yorumlanıp UTC'ye çevrilir."""
    return datetime.strptime(damga, "%Y%m%d%H%M%S").astimezone(timezone.utc).isoformat()


def _mdtm(ftp, yol: str) -> str | None:
    try:
        yanit = ftp.sendcmd(f"MDTM {yol}")            # "213 20261126174512"
        return yazici_saati(yanit.split()[-1][:14])
    except (ftplib.Error, ValueError, IndexError):
        return None


def sd_listele(ftp) -> list[dict]:
    """SD karttaki timelapse videoları: [{ad, boyut, tarih}], en yeni önce."""
    dosyalar = []
    try:
        for ad, bilgi in ftp.mlsd(TIMELAPSE_KLASORU, facts=["type", "size", "modify"]):
            if bilgi.get("type") == "file" and _AD_KALIBI.fullmatch(ad):
                tarih = None
                if bilgi.get("modify"):
                    try:
                        tarih = yazici_saati(bilgi["modify"][:14])
                    except ValueError:
                        pass
                dosyalar.append({"ad": ad, "boyut": int(bilgi.get("size") or 0), "tarih": tarih})
    except ftplib.error_perm:
        for yol in ftp.nlst(TIMELAPSE_KLASORU):
            ad = posixpath.basename(yol)
            if not _AD_KALIBI.fullmatch(ad):
                continue
            tam = f"{TIMELAPSE_KLASORU}/{ad}"
            try:
                boyut = ftp.size(tam) or 0
            except ftplib.Error:
                boyut = 0
            dosyalar.append({"ad": ad, "boyut": int(boyut), "tarih": _mdtm(ftp, tam)})
    return sorted(dosyalar, key=lambda d: (d["tarih"] or "", d["ad"]), reverse=True)


# Bambu timelapse adları: video_2026-11-26_17-45-12.avi. Sıkı kalıp; yol ayırıcı, sürücü öneki (C:),
# boşluk ve satır sonu (FTP komutuna ekleme) içeremez.
_AD_KALIBI = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.(?:avi|mp4|mov)", re.IGNORECASE)


def guvenli_ad(ad: str) -> str:
    """Panelden gelen dosya adı yalnızca timelapse klasöründeki, kalıba uyan bir dosya olabilir."""
    ad = ad if isinstance(ad, str) else ""
    if not _AD_KALIBI.fullmatch(ad) or ".." in ad:
        raise ValueError("Geçersiz dosya adı")
    return ad


# ------------------------------------------------------------------ ffmpeg

def kareden_mp4(ffmpeg: str, kareler: list[bytes], sure_sn: float, cikti: str) -> None:
    """JPEG karelerinden MP4 (H.264). Kare hızı, karelerin gerçekte geldiği hıza göre ayarlanır."""
    if len(kareler) < 2:
        raise RuntimeError("Kamera görüntüsü yok (kamera bağlı değil ya da yazıcı ışığı kapalı)")
    fps = max(1, round(len(kareler) / max(sure_sn, 1)))
    komut = [ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart", cikti]
    subprocess.run(komut, input=b"".join(kareler), check=True, timeout=300, capture_output=True)


def mp4ye_cevir(ffmpeg: str, girdi: str, cikti: str) -> None:
    """SD karttaki timelapse'i (P1 serisi AVI) panelin oynatabileceği MP4'e çevirir; 50 MB'ı aşarsa küçültür."""
    for crf, genislik in ((26, 1280), (32, 960), (36, 640)):
        komut = [ffmpeg, "-y", "-loglevel", "error", "-i", girdi, "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", str(crf), "-pix_fmt", "yuv420p", "-vf", f"scale='min({genislik},iw)':-2",
                 "-movflags", "+faststart", cikti]
        subprocess.run(komut, check=True, timeout=1800, capture_output=True)
        if os.path.getsize(cikti) <= EN_BUYUK_BAYT:
            return
    raise RuntimeError("Video 50 MB'ın altına küçültülemedi")


# ------------------------------------------------------------------ Supabase

class SupabaseKopruDepo:
    def __init__(self, url: str, key: str):
        from supabase import create_client
        self.sb = create_client(url, key)

    def durum_yaz(self, ad: str, model: str, durum: dict) -> None:
        self.sb.table("yazici_durum").upsert({"ad": ad, "model": model, "durum": durum,
                                              "goruldu": datetime.now(timezone.utc).isoformat()}).execute()

    def bekleyen_istekler(self, ad: str) -> list[dict]:
        r = (self.sb.table("yazici_istekleri").select("*").eq("durum", "bekliyor")
             .or_(f"yazici.is.null,yazici.eq.{ad}").order("id").limit(5).execute())
        return r.data or []

    def istek_guncelle(self, istek_id: int, **alanlar) -> None:
        alanlar["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.sb.table("yazici_istekleri").update(alanlar).eq("id", istek_id).execute()

    def siparis(self, siparis_id: int) -> dict | None:
        r = self.sb.table("siparisler").select("id, urun_adi, medya, baski_baslangic").eq("id", siparis_id).limit(1).execute()
        return (r.data or [None])[0]

    def aktif_siparis(self, ad: str) -> dict | None:
        """Bu yazıcıda basılmakta olan en son sipariş; yazıcı adı girilmemiş siparişler de sayılır (tek yazıcı)."""
        r = (self.sb.table("siparisler").select("id, urun_adi, medya, baski_baslangic, yazici").eq("durum", "basiliyor")
             .order("baski_baslangic", desc=True).limit(20).execute())
        satirlar = r.data or []
        return next((s for s in satirlar if s.get("yazici") == ad), None) or next((s for s in satirlar if not s.get("yazici")), None)

    def video_yukle(self, yol: str, veri: bytes) -> None:
        self.sb.storage.from_(SIP_DEPO).upload(yol, veri, {"content-type": "video/mp4", "upsert": "false"})

    def medya_ekle(self, siparis_id: int, oge: dict) -> None:
        s = self.siparis(siparis_id)
        if not s:
            raise RuntimeError(f"Sipariş bulunamadı: #{siparis_id}")
        medya = [m for m in (s.get("medya") or []) if m.get("yol") != oge["yol"]] + [oge]
        self.sb.table("siparisler").update({"medya": medya, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", siparis_id).execute()


# ------------------------------------------------------------------ köprü

class Kopru:
    def __init__(self, ayar: KopruAyar, depo, ffmpeg: str | None, ftp_ac=None, saat=time.time, bildir=None):
        self.ayar, self.depo, self.ffmpeg = ayar, depo, ffmpeg
        self.ftp_ac = ftp_ac or (lambda: ftps_ac(ayar))
        self.saat = saat
        self.bildir = bildir or (lambda metin: None)
        self.kilit = threading.Lock()
        self.rapor: dict = {}
        self.kareler: collections.deque = collections.deque()
        self.son_yazim = 0.0
        self.son_ozet: dict = {}
        self.onceki_durum: str | None = None
        self.timelapse_zamani: float | None = None
        self.biten_durum: str | None = None

    # --- yazıcıdan gelenler
    def rapor_al(self, veri: dict) -> None:
        with self.kilit:
            self.rapor = birlestir(self.rapor, veri)

    def kare_ekle(self, jpeg: bytes, t: float | None = None) -> None:
        t = self.saat() if t is None else t
        with self.kilit:
            self.kareler.append((t, jpeg))
            while self.kareler and t - self.kareler[0][0] > KAMERA_TAMPON_SN:
                self.kareler.popleft()

    def son_kareler(self, saniye: int) -> list[bytes]:
        simdi = self.saat()
        with self.kilit:
            return [j for t, j in self.kareler if simdi - t <= saniye]

    # --- döngü adımı (ana döngü birkaç saniyede bir çağırır)
    def adim(self) -> None:
        with self.kilit:
            oz = ozet(self.rapor)
        simdi = self.saat()
        durum = oz.get("durum")
        # Durum (RUNNING/FINISH…) değişince hemen, yoksa DURUM_ARALIGI'nda bir yazar; rapor yoksa da yazar
        # (panel köprünün açık olduğunu "goruldu" zamanından anlar).
        if durum != self.son_ozet.get("durum") or simdi - self.son_yazim >= DURUM_ARALIGI:
            try:
                self.depo.durum_yaz(self.ayar.ad, self.ayar.model, {**oz, "kamera": bool(self.son_kareler(10))})
                self.son_yazim, self.son_ozet = simdi, oz
            except Exception as e:  # ağ hatası köprüyü durdurmasın
                log.warning("Durum yazılamadı: %s", e)
        if bitti_mi(self.onceki_durum, durum):
            self.timelapse_zamani, self.biten_durum = simdi + TIMELAPSE_BEKLEME, durum
        if durum:
            self.onceki_durum = durum
        if self.timelapse_zamani and simdi >= self.timelapse_zamani:
            self.timelapse_zamani = None
            self.baski_bitti(oz)
        try:
            istekler = self.depo.bekleyen_istekler(self.ayar.ad)
        except Exception as e:
            log.warning("İstekler okunamadı: %s", e)
            return
        for istek in istekler:
            self.isle(istek)

    def isle(self, istek: dict) -> None:
        self.depo.istek_guncelle(istek["id"], durum="isleniyor")
        try:
            islem = {"klip": self.klip, "sd_listele": self.sd_listele, "sd_aktar": self.sd_aktar}[istek["tur"]]
            sonuc = islem(istek)
            self.depo.istek_guncelle(istek["id"], durum="tamam", sonuc=sonuc)
        except Exception as e:
            log.warning("İstek #%s (%s) başarısız: %s", istek.get("id"), istek.get("tur"), e)
            self.depo.istek_guncelle(istek["id"], durum="hata", hata=str(e)[:300] or e.__class__.__name__)

    def _ffmpeg(self) -> str:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg bulunamadı (FFMPEG_YOLU ayarla ya da ffmpeg kur)")
        return self.ffmpeg

    def _yukle_ve_ekle(self, siparis_id: int, mp4_yolu: str, ad: str, tur: str, kaynak: str | None = None) -> dict:
        boyut = os.path.getsize(mp4_yolu)
        if boyut > EN_BUYUK_BAYT:
            raise RuntimeError("Video 50 MB'tan büyük")
        yol = f"{siparis_id}/{int(self.saat() * 1000)}.mp4"
        self.depo.video_yukle(yol, Path(mp4_yolu).read_bytes())
        oge = {"yol": yol, "ad": ad[:120], "boyut": boyut, "tur": tur, "tarih": datetime.now(timezone.utc).isoformat()}
        if kaynak:
            oge["kaynak"] = kaynak
        self.depo.medya_ekle(siparis_id, oge)
        return oge

    def klip(self, istek: dict) -> dict:
        if not istek.get("siparis_id"):
            raise ValueError("Sipariş seçilmedi")
        saniye = int(istek.get("saniye") or 30)
        kareler = self.son_kareler(saniye)
        with tempfile.TemporaryDirectory() as klasor:
            cikti = os.path.join(klasor, "klip.mp4")
            kareden_mp4(self._ffmpeg(), kareler, saniye, cikti)
            ad = f"klip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{saniye}sn.mp4"
            oge = self._yukle_ve_ekle(int(istek["siparis_id"]), cikti, ad, "klip")
        return {"yol": oge["yol"], "kare": len(kareler)}

    def sd_listele(self, _istek: dict | None = None) -> dict:
        ftp = self.ftp_ac()
        try:
            return {"dosyalar": sd_listele(ftp)[:100]}
        finally:
            try:
                ftp.quit()
            except (ftplib.Error, OSError):
                pass

    def _sd_indir_cevir(self, ad: str, siparis_id: int, tur: str) -> dict:
        ad = guvenli_ad(ad)
        ftp = self.ftp_ac()
        try:
            with tempfile.TemporaryDirectory() as klasor:
                girdi = os.path.join(klasor, "girdi" + Path(ad).suffix.lower())   # uzak adı yerel yolda kullanma
                with open(girdi, "wb") as f:
                    ftp.retrbinary(f"RETR {TIMELAPSE_KLASORU}/{ad}", f.write)
                cikti = os.path.join(klasor, "cikti.mp4")
                mp4ye_cevir(self._ffmpeg(), girdi, cikti)
                return self._yukle_ve_ekle(siparis_id, cikti, Path(ad).stem + ".mp4", tur, kaynak=ad)
        finally:
            try:
                ftp.quit()
            except (ftplib.Error, OSError):
                pass

    def sd_aktar(self, istek: dict) -> dict:
        if not istek.get("siparis_id"):
            raise ValueError("Sipariş seçilmedi")
        oge = self._sd_indir_cevir(istek.get("dosya") or "", int(istek["siparis_id"]), "timelapse")
        return {"yol": oge["yol"]}

    def baski_bitti(self, oz: dict) -> None:
        """Baskı bitince: en yeni timelapse'i aktif siparişe ekle, Telegram'a haber ver."""
        basarili = self.biten_durum == "FINISH"
        dosya = oz.get("dosya") or "baskı"
        try:
            siparis = self.depo.aktif_siparis(self.ayar.ad)
        except Exception as e:
            log.warning("Aktif sipariş okunamadı: %s", e)
            siparis = None
        eklendi = None
        if siparis:
            try:
                eklendi = self.timelapse_ekle(siparis)
            except Exception as e:
                log.warning("Timelapse eklenemedi: %s", e)
        etiket = f" (#SIP-{siparis['id']} {siparis.get('urun_adi') or ''})" if siparis else ""
        if basarili:
            metin = f"🖨️ <b>Baskı bitti</b>: {html.escape(dosya)}{html.escape(etiket)}"
            metin += "\n🎞️ Timelapse siparişin video arşivine eklendi." if eklendi else ""
        else:
            metin = f"⚠️ <b>Baskı başarısız oldu</b>: {html.escape(dosya)}{html.escape(etiket)}"
        self.bildir(metin)

    def timelapse_ekle(self, siparis: dict) -> dict | None:
        """Baskı başlangıcından sonra oluşan en yeni timelapse'i siparişe ekler (zaten ekliyse eklemez)."""
        dosyalar = self.sd_listele()["dosyalar"]
        baslangic = siparis.get("baski_baslangic")
        if baslangic:
            esik = datetime.fromisoformat(baslangic.replace("Z", "+00:00")).timestamp() - 600
            dosyalar = [d for d in dosyalar if not d["tarih"] or datetime.fromisoformat(d["tarih"]).timestamp() >= esik]
        if not dosyalar:
            return None
        en_yeni = dosyalar[0]
        if any(m.get("kaynak") == en_yeni["ad"] for m in siparis.get("medya") or []):
            return None
        return self._sd_indir_cevir(en_yeni["ad"], int(siparis["id"]), "timelapse")


def telegram_bildirici(ayarlar):
    if not (ayarlar.telegram_token and ayarlar.telegram_chat_id):
        return None
    from . import bildirim

    def gonder(metin: str) -> None:
        try:
            bildirim.gonder(ayarlar.telegram_token, ayarlar.telegram_chat_id, [{"metot": "sendMessage", "veri": {"text": metin}}])
        except Exception as e:
            log.warning("Telegram'a gönderilemedi: %s", e)
    return gonder


def dene(ayar: KopruAyar) -> int:
    """Bağlantıları bir kez dener (kurulumda): MQTT, kamera, SD kart, ffmpeg, Supabase. Erişim kodunu yazdırmaz."""
    sonuc = 0
    print(f"Yazıcı: {ayar.ad} ({ayar.model}) @ {ayar.ip}")
    if sorun := seri_sorunu(ayar.seri):
        print(f"UYARI: {sorun}")
    try:
        from dataclasses import replace
        with tls_ac(ayar, MQTT_PORT, zaman_asimi=10, dogrula=False) as sok:   # yalnızca iz okunur
            iz = sertifika_izi(sok)
        if not ayar.parmak_izi:
            print(f"Sertifika parmak izi: {iz}\n  → Köprünün çalışması için .env'e ekle: YAZICI_PARMAK_IZI={iz}\n"
                  "  (Yazıcının kendi ağında olduğundan eminsen. Aşağıdaki denemeler bu oturumda bu izle yapılır.)")
            ayar = replace(ayar, parmak_izi=iz)
        elif iz == ayar.parmak_izi:
            print("Sertifika parmak izi: OK (eşleşiyor)")
        else:
            print(f"Sertifika parmak izi: EŞLEŞMİYOR! Beklenen {ayar.parmak_izi}, gelen {iz}. "
                  "Yazıcıyı sıfırlamadıysan ağında bir sorun olabilir; köprü bağlanmayacak.")
            return 8
    except OSError as e:
        print(f"Yazıcıya ulaşılamadı ({ayar.ip}:{MQTT_PORT}): {e}. IP doğru mu, yazıcı açık ve aynı ağda mı?")
        return 1
    gelen: list[dict] = []
    try:
        m = MqttIstemci(ayar, gelen.append)
        m.baslat()
        for _ in range(20):
            if gelen:
                break
            time.sleep(0.5)
        m.durdur()
        oz = ozet(birlestir({}, *gelen[:1])) if gelen else {}
        if gelen:
            print(f"MQTT: OK, durum {oz.get('durum')} %{oz.get('yuzde')}")
        elif m.kopma_sayisi >= 2:
            print("MQTT: bağlantı kuruluyor ama yazıcı hemen kapatıyor → genellikle YAZICI_SERI yanlış "
                  "(seri numarası 01P… olmalı, MAC adresi değil)")
        else:
            print("MQTT: rapor gelmedi (erişim kodu / seri / LAN modu?)")
        sonuc |= 0 if gelen else 1
    except ImportError:
        print("MQTT: paho-mqtt kurulu değil → pip install -r requirements-kopru.txt")
        sonuc |= 1
    except Exception as e:
        print(f"MQTT: hata: {e}")
        sonuc |= 1
    try:
        with tls_ac(ayar, KAMERA_PORT, zaman_asimi=10) as sok:
            sok.settimeout(15)
            sok.sendall(kamera_kimlik_paketi(ayar.erisim_kodu))
            kare = kare_oku(sok)
        print(f"Kamera: {'OK, ' + str(len(kare) // 1024) + ' KB kare' if kare else 'kare alınamadı'}")
    except Exception as e:
        print(f"Kamera: hata: {e}")
        sonuc |= 2
    try:
        ftp = ftps_ac(ayar)
        dosyalar = sd_listele(ftp)
        ftp.quit()
        print(f"SD kart: OK, {len(dosyalar)} timelapse")
    except Exception as e:
        print(f"SD kart: hata: {e} (SD kart takılı mı?)")
        sonuc |= 4
    print(f"ffmpeg: {video_duzenle.ffmpeg_yolu() or 'bulunamadı (FFMPEG_YOLU ayarla)'}")
    ayarlar = config.ayarlari_oku()
    print(f"Supabase: {'ayarlı' if ayarlar.supabase_var else 'SUPABASE_URL / SUPABASE_KEY eksik'}")
    return sonuc


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bicim = "%(asctime)s %(levelname)s %(message)s"
    if "--gunluk" in argv:   # arka planda (pythonw, görev zamanlayıcı) çalışırken: data/kopru.log (en çok 3×1 MB)
        from logging.handlers import RotatingFileHandler
        (config.KOK / "data").mkdir(exist_ok=True)
        isleyici = RotatingFileHandler(config.KOK / "data" / "kopru.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, format=bicim, handlers=[isleyici])
    else:
        logging.basicConfig(level=logging.INFO, format=bicim)
    for gurultulu in ("httpx", "httpcore", "hpack"):   # her 3 sn'deki Supabase isteklerini günlüğe yazma
        logging.getLogger(gurultulu).setLevel(logging.WARNING)
    ayar = kopru_ayarlari()
    if not ayar:
        print("Yazıcı ayarları eksik. .env dosyasına YAZICI_IP, YAZICI_ERISIM_KODU ve YAZICI_SERI ekle "
              "(yazıcı ekranı: Ayarlar → WLAN / Cihaz). Ayrıntı: README 'Yazıcı köprüsü'.")
        return 2
    if "--dene" in argv:
        return dene(ayar)
    if not ayar.parmak_izi:
        print("YAZICI_PARMAK_IZI eksik: önce `python -m urun_bulucu.kopru --dene` çalıştır, gösterilen izi .env'e ekle. "
              "Köprü, kimliği doğrulanmamış bir uca yazıcının erişim kodunu göndermez.")
        return 2
    ayarlar = config.ayarlari_oku()
    if not ayarlar.supabase_var:
        print("SUPABASE_URL ve SUPABASE_KEY (gizli anahtar) .env dosyasında olmalı.")
        return 2
    if sorun := seri_sorunu(ayar.seri):
        log.error("%s. Kamera ve SD kart çalışır ama canlı durum gelmez.", sorun)
    kopru = Kopru(ayar, SupabaseKopruDepo(ayarlar.supabase_url, ayarlar.supabase_key), video_duzenle.ffmpeg_yolu(),
                  bildir=telegram_bildirici(ayarlar))
    mqtt_istemci = MqttIstemci(ayar, kopru.rapor_al)
    mqtt_istemci.baslat()
    Kamera(ayar, kopru.kare_ekle).start()
    log.info("Köprü çalışıyor: %s (%s). Durdurmak için Ctrl+C.", ayar.ad, ayar.ip)
    try:
        while True:
            kopru.adim()
            if time.time() - mqtt_istemci.son_pushall >= PUSHALL_ARALIGI and mqtt_istemci.bagli:
                mqtt_istemci.pushall()
            time.sleep(ISTEK_ARALIGI)
    except KeyboardInterrupt:
        log.info("Köprü durduruldu")
    finally:
        mqtt_istemci.durdur()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
