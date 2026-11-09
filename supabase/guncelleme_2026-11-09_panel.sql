-- 3D Ürün Bulucu — güncelleme: maliyet, trend, panel ve işaretler
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır.
-- Tekrar çalıştırmak zararsızdır.

-- 1) Ürünlere maliyet ve trend bilgisi
alter table products add column if not exists weight_g integer;
alter table products add column if not exists color_count smallint;
alter table products add column if not exists cost_tl numeric(8,1);
alter table products add column if not exists price_tl numeric(8,1);
alter table products add column if not exists hourly_profit_tl numeric(8,1);
alter table products add column if not exists trend_rank integer;

-- 2) Panelden girilen işaretler: bastım / videosunu çektim / sattım
create table if not exists product_marks (
  product_id bigint primary key references products(id) on delete cascade,
  printed boolean not null default false,
  video boolean not null default false,
  sold_count integer not null default 0 check (sold_count >= 0),
  note text,
  updated_at timestamptz not null default now()
);
alter table product_marks enable row level security;

-- 3) Panele giriş yapabilecek e-postalar (adres buraya program tarafından eklenir,
--    depoda yazmaz). Bu tablo dışarıya tamamen kapalıdır.
create table if not exists panel_izinli (
  email text primary key
);
alter table panel_izinli enable row level security;

create or replace function public.panel_izinli_mi()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from panel_izinli where lower(email) = lower(auth.jwt() ->> 'email'));
$$;
revoke all on function public.panel_izinli_mi() from public, anon;
grant execute on function public.panel_izinli_mi() to authenticated;

-- 4) Giriş yapmış ve izinli kullanıcı verileri okuyabilir, işaretleri değiştirebilir.
--    Giriş yapmamış biri (anon) hiçbir şey göremez.
grant select on sources, products, product_snapshots, weekly_picks to authenticated;
grant select, insert, update, delete on product_marks to authenticated;

drop policy if exists panel_okur on sources;
create policy panel_okur on sources for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_okur on products;
create policy panel_okur on products for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_okur on product_snapshots;
create policy panel_okur on product_snapshots for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_okur on weekly_picks;
create policy panel_okur on weekly_picks for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_isaretler on product_marks;
create policy panel_isaretler on product_marks for all to authenticated
  using (panel_izinli_mi()) with check (panel_izinli_mi());
