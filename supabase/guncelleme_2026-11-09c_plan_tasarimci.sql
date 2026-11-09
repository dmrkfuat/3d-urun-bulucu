-- 3D Ürün Bulucu — güncelleme: tasarımcı takibi, baskı planı, filament renkleri, e-ticaret sonuçları
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-09_panel.sql çalıştırılmış olmalıdır (panel_izinli_mi fonksiyonu).

-- 1) Ürüne tasarımcı kimliği ve filament listesi (renk + gram)
alter table products add column if not exists creator_uid bigint;
alter table products add column if not exists creator_handle text;
alter table products add column if not exists filaments jsonb;   -- [{"type":"PLA","color":"#5E43B7","grams":21}]

-- 2) Tasarımcılar: özette kaç gün çıktıkları ve takip durumu
create table if not exists designers (
  source_id text not null references sources(id),
  uid bigint not null,
  name text,
  handle text,
  hit_days integer not null default 0,        -- günlük ilk 10'da çıktığı gün sayısı
  last_hit_date date,
  followed boolean not null default false,    -- true: yeni modelleri Telegram'dan bildirilir
  auto_followed boolean not null default false,
  last_design_id bigint,                      -- bildirilen en yeni model
  last_checked timestamptz,
  primary key (source_id, uid)
);
alter table designers enable row level security;

-- 3) Baskı planı: panelde "bu hafta basacağım" denen ürünler
create table if not exists print_plan (
  product_id bigint primary key references products(id) on delete cascade,
  quantity integer not null default 1 check (quantity between 1 and 100),
  done boolean not null default false,
  added_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table print_plan enable row level security;

-- 4) E-ticaret araması sonuçları (görselle arama; ürün başına en son sonuç)
create table if not exists market_checks (
  product_id bigint primary key references products(id) on delete cascade,
  checked_at timestamptz not null default now(),
  found_count integer not null default 0,
  min_price numeric(10,2),
  max_price numeric(10,2),
  currency text,
  results jsonb not null default '[]'::jsonb  -- [{"site","title","link","price","currency","thumbnail"}]
);
alter table market_checks enable row level security;

-- 5) Panel izinleri
grant select on designers to authenticated;
grant update (followed) on designers to authenticated;   -- panelden yalnızca takip açılıp kapatılabilir
grant select, insert, update, delete on print_plan to authenticated;
grant select on market_checks to authenticated;

drop policy if exists panel_okur on designers;
create policy panel_okur on designers for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_takip on designers;
create policy panel_takip on designers for update to authenticated
  using (panel_izinli_mi()) with check (panel_izinli_mi());
drop policy if exists panel_plan on print_plan;
create policy panel_plan on print_plan for all to authenticated
  using (panel_izinli_mi()) with check (panel_izinli_mi());
drop policy if exists panel_okur on market_checks;
create policy panel_okur on market_checks for select to authenticated using (panel_izinli_mi());
