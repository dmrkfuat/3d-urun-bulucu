-- 3D Ürün Bulucu — güncelleme: siparişler, Instagram istatistikleri, hikâye ve carousel paylaşımı
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-09_panel.sql ve guncelleme_2026-11-10_instagram.sql çalıştırılmış olmalıdır.

-- 1) Siparişler (panelin "Siparişler" sekmesinden girilir). Gerçek baskı süresi ve gramı girilirse
--    maliyet tahmini bunlara göre düzeltilir; satılan ürün ve kategoriler puanda öne çıkar.
create table if not exists siparisler (
  id bigint generated always as identity primary key,
  product_id bigint references products(id) on delete set null,
  urun_adi text not null check (char_length(urun_adi) between 1 and 200),
  adet integer not null default 1 check (adet between 1 and 1000),
  renk text check (char_length(renk) <= 100),
  fiyat_tl numeric(10,2) check (fiyat_tl >= 0),          -- toplam tutar (kargo hariç)
  kanal text not null default 'instagram'
    check (kanal in ('instagram', 'trendyol', 'hepsiburada', 'etsy', 'elden', 'diger')),
  durum text not null default 'yeni'
    check (durum in ('yeni', 'basiliyor', 'hazir', 'kargoda', 'teslim', 'iptal')),
  odendi boolean not null default false,
  gercek_sure_dk integer check (gercek_sure_dk > 0),     -- tüm adetler için toplam baskı süresi
  gercek_gram integer check (gercek_gram > 0),           -- tüm adetler için toplam filament
  musteri_notu text check (char_length(musteri_notu) <= 500),  -- ad/adres yazma; yalnızca kısa not
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists siparisler_tarih_idx on siparisler (created_at desc);
create index if not exists siparisler_urun_idx on siparisler (product_id);
alter table siparisler enable row level security;
grant select, insert, update, delete on siparisler to authenticated;
drop policy if exists panel_siparis on siparisler;
create policy panel_siparis on siparisler for all to authenticated
  using (panel_izinli_mi()) with check (panel_izinli_mi());

-- 2) Instagram: gönderi istatistikleri (sunucu yazar) ve gönderi türü
alter table instagram_posts add column if not exists insights jsonb;
alter table instagram_posts add column if not exists insights_at timestamptz;
alter table instagram_posts add column if not exists media_type text not null default 'REELS';
alter table instagram_posts add column if not exists image_paths text[];
alter table instagram_posts alter column video_path drop not null;   -- carousel'de video yok
alter table instagram_posts drop constraint if exists instagram_posts_media_type_check;
alter table instagram_posts add constraint instagram_posts_media_type_check
  check (media_type in ('REELS', 'STORIES', 'CAROUSEL'));
alter table instagram_posts drop constraint if exists instagram_posts_icerik_check;
alter table instagram_posts add constraint instagram_posts_icerik_check
  check ((media_type = 'CAROUSEL' and coalesce(array_length(image_paths, 1), 0) between 2 and 10)
         or (media_type <> 'CAROUSEL' and video_path is not null));

-- 3) Depolama alanı: carousel fotoğrafları için JPEG de kabul edilir (Instagram API yalnız JPEG alır).
update storage.buckets
  set allowed_mime_types = array['video/mp4', 'video/quicktime', 'image/jpeg']
  where id = 'instagram';
