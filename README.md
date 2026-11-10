# 3D Ürün Bulucu

3D yazıcıda (Bambu Lab P1S Combo, AMS) basıp Instagram/TikTok'ta paylaşılacak popüler modelleri bulur,
her birine **içerik puanı** verir ve her gün **en iyi 10 ürünün özetini** yazar.

Özet `raporlar/` klasörüne `2026-11-09.md` gibi bir dosya olarak kaydedilir. Her üründe:
link, kapak görseli, neden seçildiği, tahmini baskı süresi, **maliyet → önerilen fiyat**, lisans durumu
ve modele özel bir **video planı** (kanca, çekim adımları, açıklama, hashtag) bulunur.

- **Telegram:** her gün ilk 3 ürün kapak görseliyle telefona gelir; analiz çalışmazsa hata uyarısı,
  takip edilen tasarımcılar yeni model yüklerse bildirim gelir.
- **Sezon takvimi:** Yılbaşı, Sevgililer Günü, Anneler/Babalar Günü, bayramlar, Cadılar Bayramı,
  okula dönüş ve Öğretmenler Günü'nden 4-8 hafta önce temaya uyan modeller +5 puan alır (`sezon.py`).
- **E-ticaret araştırması (isteğe bağlı):** özetteki ürünlerin (1. sıradan başlayarak) kapak görseli + "<Türkçe ad> 3d baskı" metniyle Google
  Lens (SerpApi; GIF kapaklar yerine gerçek baskı fotoğrafı) ve aynı metinle Google Alışveriş araması.
  Görsel eşleşmeler yalnızca başlığı ürünle ilgili bir kelime içeriyorsa sayılır; Temu/DHgate gibi
  yurt dışı toptan siteler bağımsız mağaza sayılmaz.
  Arama metnine ürün tipi eklenir (ad + MakerWorld etiketlerinden: "grinch mini figür", "yılbaşı süsü").
  3'ten az sonuç gelirse ve SerpApi'de 40'tan fazla hak kaldıysa daha geniş metinle ("fidget" →
  "stres oyuncağı") bir arama daha yapılır (`PAZAR_YEDEK_ARAMA`). **Yalnızca 3D baskı ürünler** karşılaştırılır (fabrika
  üretimi ve dijital model dosyaları elenir). Trendyol, Hepsiburada, n11, Amazon TR, Çiçeksepeti, Pazarama,
  PttAVM, Etsy ve 3D baskı satan bağımsız Türk mağazaları tutulur (`config.PAZAR_SITELERI`,
  `PAZAR_BAGIMSIZ_MAGAZALAR`). Siteler doğrudan taranmaz (Trendyol
  robots.txt aramayı yasaklıyor, Hepsiburada/n11 otomatik isteği engelliyor). `SERPAPI_KEY` gerekir.
- **Web paneli:** <https://dmrkfuat.github.io/3d-urun-bulucu/> — günlük listeler, indirme grafiği,
  "bastım / videosunu çektim / sattım" işaretleri, **tüm ürünlerde arama/sıralama**, **baskı planı**
  (toplam süre, kaç gün, renk renk filament listesi), **tasarımcı takibi** ve "İşaretlerim"de
  kategoriye göre satış ve kâr. Yalnızca izinli e-postayla giriş yapılır.

---

## Şu an ne çalışıyor?

| Kaynak | Durum | Not |
|---|---|---|
| **MakerWorld** | ✅ Çalışıyor | Anahtar gerekmez. Sitenin kendi JSON uçlarıyla (resmi/belgelenmiş API değil). robots.txt izinli; kullanım şartlarında otomatik erişim yasağı yok (Kasım 2026). Baskı süresi P1S profilinden gelir. |
| Thingiverse | ✖ Kaldırıldı | Kasım 2026'da API'nin önüne Cloudflare bot kontrolü geldi (403). Eski kayıtlar veritabanında duruyor. |
| Printables | ⏸ Beklemede | Resmi API yok; site otomatik erişime Cloudflare bot kontrolü uyguluyor. |
| Etsy | ✍️ Elle liste | Etsy API'si satış adedi vermiyor ve analiz amaçlı kullanımı kısıtlıyor. Gördüğünüz çok satanları `talep/etsy_talep.csv` dosyasına yazarsınız (4. adım). |
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

### 2. Çalıştırın

Proje klasöründeki **`calistir.bat`** dosyasına çift tıklayın. İlk seferde gerekli paketleri kurar.
Program yaklaşık 2-3 dakikada (istekleri yavaş ve az sayıda yaparak) MakerWorld'den modelleri
toplar, puanlar ve özeti yazar. Anahtar gerekmez.
Bitince `raporlar` klasöründeki bugünün tarihli dosyayı açın.

> İpucu: `.md` dosyalarını VS Code'da açıp sağ üstteki "Önizleme" düğmesiyle görsellerle birlikte okuyabilirsiniz.

### 3. (İsteğe bağlı) Supabase

1. <https://supabase.com> panelinde projenizi açın.
2. **SQL Editor** → `supabase/schema.sql` dosyasının içeriğini yapıştırıp **Run**.
3. **Project Settings → API Keys** bölümünden `Project URL` ve **secret** (`sb_secret_...`) anahtarını
   `.env` içindeki `SUPABASE_URL=` ve `SUPABASE_KEY=` satırlarına yazın.

Bundan sonra veriler Supabase'e yazılır. `.env` dosyası gizlidir ve GitHub'a **gönderilmez**.

### 4. Etsy talep listesi (isteğe bağlı)

Etsy'de (ABD veya Türkiye) çok satan 3D baskı ürünleri gördükçe `talep/etsy_talep.csv`
dosyasına (Excel veya Not Defteri ile) satır ekleyin:

```csv
anahtar_kelime,ulke,not
articulated dragon,US,ilk sayfada çok yorum var
kablo düzenleyici,TR,
```

Adında bu kelimeler geçen modeller **+5 puan** alır ve özette "Etsy talep listenizle eşleşiyor" yazar.

### 5. Her gün otomatik çalışma (GitHub)

Depoda `.github/workflows/gunluk.yml` her gün **20:00 (Türkiye)** saatinde çalışır,
özeti `raporlar/` klasörüne kaydeder. Bilgisayarınızın açık olması gerekmez.
Supabase kullanıyorsanız anahtarların GitHub'a da girilmesi gerekir:
GitHub'da depo → **Settings → Secrets and variables → Actions → New repository secret**:
`SUPABASE_URL`, `SUPABASE_KEY`.

Elle çalıştırmak için: depo → **Actions → Günlük ürün analizi → Run workflow**.

### 6. Telegram bildirimi (isteğe bağlı)

1. Telegram'da **@BotFather** → `/newbot` → ad ve sonu `bot` ile biten kullanıcı adı verin.
2. Verilen anahtarı `.env` içine `TELEGRAM_BOT_TOKEN=` olarak yazın.
3. Kendi botunuzu açıp **Başlat**'a basın; sohbet numarasını (`TELEGRAM_CHAT_ID`) bulmak için gerekir.
4. GitHub Secrets'a `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ekleyin.

### 6b. E-ticaret araştırması (isteğe bağlı)

1. <https://serpapi.com> adresinde ücretsiz hesap açın (ayda 250 arama).
2. **Dashboard → API Key** değerini `.env` içine `SERPAPI_KEY=` olarak yazın ve GitHub Secrets'a
   `SERPAPI_KEY` adıyla ekleyin.
3. Günde en fazla 3 ürün aranır (ürün başına 2 arama; `config.py` → `PAZAR_GUNLUK_ADET`), aynı ürün 14 gün içinde tekrar
   aranmaz. Görsel benzerliği kesin eşleşme değildir; sonuçlar "benzer ürün" olarak okunmalıdır.

**Pazar keşfi: Türkiye'de çok satan 3D baskılar → MakerWorld modeli** (`kesif.py`, haftada bir)

Günlük analizin tersi: MakerWorld'de popüler olandan değil, Türkiye'de satılandan başlar.
1. Google Alışveriş'te kategori aramaları (`config.py` → `KESIF_SORGULARI`; yaklaşan sezon eklenir).
2. Aynı ürünün ilanları kümelenir. Google Alışveriş satış adedi vermediği için talep işareti, aynı
   ürünü satan **farklı satıcı sayısıdır** (satıcılar satan ürünü kopyalar). Satıcı, başlığın başındaki
   markadan anlaşılır ("Bezos 3D Baskı ..."); bir satıcının her renk için açtığı ilanlar tek sayılır,
   tek mağazanın ürünleri listelenmez (en az 2 satıcı). Tek sitede (ör. yalnızca Trendyol'da) birden
   çok satıcının sattığı ürünler de sayılır.
3. En çok satılan 8 ürünün fotoğrafıyla Google Lens: aynı ürünü satan diğer ilanlar eklenir ve
   sonuçlarda MakerWorld model sayfası çıkarsa **🎯 görsel eşleşme** (birebir kaynak model) olur.
4. Ürün adının İngilizcesiyle MakerWorld'de ücretsiz arama: **🔤 isimle bulundu**. Yalnızca en az
   2 ayırt edici kelimenin hepsi model adında geçiyorsa; panelde görseller yan yana gösterilir.
5. Eşleşen modelin baskı süresi ve maliyeti MakerWorld'den alınır; kâr = piyasa ortancası − maliyet.
6. **Trendyol yelpazesi:** her kategori Google Alışveriş'in kendi "Mağazalar → Trendyol" süzgeciyle bir
   kez daha aranır (sorgu başına +1 arama; `KESIF_TRENDYOL`). Trendyol'a hiç istek atılmaz; Google'ın
   dizini kullanılır. Raporda kategori başına Trendyol'daki 3D baskı ürün sayısı, fiyat aralığı ve
   ortancası, en çok ürünü olan rakip satıcılar ve öne çıkan ürünler yer alır.

Trendyol/Hepsiburada sayfaları doğrudan taranmaz: arama sayfaları `robots.txt` ile otomatik
programlara kapalıdır ve bot koruması vardır (Kasım 2026'da tek istek bile 403 aldı).

Sonuç: `raporlar/cok-satanlar-TARİH.md`, Telegram mesajı ve panelde **Çok satanlar** sekmesi.
Kota: haftada ~28 arama (ayda ~120; 10 kategori + 10 Trendyol süzgeçli + 8 görsel); SerpApi'de 50'den az hak kaldıysa atlanır, aynı ürünün Lens
sonucu 28 gün yeniden kullanılır. Elle çalıştırma: `python -m urun_bulucu.kesif` (`--telegram` ile
mesaj da gönderilir). Supabase'te bir kez `supabase/guncelleme_2026-11-10_kesif.sql` çalıştırılmalıdır.

### 6c. Instagram otomasyonu (isteğe bağlı)

Yalnızca **resmi Instagram API'si** kullanılır (şifreyle giriş, bot veya tarayıcı otomasyonu yok).

**Ne yapar?**
- Her gün ilk 10 ürünün her biri için Türkçe gönderi açıklaması yazılır: videonun ilk cümlesi, Türkçe
  ürün adı, baskı bilgisi, "DM ile sipariş" çağrısı, tasarımcı adı ve en fazla 15 etiket
  (MakerWorld'ün yabancı etiketleri Türkçeye çevrilir). İlk 3'ün açıklaması Telegram'a
  dokununca kopyalanan bloklar hâlinde gelir; hepsi panelde kartın "📸 Instagram'a planla" bölümündedir.
  **Bunun için kurulum gerekmez.**
- Paylaşım: ürünü basıp videosunu çekersin, panelde açıklamayı düzenleyip videoyu yüklersin ve saat
  seçersin. GitHub her 15 dakikada bir `.github/workflows/instagram.yml`'i çalıştırır; saati gelen
  video **Reels** olarak paylaşılır, ürüne "Videosunu çektim" işareti konur, bağlantı Telegram'a gelir.
  Paylaşılan video depodan silinir. Hata olursa Telegram'a yazılır; panelin **Instagram** sekmesinden
  "Tekrar dene" denebilir.
- Otomatik video düzenleme (ffmpeg, ücretsiz; panelde "Videoyu otomatik düzenle" kutusu, varsayılan
  açık): video dikey 1080×1920'ye getirilir (yatay/kare videoda boşluk videonun bulanık hâliyle dolar),
  ilk 2,5 saniyede açıklamanın ilk satırı büyük harflerle üstte yazar, sona 2,5 saniyelik
  "SİPARİŞ İÇİN DM AT" kartı eklenir (son kare donar ve kararır). Emojiler videoya yazılmaz.
  Düzenleme başarısız olursa video olduğu gibi paylaşılır ve Telegram'a not düşülür. Ayarlar:
  `config.py` → `INSTAGRAM_VIDEO_DUZENLE`, `INSTAGRAM_KANCA_SN`, `INSTAGRAM_SON_KART…`. Yerelde
  denemek için ffmpeg PATH'te olmalı veya `.env` → `FFMPEG_YOLU=` ile gösterilmeli.

**Bir kerelik kurulum**
1. Instagram hesabını **profesyonel hesaba** çevir: Ayarlar → Hesap türü ve araçlar →
   Profesyonel hesaba geç (İşletme veya İçerik üreticisi).
2. <https://developers.facebook.com> → **Uygulama oluştur** (tür: İşletme) → **Instagram** ürününü
   ekle → **API setup with Instagram business login** → hesabını ekle → **Generate token**.
   İzinler: `instagram_business_basic`, `instagram_business_content_publish`. Token 60 gün geçerlidir;
   sistem haftada bir kendisi yeniler (yenisi Supabase'te dışarıya kapalı `gizli_ayarlar` tablosunda tutulur).
3. Token'ı GitHub'da **Settings → Secrets and variables → Actions** altına `INSTAGRAM_TOKEN` adıyla ekle
   (yerelde denemek için `.env` → `INSTAGRAM_TOKEN=`). Token hiçbir yere yazdırılmaz.
4. Supabase **SQL Editor** → `supabase/guncelleme_2026-11-10_instagram.sql` → **Run**
   (açıklama sütunu, gönderi tablosu, kapalı video deposu ve izinler).

**Video şartları (Instagram):** MP4 veya MOV, 3 sn–15 dk, dikey 9:16 önerilir, en fazla 1920 px
genişlik. Panelden yükleme sınırı 50 MB'tır (Supabase ücretsiz planı); telefonda 1080p dışa aktarmak
yeterlidir. Instagram API ile günde en fazla 100 gönderi paylaşılabilir.

**Zamanlama:** GitHub zamanlanmış görevleri birkaç dakika (yoğun saatlerde 15-30 dk) gecikebilir;
gönderi seçtiğin saatten biraz sonra çıkabilir.

**Telif notu:** Paylaşılan video ve fotoğraflar senin kendi baskının olmalı. MakerWorld'deki tasarımcı
fotoğrafları tasarımcıya aittir; açıklamada tasarımcı adı otomatik yazılır.

### 7. Web paneli

Panel `panel/` klasöründedir ve GitHub Pages ile yayınlanır (`.github/workflows/panel.yml`).
Bir kerelik kurulum:
1. Supabase **SQL Editor** → `supabase/guncelleme_2026-11-09_panel.sql` → **Run**.
2. **Authentication → URL Configuration → Site URL**: panel adresi.
3. **Publishable key**'i `panel/ayar.js` dosyasına yazın (bu anahtar tarayıcı için tasarlanmıştır;
   **secret** anahtarı asla buraya yazmayın — yayın iş akışı bunu kontrol eder).
4. Giriş izni: e-posta `panel_izinli` tablosuna eklenir ve Supabase'te kullanıcı oluşturulur
   (**Authentication → Users → Add user**). Panelde e-postanızı yazınca giriş bağlantısı gelir.

---

## İçerik puanı nasıl hesaplanır? (100 üzerinden)

| Bileşen | Ağırlık | Açıklama |
|---|---:|---|
| Popülerlik | 25 | Beğeni, indirme ve baskı sayısı (logaritmik, o günkü en iyiye göre) |
| Son 7 gündeki artış | 25 | Bir hafta önceki kayda göre günlük artış. İlk hafta henüz kayıt olmadığı için "yayından beri günlük ortalama" kullanılır. |
| Satış potansiyeli | 20 | Saat başına kazanç (%40), parça başına kâr (%30), fiyat aralığı (%30: ≤300 TL en iyi, 1000 TL üstü zor satar) |
| Görsel çekicilik | 15 | Hareketli parça / print-in-place (en yüksek), çok renkli (AMS), "satisfying", ışık efekti |
| Kısa baskı | 10 | ≤2 sa en iyi; 12 saatin altı "kısa"; 12 saatten uzun düşük puan. Süre yazmıyorsa nötr. |
| Lisans | 5 | Satılabilir > NC (yalnızca içerik) > belirsiz |
| Bonus | +5 / +5 / +5 | Etsy talep listesiyle eşleşme; MakerWorld "Trending" listesinde olma; sezon ürünü |
| Piyasa bonusu | −5…+5 | E-ticarette aranmış ürünlerde: Türkiye'deki 3D baskı benzerlerinin ortancası maliyetin ≥5 katı +5, ≥3 katı +3, 1,5 katından az −3; 12+ satış sonucu (kalabalık pazar) −2 |

Aynı kategoriden en fazla 4 ürün seçilir (çeşitlilik için).

### Maliyet tahmini

`maliyet = gram × (1 + fire) × filament TL/kg ÷ 1000 + baskı saati × saat maliyeti`,
`önerilen fiyat = maliyet × fiyat çarpanı` (en az `EN_DUSUK_FIYAT_TL`, 5 TL'ye yuvarlanır).
Gram ve süre modelin P1S profilinden gelir. Varsayılanlar `config.py`'de: 800 TL/kg, saatlik 3 TL,
%10 fire, ×3, en az 50 TL. Etsy/kargo ücreti ve işçilik dahil değildir.

**Piyasaya göre fiyat:** ürün e-ticarette aranmışsa ve en az 3 fiyatlı 3D baskı benzeri bulunduysa
önerilen fiyat `ortanca × 0,9` olur (rekabetçi), ama maliyetin 1,5 katının altına inmez
(`PIYASA_FIYAT_ORANI`, `PIYASA_EN_AZ_KAR_CARPANI`). Raporda maliyete göre fiyat da yazılır.
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

- Baskı süresi modelin P1S profilinden gelir; P1S profili yoksa varsayılan profil kullanılır
  (başka yazıcı için hazırlanmış olabilir). Profil hiç yoksa "bilinmiyor" görünür.
- Tek kaynak MakerWorld olduğu için, MakerWorld uçları değişir veya istekleri engellerse
  o gün özet yazılamaz ("MakerWorld'den veri alınamadı" hatası).
- Popüler modellerin bir kısmı marka/karakter içerir (Minecraft, Coraline vb.); lisans
  🟢 olsa bile bunların baskısını satmak marka hakkı sorunu doğurabilir.

---

## Klasör yapısı

```
calistir.bat              ← çift tıkla çalıştır
.env.example              ← anahtar şablonu (.env'in kopyalanacağı dosya)
requirements.txt          ← gerekli Python paketleri
supabase/schema.sql       ← Supabase tabloları (+ guncelleme_*.sql)
talep/etsy_talep.csv      ← Etsy talep listeniz
raporlar/                 ← günlük özetler
panel/                    ← web paneli (GitHub Pages)
urun_bulucu/
  __main__.py             ← ana akış
  config.py               ← ayarlar (kategoriler, süreler, maliyet)
  kaynaklar/makerworld.py ← MakerWorld (arama + Trending)
  analiz.py               ← baskı süresi, malzeme, görsel özellikler
  lisans.py               ← lisans sınıflandırma
  puanlama.py             ← içerik puanı
  maliyet.py              ← maliyet, önerilen fiyat, saatlik kazanç
  video.py                ← modele özel video planı
  sezon.py                ← sezon takvimi
  tasarimci.py            ← tasarımcı takibi
  pazar.py                ← e-ticaret araştırması (SerpApi Google Lens)
  kesif.py                ← pazar keşfi: Türkiye'de çok satanlar → MakerWorld modeli (haftalık)
  ozet.py                 ← özet (rapor)
  bildirim.py             ← Telegram
  instagram.py            ← Instagram açıklaması + zamanlanmış Reels paylaşımı
  video_duzenle.py        ← Reels öncesi video düzenleme (ffmpeg: 9:16, kanca yazısı, DM kartı)
  db.py                   ← Supabase / SQLite
tests/                    ← otomatik testler
```

Geliştirici notu: testler `.venv\Scripts\python -m pytest -q` ile çalışır.

## Sorun giderme

| Mesaj | Çözüm |
|---|---|
| `MakerWorld'den veri alınamadı` | Birkaç saat sonra tekrar deneyin; sürerse MakerWorld'ün site yapısı değişmiş olabilir. |
| `Python bulunamadı` | 1. adım; kurulumda "Add to PATH" işaretli olmalı. |
