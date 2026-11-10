"""Ayarlar: .env okuma ve sabit tercihler."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent.parent
load_dotenv(KOK / ".env")

YAZICI = "Bambu Lab P1S Combo (AMS, 4 renk, 256x256x256 mm)"

# Bu süreden kısa baskılar "kısa" sayılır (kullanıcı tercihi).
KISA_BASKI_SAAT = 12

# Özette kaç ürün gösterilecek.
OZET_ADET = 10
# Özette aynı kategoriden en fazla kaç ürün olsun (çeşitlilik için).
KATEGORI_BASINA_EN_FAZLA = 4

# Kategori -> MakerWorld'de aranacak İngilizce terimler.
KATEGORILER: dict[str, list[str]] = {
    "Fidget ve oyuncak": ["fidget", "print in place toy"],
    "Eklemli figür": ["articulated", "flexi"],
    "Masa ve ofis düzenleyici": ["desk organizer", "pen holder"],
    "Ev dekorasyonu ve saksı": ["planter", "vase"],
    "Hediyelik": ["gift", "keychain"],
    "Telefon ve kablo aksesuarı": ["phone stand", "cable organizer"],
}

# Her terim için kaç arama sonucu alınacak.
ARAMA_ADET = 30
# Yalnızca son kaç günde yüklenen modeller aranır (trend). None = tüm zamanlar.
MAKERWORLD_GUN = 30
# Kaç modelin detayı çekilecek. Detay yanıtları büyük (~0,5 MB); siteyi yormamak için sınırlı.
MAKERWORLD_DETAY_LIMITI = 60
# Kullanıcı tercihi: MakerWorld modellerinin hepsi lisansına bakılmadan 🟢 satılabilir sayılır.
# Asıl lisans metni raporda yine gösterilir. False yapılırsa lisansa göre sınıflandırılır.
MAKERWORLD_HEPSI_SATILABILIR = True

# Trend listesinden (MakerWorld "Trending") kaç modelin detayı çekilecek.
MAKERWORLD_TREND_ADET = 15
# Trend listesindeki modellere verilen bonus puan.
TREND_BONUS = 5

# --- Maliyet tahmini (rapor ve panelde gösterilir) ---
FILAMENT_TL_KG = 800        # 1 kg filament fiyatı
SAAT_MALIYETI_TL = 3        # baskının 1 saati: elektrik (~0,1 kWh) + nozul/tabla yıpranması
FIRE_ORANI = 0.10           # hatalı baskı ve renk değişimi atığı için filamente eklenen pay
FIYAT_CARPANI = 3           # önerilen satış fiyatı = maliyet × bu sayı
EN_DUSUK_FIYAT_TL = 50      # önerilen fiyat bunun altına inmez

# Piyasaya göre fiyat: ürünün Türkiye'deki 3D baskı benzerlerinin en az PIYASA_EN_AZ_FIYATLI fiyatı
# biliniyorsa önerilen fiyat = ortanca × PIYASA_FIYAT_ORANI (biraz altında, rekabetçi); ama
# maliyetin PIYASA_EN_AZ_KAR_CARPANI katından aşağı inmez.
PIYASA_FIYAT_ORANI = 0.9
PIYASA_EN_AZ_KAR_CARPANI = 1.5
PIYASA_EN_AZ_FIYATLI = 3

# Satış potansiyeli: saat başına ve parça başına kazanç bu değerlerde tam puan alır.
SATIS_TAM_SAATLIK_TL = 100
SATIS_TAM_PARCA_KAR_TL = 150

# --- E-ticaret araştırması (SerpApi: Google Lens + Google Alışveriş; ücretsiz plan ayda 250 arama) ---
PAZAR_GUNLUK_ADET = 3        # günde kaç ürün (ürün başına 2 arama: 3 × 2 × 30 = 180 < 250)
PAZAR_YENILEME_GUN = 14      # aynı ürün bu kadar gün geçmeden tekrar aranmaz
# Az sonuç gelirse daha geniş metinle (eş anlamlılar / ilk kelime atılmış) bir Alışveriş araması daha.
# Yalnızca SerpApi'de bu ay PAZAR_YEDEK_KOTA_ESIGI'nden fazla hak kaldıysa yapılır.
PAZAR_YEDEK_ARAMA = True
PAZAR_YEDEK_ALT_SINIR = 3       # bundan az 3D baskı satış sonucu gelirse
PAZAR_YEDEK_KOTA_ESIGI = 40
# Yalnızca bu sitelerden gelen sonuçlar tutulur: alan adı → gösterilecek ad.
# Bağlantının alan adı bunlardan biri (veya alt alanı) olmalı; Google Alışveriş sonuçlarında
# bağlantı Google'a gittiği için satıcı adı (ör. "Trendyol", "trendyol.com") eşleşmesi kullanılır.
PAZAR_SITELERI = {
    "trendyol.com": "Trendyol",
    "hepsiburada.com": "Hepsiburada",
    "n11.com": "n11",
    "amazon.com.tr": "Amazon TR",
    "ciceksepeti.com": "Çiçeksepeti",
    "pazarama.com": "Pazarama",
    "pttavm.com": "PttAVM",
    "etsy.com": "Etsy",
}
# Birebir karşılaştırma: yalnızca 3D baskı ürünler sayılır. Google Alışveriş'te 3D baskı satan
# bağımsız Türk mağazaları (ör. kendi sitesi olan atölyeler) da tutulsun mu? False: yalnız PAZAR_SITELERI.
PAZAR_BAGIMSIZ_MAGAZALAR = True
PAZAR_EN_DUSUK_FIYAT_TL = 20     # bunun altı (dosya satışı, hatalı fiyat) sayılmaz
# Bu tarihten önce yapılmış aramalar eski kurallarla yapıldı (3D şartı, sosyal medya ve görselden
# kelime yokken, Lens yalnız görselle ararken); yeniden aranır.
PAZAR_KURAL_TARIHI = "2026-11-09T17:49:00+00:00"

# --- Pazar keşfi: Türkiye'de çok satan 3D baskılar → MakerWorld'deki birebir modeli (kesif.py) ---
KESIF_ARALIK_GUN = 7          # haftada bir (günlük analizle birlikte)
KESIF_SORGULARI = [           # Google Alışveriş aramaları (her biri 1 SerpApi araması); aktif sezon eklenir
    "3d baskı fidget", "3d baskı oyuncak", "3d baskı figür", "3d baskı dekoratif",
    "3d baskı saksı", "3d baskı anahtarlık", "3d baskı masaüstü düzenleyici", "3d baskı lamba",
]
KESIF_EN_AZ_ILAN = 2          # en az bu kadar ayrı ilanı olan ürünler listelenir
KESIF_EN_AZ_SITE = 2          # ve en az bu kadar farklı sitede/mağazada satılan
KESIF_RAPOR_ADET = 12         # raporda en çok kaç ürün
KESIF_LENS_ADET = 8           # en çok ilanlı kaç ürünün görseliyle Lens araması yapılır
KESIF_YENILEME_GUN = 28       # aynı ürünün Lens sonucu bu kadar gün yeniden kullanılır (kota)
KESIF_GORSEL_ESLESME = 2      # Lens'te çıkan en çok kaç MakerWorld modeli
KESIF_ISIM_ESLESME = 2        # isimle MakerWorld aramasından en çok kaç model
KESIF_KOTA_ESIGI = 50         # SerpApi'de bundan az hak kaldıysa keşif yapılmaz (günlük arama korunur)

# --- Instagram (resmi Instagram API, "Instagram Login" ile; şifreyle giriş/bot yok) ---
# Açıklama metni her gün ilk 10 için üretilir (anahtar gerekmez). Paylaşım için INSTAGRAM_TOKEN
# (GitHub Secrets) ve Supabase'te supabase/guncelleme_2026-11-10_instagram.sql gerekir.
INSTAGRAM_API = "https://graph.instagram.com/v25.0"   # v25.0: Temmuz 2028'e kadar geçerli
INSTAGRAM_TOKEN_API = "https://graph.instagram.com/refresh_access_token"
INSTAGRAM_ETIKET_ADET = 15          # açıklamadaki etiket sayısı (Instagram sınırı 30)
INSTAGRAM_ACIKLAMA_SINIRI = 2200    # Instagram sınırı
INSTAGRAM_TOKEN_YENILEME_GUN = 7    # token (60 gün geçerli) bu kadar günde bir yenilenir
INSTAGRAM_BEKLEME_SN = 240          # bir çalışmada videonun işlenmesi en fazla bu kadar beklenir
INSTAGRAM_KONTROL_ARALIGI_SN = 20
INSTAGRAM_IMZALI_URL_SN = 6 * 3600  # Instagram'ın videoyu indirmesi için geçici bağlantı süresi
INSTAGRAM_CALISMA_BASINA_EN_FAZLA = 3  # bir çalışmada en fazla kaç gönderi başlatılır
INSTAGRAM_PAYLASINCA_VIDEOYU_SIL = True  # depolama dolmasın (Supabase ücretsiz: 1 GB)
INSTAGRAM_DEPO = "instagram"        # Supabase Storage alanı (bucket) adı
INSTAGRAM_DEPO_SINIRI_MB = 50       # depolama alanının dosya sınırı (SQL'deki file_size_limit)
# Paylaşmadan önce video düzenleme (ffmpeg): 9:16, başta kanca yazısı, sonda DM kartı.
# Panelde gönderi başına kapatılabilir ("Videoyu otomatik düzenle" kutusu).
INSTAGRAM_VIDEO_DUZENLE = True
INSTAGRAM_KANCA_SN = 2.5            # kanca yazısı videonun ilk kaç saniyesinde görünür
INSTAGRAM_SON_KART_SN = 2.5         # sona eklenen "DM" kartının süresi (0: eklenmez)
INSTAGRAM_SON_KART = ("SİPARİŞ İÇİN DM AT", "İstediğin renkte basılır")
INSTAGRAM_DUZENLEME_SURESI_SN = 400  # bir videonun düzenlenmesi en fazla bu kadar sürebilir

# Web paneli (GitHub Pages). Telegram mesajının sonunda bağlantısı verilir.
PANEL_URL = "https://dmrkfuat.github.io/3d-urun-bulucu/"

RAPOR_KLASORU = KOK / "raporlar"
TALEP_DOSYASI = KOK / "talep" / "etsy_talep.csv"


@dataclass(frozen=True)
class Ayarlar:
    supabase_url: str
    supabase_key: str
    veritabani_yolu: Path
    telegram_token: str = ""
    telegram_chat_id: str = ""
    panel_url: str = ""
    serpapi_key: str = ""
    instagram_token: str = ""

    @property
    def supabase_var(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


def ayarlari_oku() -> Ayarlar:
    return Ayarlar(
        supabase_url=os.getenv("SUPABASE_URL", "").strip(),
        supabase_key=os.getenv("SUPABASE_KEY", "").strip(),
        veritabani_yolu=Path(os.getenv("VERITABANI_YOLU", KOK / "data" / "urunler.db")),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        panel_url=os.getenv("PANEL_URL", "").strip() or PANEL_URL,
        serpapi_key=os.getenv("SERPAPI_KEY", "").strip(),
        instagram_token=os.getenv("INSTAGRAM_TOKEN", "").strip(),
    )
