-- 3D Ürün Bulucu — güncelleme: pazar keşfi (Türkiye'de çok satan 3D baskılar → MakerWorld modeli)
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-09_panel.sql çalıştırılmış olmalıdır (panel_izinli_mi fonksiyonu).

create table if not exists market_discovery (
  id bigint generated always as identity primary key,
  kesif_tarihi date not null,
  anahtar text not null,                 -- ürünün ayırt edici kelimeleri (haftadan haftaya eşleştirmek için)
  ad text not null,
  ilan_sayisi integer not null default 0,  -- aynı ürünü satan ayrı ilan sayısı (talep işareti)
  siteler jsonb not null default '{}',     -- {"Hepsiburada": 11, "n11": 2, ...}
  fiyat_min numeric(10,2),
  fiyat_medyan numeric(10,2),
  fiyat_max numeric(10,2),
  gorsel text,
  sorgu text,
  lens_yapildi boolean not null default false,
  mw_sorgu text,
  ilanlar jsonb not null default '[]',
  eslesmeler jsonb not null default '[]',      -- MakerWorld modelleri (görsel / isim eşleşmesi)
  diger_kaynaklar jsonb not null default '[]', -- Lens'te çıkan model sayfaları (Printables vb.)
  created_at timestamptz not null default now(),
  unique (kesif_tarihi, anahtar)
);
create index if not exists market_discovery_tarih_idx on market_discovery (kesif_tarihi desc);
alter table market_discovery enable row level security;

-- Panel yalnızca okur; yazan sunucudur (gizli anahtarla).
grant select on market_discovery to authenticated;
drop policy if exists panel_okur on market_discovery;
create policy panel_okur on market_discovery for select to authenticated using (panel_izinli_mi());
