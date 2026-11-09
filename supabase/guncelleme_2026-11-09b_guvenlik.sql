-- 3D Ürün Bulucu — güvenlik sıkılaştırması (panel izni)
-- Supabase panel > SQL Editor'e yapıştırıp "Run" ile bir kez çalıştırılır. Tekrar çalıştırmak zararsızdır.
--
-- Önceki sürüm yalnızca giriş belgesindeki (JWT) e-posta alanına bakıyordu. Bu sürüm, giriş yapan
-- hesabın kimliğini (auth.uid()) auth.users tablosunda bulur ve hem e-postanın izin listesinde
-- olmasını hem de doğrulanmış olmasını şart koşar.

create or replace function public.panel_izinli_mi()
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select exists (
    select 1
    from auth.users u
    join public.panel_izinli p on lower(p.email) = lower(u.email)
    where u.id = auth.uid()
      and u.email_confirmed_at is not null
  );
$$;
revoke all on function public.panel_izinli_mi() from public, anon;
grant execute on function public.panel_izinli_mi() to authenticated;
