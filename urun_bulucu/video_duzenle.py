"""Reels videosunu paylaşmadan önce hazırlar (ffmpeg; ücretsiz, yapay zekâ servisi yok).

- Görüntü dikey 1080x1920'ye (9:16) getirilir; yatay/kare videoların boşluğu videonun
  bulanıklaştırılmış hâliyle doldurulur (siyah bant yok).
- İlk INSTAGRAM_KANCA_SN saniyede açıklamanın ilk satırı (kanca) büyük harflerle üstte yazar.
- Sona INSTAGRAM_SON_KART_SN saniyelik kart eklenir: son kare donar, kararır, "SİPARİŞ İÇİN DM AT".
- Ses yoksa sessiz ses kanalı eklenir; çıktı H.264 + AAC MP4 (Instagram'ın istediği biçim).

ffmpeg GitHub Actions'ta apt ile kurulur. Yerelde PATH'te yoksa FFMPEG_YOLU ortam değişkeniyle
gösterilebilir; bulunamazsa video düzenlenmeden paylaşılır.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unicodedata
from pathlib import Path

from . import config

GENISLIK, YUKSEKLIK, FPS = 1080, 1920, 30
FONTLAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


class VideoDuzenlemeHatasi(RuntimeError):
    pass


# Güvenlik: yüklenen dosya ne olursa olsun yalnızca MP4/MOV olarak açılır (-f mov). Uzantısı .mp4
# olan bir HLS/concat listesi ffmpeg'e yerel dosya okutamaz veya dış adrese istek attıramaz;
# yalnızca yerel dosya protokolü açıktır. ffmpeg, sırları (Supabase/Instagram anahtarları)
# içermeyen sade bir ortamla çalıştırılır.
GIRIS_SECENEKLERI = ["-f", "mov", "-protocol_whitelist", "file"]


def _ortam() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}


def ffmpeg_yolu() -> str | None:
    ozel = os.getenv("FFMPEG_YOLU", "").strip()
    if ozel and Path(ozel).is_file():
        return ozel
    return shutil.which("ffmpeg")


def font_bul() -> str | None:
    return next((f for f in FONTLAR if Path(f).is_file()), None)


def hazir_yolu(video_yolu: str) -> str:
    """Düzenlenmiş videonun depodaki adı: '7/123.mov' → '7/123_hazir.mp4'."""
    return re.sub(r"\.[^./]+$", "", video_yolu) + "_hazir.mp4"


def tr_buyuk(metin: str) -> str:
    """Türkçe büyük harf (str.upper 'i'yi 'I' yapar)."""
    return metin.replace("i", "İ").replace("ı", "I").upper()


def yazilabilir(metin: str) -> str:
    """Fontta olmayan emoji ve sembolleri atar, boşlukları sadeleştirir."""
    temiz = "".join(c for c in metin if unicodedata.category(c) not in ("So", "Sk", "Cf", "Cs", "Co", "Cn")
                    and c != "\ufe0f")
    return re.sub(r"\s+", " ", temiz).strip(" -–—·,")


def kanca_metni(aciklama: str) -> str:
    """Açıklamanın yazı içeren ilk satırı (etiket satırı değil), emojisiz."""
    for satir in (aciklama or "").splitlines():
        s = yazilabilir(satir)
        if s and not s.startswith("#"):
            return s
    return ""


def satirlara_bol(metin: str, genislik: int = 18, en_fazla: int = 4) -> list[str]:
    satirlar = textwrap.wrap(metin, width=genislik, break_long_words=True)
    if len(satirlar) > en_fazla:
        satirlar = satirlar[:en_fazla]
        satirlar[-1] = satirlar[-1][: genislik - 1].rstrip() + "…"
    return satirlar


def bilgi(ffmpeg: str, giris: Path) -> tuple[float, bool]:
    """(süre sn, ses var mı) — ffprobe gerekmesin diye ffmpeg'in kendi çıktısından okunur."""
    sonuc = subprocess.run([ffmpeg, "-hide_banner", *GIRIS_SECENEKLERI, "-i", str(giris)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60, env=_ortam())
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", sonuc.stderr)
    if not m:
        raise VideoDuzenlemeHatasi("video okunamadı (bozuk veya desteklenmeyen biçim)")
    sure = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return sure, bool(re.search(r"Stream #\S+.*: Audio:", sonuc.stderr))


def _yazi(dosya: str, boyut: int, y: str, sart: str, kutu: bool) -> str:
    """drawtext filtresi; metin dosyadan okunur (kaçış derdi yok), yatayda ortalanır."""
    f = (f"drawtext=fontfile=font.ttf:textfile={dosya}:expansion=none:fontsize={boyut}:fontcolor=white"
         f":x=(w-text_w)/2:y={y}:enable='{sart}'")
    if kutu:
        f += ":box=1:boxcolor=black@0.6:boxborderw=22"
    else:
        f += ":shadowcolor=black@0.7:shadowx=3:shadowy=3"
    return f


def filtre(kanca: list[str], son: list[str], sure: float, ses_var: bool) -> tuple[str, float]:
    """filter_complex metni ve kanca süresi. Metin dosyaları: k0.txt…, s0.txt…"""
    kanca_sn = min(config.INSTAGRAM_KANCA_SN, max(sure - 0.5, 0.5))
    son_sn = config.INSTAGRAM_SON_KART_SN
    v = [
        f"[0:v]split=2[a][b]",
        f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
        f"scale={GENISLIK}:{YUKSEKLIK}[arka]",
        f"[b]scale={GENISLIK}:{YUKSEKLIK}:force_original_aspect_ratio=decrease[on]",
    ]
    zincir = ["overlay=(W-w)/2:(H-h)/2", f"fps={FPS}", "format=yuv420p", "setsar=1"]
    if son:
        zincir.append(f"tpad=stop_mode=clone:stop_duration={son_sn}")
    boyut, aralik = 76, 112
    y0 = int(YUKSEKLIK * 0.16)
    for i in range(len(kanca)):
        zincir.append(_yazi(f"k{i}.txt", boyut, str(y0 + i * aralik), f"lt(t,{kanca_sn:.2f})", kutu=True))
    if son:
        sart = f"gte(t,{sure:.3f})"
        zincir.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.62:t=fill:enable='{sart}'")
        ust = YUKSEKLIK // 2 - 90
        for i in range(len(son)):
            zincir.append(_yazi(f"s{i}.txt", 88 if i == 0 else 54, str(ust + (0 if i == 0 else 50 + i * 80)),
                                sart, kutu=False))
    v.append("[arka][on]" + ",".join(zincir) + "[v]")
    if ses_var:
        v.append("[0:a]aresample=44100,apad[s]")
    return ";".join(v), kanca_sn


def duzenle(giris: Path, cikis: Path, aciklama: str, ffmpeg: str | None = None) -> dict:
    """Videoyu hazırlar; {'sure', 'kanca'} döndürür. Sorun olursa VideoDuzenlemeHatasi."""
    ffmpeg = ffmpeg or ffmpeg_yolu()
    if not ffmpeg:
        raise VideoDuzenlemeHatasi("ffmpeg bulunamadı")
    font = font_bul()
    if not font:
        raise VideoDuzenlemeHatasi("yazı tipi bulunamadı")
    sure, ses_var = bilgi(ffmpeg, giris)
    if sure < 3:
        raise VideoDuzenlemeHatasi(f"video çok kısa ({sure:.1f} sn; Instagram en az 3 sn ister)")
    kanca = satirlara_bol(tr_buyuk(kanca_metni(aciklama)))
    son = list(config.INSTAGRAM_SON_KART) if config.INSTAGRAM_SON_KART_SN > 0 else []
    toplam = sure + (config.INSTAGRAM_SON_KART_SN if son else 0)
    # Depolama sınırına sığsın: toplam bit hızı ~ (sınırın %85'i) / süre; en fazla 6 Mbit/sn.
    butce = config.INSTAGRAM_DEPO_SINIRI_MB * 8_000_000 * 0.85 / toplam
    video_hizi = int(max(min(6_000_000, butce - 160_000), 400_000))

    with tempfile.TemporaryDirectory() as d:
        klasor = Path(d)
        shutil.copyfile(font, klasor / "font.ttf")
        for ad, satirlar in (("k", kanca), ("s", son)):
            for i, s in enumerate(satirlar):
                (klasor / f"{ad}{i}.txt").write_text(s, encoding="utf-8")
        filtre_metni, kanca_sn = filtre(kanca, son, sure, ses_var)
        komut = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *GIRIS_SECENEKLERI,
                 "-i", str(Path(giris).resolve())]
        if not ses_var:
            komut += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        komut += ["-filter_complex", filtre_metni, "-map", "[v]", "-map", "[s]" if ses_var else "1:a",
                  "-t", f"{toplam:.3f}",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high",
                  "-maxrate", str(video_hizi), "-bufsize", str(video_hizi * 2), "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
                  str(Path(cikis).resolve())]
        try:
            sonuc = subprocess.run(komut, cwd=klasor, env=_ortam(), capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=config.INSTAGRAM_DUZENLEME_SURESI_SN)
        except subprocess.TimeoutExpired as e:
            raise VideoDuzenlemeHatasi("video düzenleme çok uzun sürdü") from e
    if sonuc.returncode != 0 or not Path(cikis).is_file():
        raise VideoDuzenlemeHatasi("ffmpeg hatası: " + (sonuc.stderr.strip().splitlines() or ["?"])[-1][:200])
    return {"sure": toplam, "kanca": kanca, "kanca_sn": kanca_sn}
