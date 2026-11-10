-- 3D Ürün Bulucu — güncelleme: Instagram açıklamaları ve zamanlanmış Reels paylaşımı
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-09_panel.sql çalıştırılmış olmalıdır (panel_izinli_mi fonksiyonu).

-- 1) Günlük seçimlere Instagram açıklama metni
alter table weekly_picks add column if not exists instagram_caption text;

-- 2) Zamanlanmış Instagram gönderileri (panelden eklenir, GitHub Actions paylaşır)
create table if not exists instagram_posts (
  id bigint generated always as identity primary key,
  product_id bigint references products(id) on delete set null,
  video_path text not null,                      -- 'instagram' depolama alanındaki dosya
  caption text not null default '' check (char_length(caption) <= 2200),
  scheduled_at timestamptz not null,
  status text not null default 'bekliyor'
    check (status in ('bekliyor', 'isleniyor', 'paylasildi', 'hata')),
  container_id text,
  media_id text,
  permalink text,
  error text,
  attempts integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  published_at timestamptz
);
create index if not exists instagram_posts_status_idx on instagram_posts (status, scheduled_at);
alter table instagram_posts enable row level security;

-- Panel: gönderi ekler (yalnızca 'bekliyor'), açıklamayı/saati değiştirir, hatalıyı tekrar
-- 'bekliyor'a alır, işlenmekte olmayanı siler. Paylaşım sonucu alanlarını yalnızca sunucu yazar.
grant select, insert, delete on instagram_posts to authenticated;
grant update (caption, scheduled_at, status, error, updated_at) on instagram_posts to authenticated;

drop policy if exists panel_okur on instagram_posts;
create policy panel_okur on instagram_posts for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_ekler on instagram_posts;
create policy panel_ekler on instagram_posts for insert to authenticated
  with check (panel_izinli_mi() and status = 'bekliyor');
drop policy if exists panel_gunceller on instagram_posts;
create policy panel_gunceller on instagram_posts for update to authenticated
  using (panel_izinli_mi() and status in ('bekliyor', 'hata'))
  with check (panel_izinli_mi() and status = 'bekliyor');
drop policy if exists panel_siler on instagram_posts;
create policy panel_siler on instagram_posts for delete to authenticated
  using (panel_izinli_mi() and status <> 'isleniyor');

-- 3) Videolar için depolama alanı: herkese KAPALI. Instagram videoyu, sunucunun ürettiği
--    birkaç saatlik geçici (imzalı) bağlantıdan indirir. En fazla 50 MB, yalnızca MP4/MOV.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('instagram', 'instagram', false, 52428800, array['video/mp4', 'video/quicktime'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists instagram_panel_yukler on storage.objects;
create policy instagram_panel_yukler on storage.objects for insert to authenticated
  with check (bucket_id = 'instagram' and public.panel_izinli_mi());
drop policy if exists instagram_panel_okur on storage.objects;
create policy instagram_panel_okur on storage.objects for select to authenticated
  using (bucket_id = 'instagram' and public.panel_izinli_mi());
drop policy if exists instagram_panel_siler on storage.objects;
create policy instagram_panel_siler on storage.objects for delete to authenticated
  using (bucket_id = 'instagram' and public.panel_izinli_mi());

-- 4) Sunucunun gizli ayarları (yenilenen Instagram token'ı). Panel ve dışarısı ERİŞEMEZ:
--    RLS açık, hiçbir izin kuralı yok; yalnızca gizli (secret) anahtarla çalışan sunucu okur/yazar.
create table if not exists gizli_ayarlar (
  anahtar text primary key,
  deger text not null,
  kaynak text,              -- GitHub'daki token'ın kısa özeti (değişti mi diye; token'ın kendisi değil)
  yenilendi timestamptz
);
alter table gizli_ayarlar enable row level security;
revoke all on gizli_ayarlar from anon, authenticated;
