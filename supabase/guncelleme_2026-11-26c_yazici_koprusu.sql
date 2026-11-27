-- 3D Ürün Bulucu — güncelleme: yazıcı köprüsü (Bambu Lab yazıcının canlı durumu, kamera klibi, SD karttaki timelapse)
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-26b_siparis_detay.sql çalıştırılmış olmalıdır (siparisler.medya ve 'siparis' depolama alanı).
--
-- Köprü (python -m urun_bulucu.kopru) evdeki bilgisayarda çalışır, yazıcıya yerel ağdan bağlanır ve
-- gizli (secret) anahtarla buraya yazar. Panel yalnızca okur ve istek ekler; yazıcının IP'si, seri numarası
-- ve LAN erişim kodu buraya HİÇ yazılmaz (yalnızca köprünün çalıştığı bilgisayardaki .env dosyasındadır).

-- 1) Yazıcının son durumu (köprü ~10 saniyede bir günceller)
create table if not exists yazici_durum (
  ad text primary key check (char_length(ad) between 1 and 60),   -- panelde siparişe yazılan yazıcı adıyla aynı
  model text check (char_length(model) <= 60),
  durum jsonb not null default '{}'::jsonb,   -- {durum, yuzde, kalan_dk, katman, toplam_katman, nozul, tabla, ams, dosya, ...}
  goruldu timestamptz not null default now()  -- köprünün son yazdığı an (eskiyse köprü kapalı demektir)
);
alter table yazici_durum enable row level security;
grant select on yazici_durum to authenticated;
drop policy if exists panel_okur on yazici_durum;
create policy panel_okur on yazici_durum for select to authenticated using (panel_izinli_mi());

-- 2) Panelden köprüye istekler: kamera klibi, SD kartı listeleme, SD karttan siparişe aktarma
create table if not exists yazici_istekleri (
  id bigint generated always as identity primary key,
  yazici text,                                          -- boşsa tek/ilk köprü işler
  tur text not null check (tur in ('klip', 'sd_listele', 'sd_aktar')),
  siparis_id bigint references siparisler(id) on delete cascade,
  saniye integer check (saniye between 5 and 120),     -- klip uzunluğu
  dosya text check (char_length(dosya) <= 200),        -- SD karttaki dosya adı (sd_aktar)
  durum text not null default 'bekliyor' check (durum in ('bekliyor', 'isleniyor', 'tamam', 'hata')),
  sonuc jsonb,
  hata text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists yazici_istekleri_durum_idx on yazici_istekleri (durum, id);
alter table yazici_istekleri enable row level security;
grant select, insert, delete on yazici_istekleri to authenticated;
drop policy if exists panel_okur on yazici_istekleri;
create policy panel_okur on yazici_istekleri for select to authenticated using (panel_izinli_mi());
drop policy if exists panel_ekler on yazici_istekleri;
create policy panel_ekler on yazici_istekleri for insert to authenticated
  with check (panel_izinli_mi() and durum = 'bekliyor' and sonuc is null and hata is null);
drop policy if exists panel_siler on yazici_istekleri;
create policy panel_siler on yazici_istekleri for delete to authenticated
  using (panel_izinli_mi() and durum <> 'isleniyor');
