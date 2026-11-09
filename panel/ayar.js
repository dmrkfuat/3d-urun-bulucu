// Panelin bağlandığı Supabase projesi.
// Bu iki değer tarayıcıda çalışan uygulamalar için herkese açık olacak şekilde tasarlanmıştır:
// "publishable" anahtar tek başına hiçbir veriyi göstermez. Veriyi yalnızca giriş yapmış ve
// panel_izinli tablosunda e-postası olan kullanıcı görür (Supabase RLS izinleri).
// GİZLİ ("secret", sb_secret_...) ANAHTARI ASLA BURAYA YAZMAYIN.
window.PANEL_AYAR = {
  supabaseUrl: "https://mhkyvvartqboifkwpktn.supabase.co",
  publishableKey: "sb_publishable_wW-50XwvN6WmaNK-d7LXyg_gDyGQXq3",
};
