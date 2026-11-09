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

RAPOR_KLASORU = KOK / "raporlar"
TALEP_DOSYASI = KOK / "talep" / "etsy_talep.csv"


@dataclass(frozen=True)
class Ayarlar:
    supabase_url: str
    supabase_key: str
    veritabani_yolu: Path

    @property
    def supabase_var(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


def ayarlari_oku() -> Ayarlar:
    return Ayarlar(
        supabase_url=os.getenv("SUPABASE_URL", "").strip(),
        supabase_key=os.getenv("SUPABASE_KEY", "").strip(),
        veritabani_yolu=Path(os.getenv("VERITABANI_YOLU", KOK / "data" / "urunler.db")),
    )
