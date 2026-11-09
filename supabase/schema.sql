-- 3D Ürün Bulucu — Supabase tabloları
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır.
-- Tekrar çalıştırmak zararsızdır (if not exists).

create table if not exists sources (
  id text primary key,
  name text not null,
  base_url text,
  access_method text,
  notes text
);

create table if not exists products (
  id bigint generated always as identity primary key,
  source_id text not null references sources(id),
  external_id text not null,
  name text not null,
  url text not null,
  category text,
  creator text,
  downloads integer default 0,
  likes integer default 0,
  makes integer default 0,
  views integer default 0,
  published_at timestamptz,
  license text,
  license_flag text check (license_flag in ('ticari_serbest', 'nc_sadece_icerik', 'kontrol_et')),
  print_time_min integer,
  material text,
  image_url text,
  weight_g integer,
  color_count smallint,
  cost_tl numeric(8,1),
  price_tl numeric(8,1),
  hourly_profit_tl numeric(8,1),
  trend_rank integer,
  tags jsonb default '[]'::jsonb,
  features jsonb default '[]'::jsonb,
  score numeric(5,1),
  score_detail jsonb,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  unique (source_id, external_id)  -- aynı model iki kez eklenmez
);

-- Günlük indirme/beğeni sayıları: "son 7 gündeki artış" buradan hesaplanır.
create table if not exists product_snapshots (
  product_id bigint not null references products(id) on delete cascade,
  snap_date date not null,
  downloads integer,
  likes integer,
  primary key (product_id, snap_date)
);

-- Özet seçimleri (şimdilik her gün yazılıyor).
create table if not exists weekly_picks (
  id bigint generated always as identity primary key,
  pick_date date not null,
  rank smallint not null,
  product_id bigint not null references products(id),
  score numeric(5,1),
  reason text,
  video_idea text,
  unique (pick_date, rank)
);

create index if not exists products_score_idx on products (score desc);

-- Tablolar dışarıya kapalı; program "secret/service_role" anahtarıyla yazar.
alter table sources enable row level security;
alter table products enable row level security;
alter table product_snapshots enable row level security;
alter table weekly_picks enable row level security;

-- Panel, işaretler ve izinler için: guncelleme_2026-11-09_panel.sql dosyasını da çalıştırın.
