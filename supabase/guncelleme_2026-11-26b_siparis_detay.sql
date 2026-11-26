-- 3D Ürün Bulucu — güncelleme: sipariş detayları (müşteri, teslimat, kargo, yazıcı, termin) ve sipariş videoları
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
-- Önce guncelleme_2026-11-26_performans.sql çalıştırılmış olmalıdır (siparisler tablosu).
--
-- KVKK notu: müşteri adı, telefonu, adresi ve TC kimlik numarası kişisel veridir. Tablo yalnızca
-- panel_izinli listesindeki hesaplara açıktır (RLS). Yalnızca fatura/kargo için gereken bilgiyi gir;
-- teslim edilip faturası kesilen siparişlerin kişisel bilgilerini bir süre sonra silmen önerilir.

-- 1) Müşteri, teslimat ve fatura
alter table siparisler add column if not exists musteri_adi text check (char_length(musteri_adi) <= 120);
alter table siparisler add column if not exists musteri_telefon text check (char_length(musteri_telefon) <= 30);
alter table siparisler add column if not exists musteri_eposta text check (char_length(musteri_eposta) <= 200);
alter table siparisler add column if not exists musteri_tc text check (musteri_tc ~ '^[0-9]{11}$');
alter table siparisler add column if not exists teslimat_adresi text check (char_length(teslimat_adresi) <= 500);
alter table siparisler add column if not exists fatura_no text check (char_length(fatura_no) <= 50);
alter table siparisler add column if not exists odeme_yontemi text
  check (odeme_yontemi in ('kart', 'havale', 'kapida', 'pazaryeri', 'nakit', 'diger'));

-- 2) Kargo ve takip
alter table siparisler add column if not exists kargo_firmasi text check (char_length(kargo_firmasi) <= 50);
alter table siparisler add column if not exists takip_no text check (char_length(takip_no) <= 60);

-- 3) Üretim: termin, öncelik, yazıcı ataması ve ilerleme
alter table siparisler add column if not exists termin timestamptz;
alter table siparisler add column if not exists acil boolean not null default false;
alter table siparisler add column if not exists yazici text check (char_length(yazici) <= 60);
alter table siparisler add column if not exists baski_baslangic timestamptz;     -- "Basılıyor"a geçince panel yazar
alter table siparisler add column if not exists ilerleme integer check (ilerleme between 0 and 100);  -- boşsa süreden hesaplanır

-- 4) Siparişe bağlı videolar (timelapse, klip, hata klibi): [{yol, ad, boyut, tur, tarih}]
alter table siparisler add column if not exists medya jsonb not null default '[]'::jsonb;

-- 5) Sipariş videoları için depolama alanı: herkese KAPALI, yalnızca izinli panel kullanıcıları.
--    En fazla 50 MB, MP4/MOV (timelapse) ve JPEG/PNG (kare). Instagram'a planlanan video
--    'instagram' alanına kopyalanır; paylaşıldıktan sonra oradan silinse de burada kalır.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('siparis', 'siparis', false, 52428800, array['video/mp4', 'video/quicktime', 'image/jpeg', 'image/png'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists siparis_panel_yukler on storage.objects;
create policy siparis_panel_yukler on storage.objects for insert to authenticated
  with check (bucket_id = 'siparis' and public.panel_izinli_mi());
drop policy if exists siparis_panel_okur on storage.objects;
create policy siparis_panel_okur on storage.objects for select to authenticated
  using (bucket_id = 'siparis' and public.panel_izinli_mi());
drop policy if exists siparis_panel_siler on storage.objects;
create policy siparis_panel_siler on storage.objects for delete to authenticated
  using (bucket_id = 'siparis' and public.panel_izinli_mi());
