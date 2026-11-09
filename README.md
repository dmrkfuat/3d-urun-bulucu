# 3D Ürün Bulucu

3D yazıcıda (Bambu Lab P1S Combo, AMS) basıp Instagram/TikTok'ta paylaşılacak popüler modelleri bulur,
her birine **içerik puanı** verir ve her gün **en iyi 10 ürünün özetini** yazar.

Özet `raporlar/` klasörüne `2026-11-09.md` gibi bir dosya olarak kaydedilir. Her üründe:
link, kapak görseli, neden seçildiği, tahmini baskı süresi, lisans durumu ve kısa bir video fikri bulunur.

---

## Şu an ne çalışıyor?

| Kaynak | Durum | Not |
|---|---|---|
| **Thingiverse** | ✅ Çalışıyor | Resmi API ile. Ücretsiz bir anahtar gerekir (aşağıda 2. adım). |
| Printables | ⏸ Beklemede | Resmi API yok; site otomatik erişime Cloudflare bot kontrolü uyguluyor. |
| **MakerWorld** | ✅ Çalışıyor | Anahtar gerekmez. Sitenin kendi JSON uçlarıyla (resmi/belgelenmiş API değil). robots.txt izinli; kullanım şartlarında otomatik erişim yasağı yok (Kasım 2026). Baskı süresi P1S profilinden gelir. |
| Etsy | ✍️ Elle liste | Etsy API'si satış adedi vermiyor ve analiz amaçlı kullanımı kısıtlıyor. Gördüğünüz çok satanları `talep/etsy_talep.csv` dosyasına yazarsınız (6. adım). |
| Google Trends | ✖ Kapalı | Sizin tercihinizle atlandı. |

Veritabanı: `.env` içinde Supabase anahtarları varsa **Supabase**, yoksa bilgisayardaki
`data/urunler.db` dosyası kullanılır. İkisi de aynı tabloları tutar: `sources`, `products`,
`product_snapshots` (günlük sayılar — "son 7 günde artış" için), `weekly_picks` (özet seçimleri).
Aynı model iki kez eklenmez; tekrar görüldüğünde sayıları güncellenir.

---

## Kurulum ve çalıştırma (adım adım)

### 1. Python

Bu bilgisayarda Python 3.13 zaten kurulu. Başka bir bilgisayarda: <https://www.python.org/downloads/>
adresinden indirip kurun; kurulumda **"Add python.exe to PATH"** kutusunu işaretleyin.

### 2. Thingiverse anahtarı (bir kerelik, ~2 dakika)

1. <https://www.thingiverse.com> adresinde hesabınızla giriş yapın.
2. <https://www.thingiverse.com/apps/create> adresine gidin.
3. Uygulama türü olarak **Web App** seçin. Ad: `3d-urun-bulucu`, açıklama: `Kişisel araştırma`.
   (Ekrandaki isimler biraz farklı olabilir.)
4. Kaydedin. Açılan sayfada **App Token** yazan değeri kopyalayın.

### 3. Anahtarı programa verin

1. Proje klasöründeki **`calistir.bat`** dosyasına çift tıklayın.
2. İlk seferde gerekli paketleri kurar ve Not Defteri'nde `.env` dosyasını açar.
3. `THINGIVERSE_TOKEN=` satırının sonuna kopyaladığınız anahtarı yapıştırın, kaydedip kapatın.

`.env` dosyası gizlidir ve GitHub'a **gönderilmez**.

### 4. Çalıştırın

`calistir.bat` dosyasına tekrar çift tıklayın. Program yaklaşık 2-3 dakikada
(istekleri yavaş ve az sayıda yaparak) modelleri toplar, puanlar ve özeti yazar.
Bitince `raporlar` klasöründeki bugünün tarihli dosyayı açın.

> İpucu: `.md` dosyalarını VS Code'da açıp sağ üstteki "Önizleme" düğmesiyle görsellerle birlikte okuyabilirsiniz.

### 5. (İsteğe bağlı) Supabase

1. <https://supabase.com> panelinde projenizi açın.
2. **SQL Editor** → `supabase/schema.sql` dosyasının içeriğini yapıştırıp **Run**.
3. **Project Settings → API** bölümünden `Project URL` ve **secret / service_role** anahtarını
   `.env` içindeki `SUPABASE_URL=` ve `SUPABASE_KEY=` satırlarına yazın.

Bundan sonra veriler Supabase'e yazılır.

### 6. Etsy talep listesi (isteğe bağlı)

Etsy'de (ABD veya Türkiye) çok satan 3D baskı ürünleri gördükçe `talep/etsy_talep.csv`
dosyasına (Excel veya Not Defteri ile) satır ekleyin:

```csv
anahtar_kelime,ulke,not
articulated dragon,US,ilk sayfada çok yorum var
kablo düzenleyici,TR,
```

Adında bu kelimeler geçen modeller **+5 puan** alır ve özette "Etsy talep listenizle eşleşiyor" yazar.

### 7. Her gün otomatik çalışma (GitHub)

Depoda `.github/workflows/gunluk.yml` her gün **20:00 (Türkiye)** saatinde çalışır,
özeti `raporlar/` klasörüne kaydeder. Bilgisayarınızın açık olması gerekmez.
Bunun için anahtarların GitHub'a da girilmesi gerekir:
GitHub'da depo → **Settings → Secrets and variables → Actions → New repository secret**:
`THINGIVERSE_TOKEN` (ve Supabase kullanıyorsanız `SUPABASE_URL`, `SUPABASE_KEY`).

Elle çalıştırmak için: depo → **Actions → Günlük ürün analizi → Run workflow**.

---

## İçerik puanı nasıl hesaplanır? (100 üzerinden)

| Bileşen | Ağırlık | Açıklama |
|---|---:|---|
| Popülerlik | 30 | Beğeni, indirme ve "make" sayısı (logaritmik, o günkü en iyiye göre) |
| Son 7 gündeki artış | 25 | Bir hafta önceki kayda göre günlük artış. İlk hafta henüz kayıt olmadığı için "yayından beri günlük ortalama" kullanılır. |
| Görsel çekicilik | 20 | Hareketli parça / print-in-place (en yüksek), çok renkli (AMS), "satisfying", ışık efekti |
| Kısa baskı | 15 | ≤2 sa en iyi; 12 saatin altı "kısa"; 12 saatten uzun düşük puan. Süre yazmıyorsa nötr. |
| Lisans | 10 | Satılabilir > NC (yalnızca içerik) > belirsiz |

Aynı kategoriden en fazla 4 ürün seçilir (çeşitlilik için).
Ayarlar (`kategoriler`, `kısa baskı süresi`, özet adedi) `urun_bulucu/config.py` dosyasındadır.

### Lisans işaretleri

- 🟢 **Satılabilir** — CC BY, CC0, GPL vb. (Atıf gerekebilir.)
- 🟡 **NC / kişisel kullanım** — Ticari kullanıma kapalı: **satmayın**, ama içerikte gösterebilirsiniz.
  MakerWorld'ün "Standard Digital File License" ve "MakerWorld Exclusive License" lisansları da
  normalde buraya girer (baskıyı satmak için tasarımcının ücretli ticari lisansı gerekir).
  **Şu anki ayar:** `config.py` → `MAKERWORLD_HEPSI_SATILABILIR = True`, yani MakerWorld
  modellerinin hepsi 🟢 sayılıyor; raporda asıl lisans metni yine yazar. Lisansa göre
  sınıflandırma için `False` yapın.
- 🔴 **Kontrol et** — Lisans yazmıyor veya standart dışı; model sayfasından kontrol edin.

Bu işaretler bilgilendirme amaçlıdır, hukuki görüş değildir.

### Bilinen sınırlar

- Thingiverse baskı süresini ayrı bir alan olarak vermez; süre yalnızca tasarımcı açıklamaya
  yazdıysa bulunur, yoksa "bilinmiyor" görünür.
- Thingiverse'in indirme sayıları bazen şişkin olabilir; bu yüzden beğeni daha ağır sayılır.
- MakerWorld'ün sayıları Thingiverse'ten çok büyüktür; popülerlik ve artış her sitenin kendi
  içinde ölçeklenir. Yine de MakerWorld modellerinin baskı süresi bilindiği için sık öne çıkarlar.
- MakerWorld uçları haber verilmeden değişebilir veya GitHub sunucularından gelen isteği
  engelleyebilir. O gün MakerWorld atlanır ve özet Thingiverse ile yazılır (`config.py` →
  `MAKERWORLD_AKTIF = False` ile tamamen kapatılabilir).
- Popüler modellerin bir kısmı marka/karakter içerir (Minecraft, Coraline vb.); lisans
  🟢 olsa bile bunların baskısını satmak marka hakkı sorunu doğurabilir.

---

## Klasör yapısı

```
calistir.bat              ← çift tıkla çalıştır
.env.example              ← anahtar şablonu (.env'in kopyalanacağı dosya)
requirements.txt          ← gerekli Python paketleri
supabase/schema.sql       ← Supabase tabloları
talep/etsy_talep.csv      ← Etsy talep listeniz
raporlar/                 ← günlük özetler
urun_bulucu/
  __main__.py             ← ana akış
  config.py               ← ayarlar (kategoriler, süreler)
  kaynaklar/thingiverse.py← Thingiverse API
  kaynaklar/makerworld.py ← MakerWorld
  analiz.py               ← baskı süresi, malzeme, görsel özellikler
  lisans.py               ← lisans sınıflandırma
  puanlama.py             ← içerik puanı
  ozet.py                 ← özet ve video fikirleri
  db.py                   ← Supabase / SQLite
tests/                    ← otomatik testler
```

Geliştirici notu: testler `.venv\Scripts\python -m pytest -q` ile çalışır.

## Sorun giderme

| Mesaj | Çözüm |
|---|---|
| `THINGIVERSE_TOKEN bulunamadı` | 2. ve 3. adım: `.env` içine anahtarı yazın. |
| `anahtarı geçersiz (401)` | Thingiverse'te uygulama sayfasından App Token'ı tekrar kopyalayın. |
| `Python bulunamadı` | 1. adım; kurulumda "Add to PATH" işaretli olmalı. |
