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

# --- E-ticaret araştırması (SerpApi: Google Lens + Google Alışveriş; ücretsiz plan ayda 250 arama) ---
PAZAR_GUNLUK_ADET = 3        # günde kaç ürün (ürün başına 2 arama: 3 × 2 × 30 = 180 < 250)
PAZAR_YENILEME_GUN = 14      # aynı ürün bu kadar gün geçmeden tekrar aranmaz
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
# kelime yokken); yeniden aranır.
PAZAR_KURAL_TARIHI = "2026-11-09T17:39:00+00:00"

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
    )
