-- 3D Ürün Bulucu — güncelleme: Trendyol 3D mağaza analizi (en çok satan 3D ürünler ve aktif mağazalar)
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-09_panel.sql çalıştırılmış olmalıdır (panel_izinli_mi fonksiyonu).
--
-- Her hafta okunan her 3D baskı ürünün o günkü sayıları bir satır olarak tutulur; iki hafta arasındaki
-- değerlendirme ve favori artışı ürünün SATIŞ HIZIDIR. Mağaza sahibinin kişisel bilgileri tutulmaz.

create table if not exists trendyol_products (
  id bigint generated always as identity primary key,
  tarih date not null,
  urun_id bigint not null,               -- Trendyol ürün numarası (adresteki -p-<sayı>)
  url text not null,
  ad text not null,
  marka text,
  magaza_id bigint,
  magaza text,
  kategori text,
  fiyat numeric(10,2),
  degerlendirme integer not null default 0,  -- değerlendirme (puan) sayısı: satışla en çok örtüşen açık veri
  yorum integer not null default 0,
  puan numeric(3,2),
  favori integer not null default 0,
  gorsel text,
  created_at timestamptz not null default now(),
  unique (tarih, urun_id)
);
create index if not exists trendyol_products_tarih_idx on trendyol_products (tarih desc);
create index if not exists trendyol_products_urun_idx on trendyol_products (urun_id, tarih desc);
alter table trendyol_products enable row level security;

-- Panel yalnızca okur; yazan sunucudur (gizli anahtarla).
grant select on trendyol_products to authenticated;
drop policy if exists panel_okur on trendyol_products;
create policy panel_okur on trendyol_products for select to authenticated using (panel_izinli_mi());
