(() => {
  const $ = (s) => document.querySelector(s);
  const ayar = window.PANEL_AYAR || {};
  const durum = $("#durum");

  function goster(id) {
    for (const b of ["#girisEkrani", "#uygulama"]) $(b).hidden = b !== id;
    durum.hidden = true;
  }
  function durumYaz(metin, hata = false) {
    $("#girisEkrani").hidden = true; $("#uygulama").hidden = true;
    durum.hidden = false; durum.className = hata ? "hata" : "bos"; durum.textContent = metin;
  }
  if (!ayar.supabaseUrl || !ayar.publishableKey || !window.supabase) {
    durumYaz("Panel ayarı eksik (ayar.js) veya kütüphane yüklenemedi.", true);
    return;
  }

  const sb = window.supabase.createClient(ayar.supabaseUrl, ayar.publishableKey, {
    auth: { flowType: "implicit", persistSession: true, detectSessionInUrl: true },
  });

  const tl = (n) => n == null ? "-" : `${Math.round(Number(n)).toLocaleString("tr-TR")} TL`;
  const sure = (dk) => {
    if (dk == null) return "-";
    const s = Math.floor(dk / 60), d = dk % 60;
    return s && d ? `${s} sa ${d} dk` : s ? `${s} sa` : `${d} dk`;
  };
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Veritabanından gelen bağlantılar yalnızca https ise kullanılır (javascript:, data: vb. engellenir).
  const url = (u) => { try { const x = new URL(String(u)); return x.protocol === "https:" ? esc(x.href) : "#"; } catch (e) { return "#"; } };
  // Satış bağlantısı (sunucudaki pazar.satis_linki ile aynı kural): doğrudan ürün sayfası >
  // pazar yerinin kendi arama sayfası (ürün adıyla) > Google ürün sayfası.
  const PAZAR_ALANLARI = ["trendyol.com", "hepsiburada.com", "n11.com", "amazon.com.tr", "ciceksepeti.com", "pazarama.com", "pttavm.com", "etsy.com"];
  const SITE_ARAMA = {
    "Trendyol": "https://www.trendyol.com/sr?q=", "Hepsiburada": "https://www.hepsiburada.com/ara?q=",
    "n11": "https://www.n11.com/arama?q=", "Amazon TR": "https://www.amazon.com.tr/s?k=",
    "Çiçeksepeti": "https://www.ciceksepeti.com/arama?query=", "Pazarama": "https://www.pazarama.com/arama?q=",
    "PttAVM": "https://www.pttavm.com/arama?q=", "Etsy": "https://www.etsy.com/search?q=",
  };
  const satisLinki = (x) => {
    let host = "";
    try { host = new URL(x.link).hostname.toLowerCase(); } catch (e) { /* bağlantı yok */ }
    if (host && PAZAR_ALANLARI.some((a) => host === a || host.endsWith("." + a))) return x.link;
    if (x.pazar_yeri !== false && SITE_ARAMA[x.site] && x.title) return SITE_ARAMA[x.site] + encodeURIComponent(x.title.slice(0, 80));
    return x.link;
  };
  // Sosyal medya sayfaları (Lens görsel eşleşmesi); Türkçe ve satış belirtisi olanlar işaretli.
  const sosyalHtml = (o) => {
    const liste = ((o && o.results) || []).filter((x) => x.kaynak === "sosyal");
    if (!liste.length) return "";
    return `<p style="margin:8px 0 2px"><b>📱 Sosyal medyada</b></p><ul style="margin:0;padding-left:18px">${liste.map((x) => {
      const isaret = [x.tr ? "Türkçe" : "", x.satis ? "satış" : ""].filter(Boolean).join(", ");
      return `<li>${esc(x.site)}: <a href="${url(x.link)}" target="_blank" rel="noopener">${esc((x.title || "gönderi").slice(0, 60))}</a>${isaret ? ` <span class="muted">(${esc(isaret)})</span>` : ""}</li>`;
    }).join("")}</ul>`;
  };
  const LISANS = { ticari_serbest: "🟢 satılabilir", nc_sadece_icerik: "🟡 NC", kontrol_et: "🔴 kontrol et" };

  let secimler = [];
  let isaretler = new Map();
  let pazar = new Map();
  let planIdleri = new Set();

  async function planIdleriYukle() {
    const { data, error } = await sb.from("print_plan").select("product_id").eq("done", false);
    planIdleri = new Set(error ? [] : data.map((r) => r.product_id));
  }
  async function planaEkleCikar(pid, dugme) {
    const varMi = planIdleri.has(pid);
    const { error } = varMi
      ? await sb.from("print_plan").delete().eq("product_id", pid)
      : await sb.from("print_plan").upsert({ product_id: pid, quantity: 1, done: false, updated_at: new Date().toISOString() });
    if (error) { alert("Plan güncellenemedi: " + error.message); return; }
    varMi ? planIdleri.delete(pid) : planIdleri.add(pid);
    if (dugme) dugme.textContent = planIdleri.has(pid) ? "✓ Planda" : "📋 Plana ekle";
  }
  // Satış sonuçları: "birebir" işaretli olanlar MakerWorld modeliyle AYNI ürün (sunucudaki
  // pazar.ayni_urun_mu kuralı); diğerleri aynı kategoride farklı ürünlerdir, fiyata katılmaz.
  const ayniUrunler = (o) => ((o && o.results) || []).filter((r) => r.kaynak !== "sosyal" && r.birebir);
  const benzerUrunler = (o) => ((o && o.results) || []).filter((r) => r.kaynak !== "sosyal" && !r.birebir);
  const pazarYazi = (o, onerilen) => {
    if (!o) return "";
    const ayni = ayniUrunler(o), benzer = benzerUrunler(o).length;
    const ek = benzer ? ` (aynı kategoride ${benzer} farklı ürün; fiyata katılmadı)` : "";
    if (!ayni.length) return "🛒 Aynı ürün Türkiye'de satışta bulunamadı" + ek;
    const sayac = {};
    ayni.forEach((r) => { sayac[r.site] = (sayac[r.site] || 0) + 1; });
    const siteler = Object.entries(sayac).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([s, n]) => `${s} ${n}`).join(", ");
    const ortanca = (d) => { const k = [...d].sort((a, b) => a - b); return k.length % 2 ? k[(k.length - 1) / 2] : (k[k.length / 2 - 1] + k[k.length / 2]) / 2; };
    let kume = ayni.filter((r) => r.price != null).map((r) => r.price);
    if (!kume.length) return `🛒 Aynı ürün satışta: ${siteler}` + ek;
    if (kume.length >= 3) { const m = ortanca(kume); kume = kume.filter((f) => f >= m / 5 && f <= m * 5); }  // uç değerler (sunucuyla aynı kural)
    return `🛒 Aynı ürün satışta: ${siteler} · ${Math.round(Math.min(...kume))}–${Math.round(Math.max(...kume))} TL (ortanca ${Math.round(ortanca(kume))} TL)` +
      (onerilen ? ` · senin fiyatın ${Math.round(onerilen)} TL` : "") + ek;
  };
  const satisSatiri = (x) => `<li>${esc(x.site)}: <a href="${url(satisLinki(x))}" target="_blank" rel="noopener">${esc((x.title || "ürün").slice(0, 60))}</a>${x.price != null ? ` — ${Math.round(x.price)} TL` : ""}${x.pazar_yeri === false ? ' <span class="muted">(bağımsız mağaza)</span>' : ""}${x.kaynak === "görsel" ? ' <span class="muted">(görsel eşleşme)</span>' : ""}${x.gorsel_karar === "ayni" ? ' <span class="muted">✓ fotoğraf aynı</span>' : ""}${x.gorsel_neden ? ` <span class="muted" title="${esc(x.gorsel_neden)}">ⓘ</span>` : ""}</li>`;
  const pazarListesi = (o) => {
    const ayni = ayniUrunler(o), benzer = benzerUrunler(o);
    return (ayni.length ? `<p style="margin:6px 0 2px"><b>Aynı ürün</b></p><ul style="margin:0;padding-left:18px">${ayni.slice(0, 10).map(satisSatiri).join("")}</ul>` : "")
      + (benzer.length ? `<p class="muted" style="margin:8px 0 2px">Aynı kategoride, farklı ürünler (fiyata katılmadı)</p><ul class="muted" style="margin:0;padding-left:18px">${benzer.slice(0, 5).map(satisSatiri).join("")}</ul>` : "");
  };
  const grafikler = new Map();

  // ------------------------------------------------------------ giriş
  $("#girisFormu").addEventListener("submit", async (e) => {
    e.preventDefault();
    const mesaj = $("#girisMesaj");
    mesaj.textContent = "Gönderiliyor...";
    const { error } = await sb.auth.signInWithOtp({
      email: $("#eposta").value.trim(),
      options: { shouldCreateUser: false, emailRedirectTo: location.origin + location.pathname },
    });
    mesaj.textContent = error
      ? "Gönderilemedi: " + (error.message.includes("Signups not allowed") ? "bu adres izinli değil." : error.message)
      : "Bağlantı gönderildi. E-postandaki bağlantıya bu cihazda tıkla.";
  });
  $("#cikis").addEventListener("click", async () => { await sb.auth.signOut(); goster("#girisEkrani"); });
  // Üst bardaki arama: Enter'a basınca "Tüm ürünler" sekmesinde aynı kelimeyle arar.
  $("#ustAra").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    $("#tumAra").value = e.target.value.trim();
    document.querySelector('[data-sekme="tum"]').click();
  });

  // ------------------------------------------------------------ sekmeler
  const SEKME_YUKLE = { liste: () => kartlariCiz(), tum: () => tumYukle(), plan: () => planYukle(),
                        tasarimci: () => tasarimciYukle(), performans: () => performansYukle(),
                        kesif: () => kesifYukle(), instagram: () => igYukle(), siparis: () => siparisYukle() };
  document.querySelectorAll("[data-sekme]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-sekme]").forEach((x) => {
      x.setAttribute("aria-selected", String(x === b));
      $(`#${x.dataset.sekme}Sekmesi`).hidden = x !== b;
    });
    Promise.resolve(SEKME_YUKLE[b.dataset.sekme]()).catch((e) => durumYaz("Veri alınamadı: " + (e.message || e), true));
  }));

  // ------------------------------------------------------------ veri
  async function gunleriYukle() {
    const { data, error } = await sb.from("weekly_picks").select("pick_date").order("pick_date", { ascending: false }).limit(500);
    if (error) throw error;
    const gunler = [...new Set(data.map((r) => r.pick_date))];
    if (!gunler.length) { durumYaz("Henüz hiç özet yok veya bu hesabın görme izni yok."); return false; }
    $("#gun").innerHTML = gunler.map((g) => `<option>${g}</option>`).join("");
    return true;
  }

  async function listeYukle() {
    const gun = $("#gun").value;
    const { data, error } = await sb.from("weekly_picks")
      .select("*, products(*)")  // instagram_caption sütunu SQL güncellemesinden önce yoktur
      .eq("pick_date", gun).order("rank");
    if (error) throw error;
    secimler = data.filter((r) => r.products);
    const ids = secimler.map((r) => r.product_id);
    const im = ids.length ? await sb.from("product_marks").select("*").in("product_id", ids) : { data: [] };
    if (im.error) throw im.error;
    isaretler = new Map(im.data.map((m) => [m.product_id, m]));
    // Bu tablolar SQL güncellemesi çalıştırılmadıysa yoktur; panel yine çalışsın.
    const pz = ids.length ? await sb.from("market_checks").select("*").in("product_id", ids) : { data: [] };
    pazar = new Map((pz.data || []).map((m) => [m.product_id, m]));
    await planIdleriYukle();
    const kategoriler = [...new Set(secimler.map((r) => r.products.category).filter(Boolean))];
    const secili = $("#kategori").value;
    $("#kategori").innerHTML = `<option value="">Hepsi</option>` + kategoriler.map((k) => `<option ${k === secili ? "selected" : ""}>${esc(k)}</option>`).join("");
    kartlariCiz();
  }

  // ------------------------------------------------------------ günlük liste (kart / tablo görünümü)
  const lIkon = (ad, boy = 18, sinif = "") => `<span class="material-symbols-outlined text-[${boy}px] ${sinif}">${ad}</span>`;
  const LISANS_ROZET = { ticari_serbest: ["Satılabilir", "text-tertiary"], nc_sadece_icerik: ["NC: satılamaz", "text-secondary"], kontrol_et: ["Lisansı kontrol et", "text-error"] };
  const listeSecili = new Set();          // toplu işaretleme için seçilen ürünler
  let listeTopluAcik = false;
  let listeGorunum = (() => { try { return localStorage.getItem("listeGorunum") === "tablo" ? "tablo" : "kart"; } catch (_) { return "kart"; } })();

  const isaretVar = (m) => m && (m.printed || m.video || m.sold_count > 0 || (m.note || "").trim());

  function listeFiltreli() {
    const kat = $("#kategori").value, sadeceIsaretsiz = $("#isaretsiz").checked, sira = $("#listeSira").value;
    const ara = $("#listeAra").value.trim().toLocaleLowerCase("tr-TR");
    const liste = secimler.filter((r) => (!kat || r.products.category === kat)
      && (!sadeceIsaretsiz || !isaretVar(isaretler.get(r.product_id)))
      && (!ara || [r.products.name, r.products.creator, r.products.category].filter(Boolean).join(" ").toLocaleLowerCase("tr-TR").includes(ara)));
    const artan = ["rank", "print_time_min", "cost_tl"].includes(sira);
    const deger = (r) => sira === "rank" ? r.rank : sira === "score" ? Number(r.score) : r.products[sira];
    return liste.sort((a, b) => {
      const x = deger(a), y = deger(b);
      if (x == null) return 1;
      if (y == null) return -1;
      return artan ? x - y : y - x;
    });
  }

  // Günün özeti: seçilen günün tüm modelleri üzerinden (filtreden bağımsız).
  function listeKpiCiz() {
    const n = secimler.length, m = (r) => isaretler.get(r.product_id) || {};
    const basilan = secimler.filter((r) => m(r).printed).length;
    const planda = secimler.filter((r) => planIdleri.has(r.product_id)).length;
    const isaretsiz = secimler.filter((r) => !isaretVar(isaretler.get(r.product_id))).length;
    const trend = secimler.filter((r) => r.products.trend_rank).length;
    const satis = secimler.reduce((t, r) => t + (m(r).sold_count || 0), 0);
    const ciro = secimler.reduce((t, r) => t + (m(r).sold_count || 0) * (r.products.price_tl || 0), 0);
    const satilan = secimler.filter((r) => m(r).sold_count > 0).length;
    const ortPuan = n ? Math.round(secimler.reduce((t, r) => t + Number(r.score || 0), 0) / n) : 0;
    const yuzde = (a) => n ? Math.round((a / n) * 100) : 0;
    const kart = (baslik, ikon, ikonSinif, deger, birim, sag, cubuk, oran, degerSinif = "text-on-surface") => `
      <div class="bg-white rounded-xl p-3 shadow-sm flex flex-col justify-between transition-all hover:shadow-md">
        <div class="flex items-center justify-between"><span class="font-label-sm text-label-sm uppercase tracking-wider text-outline">${baslik}</span>
          <div class="w-8 h-8 rounded-lg ${ikonSinif} flex items-center justify-center">${lIkon(ikon)}</div></div>
        <div class="mt-2 flex items-baseline justify-between gap-2"><div><span class="font-headline-lg text-headline-lg font-bold ${degerSinif}">${deger}</span><span class="font-label-md text-label-md text-on-surface-variant ml-1">${birim}</span></div>${sag}</div>
        <div class="mt-2 w-full bg-surface-container-low rounded-full h-1.5 overflow-hidden"><div class="${cubuk} h-full rounded-full" style="width:${oran}%"></div></div>
      </div>`;
    $("#listeKpi").innerHTML =
      kart("Günün Seçimi", "inventory_2", "bg-surface-container-low text-primary", n, "model",
        `<span class="flex items-center gap-0.5 px-2 py-0.5 rounded-full bg-surface-container-high text-primary font-label-sm text-label-sm">${lIkon("star", 14)} ort. puan ${ortPuan}</span>`, "bg-primary", Math.min(100, ortPuan)) +
      kart("Basılan / Planda", "precision_manufacturing", "bg-surface-container-low text-tertiary", basilan, "basıldı",
        `<span class="flex items-center gap-1 font-label-sm text-label-sm text-tertiary"><span class="w-2 h-2 rounded-full bg-tertiary-container animate-pulse"></span>${planda} planda</span>`, "bg-tertiary-container", yuzde(basilan)) +
      kart("İşaretlenmemiş", "priority_high", "bg-error-container text-error", isaretsiz, "bekliyor",
        `<span class="px-2 py-0.5 rounded-full bg-surface-container-low text-error font-label-sm text-label-sm font-semibold">🔥 Trend: ${trend}</span>`, "bg-error", yuzde(isaretsiz), isaretsiz ? "text-error" : "text-on-surface") +
      kart("Satılan", "check_circle", "bg-surface-container-low text-secondary", satis, "satış",
        `<span class="font-label-md text-label-md text-secondary font-bold">${tl(ciro)}</span>`, "bg-secondary-container", yuzde(satilan));
  }

  function listeSeritCiz(liste) {
    const filament = liste.reduce((t, r) => t + (r.products.weight_g || 0), 0);
    const sureT = liste.reduce((t, r) => t + (r.products.print_time_min || 0), 0);
    $("#listeSeritBilgi").innerHTML = `<span class="flex items-center gap-1 font-semibold text-on-surface">${lIkon("check_circle", 18, "text-tertiary")} ${liste.length} model listelendi</span>
      <span class="text-outline">•</span><span>Filament: <strong class="text-on-surface">${Math.round(filament).toLocaleString("tr-TR")} g</strong></span>
      <span class="hidden md:inline text-outline">•</span><span class="hidden md:inline">Toplam baskı süresi: <strong class="text-on-surface">${esc(sureT ? sure(sureT) : "-")}</strong></span>`;
  }

  function listeTopluCiz() {
    $("#listeTopluBar").hidden = !(listeTopluAcik || listeSecili.size);
    $("#listeTopluSay").textContent = listeSecili.size ? `${listeSecili.size} model seçili` : "Kartlardaki kutudan model seç";
  }

  function kartlariCiz() {
    grafikler.forEach((g) => g.destroy()); grafikler.clear();
    listeKpiCiz();
    for (const id of [...listeSecili]) if (!secimler.some((r) => r.product_id === id)) listeSecili.delete(id);
    listeTopluCiz();
    document.querySelectorAll("[data-gorunum]").forEach((b) => {
      const aktif = b.dataset.gorunum === listeGorunum;
      b.setAttribute("aria-pressed", String(aktif));
      b.className = `p-1.5 rounded-md ${aktif ? "bg-white text-primary shadow-sm" : "text-on-surface-variant hover:text-on-surface"}`;
    });
    const liste = listeFiltreli();
    listeSeritCiz(liste);
    const kap = $("#kartlar"), tabloKap = $("#listeTabloKap");
    if (!liste.length) {
      kap.hidden = false; tabloKap.hidden = true;
      kap.innerHTML = `<div class="col-span-full bos">Bu filtreye uyan ürün yok.</div>`;
      return;
    }
    kap.hidden = listeGorunum !== "kart"; tabloKap.hidden = listeGorunum !== "tablo";
    if (listeGorunum === "tablo") { kap.innerHTML = ""; return listeTabloCiz(liste); }
    kap.innerHTML = liste.map(kartHtml).join("");
    kap.querySelectorAll("[data-pid]").forEach(kartBagla);
  }

  const planDugmeSinifi = (planda) => `planDugme flex items-center gap-1 px-3 py-1.5 rounded-lg font-label-md text-label-md transition-all shadow-sm ${planda ? "bg-tertiary text-on-tertiary" : "bg-white text-on-surface hover:bg-primary hover:text-on-primary"}`;

  function kartHtml(r) {
    const p = r.products, m = isaretler.get(r.product_id) || {}, d = p.score_detail || {};
    const planda = planIdleri.has(r.product_id);
    const [lisansAd, lisansRenk] = LISANS_ROZET[p.license_flag] || ["Lisans ?", "text-outline"];
    const bayrak = p.trend_rank ? [`🔥 Trend #${p.trend_rank}`, "bg-error text-on-error"]
      : d.sezon ? [d.sezon, "bg-tertiary text-on-tertiary"]
      : m.sold_count > 0 ? [`💰 ${m.sold_count} satıldı`, "bg-secondary text-on-secondary"] : null;
    const [durumIkon, durumAd, durumRenk] = m.printed ? ["verified", "Basıldı", "text-tertiary"]
      : planda ? ["hourglass_top", "Planda, sırada", "text-secondary"]
      : m.video ? ["videocam", "Videosu çekildi", "text-primary"] : ["fiber_new", "Yeni seçim", "text-primary"];
    const cip = (metin, baslik = "") => `<span class="px-2 py-0.5 rounded-full bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm"${baslik ? ` title="${esc(baslik)}"` : ""}>${metin}</span>`;
    const cipler = [
      d.satis_bonusu ? cip(`💰 sattın +${d.satis_bonusu}`, d.satis_gecmisi) : "",
      d.instagram_bonusu ? cip(`📸 IG ${d.instagram_bonusu > 0 ? "+" : ""}${d.instagram_bonusu}`, d.instagram) : "",
      d.etsy_bonusu ? cip(`🧶 Etsy ${Number(d.etsy_favori).toLocaleString("tr-TR")}♥`, "Etsy'de benzerlerinin favori toplamı") : "",
      p.color_count > 1 ? cip(`${p.color_count} renk`) : "",
      p.trend_rank && d.sezon ? cip(esc(d.sezon)) : "",
    ].join("");
    const param = (ad, deger, renk = "text-on-surface") => `<div><span class="block font-label-sm text-label-sm text-outline">${ad}</span><span class="font-label-md text-label-md font-semibold ${renk}">${deger}</span></div>`;
    const detay = (sinif, ozet, icerik, acik = false) => `<details class="${sinif} rounded-lg bg-surface-container-low/60 px-3 py-1.5"${acik ? " open" : ""}><summary class="font-label-md text-label-md py-1">${ozet}</summary>${icerik}</details>`;
    const o = pazar.get(r.product_id);
    return `
    <article class="urunKart bg-white rounded-xl shadow-sm hover:shadow-md transition-all flex flex-col overflow-hidden group" data-pid="${r.product_id}">
      <div class="relative w-full h-52 bg-surface-container overflow-hidden shrink-0">
        ${p.image_url ? `<img src="${url(p.image_url)}" alt="" loading="lazy" class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105">`
          : `<div class="w-full h-full flex items-center justify-center text-outline">${lIkon("view_in_ar", 48)}</div>`}
        <div class="absolute top-2 left-2 flex items-center gap-1.5 flex-wrap">
          <span class="px-2 py-0.5 rounded-full bg-white/90 backdrop-blur-sm font-label-sm text-label-sm font-bold ${lisansRenk}">${lisansAd}</span>
          <span class="px-2 py-0.5 rounded-full bg-white/90 backdrop-blur-sm font-label-sm text-label-sm text-on-surface">#${r.rank} • ${esc(r.score)} puan</span>
        </div>
        <div class="absolute top-2 right-2 flex items-center gap-2">
          ${bayrak ? `<span class="px-2 py-0.5 rounded-full ${bayrak[1]} font-label-sm text-label-sm font-semibold shadow-sm">${esc(bayrak[0])}</span>` : ""}
          <label class="w-7 h-7 rounded-lg bg-white/90 backdrop-blur-sm flex items-center justify-center cursor-pointer shadow-sm" title="Toplu işaretleme için seç">
            <input type="checkbox" data-lsec="${r.product_id}" ${listeSecili.has(r.product_id) ? "checked" : ""} class="w-4 h-4 rounded accent-primary-container cursor-pointer" aria-label="Modeli seç"></label>
        </div>
        <div class="absolute bottom-0 left-0 right-0 bg-white/95 backdrop-blur-sm px-3 py-1.5 flex items-center justify-between">
          <div class="flex items-center gap-1.5 font-label-sm text-label-sm ${durumRenk}">${lIkon(durumIkon, 16)}<span class="font-semibold">${durumAd}</span></div>
          <span class="font-label-sm text-label-sm text-outline">Baskı: ${esc(sure(p.print_time_min))}</span>
        </div>
      </div>
      <div class="p-3 flex flex-col gap-2 flex-1">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <h3 class="font-headline-sm text-headline-sm font-semibold"><a href="${url(p.url)}" target="_blank" rel="noopener" class="text-on-surface no-underline group-hover:text-primary transition-colors">${esc(p.name)}</a></h3>
            <p class="font-body-sm text-body-sm text-on-surface-variant">Tasarımcı: <strong class="text-on-surface">${esc(p.creator || "-")}</strong> • ${esc(p.category || "-")}</p>
          </div>
          <span class="px-2 py-1 rounded-lg bg-surface-container-high text-primary font-label-sm text-label-sm font-bold whitespace-nowrap shrink-0" title="Önerilen satış fiyatı">${p.price_tl != null ? tl(p.price_tl) : "-"}</span>
        </div>
        <div class="grid grid-cols-4 gap-1 p-2 rounded-lg bg-surface-container-low text-center">
          ${param("Malzeme", esc(p.material || "-"))}
          ${param("Ağırlık", p.weight_g ? `${Math.round(p.weight_g)} g` : "-")}
          ${param("Maliyet", p.cost_tl != null ? tl(p.cost_tl) : "-")}
          ${param("Saatlik", p.hourly_profit_tl != null ? tl(p.hourly_profit_tl) : "-", "text-secondary")}
        </div>
        ${cipler ? `<div class="flex flex-wrap gap-1.5">${cipler}</div>` : ""}
        <p class="font-body-sm text-body-sm text-on-surface-variant">${esc(r.reason)}</p>
        <div class="flex flex-wrap items-center gap-2 pt-2 border-t border-surface-container-high">
          <label class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-surface-container-low font-label-md text-label-md cursor-pointer"><input type="checkbox" name="printed" ${m.printed ? "checked" : ""} class="w-4 h-4 accent-primary"> Bastım</label>
          <label class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-surface-container-low font-label-md text-label-md cursor-pointer"><input type="checkbox" name="video" ${m.video ? "checked" : ""} class="w-4 h-4 accent-primary"> Video çektim</label>
          <span class="sayac px-2 py-0.5 rounded-lg bg-surface-container-low font-label-md text-label-md">Sattım
            <button type="button" data-adim="-1" aria-label="Azalt">−</button><output>${m.sold_count || 0}</output><button type="button" data-adim="1" aria-label="Artır">+</button></span>
          <span class="kaydedildi isaretDurum font-label-sm text-label-sm" role="status"></span>
        </div>
        <div class="flex flex-col gap-1.5">
          ${detay("notAc", "📝 Not", `<textarea class="not w-full mt-1" placeholder="Not (ör. hangi renkte bastın, nerede sattın)">${esc(m.note || "")}</textarea>`, !!(m.note || "").trim())}
          ${o ? detay("pazarAc", esc(pazarYazi(o, p.price_tl)), `${pazarListesi(o)}${sosyalHtml(o)}${o.results?.[0]?.sorgu ? `<p class="muted">Arama metni: "${esc(o.results[0].sorgu)}" · ${esc(String(o.checked_at).slice(0, 10))}</p>` : ""}`) : ""}
          ${detay("videoAc", "🎬 Video fikri", `<pre class="font-body-sm text-body-sm whitespace-pre-wrap m-0 pb-1">${esc(r.video_idea)}</pre>`)}
          <details class="igAc rounded-lg bg-surface-container-low/60 px-3 py-1.5"><summary class="font-label-md text-label-md py-1">📸 Instagram'a planla</summary>
            <div class="ig">
              <textarea class="igMetin" rows="9" maxlength="2200" aria-label="Instagram açıklaması" placeholder="Açıklama (bu gün için otomatik metin yok)">${esc(r.instagram_caption || "")}</textarea>
              <div class="satir"><button type="button" class="ikincil igKopyala">Metni kopyala</button><span class="muted igSayac"></span></div>
              <label>Video (MP4/MOV, en fazla 50 MB, dikey 9:16 önerilir)<input type="file" class="igVideo" accept="video/mp4,video/quicktime,.mp4,.mov"></label>
              <label class="igDuzenle" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" class="igDuzenleKutu" checked> Videoyu otomatik düzenle: açıklamanın ilk satırı başta yazı olarak, sonda "Sipariş için DM at" kartı, 9:16</label>
              <label class="igDuzenle" style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" class="igHikayeKutu"> Aynı videoyu hikâye olarak da paylaş (hikâye videosu en çok 60 sn)</label>
              <label>Paylaşım zamanı<input type="datetime-local" class="igZaman"></label>
              <div class="satir"><button type="button" class="ana igPlanla">Videoyu planla</button><span class="kaydedildi igDurum" role="status"></span></div>
              <label>Ya da kendi fotoğraflarınla carousel (2-10 fotoğraf; JPEG'e çevrilir, 4:5 ile 1.91:1 dışı ortadan kırpılır)<input type="file" class="igFoto" accept="image/*" multiple></label>
              <div class="satir"><button type="button" class="ikincil igCarousel">Carousel planla</button></div>
            </div>
          </details>
          ${detay("grafikAc", "📈 İndirme geçmişi", `<div class="grafik"><canvas></canvas></div>`)}
        </div>
      </div>
      <div class="px-3 py-2 bg-surface-container-low flex items-center justify-between">
        <div class="flex items-center gap-1">
          <a href="${url(p.url)}" target="_blank" rel="noopener" title="MakerWorld'de aç" class="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white transition-colors no-underline">${lIkon("view_in_ar")}</a>
          <button type="button" data-ac="grafikAc" title="İndirme geçmişi" class="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white transition-colors">${lIkon("monitoring")}</button>
          <button type="button" data-ac="igAc" title="Instagram'a planla" class="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white transition-colors">${lIkon("photo_camera")}</button>
          <button type="button" data-ac="videoAc" title="Video fikri" class="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-white transition-colors">${lIkon("movie")}</button>
        </div>
        <button type="button" class="${planDugmeSinifi(planda)}"><span class="planYazi">${planda ? "✓ Planda" : "Plana ekle"}</span>${lIkon(planda ? "event_available" : "queue", 16, "planIkon")}</button>
      </div>
    </article>`;
  }

  function kartBagla(kart) {
    const pid = Number(kart.dataset.pid);
    const durumAlan = kart.querySelector(".isaretDurum");
    let zaman;
    const kaydet = async () => {
      const kayit = {
        product_id: pid,
        printed: kart.querySelector("[name=printed]").checked,
        video: kart.querySelector("[name=video]").checked,
        sold_count: Number(kart.querySelector("output").textContent),
        note: kart.querySelector(".not").value.trim() || null,
        updated_at: new Date().toISOString(),
      };
      durumAlan.textContent = "Kaydediliyor...";
      const { error } = await sb.from("product_marks").upsert(kayit);
      durumAlan.style.color = error ? "var(--bad)" : "";
      durumAlan.textContent = error ? "Kaydedilemedi: " + error.message : "Kaydedildi ✓";
      if (!error) { isaretler.set(pid, kayit); listeKpiCiz(); }
    };
    // Yalnızca işaret kutuları kaydeder (Instagram bölümündeki kutular değil)
    kart.querySelectorAll("[name=printed], [name=video]").forEach((c) => c.addEventListener("change", kaydet));
    kart.querySelectorAll("[data-adim]").forEach((b) => b.addEventListener("click", () => {
      const o = kart.querySelector("output");
      o.textContent = Math.max(0, Number(o.textContent) + Number(b.dataset.adim));
      kaydet();
    }));
    kart.querySelector(".not").addEventListener("input", () => { clearTimeout(zaman); zaman = setTimeout(kaydet, 800); });
    kart.querySelector(".grafikAc").addEventListener("toggle", (e) => { if (e.target.open) grafikCiz(pid, kart); }, { once: true });
    kart.querySelector(".planDugme").addEventListener("click", async (e) => {
      const dugme = e.currentTarget;
      await planaEkleCikar(pid, dugme.querySelector(".planYazi"));
      const planda = planIdleri.has(pid);
      dugme.className = planDugmeSinifi(planda);
      dugme.querySelector(".planYazi").textContent = planda ? "✓ Planda" : "Plana ekle";
      dugme.querySelector(".planIkon").textContent = planda ? "event_available" : "queue";
      listeKpiCiz();
    });
    kart.querySelectorAll("[data-ac]").forEach((b) => b.addEventListener("click", () => {
      const bolum = kart.querySelector(`.${b.dataset.ac}`);
      if (!bolum) return;
      bolum.open = !bolum.open;
      if (bolum.open) bolum.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }));
    kart.querySelector("[data-lsec]").addEventListener("change", (e) => {
      if (e.target.checked) listeSecili.add(pid); else listeSecili.delete(pid);
      listeTopluCiz();
    });
    igBagla(kart, pid);
  }

  function listeTabloCiz(liste) {
    const th = (metin, ek = "") => `<th class="p-3 font-label-sm text-label-sm ${ek}" style="border-bottom:0">${metin}</th>`;
    const rozet = (metin, sinif) => `<span class="px-1.5 py-0.5 rounded font-label-sm text-label-sm ${sinif}">${metin}</span>`;
    const hepsi = liste.every((r) => listeSecili.has(r.product_id));
    $("#listeTablo").innerHTML = `<thead><tr class="bg-surface-container-low text-outline font-label-sm text-label-sm uppercase tracking-wider">
        <th class="p-3 w-10" style="border-bottom:0"><input type="checkbox" id="listeHepsi" ${hepsi ? "checked" : ""} class="w-4 h-4 rounded accent-primary cursor-pointer" aria-label="Listelenenlerin hepsini seç"></th>
        ${th("#")}${th("Model")}${th("Puan", "text-right")}${th("Baskı")}${th("Ağırlık", "text-right")}${th("Maliyet → Fiyat", "text-right")}${th("Saatlik", "text-right")}${th("Durum")}${th("", "text-right")}</tr></thead>
      <tbody class="text-on-surface font-body-sm text-body-sm">${liste.map((r, i) => {
        const p = r.products, m = isaretler.get(r.product_id) || {}, planda = planIdleri.has(r.product_id);
        const durum = [m.printed ? rozet("✓ Basıldı", "bg-tertiary-fixed/30 text-tertiary") : "", m.video ? rozet("🎬 Video", "bg-primary-fixed text-on-primary-fixed-variant") : "",
          m.sold_count > 0 ? rozet(`💰 ${m.sold_count}`, "bg-secondary-fixed text-on-secondary-fixed-variant") : "", planda ? rozet("📋 Planda", "bg-surface-container-high text-on-surface-variant") : ""].join(" ") || `<span class="text-outline">—</span>`;
        return `<tr data-ltpid="${r.product_id}" class="${i % 2 ? "bg-surface-container-low/20" : "bg-white"} hover:bg-surface-container-low/60 transition-colors">
          <td class="p-3" style="border-bottom:0"><input type="checkbox" data-lsec="${r.product_id}" ${listeSecili.has(r.product_id) ? "checked" : ""} class="w-4 h-4 rounded accent-primary cursor-pointer" aria-label="Modeli seç"></td>
          <td class="p-3 font-label-md text-label-md font-bold text-primary" style="border-bottom:0">${r.rank}</td>
          <td class="p-3" style="border-bottom:0"><div class="flex items-center gap-3"><div class="w-10 h-10 rounded-lg bg-surface-container-high overflow-hidden shrink-0 flex items-center justify-center">${p.image_url ? `<img src="${url(p.image_url)}" alt="" loading="lazy" class="w-full h-full object-cover">` : lIkon("view_in_ar", 20, "text-outline")}</div>
            <div class="min-w-0 max-w-[280px]"><a href="${url(p.url)}" target="_blank" rel="noopener" class="font-label-md text-label-md font-medium text-on-surface hover:text-primary no-underline truncate block">${esc(p.name)}</a><span class="font-label-sm text-label-sm text-outline">${esc(p.category || "-")} • ${esc(p.creator || "-")}${p.trend_rank ? ` • 🔥 #${p.trend_rank}` : ""}</span></div></div></td>
          <td class="p-3 text-right font-semibold" style="border-bottom:0">${esc(r.score)}</td>
          <td class="p-3" style="border-bottom:0">${esc(sure(p.print_time_min))}</td>
          <td class="p-3 text-right" style="border-bottom:0">${p.weight_g ? `${Math.round(p.weight_g)} g` : "-"}</td>
          <td class="p-3 text-right" style="border-bottom:0">${p.cost_tl == null ? "-" : `${Math.round(p.cost_tl)} → ${Math.round(p.price_tl)}`}</td>
          <td class="p-3 text-right text-secondary font-semibold" style="border-bottom:0">${tl(p.hourly_profit_tl)}</td>
          <td class="p-3" style="border-bottom:0">${durum}</td>
          <td class="p-3 text-right whitespace-nowrap" style="border-bottom:0"><button type="button" data-lplan="${r.product_id}" class="px-2.5 py-1 rounded-lg font-label-sm text-label-sm ${planda ? "bg-tertiary text-on-tertiary" : "bg-surface-container-low text-on-surface hover:bg-primary hover:text-on-primary"}">${planda ? "✓ Planda" : "Plana ekle"}</button></td>
        </tr>`;
      }).join("")}</tbody>`;
  }

  async function listeToplu(islem) {
    if (islem === "temizle") { listeSecili.clear(); listeTopluAcik = false; return kartlariCiz(); }
    if (islem === "secHepsi") { listeFiltreli().forEach((r) => listeSecili.add(r.product_id)); return kartlariCiz(); }
    const ids = [...listeSecili];
    if (!ids.length) return alert("Önce kartlardaki kutudan model seç.");
    const simdi = new Date().toISOString();
    if (islem === "plan") {
      const yeni = ids.filter((id) => !planIdleri.has(id));
      if (yeni.length) {
        const { error } = await sb.from("print_plan").upsert(yeni.map((id) => ({ product_id: id, quantity: 1, done: false, updated_at: simdi })));
        if (error) return alert("Plan güncellenemedi: " + error.message);
        yeni.forEach((id) => planIdleri.add(id));
      }
    } else if (islem === "printed" || islem === "video") {
      const kayitlar = ids.map((id) => {
        const m = isaretler.get(id) || {};
        return { product_id: id, printed: !!m.printed, video: !!m.video, sold_count: m.sold_count || 0, note: m.note || null, [islem]: true, updated_at: simdi };
      });
      const { error } = await sb.from("product_marks").upsert(kayitlar);
      if (error) return alert("Kaydedilemedi: " + error.message);
      kayitlar.forEach((k) => isaretler.set(k.product_id, k));
    }
    kartlariCiz();
  }

  // Günlük liste kontrolleri (kategori ve "sadece işaretlenmemiş" başlatma bölümünde bağlanır)
  $("#listeAra").addEventListener("input", kartlariCiz);
  $("#listeSira").addEventListener("change", kartlariCiz);
  document.querySelectorAll("[data-gorunum]").forEach((b) => b.addEventListener("click", () => {
    listeGorunum = b.dataset.gorunum;
    try { localStorage.setItem("listeGorunum", listeGorunum); } catch (_) { /* tarayıcı depolaması kapalı olabilir */ }
    kartlariCiz();
  }));
  $("#listeTopluAc").addEventListener("click", () => { listeTopluAcik = !listeTopluAcik; listeTopluCiz(); });
  $("#listeTopluBar").addEventListener("click", (e) => { const b = e.target.closest("[data-ltoplu]"); if (b) listeToplu(b.dataset.ltoplu); });
  $("#listePlanaGit").addEventListener("click", () => document.querySelector('[data-sekme="plan"]').click());
  $("#listeTablo").addEventListener("change", (e) => {
    if (e.target.id === "listeHepsi") {
      listeFiltreli().forEach((r) => e.target.checked ? listeSecili.add(r.product_id) : listeSecili.delete(r.product_id));
      return kartlariCiz();
    }
    const sec = e.target.closest("[data-lsec]");
    if (sec) { const id = Number(sec.dataset.lsec); if (sec.checked) listeSecili.add(id); else listeSecili.delete(id); listeTopluCiz(); }
  });
  $("#listeTablo").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-lplan]");
    if (!b) return;
    await planaEkleCikar(Number(b.dataset.lplan));
    kartlariCiz();
  });

  // ------------------------------------------------------------ Instagram
  const IG_DEPO = "instagram", IG_EN_BUYUK = 50 * 1024 * 1024;
  const yerelZaman = (d) => { const p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
  const varsayilanZaman = () => { const d = new Date(); d.setHours(20, 0, 0, 0); if (d <= new Date()) d.setDate(d.getDate() + 1); return yerelZaman(d); };
  const etiketSayisi = (t) => (t.match(/#[\p{L}\p{N}_]/gu) || []).length;

  function igBagla(kart, pid) {
    const metin = kart.querySelector(".igMetin"), sayac = kart.querySelector(".igSayac");
    const durumAlan = kart.querySelector(".igDurum"), dugme = kart.querySelector(".igPlanla");
    const yaz = (t, hata = false) => { durumAlan.textContent = t; durumAlan.style.color = hata ? "var(--bad)" : ""; };
    const say = () => { sayac.textContent = `${metin.value.length}/2200 karakter · ${etiketSayisi(metin.value)}/30 etiket`; };
    kart.querySelector(".igAc").addEventListener("toggle", (e) => {
      if (e.target.open && !kart.querySelector(".igZaman").value) kart.querySelector(".igZaman").value = varsayilanZaman();
      say();
    });
    metin.addEventListener("input", say);
    kart.querySelector(".igKopyala").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(metin.value); yaz("Kopyalandı ✓"); }
      catch (e) { metin.select(); yaz("Seçildi; kopyalamak için Ctrl+C"); }
    });
    dugme.addEventListener("click", async () => {
      const dosya = kart.querySelector(".igVideo").files[0];
      const zaman = new Date(kart.querySelector(".igZaman").value);
      const aciklama = metin.value.trim();
      if (!dosya) return yaz("Önce videoyu seç.", true);
      if (dosya.size > IG_EN_BUYUK) return yaz("Video 50 MB'tan büyük; telefonda 1080p olarak dışa aktarıp tekrar dene.", true);
      if (isNaN(zaman)) return yaz("Paylaşım zamanını seç.", true);
      if (aciklama.length > 2200 || etiketSayisi(aciklama) > 30) return yaz("Açıklama en fazla 2200 karakter ve 30 etiket olabilir.", true);
      const mov = /quicktime/.test(dosya.type) || /\.mov$/i.test(dosya.name);
      const yol = `${pid}/${Date.now()}.${mov ? "mov" : "mp4"}`;
      dugme.disabled = true; yaz("Video yükleniyor...");
      try {
        const yk = await sb.storage.from(IG_DEPO).upload(yol, dosya, { contentType: mov ? "video/quicktime" : "video/mp4", upsert: false });
        if (yk.error) return yaz("Video yüklenemedi: " + yk.error.message + igSqlIpucu(yk.error), true);
        const kayit = { product_id: pid, video_path: yol, caption: aciklama, scheduled_at: zaman.toISOString() };
        if (!kart.querySelector(".igDuzenleKutu").checked) kayit.video_edit = false;  // varsayılan: düzenlenir
        const kayitlar = [kayit];
        // Hikâye: aynı video ayrı bir gönderi olarak (açıklamasız); video son gönderi paylaşılınca silinir.
        if (kart.querySelector(".igHikayeKutu").checked) kayitlar.push({ ...kayit, caption: "", media_type: "STORIES" });
        const { error } = await sb.from("instagram_posts").insert(kayitlar);
        if (error) { await sb.storage.from(IG_DEPO).remove([yol]); return yaz("Planlanamadı: " + error.message + igSqlIpucu(error), true); }
        kart.querySelector(".igVideo").value = "";
        kart.querySelector(".igHikayeKutu").checked = false;
        yaz(zaman <= new Date() ? "Planlandı ✓ İlk kontrolde (15 dk içinde) paylaşılacak." : `Planlandı ✓ ${zaman.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })}`);
      } finally { dugme.disabled = false; }
    });
    const carDugme = kart.querySelector(".igCarousel");
    carDugme.addEventListener("click", async () => {
      const dosyalar = [...kart.querySelector(".igFoto").files];
      const zaman = new Date(kart.querySelector(".igZaman").value);
      const aciklama = metin.value.trim();
      if (dosyalar.length < 2 || dosyalar.length > 10) return yaz("Carousel için 2-10 fotoğraf seç.", true);
      if (isNaN(zaman)) return yaz("Paylaşım zamanını seç.", true);
      if (aciklama.length > 2200 || etiketSayisi(aciklama) > 30) return yaz("Açıklama en fazla 2200 karakter ve 30 etiket olabilir.", true);
      carDugme.disabled = true; yaz("Fotoğraflar hazırlanıyor...");
      const yollar = [];
      try {
        const oran = await ilkOran(dosyalar[0]);
        for (const [i, d] of dosyalar.entries()) {
          const jpeg = await jpegYap(d, oran);
          const yol = `${pid}/${Date.now()}_${i + 1}.jpg`;
          const yk = await sb.storage.from(IG_DEPO).upload(yol, jpeg, { contentType: "image/jpeg", upsert: false });
          if (yk.error) throw new Error("Fotoğraf yüklenemedi: " + yk.error.message + igSqlIpucu(yk.error));
          yollar.push(yol);
          yaz(`Yükleniyor ${i + 1}/${dosyalar.length}...`);
        }
        const { error } = await sb.from("instagram_posts").insert({ product_id: pid, media_type: "CAROUSEL", image_paths: yollar, caption: aciklama, scheduled_at: zaman.toISOString() });
        if (error) throw new Error("Planlanamadı: " + error.message + igSqlIpucu(error));
        kart.querySelector(".igFoto").value = "";
        yaz(`Carousel planlandı ✓ ${zaman.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })}`);
      } catch (e) {
        if (yollar.length) await sb.storage.from(IG_DEPO).remove(yollar);
        yaz(e.message || String(e), true);
      } finally { carDugme.disabled = false; }
    });
  }
  // Instagram carousel'i ilk fotoğrafın oranında gösterir; oran 4:5 ile 1.91:1 arasında olmalı.
  const IG_ORAN = [0.8, 1.91];
  async function ilkOran(dosya) {
    const b = await createImageBitmap(dosya);
    return Math.min(IG_ORAN[1], Math.max(IG_ORAN[0], b.width / b.height));
  }
  async function jpegYap(dosya, oran) {
    let bmp;
    try { bmp = await createImageBitmap(dosya); } catch (e) { throw new Error(`${dosya.name} açılamadı (HEIC ise telefonda JPEG olarak paylaş).`); }
    let sx = 0, sy = 0, sw = bmp.width, sh = bmp.height;
    if (sw / sh > oran) { const y = Math.round(sh * oran); sx = Math.round((sw - y) / 2); sw = y; }
    else { const y = Math.round(sw / oran); sy = Math.round((sh - y) / 2); sh = y; }
    const olcek = Math.min(1, 1440 / sw);
    const c = document.createElement("canvas");
    c.width = Math.round(sw * olcek); c.height = Math.round(sh * olcek);
    c.getContext("2d").drawImage(bmp, sx, sy, sw, sh, 0, 0, c.width, c.height);
    return new Promise((ok, red) => c.toBlob((b) => b ? ok(b) : red(new Error("JPEG'e çevrilemedi")), "image/jpeg", 0.9));
  }
  const igSqlIpucu = (h) => /instagram|bucket|not found|relation|mime|media_type|image_paths/i.test(h.message || "") ? " (Supabase'te supabase/guncelleme_2026-11-10_instagram.sql ve guncelleme_2026-11-26_performans.sql çalıştırıldı mı?)" : "";

  // ------------------------------------------------------------ çok satanlar (pazar keşfi)
  const ESLESME = { "görsel": "🎯 görsel eşleşme", "isim": "🔤 isimle bulundu, görseli karşılaştır" };
  async function kesifYukle() {
    const kap = $("#kesifListe");
    const son = await sb.from("market_discovery").select("kesif_tarihi").order("kesif_tarihi", { ascending: false }).limit(1);
    if (son.error) { kap.innerHTML = `<div class="hata">${esc(son.error.message)}${/market_discovery|relation/i.test(son.error.message) ? " (Supabase'te supabase/guncelleme_2026-11-10_kesif.sql çalıştırıldı mı?)" : ""}</div>`; return; }
    if (!son.data.length) { kap.innerHTML = `<div class="bos">Henüz keşif yapılmadı. Haftada bir günlük analizle birlikte çalışır.</div>`; return; }
    const gun = son.data[0].kesif_tarihi;
    const { data: satirlar, error } = await sb.from("market_discovery").select("*").eq("kesif_tarihi", gun).order("ilan_sayisi", { ascending: false });
    const saticiSayisi = (k) => Object.values(k.siteler || {}).reduce((t, n) => t + Number(n || 0), 0);
    const data = (satirlar || []).slice().sort((a, b) => saticiSayisi(b) - saticiSayisi(a) || b.ilan_sayisi - a.ilan_sayisi);
    if (error) { kap.innerHTML = `<div class="hata">${esc(error.message)}</div>`; return; }
    await planIdleriYukle();
    kap.innerHTML = `<p class="muted">Keşif tarihi: ${esc(new Date(gun).toLocaleDateString("tr-TR", { dateStyle: "long" }))}</p>` + data.map((k, n) => {
      const modeller = k.eslesmeler || [];
      const siteler = Object.entries(k.siteler || {}).sort((a, b) => b[1] - a[1]).map(([s, a]) => `<span class="cip">${esc(s)} ${a}</span>`).join("");
      const fiyat = k.fiyat_medyan ? `${tl(k.fiyat_min)} – ${tl(k.fiyat_max)} (ortanca ${tl(k.fiyat_medyan)})` : "fiyat yok";
      const gorseller = `<figure class="pazar">${k.gorsel ? `<img src="${url(k.gorsel)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}<figcaption>🛒 E-ticarette satılan</figcaption></figure>`
        + modeller.map((m) => `<figure>${m.image_url ? `<img src="${url(m.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}<figcaption>${m.eslesme === "görsel" ? "🎯" : "🔤"} ${esc(m.name)}</figcaption></figure>`).join("");
      const ilanlar = (k.ilanlar || []).slice(0, 10).map((i) => `<li><a href="${url(i.link)}" target="_blank" rel="noopener">${esc(i.site)}: ${esc((i.title || "ilan").slice(0, 70))}</a>${i.price ? " — " + tl(i.price) : ""}</li>`).join("");
      const satirlar = modeller.length ? modeller.map((m) => `<div class="modelSatir">
          <span>${ESLESME[m.eslesme] || esc(m.eslesme)}</span>
          <a href="${url(m.url)}" target="_blank" rel="noopener">${esc(m.name)}</a>
          <span class="muted">${sure(m.print_time_min)} baskı · maliyet ${tl(m.cost_tl)}${m.kar_tl != null ? ` · ilan başına ~${tl(m.kar_tl)} kâr` : ""}${m.saatlik_kar_tl ? ` (saatte ~${tl(m.saatlik_kar_tl)})` : ""}</span>
          ${m.product_id ? `<button type="button" class="ikincil" data-kesif-plan="${Number(m.product_id)}">${planIdleri.has(m.product_id) ? "✓ Planda" : "📋 Plana ekle"}</button>` : ""}
        </div>`).join("") : `<div class="modelSatir muted">MakerWorld'de eşleşen model bulunamadı${k.mw_sorgu ? ` (aranan: "${esc(k.mw_sorgu)}")` : ""}.</div>`;
      const diger = (k.diger_kaynaklar || []).filter((m) => m.site !== "MakerWorld").slice(0, 3)
        .map((m) => `<a href="${url(m.link)}" target="_blank" rel="noopener">${esc(m.site)}</a>`).join(" · ");
      return `<article class="kesifKart">
        <div class="ust"><span class="sira">${n + 1}.</span><span class="ad">${esc(k.ad)}</span><span class="puan">${saticiSayisi(k)} satıcı</span></div>
        <div class="yanyana">${gorseller}</div>
        <div class="cipler"><span class="muted" style="font-size:13px">Satıcılar:</span>${siteler}<span class="muted" style="font-size:13px">· ${k.ilan_sayisi} ilan</span></div>
        <div>💰 ${fiyat}</div>
        ${satirlar}
        ${diger ? `<div class="muted" style="font-size:13px">Diğer model siteleri: ${diger}</div>` : ""}
        <details><summary>İlanlar (${(k.ilanlar || []).length})</summary><ul>${ilanlar}</ul></details>
      </article>`;
    }).join("");
    kap.querySelectorAll("[data-kesif-plan]").forEach((b) => b.addEventListener("click", () => planaEkleCikar(Number(b.dataset.kesifPlan), b)));
  }

  const IG_DURUM = { bekliyor: "⏳ Bekliyor", isleniyor: "⚙️ İşleniyor", paylasildi: "✅ Paylaşıldı", hata: "⚠️ Hata" };
  const IG_TUR = { REELS: "🎬 Reels", STORIES: "📱 Hikâye", CAROUSEL: "🖼️ Carousel" };
  // Günlük analiz paylaşılan gönderilerin istatistiğini günde bir günceller.
  const igIstatistik = (i) => !i ? "" : [["reach", "erişim"], ["views", "izlenme"], ["likes", "beğeni"], ["saved", "kaydetme"], ["shares", "paylaşım"], ["comments", "yorum"]]
    .filter(([k]) => i[k] != null).map(([k, ad]) => `${Number(i[k]).toLocaleString("tr-TR")} ${ad}`).join("<br>");
  async function igYukle() {
    const tablo = $("#igTablo");
    const { data, error } = await sb.from("instagram_posts").select("*, products(name, url)").order("scheduled_at", { ascending: false }).limit(100);
    if (error) { tablo.innerHTML = `<tr><td class="hata">${esc(error.message + igSqlIpucu(error))}</td></tr>`; return; }
    if (!data.length) { tablo.innerHTML = `<tr><td class="muted">Henüz planlanmış gönderi yok. Günlük listede bir ürünün "📸 Instagram'a planla" bölümünü kullan.</td></tr>`; return; }
    tablo.innerHTML = `<tr><th>Ürün</th><th>Tür</th><th>Zaman</th><th>Durum</th><th>İstatistik</th><th>Sonuç</th><th></th></tr>` + data.map((g) => `<tr data-ig="${g.id}">
      <td>${g.products ? `<a href="${url(g.products.url)}" target="_blank" rel="noopener">${esc(g.products.name)}</a>` : "-"}
        ${g.caption ? `<details><summary>Açıklama</summary><pre>${esc(g.caption)}</pre></details>` : ""}</td>
      <td>${IG_TUR[g.media_type || "REELS"] || esc(g.media_type)}</td>
      <td>${esc(new Date(g.scheduled_at).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" }))}</td>
      <td>${IG_DURUM[g.status] || esc(g.status)}</td>
      <td>${igIstatistik(g.insights)}</td>
      <td>${g.permalink ? `<a href="${url(g.permalink)}" target="_blank" rel="noopener">Instagram'da aç</a>` : g.error ? `<span class="hata" style="padding:0;border:0;background:none">${esc(g.error)}</span>` : ""}</td>
      <td>${g.status === "hata" ? `<button type="button" class="ikincil" data-tekrar>Tekrar dene</button> ` : ""}${g.status === "isleniyor" ? "" : `<button type="button" class="ikincil" data-sil>${g.status === "bekliyor" ? "İptal" : "Sil"}</button>`}</td></tr>`).join("");
    tablo.querySelectorAll("tr[data-ig]").forEach((tr) => {
      const g = data.find((x) => x.id === Number(tr.dataset.ig));
      tr.querySelector("[data-tekrar]")?.addEventListener("click", async () => {
        const { error } = await sb.from("instagram_posts").update({ status: "bekliyor", error: null, scheduled_at: new Date().toISOString(), updated_at: new Date().toISOString() }).eq("id", g.id);
        if (error) alert("Güncellenemedi: " + error.message); else igYukle();
      });
      tr.querySelector("[data-sil]")?.addEventListener("click", async () => {
        if (!confirm(g.status === "bekliyor" ? "Bu gönderi iptal edilsin ve video silinsin mi?" : "Bu kayıt silinsin mi?")) return;
        if (g.status !== "paylasildi") {
          const ayniVideo = g.video_path && data.some((x) => x.id !== g.id && x.video_path === g.video_path && ["bekliyor", "isleniyor"].includes(x.status));
          const yollar = g.media_type === "CAROUSEL" ? (g.image_paths || [])
            : ayniVideo ? [] : [g.video_path, g.video_path.replace(/\.[^./]+$/, "") + "_hazir.mp4"];
          if (yollar.length) await sb.storage.from(IG_DEPO).remove(yollar);
        }
        const { error } = await sb.from("instagram_posts").delete().eq("id", g.id);
        if (error) alert("Silinemedi: " + error.message); else igYukle();
      });
    });
  }

  // ------------------------------------------------------------ siparişler
  const SIP_DURUM = { yeni: "🆕 Yeni", basiliyor: "🖨️ Basılıyor", hazir: "📦 Hazır", kargoda: "🚚 Kargoda", teslim: "✅ Teslim", iptal: "✖️ İptal" };
  const SIP_KANAL = { instagram: "Instagram", trendyol: "Trendyol", hepsiburada: "Hepsiburada", etsy: "Etsy", elden: "Elden", diger: "Diğer" };
  const sipSqlIpucu = (h) => /siparisler|relation|not found|column|schema cache|bucket/i.test(h.message || "") ? " (Supabase'te supabase/guncelleme_2026-11-26_performans.sql ve guncelleme_2026-11-26b_siparis_detay.sql çalıştırıldı mı?)" : "";
  const secenekler = (o, secili) => Object.entries(o).map(([k, v]) => `<option value="${k}"${k === secili ? " selected" : ""}>${esc(v)}</option>`).join("");
  let sipUrunAdi = new Map();   // ürün adı → product_id (listeden seçilirse)
  let sipBagli = false;
  let sipVeri = [];             // yüklenen siparişler (filtreleme ve sayfalama istemci tarafında)
  let sipSekme = "tum";         // hızlı sekme: tum | kuyruk | kargo | teslim
  let sipSayfa = 1;
  let sipCekmeId = null;
  let sipTopluAcik = false;
  const sipSecili = new Set();  // toplu işlem için seçilen sipariş id'leri
  const SIP_HIZLI = { tum: "Tümü", kuyruk: "Baskı Kuyruğu", kargo: "Kargo Bekleyen", teslim: "Teslim Edilen" };
  const SIP_HIZLI_DURUM = { kuyruk: ["yeni", "basiliyor"], kargo: ["hazir", "kargoda"], teslim: ["teslim"] };
  const SIP_AKIS = ["yeni", "basiliyor", "hazir", "kargoda", "teslim"];
  const SIP_ILERI = { yeni: "Baskıya başla", basiliyor: "Üretimi tamamla & pakete gönder", hazir: "Kargoya verildi", kargoda: "Teslim edildi" };
  const SIP_ODEME = { kart: "Kredi kartı", havale: "Havale/EFT", kapida: "Kapıda ödeme", pazaryeri: "Pazaryeri", nakit: "Nakit", diger: "Diğer" };
  const SIP_SOL = { yeni: "border-primary", basiliyor: "border-secondary", hazir: "border-tertiary", kargoda: "border-tertiary", teslim: "border-tertiary", iptal: "border-outline-variant" };
  const SIP_PILL = { yeni: "bg-primary-fixed text-on-primary-fixed-variant", basiliyor: "bg-error-container text-on-error-container", hazir: "bg-secondary-fixed text-on-secondary-fixed-variant", kargoda: "bg-primary-fixed text-on-primary-fixed-variant", teslim: "bg-tertiary-fixed/30 text-tertiary", iptal: "bg-surface-container-high text-on-surface-variant" };
  const sipGecerli = () => sipVeri.filter((s) => s.durum !== "iptal");
  const sipBul = (id) => sipVeri.find((x) => x.id === id);
  const sipIkon = (ad, sinif = "text-[18px]") => `<span class="material-symbols-outlined ${sinif}">${ad}</span>`;
  const sipAcikMi = (s) => !["teslim", "iptal"].includes(s.durum);
  const tcMaske = (t) => t ? `${t.slice(0, 3)}******${t.slice(-2)}` : "-";
  const sehir = (a) => (a || "").split(/[,\n]/).map((x) => x.trim()).filter(Boolean).pop()?.slice(0, 30) || "";
  // datetime-local girdisi için yerel saat biçimi
  const sipYerelZaman = (t) => { if (!t) return ""; const d = new Date(t); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

  // "Bugün, 14:32" / "Dün, 18:40" / "25 Kas, 16:50" (geleceği de "Yarın" diye yazar)
  function sipZaman(t) {
    const d = new Date(t), simdi = new Date();
    const gun = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const fark = Math.round((gun(simdi) - gun(d)) / 864e5);
    const saat = d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    if (fark === 0) return `Bugün, ${saat}`;
    if (fark === 1) return `Dün, ${saat}`;
    if (fark === -1) return `Yarın, ${saat}`;
    return `${d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" })}, ${saat}`;
  }

  // Baskı ilerlemesi: elle girilmişse o; yoksa "Basılıyor"a geçiş zamanı ve MakerWorld süre tahmininden.
  function sipToplamDk(s) { return s.products?.print_time_min ? s.products.print_time_min * s.adet : null; }

  // ------------------------------------------------------------ yazıcı köprüsü (python -m urun_bulucu.kopru)
  let sipYazicilar = [];        // yazici_durum satırları: {ad, model, durum, goruldu}
  const YAZICI_DURUM = { IDLE: "Boşta", PREPARE: "Hazırlanıyor", SLICING: "Dilimleniyor", RUNNING: "Yazdırıyor", PAUSE: "Duraklatıldı", FINISH: "Bitti", FAILED: "Başarısız" };
  const yaziciSqlIpucu = (h) => /yazici_|relation|not found|schema cache/i.test(h.message || "") ? " (Supabase'te supabase/guncelleme_2026-11-26c_yazici_koprusu.sql çalıştırıldı mı?)" : "";
  const yaziciBagli = (y) => !!y && Date.now() - new Date(y.goruldu).getTime() < 60000;
  const saniyeOnce = (t) => { const sn = Math.max(0, Math.round((Date.now() - new Date(t).getTime()) / 1000)); return sn < 60 ? `${sn} sn önce` : sn < 3600 ? `${Math.round(sn / 60)} dk önce` : sipZaman(t); };
  // Siparişin yazıcısı: adı eşleşen köprü; ad girilmemişse ve tek köprü varsa o.
  const sipYaziciSatiri = (s) => sipYazicilar.find((y) => y.ad === s.yazici) || (!s.yazici && sipYazicilar.length === 1 ? sipYazicilar[0] : null);
  async function yaziciGetir() {
    const { data, error } = await sb.from("yazici_durum").select("*");
    sipYazicilar = error ? [] : data || [];
    return sipYazicilar;
  }
  // Basılmakta olan sipariş için köprünün canlı verisi (yoksa null → tahmin kullanılır)
  function sipCanli(s) {
    if (s.durum !== "basiliyor") return null;
    const y = sipYaziciSatiri(s);
    if (!yaziciBagli(y)) return null;
    const d = y.durum || {};
    return ["RUNNING", "PAUSE", "PREPARE"].includes(d.durum) ? d : null;
  }
  // Panelden köprüye istek gönderir ve sonucunu bekler (köprü 3 sn'de bir bakar).
  async function yaziciIstek(tur, ek = {}) {
    const { data, error } = await sb.from("yazici_istekleri").insert({ tur, ...ek }).select("id").single();
    if (error) throw new Error(error.message + yaziciSqlIpucu(error));
    const bitis = Date.now() + 5 * 60e3;
    while (Date.now() < bitis) {
      await new Promise((r) => setTimeout(r, 2000));
      const { data: r } = await sb.from("yazici_istekleri").select("durum, sonuc, hata").eq("id", data.id).single();
      if (r?.durum === "tamam" || r?.durum === "hata") {
        sb.from("yazici_istekleri").delete().eq("id", data.id).then(() => {}, () => {});
        if (r.durum === "hata") throw new Error(r.hata || "Köprü isteği işleyemedi");
        return r.sonuc || {};
      }
    }
    throw new Error("Köprü 5 dakikada yanıt vermedi; evdeki bilgisayarda köprü çalışıyor mu?");
  }

  function sipIlerleme(s) {
    if (["hazir", "kargoda", "teslim"].includes(s.durum)) return 100;
    if (s.durum !== "basiliyor") return null;
    const canli = sipCanli(s);
    if (canli?.yuzde != null) return canli.yuzde;
    if (s.ilerleme != null) return s.ilerleme;
    const toplam = sipToplamDk(s);
    if (!s.baski_baslangic || !toplam) return null;
    const gecen = (Date.now() - new Date(s.baski_baslangic).getTime()) / 6e4;
    return Math.min(99, Math.max(0, Math.round((gecen / toplam) * 100)));
  }
  function sipKalanDk(s) {
    const canli = sipCanli(s);
    if (canli?.kalan_dk != null) return canli.kalan_dk;
    const toplam = sipToplamDk(s), yuzde = sipIlerleme(s);
    if (s.durum !== "basiliyor" || !toplam || yuzde == null) return null;
    return Math.max(0, Math.round(toplam * (1 - yuzde / 100)));
  }

  async function sipUrunleriYukle() {
    const { data } = await sb.from("weekly_picks").select("product_id, products(name)").order("pick_date", { ascending: false }).limit(800);
    sipUrunAdi = new Map();
    for (const r of data || []) if (r.products?.name && !sipUrunAdi.has(r.products.name)) sipUrunAdi.set(r.products.name, r.product_id);
    $("#sipUrunler").innerHTML = [...sipUrunAdi.keys()].map((ad) => `<option value="${esc(ad)}"></option>`).join("");
  }

  async function sipGuncelleCok(id, alanlar) {
    const { error } = await sb.from("siparisler").update({ ...alanlar, updated_at: new Date().toISOString() }).eq("id", id);
    if (error) { alert("Güncellenemedi: " + error.message + sipSqlIpucu(error)); return false; }
    return true;
  }
  const sipGuncelle = (id, alan, deger) => sipGuncelleCok(id, { [alan]: deger });
  // Durum değişince "Basılıyor"a ilk geçişte baskı başlangıç zamanı yazılır (ilerleme hesabı için).
  function sipDurumAlanlari(s, durum) {
    const alanlar = { durum };
    if (durum === "basiliyor" && !s.baski_baslangic) alanlar.baski_baslangic = new Date().toISOString();
    // Tek yazıcı (köprü) varsa ve siparişe yazıcı yazılmamışsa otomatik atanır.
    if (durum === "basiliyor" && !s.yazici && sipYazicilar.length === 1) alanlar.yazici = sipYazicilar[0].ad;
    return alanlar;
  }

  async function sipSil(id) {
    if (id == null || !confirm("Bu sipariş silinsin mi? (Bağlı videolar da silinir.)")) return;
    const s = sipBul(id);
    const { error } = await sb.from("siparisler").delete().eq("id", id);
    if (error) return alert("Silinemedi: " + error.message);
    const yollar = sipMedya(s).map((m) => m.yol).filter((y) => !sipVeri.some((x) => x.id !== id && sipMedya(x).some((m) => m.yol === y)));
    if (yollar.length) await sb.storage.from(SIP_DEPO).remove(yollar);
    if (sipCekmeId === id) sipCekmeKapat();
    sipSecili.delete(id);
    siparisYukle();
  }

  // Çekmece ve formdaki alanların değerini veritabanı biçimine çevirir; geçersizse null + uyarı.
  function sipAlanDegeri(el) {
    if (el.type === "checkbox") return { deger: el.checked };
    if (el.type === "number" || el.type === "range") return { deger: el.value === "" ? null : Number(el.value) };
    if (el.type === "datetime-local") return { deger: el.value ? new Date(el.value).toISOString() : null };
    const deger = el.value.trim() || null;
    if (el.dataset.cekmeAlan === "musteri_tc" && deger && !/^\d{11}$/.test(deger)) return { hata: "TC kimlik no 11 haneli rakam olmalı." };
    return { deger };
  }

  function sipFormBagla() {
    if (sipBagli) return;
    sipBagli = true;
    $("#sipKanal").innerHTML = secenekler(SIP_KANAL, "instagram");
    $("#sipOdeme").innerHTML = `<option value="">Belirtilmedi</option>` + secenekler(SIP_ODEME, "");
    $("#sipFiltreDurum").innerHTML = `<option value="">Tüm Durumlar</option>` + secenekler(SIP_DURUM, "");
    $("#sipFiltreKanal").innerHTML = `<option value="">Tüm Kanallar</option>` + secenekler(SIP_KANAL, "");
    $("#sipTopluDurum").innerHTML = `<option value="">Durumu değiştir…</option>` + secenekler(SIP_DURUM, "");
    const yeniden = () => { sipSayfa = 1; sipCiz(); };
    ["#sipFiltreTarih", "#sipFiltreDurum", "#sipFiltreKanal", "#sipOdenmemis", "#sipSadeceAcil", "#sipSayfaBoy"].forEach((id) => $(id).addEventListener("change", yeniden));
    $("#sipAra").addEventListener("input", yeniden);
    $("#sipHizli").addEventListener("click", (e) => {
      const b = e.target.closest("[data-h]");
      if (b) { sipSekme = b.dataset.h; yeniden(); }
    });
    $("#sipSayfaNav").addEventListener("click", (e) => {
      const b = e.target.closest("[data-sayfa]");
      if (b && !b.disabled) { sipSayfa = Number(b.dataset.sayfa); sipCiz(); }
    });
    $("#sipYeniAc").addEventListener("click", () => { $("#sipFormKart").hidden = !$("#sipFormKart").hidden; });
    $("#sipCsv").addEventListener("click", () => sipCsvIndir(sipFiltreli()));
    $("#sipTopluAc").addEventListener("click", () => { sipTopluAcik = !sipTopluAcik; sipTopluCiz(); });
    $("#sipTopluBar").addEventListener("click", (e) => { const b = e.target.closest("[data-toplu]"); if (b) sipToplu(b.dataset.toplu); });

    // Tablo: seçim kutuları, satır düğmeleri ve satır içi alanlar (olay devri; tablo her çizimde yenilenir).
    const tablo = $("#siparisTablo");
    tablo.addEventListener("change", async (e) => {
      if (e.target.id === "sipHepsi") {
        tablo.querySelectorAll("[data-sec]").forEach((k) => { k.checked = e.target.checked; const id = Number(k.dataset.sec); if (k.checked) sipSecili.add(id); else sipSecili.delete(id); });
        return sipTopluCiz();
      }
      const sec = e.target.closest("[data-sec]");
      if (sec) { const id = Number(sec.dataset.sec); if (sec.checked) sipSecili.add(id); else sipSecili.delete(id); return sipTopluCiz(); }
      const el = e.target.closest("[data-alan]");
      if (!el) return;
      const s = sipBul(Number(el.closest("tr").dataset.sip));
      const alanlar = el.dataset.alan === "durum" ? sipDurumAlanlari(s, el.value) : { [el.dataset.alan]: el.value };
      if (await sipGuncelleCok(s.id, alanlar)) siparisYukle();
    });
    tablo.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-islem]");
      if (!b) return;
      const s = sipBul(Number(b.closest("tr").dataset.sip));
      if (!s) return;
      const islem = b.dataset.islem;
      if (islem === "detay") sipCekmeAc(s.id);
      else if (islem === "video") medyaAc(s.id);
      else if (islem === "irsaliye") sipIrsaliye(s);
      else if (islem === "ata") { sipCekmeAc(s.id); setTimeout(() => $('#sipCekmeIcerik [data-cekme-alan="yazici"]')?.focus(), 50); }
      else if (islem === "odendi") { if (await sipGuncelle(s.id, "odendi", !s.odendi)) siparisYukle(); }
    });

    // Çekmece: tek dinleyici; kapatma, bölüme gitme, durum adımları, silme ve alan değişiklikleri.
    const cekmece = $("#sipCekmece");
    cekmece.addEventListener("click", async (e) => {
      if (e.target.closest("[data-kapat]")) return sipCekmeKapat();
      const git = e.target.closest("[data-git]");
      if (git) {
        cekmece.querySelectorAll("[data-git]").forEach((b) => b.setAttribute("aria-selected", String(b === git)));
        return document.getElementById(git.dataset.git)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      const s = sipBul(sipCekmeId);
      if (!s) return;
      if (e.target.closest("[data-tc-goster]")) { e.target.closest("[data-tc-goster]").outerHTML = `<input type="text" maxlength="11" inputmode="numeric" data-cekme-alan="musteri_tc" value="${esc(s.musteri_tc || "")}" class="w-36 font-mono" style="padding:3px 6px">`; return; }
      if (e.target.closest("[data-ilerleme-oto]")) { if (await sipGuncelle(s.id, "ilerleme", null)) siparisYukle(); return; }
      if (e.target.closest("[data-video]")) return medyaAc(s.id);
      if (e.target.closest("[data-yazdir]")) return sipIrsaliye(s);
      if (e.target.closest("#sipCekmeSil")) return sipSil(s.id);
      if (e.target.closest("#sipCekmeTakip")) {
        if (!s.takip_no) return alert("Bu siparişe takip no girilmemiş.");
        try { await navigator.clipboard.writeText(s.takip_no); alert("Takip no kopyalandı: " + s.takip_no); } catch (_) { prompt("Takip no:", s.takip_no); }
        return;
      }
      if (e.target.closest("#sipCekmeIleri")) {
        const sonraki = SIP_AKIS[SIP_AKIS.indexOf(s.durum) + 1];
        if (sonraki && await sipGuncelleCok(s.id, sipDurumAlanlari(s, sonraki))) siparisYukle();
        return;
      }
      if (e.target.closest("#sipCekmeIptal")) {
        if (confirm("Sipariş iptal edilsin mi? (Silinmez, iptal olarak kalır.)") && await sipGuncelle(s.id, "durum", "iptal")) siparisYukle();
      }
    });
    cekmece.addEventListener("change", async (e) => {
      const el = e.target.closest("[data-cekme-alan]");
      const s = sipBul(sipCekmeId);
      if (!el || !s) return;
      const { deger, hata } = sipAlanDegeri(el);
      if (hata) return alert(hata);
      const alan = el.dataset.cekmeAlan;
      const alanlar = alan === "durum" ? sipDurumAlanlari(s, deger) : { [alan]: deger };
      if (await sipGuncelleCok(s.id, alanlar)) siparisYukle();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (medyaSipId != null) medyaKapat(); else if (sipCekmeId != null) sipCekmeKapat();
    });

    const sayi = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };
    const metin = (id) => $(id).value.trim() || null;
    $("#siparisFormu").addEventListener("submit", async (e) => {
      e.preventDefault();
      const ad = $("#sipUrun").value.trim();
      const kayit = { urun_adi: ad, product_id: sipUrunAdi.get(ad) ?? null, adet: sayi("#sipAdet") || 1,
        renk: metin("#sipRenk"), fiyat_tl: sayi("#sipFiyat"), kanal: $("#sipKanal").value,
        gercek_sure_dk: sayi("#sipSure"), gercek_gram: sayi("#sipGram"), musteri_notu: metin("#sipNot") };
      // Yeni alanlar yalnızca doluysa gönderilir: SQL güncellemesi yapılmadan da temel form çalışır.
      const ek = { musteri_adi: metin("#sipMusteri"), musteri_telefon: metin("#sipTel"), musteri_eposta: metin("#sipEposta"),
        musteri_tc: metin("#sipTc"), teslimat_adresi: metin("#sipAdres"), odeme_yontemi: $("#sipOdeme").value || null,
        termin: $("#sipTermin").value ? new Date($("#sipTermin").value).toISOString() : null, yazici: metin("#sipYazici"),
        kargo_firmasi: metin("#sipKargo"), takip_no: metin("#sipTakip"), fatura_no: metin("#sipFatura"), acil: $("#sipAcil").checked || null };
      for (const [k, v] of Object.entries(ek)) if (v != null) kayit[k] = v;
      const durumYaz = (m, hata) => { $("#sipDurum").textContent = m; $("#sipDurum").style.color = hata ? "var(--bad)" : ""; };
      if (kayit.musteri_tc && !/^\d{11}$/.test(kayit.musteri_tc)) return durumYaz("TC kimlik no 11 haneli rakam olmalı.", true);
      const { error } = await sb.from("siparisler").insert(kayit);
      durumYaz(error ? "Eklenemedi: " + error.message + sipSqlIpucu(error) : "Eklendi ✓", !!error);
      if (!error) { $("#siparisFormu").reset(); $("#sipAdet").value = 1; $("#sipFormKart").hidden = true; siparisYukle(); }
    });
  }

  // 1. Üst kartlar (mockup'taki 4 kart), tüm siparişler üzerinden; filtreden bağımsız.
  function sipOzetCiz() {
    const g = sipGecerli();
    const say = (d) => g.filter((s) => s.durum === d).length;
    const ciro = g.reduce((t, s) => t + Number(s.fiyat_tl || 0), 0);
    const maliyet = g.reduce((t, s) => t + (s.products?.cost_tl || 0) * s.adet, 0);
    const kar = ciro - maliyet;
    const odenmemis = g.filter((s) => !s.odendi).length;
    const acik = g.filter(sipAcikMi);
    const acil = acik.filter((s) => s.acil && ["yeni", "basiliyor"].includes(s.durum)).length;
    const yas = (s) => Date.now() - new Date(s.created_at).getTime();
    const son7 = g.filter((s) => yas(s) < 7 * 864e5).length;
    const onceki7 = g.filter((s) => yas(s) >= 7 * 864e5 && yas(s) < 14 * 864e5).length;
    const trend = onceki7 ? Math.round(((son7 - onceki7) / onceki7) * 1000) / 10 : null;
    const basilan = g.filter((s) => s.durum === "basiliyor");
    const ort = basilan.map(sipIlerleme).filter((x) => x != null);
    const ortIlerleme = ort.length ? Math.round(ort.reduce((a, b) => a + b, 0) / ort.length) : 0;
    const yazicilar = new Set(basilan.map((s) => s.yazici).filter(Boolean));
    const teslimOran = g.length ? Math.round((say("teslim") / g.length) * 1000) / 10 : 0;
    const gecikmis = acik.filter((s) => s.termin && new Date(s.termin) < new Date() && s.durum !== "kargoda").length;

    const kart = (ad, ikon, ikonSinif, halka, govde) => `<div class="p-5 rounded-xl bg-white shadow-sm hover:shadow-md transition-shadow relative overflow-hidden flex flex-col justify-between">
        <div class="absolute -right-4 -top-4 w-24 h-24 rounded-full ${halka} pointer-events-none"></div>
        <div class="flex items-center justify-between mb-3"><span class="font-label-md text-label-md text-outline">${ad}</span>
          <div class="w-9 h-9 rounded-lg ${ikonSinif} flex items-center justify-center">${sipIkon(ikon, "text-[20px]")}</div></div>
        <div>${govde}</div></div>`;
    const buyuk = (deger, birim, birimSinif = "text-outline") => `<div class="flex items-baseline gap-2"><span class="font-headline-xl text-headline-xl text-on-surface">${deger}</span><span class="font-label-sm text-label-sm ${birimSinif}">${birim}</span></div>`;
    const trendHtml = trend == null
      ? `<span class="font-label-sm text-label-sm text-outline">Son 7 günde ${son7} sipariş</span>`
      : `<span class="flex items-center font-label-sm text-label-sm ${trend >= 0 ? "text-tertiary" : "text-error"} font-semibold">${sipIkon(trend >= 0 ? "trending_up" : "trending_down", "text-[14px]")} ${trend >= 0 ? "+" : ""}${trend.toLocaleString("tr-TR")}%</span><span class="font-label-sm text-label-sm text-outline">geçen haftaya göre</span>`;

    $("#siparisOzet").innerHTML =
      kart("Toplam Sipariş", "orders", "bg-surface-container-high text-primary", "bg-primary/5",
        buyuk(g.length, "adet") + `<div class="flex items-center gap-1.5 mt-2">${trendHtml}</div>`) +
      kart("Baskı Bekleyen", "hourglass_top", "bg-error-container text-on-error-container", "bg-error/5",
        buyuk(say("yeni"), "sipariş") + `<div class="flex items-center gap-2 mt-2"><span class="px-2 py-0.5 rounded-full bg-surface-container-high text-error font-label-sm text-label-sm font-semibold">${acil} Acil Öncelikli</span><span class="font-label-sm text-label-sm text-outline">${odenmemis} ödenmemiş</span></div>`) +
      kart("Üretimde Olanlar", "print", "bg-secondary-fixed text-on-secondary-fixed", "bg-secondary/5",
        buyuk(basilan.length, "aktif baskı") + `<div class="w-full bg-surface-container-high h-1.5 rounded-full mt-2.5 overflow-hidden"><div class="bg-secondary-container h-full rounded-full" style="width:${ortIlerleme}%"></div></div>
         <div class="flex items-center justify-between font-label-sm text-label-sm text-outline mt-1.5"><span>%${ortIlerleme} Ortalama ilerleme</span><span>${yazicilar.size} Yazıcı</span></div>`) +
      kart("Kargoya Hazır / Sevk", "local_shipping", "bg-surface-container text-tertiary", "bg-tertiary-fixed/15",
        buyuk(say("hazir") + say("kargoda"), tl(ciro), "text-tertiary font-semibold") + `<div class="flex items-center justify-between mt-2 font-label-sm text-label-sm"><span class="text-outline">Başarılı Teslimat:</span><span class="text-tertiary font-semibold">%${teslimOran.toLocaleString("tr-TR")} Oran</span></div>
         <div class="flex items-center justify-between mt-1 font-label-sm text-label-sm"><span class="text-outline">Tahmini kâr:</span><span class="text-tertiary font-semibold">${tl(kar)}</span></div>`);

    $("#sipDurumCip").innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-tertiary-container"></span>
      <span class="font-label-sm text-label-sm text-on-surface-variant font-semibold">${yazicilar.size} Yazıcı Aktif</span><span class="text-outline text-label-sm">|</span>
      <span class="font-label-sm text-label-sm text-primary font-semibold">${acik.length} açık sipariş</span>
      ${gecikmis ? `<span class="text-outline text-label-sm">|</span><span class="font-label-sm text-label-sm text-error font-semibold">${gecikmis} Termin Geçti</span>` : ""}`;

    // Bilinen yazıcılar (forma ve çekmeceye öneri listesi)
    $("#sipYazicilar").innerHTML = [...new Set(sipVeri.map((s) => s.yazici).filter(Boolean))].map((y) => `<option value="${esc(y)}"></option>`).join("");
    sipEntegrasyonCiz();
  }

  // 4. Entegrasyon kartları: gerçek bağlantılar kurulmadığı için durumlarını dürüstçe gösterir.
  function sipEntegrasyonCiz() {
    const takipli = sipVeri.filter((s) => s.takip_no).length, kargoda = sipVeri.filter((s) => s.durum === "kargoda").length;
    const firmalar = [...new Set(sipVeri.map((s) => s.kargo_firmasi).filter(Boolean))].slice(0, 2).join(", ");
    const son = sipVeri[0];
    const kanallar = {};
    for (const s of sipVeri) kanallar[s.kanal] = (kanallar[s.kanal] || 0) + 1;
    const enCok = Object.entries(kanallar).sort((a, b) => b[1] - a[1])[0];
    const yazicilar = new Set(sipVeri.filter((s) => s.durum === "basiliyor" && s.yazici).map((s) => s.yazici));
    const kart = (ikon, ikonSinif, baslik, alt, sag) => `<div class="p-3 rounded-xl bg-white shadow-sm flex items-center justify-between gap-3">
        <div class="flex items-center gap-3 min-w-0"><div class="w-10 h-10 rounded-lg ${ikonSinif} flex items-center justify-center shrink-0">${sipIkon(ikon, "text-[20px]")}</div>
        <div class="min-w-0"><div class="font-label-md text-label-md font-semibold text-on-surface">${baslik}</div><div class="font-label-sm text-label-sm text-outline mt-0.5">${alt}</div></div></div>${sag}</div>`;
    const rozet = (metin) => `<span class="px-2 py-0.5 rounded bg-surface-container text-outline font-label-sm text-label-sm font-semibold shrink-0">${metin}</span>`;
    $("#sipEntegrasyon").innerHTML =
      kart("local_shipping", "bg-tertiary-fixed/20 text-tertiary", "Kargo Takibi",
        `<span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-outline-variant"></span>${takipli} siparişte takip no • ${kargoda} kargoda${firmalar ? ` • ${esc(firmalar)}` : ""}</span>`, rozet("API yok, elle")) +
      kart("sync", "bg-secondary-fixed text-on-secondary-fixed", "Pazaryeri Siparişleri",
        son ? `Son sipariş: ${esc(sipZaman(son.created_at))}${enCok ? ` • en çok ${esc(SIP_KANAL[enCok[0]] || enCok[0])}` : ""}` : "Henüz sipariş yok", rozet("Webhook bağlı değil")) +
      (() => {
        const bagli = sipYazicilar.filter(yaziciBagli);
        if (bagli.length) {
          const y = bagli[0], d = y.durum || {};
          const ayrinti = [YAZICI_DURUM[d.durum] || "Rapor bekleniyor", d.yuzde != null && ["RUNNING", "PAUSE"].includes(d.durum) ? `%${d.yuzde}` : "",
            d.nozul != null ? `${d.nozul}°C / ${d.tabla ?? "-"}°C` : ""].filter(Boolean).join(" • ");
          return kart("router", "bg-primary-fixed text-on-primary-fixed-variant", esc(bagli.length > 1 ? `${bagli.length} Yazıcı Bağlı` : y.ad),
            `<span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse"></span>${esc(ayrinti)} • ${esc(saniyeOnce(y.goruldu))}</span>`,
            `<span class="px-2 py-0.5 rounded bg-tertiary-fixed/30 text-tertiary font-label-sm text-label-sm font-semibold shrink-0">Köprü bağlı</span>`);
        }
        const son = sipYazicilar[0];
        return kart("router", "bg-primary-fixed text-on-primary-fixed-variant", "Bambu Yazıcılar",
          son ? `Köprü kapalı • son sinyal ${esc(saniyeOnce(son.goruldu))}` : `${yazicilar.size} yazıcıda baskı var (panelden atanan)`,
          rozet(son ? "Köprü kapalı" : "Köprü kurulmadı"));
      })();
  }

  function sipHizliCiz() {
    const g = sipGecerli();
    const say = (k) => k === "tum" ? g.length : g.filter((s) => SIP_HIZLI_DURUM[k].includes(s.durum)).length;
    $("#sipHizli").innerHTML = Object.entries(SIP_HIZLI).map(([k, ad]) =>
      `<button type="button" data-h="${k}" class="px-3 py-1 rounded-md font-label-sm text-label-sm whitespace-nowrap transition-colors ${sipSekme === k ? "bg-surface-container-high text-primary font-semibold" : "text-on-surface-variant hover:bg-surface-container-low"}">${ad} (${say(k)})</button>`).join("");
  }

  function sipFiltreli() {
    const durum = $("#sipFiltreDurum").value, kanal = $("#sipFiltreKanal").value, tarih = $("#sipFiltreTarih").value;
    const ara = $("#sipAra").value.trim().replace(/^#?(sip-)?/i, "").toLocaleLowerCase("tr-TR");
    const odenmemis = $("#sipOdenmemis").checked, acil = $("#sipSadeceAcil").checked;
    const sinir = tarih === "bugun" ? new Date(new Date().setHours(0, 0, 0, 0)) : tarih ? new Date(Date.now() - Number(tarih) * 864e5) : null;
    const sekme = SIP_HIZLI_DURUM[sipSekme];
    return sipVeri.filter((s) => (!sekme || sekme.includes(s.durum)) && (!durum || s.durum === durum)
      && (!kanal || s.kanal === kanal) && (!odenmemis || !s.odendi) && (!acil || s.acil)
      && (!sinir || new Date(s.created_at) >= sinir)
      && (!ara || [s.id, s.urun_adi, s.renk, s.musteri_notu, s.musteri_adi, s.takip_no, s.yazici, s.fatura_no].filter(Boolean).join(" ").toLocaleLowerCase("tr-TR").includes(ara)));
  }

  function sipGorsel(s, sinif) {
    return s.products?.image_url
      ? `<img src="${url(s.products.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="w-full h-full object-cover">`
      : sipIkon("view_in_ar", `text-outline ${sinif}`);
  }

  function sipYaziciHucre(s) {
    const yuzde = sipIlerleme(s), kalan = sipKalanDk(s);
    if (s.durum === "iptal") return `<span class="font-label-sm text-label-sm text-outline">İptal edildi</span>`;
    if (["hazir", "teslim"].includes(s.durum)) return `<span class="font-label-sm text-label-sm text-tertiary font-semibold flex items-center gap-1">${sipIkon("check_circle", "text-[16px]")} Tamamlandı</span><span class="font-label-sm text-label-sm text-outline mt-0.5 block">${s.durum === "hazir" ? "Paketlemede" : "Teslim edildi"}${s.yazici ? ` • ${esc(s.yazici)}` : ""}</span>`;
    if (s.durum === "kargoda") return `<span class="font-label-sm text-label-sm text-outline">${esc(s.kargo_firmasi || "Kargoda")}</span><span class="font-label-sm text-label-sm text-primary font-semibold block mt-0.5">${s.takip_no ? `Takip: #${esc(s.takip_no)}` : "Takip no yok"}</span>`;
    const canli = sipCanli(s);
    const yaziciAd = s.yazici || (canli ? sipYaziciSatiri(s).ad : "");
    if (!yaziciAd) return `<span class="font-label-sm text-label-sm text-outline italic">Atanmamış (boşta yazıcı aranıyor)</span>
      <button type="button" data-islem="ata" class="mt-1 flex items-center gap-1 px-2 py-0.5 rounded bg-primary-fixed text-primary font-label-sm text-label-sm font-semibold hover:bg-primary hover:text-on-primary transition-colors">${sipIkon("send_to_mobile", "text-[14px]")} Yazıcıya Ata</button>`;
    if (s.durum === "yeni") return `<div class="font-label-sm text-label-sm font-semibold text-on-surface">${esc(s.yazici)}</div><span class="font-label-sm text-label-sm text-outline mt-0.5 block">Sırada, başlamadı</span>`;
    return `<div class="flex items-center justify-between gap-2 text-label-sm mb-1 w-36"><span class="font-semibold text-on-surface truncate">${esc(yaziciAd)}</span><span class="text-secondary font-bold">${yuzde != null ? `%${yuzde}` : "—"}</span></div>
      <div class="w-36 bg-surface-container-high h-1.5 rounded-full overflow-hidden"><div class="${canli?.durum === "PAUSE" ? "bg-error" : "bg-secondary-container"} h-full rounded-full" style="width:${yuzde || 0}%"></div></div>
      <span class="font-label-sm text-label-sm text-outline mt-1 block">${kalan != null ? `Kalan Süre: ${esc(sure(kalan))}` : "Süre tahmini yok"}</span>
      ${canli ? `<span class="font-label-sm text-label-sm ${canli.durum === "PAUSE" ? "text-error" : "text-tertiary"} flex items-center gap-1 mt-0.5"><span class="w-1.5 h-1.5 rounded-full ${canli.durum === "PAUSE" ? "bg-error" : "bg-tertiary animate-pulse"}"></span>${canli.durum === "PAUSE" ? "Duraklatıldı" : "Canlı"}${canli.katman != null && canli.toplam_katman ? ` • Katman ${canli.katman}/${canli.toplam_katman}` : ""}</span>` : ""}`;
  }

  function sipSatirHtml(s, i) {
    const gram = s.products?.weight_g ? `${s.products.weight_g * s.adet} g` : "";
    const ad = s.products?.url
      ? `<a href="${url(s.products.url)}" target="_blank" rel="noopener" class="font-label-md text-label-md font-medium text-on-surface hover:text-primary no-underline truncate block">${esc(s.urun_adi)} x${s.adet}</a>`
      : `<div class="font-label-md text-label-md font-medium text-on-surface truncate">${esc(s.urun_adi)} x${s.adet}</div>`;
    const terminGecti = s.termin && sipAcikMi(s) && new Date(s.termin) < new Date();
    const vurgulu = s.acil && sipAcikMi(s);
    const zemin = vurgulu ? "bg-primary/5 shadow-sm" : i % 2 ? "bg-surface-container-low/20" : "bg-white";
    const medyaSay = sipMedya(s).length;
    const sehirAd = sehir(s.teslimat_adresi);
    return `<tr data-sip="${s.id}" class="${zemin} border-l-4 ${vurgulu ? "border-primary" : SIP_SOL[s.durum] || "border-transparent"} hover:bg-surface-container-low/60 transition-colors ${s.durum === "iptal" ? "opacity-50" : ""}">
      <td class="p-3 align-top" style="border-bottom:0"><input type="checkbox" data-sec="${s.id}" ${sipSecili.has(s.id) ? "checked" : ""} class="w-4 h-4 rounded accent-primary cursor-pointer" aria-label="Siparişi seç"></td>
      <td class="p-3 align-top" style="border-bottom:0">
        <div class="flex items-center gap-1.5"><span class="font-label-md text-label-md font-bold text-primary">#SIP-${s.id}</span>${vurgulu ? `<span class="material-symbols-outlined text-[14px] text-error" title="Öncelikli Sipariş">priority_high</span>` : ""}</div>
        <span class="font-label-sm text-label-sm text-outline">${esc(sipZaman(s.created_at))}</span>
        ${s.termin && sipAcikMi(s) ? `<span class="font-label-sm text-label-sm ${terminGecti ? "text-error" : "text-outline"} flex items-center gap-0.5 mt-0.5">${sipIkon("alarm", "text-[13px]")}${esc(sipZaman(s.termin))}</span>` : ""}</td>
      <td class="p-3 align-top" style="border-bottom:0">
        <div class="font-label-md text-label-md font-semibold text-on-surface">${esc(s.musteri_adi || "Müşteri adı yok")}</div>
        <div class="flex items-center gap-1.5 mt-0.5 flex-wrap"><span class="px-2 py-0.5 rounded bg-surface-container-high text-on-secondary-fixed-variant font-label-sm text-label-sm">${esc(SIP_KANAL[s.kanal] || s.kanal)}</span>${sehirAd ? `<span class="text-outline text-label-sm">• ${esc(sehirAd)}</span>` : s.musteri_tc ? `<span class="text-outline text-label-sm">• TC: ${esc(s.musteri_tc.slice(0, 3))}***</span>` : ""}</div>
        ${s.musteri_notu ? `<div class="font-label-sm text-label-sm text-outline mt-1 max-w-[200px] truncate" title="${esc(s.musteri_notu)}">${esc(s.musteri_notu)}</div>` : ""}</td>
      <td class="p-3 align-top" style="border-bottom:0">
        <div class="flex items-center gap-3"><div class="w-10 h-10 rounded-lg bg-surface-container-high flex items-center justify-center shrink-0 overflow-hidden">${sipGorsel(s, "text-[22px]")}</div>
        <div class="min-w-0 max-w-[220px]">${ad}<div class="flex items-center gap-1.5 mt-0.5 flex-wrap">${s.renk ? `<span class="px-1.5 rounded bg-surface-container-high text-primary font-label-sm text-label-sm">${esc(s.renk)}</span>` : ""}${gram ? `<span class="font-label-sm text-label-sm text-outline">${gram}</span>` : ""}</div></div></div></td>
      <td class="p-3 align-top" style="border-bottom:0">${sipYaziciHucre(s)}</td>
      <td class="p-3 align-top" style="border-bottom:0">
        <div class="font-label-md text-label-md font-bold text-on-surface">${s.fiyat_tl != null ? tl(s.fiyat_tl) : "-"}</div>
        <button type="button" data-islem="odendi" title="Ödeme durumunu değiştir" class="mt-0.5 px-1.5 py-0.5 rounded bg-surface-container-high font-label-sm text-label-sm ${s.odendi ? "text-tertiary" : "text-error"}">${s.odendi ? "Ödendi" : "Ödenmedi"}${s.odeme_yontemi ? ` (${esc(SIP_ODEME[s.odeme_yontemi] || s.odeme_yontemi)})` : ""}</button></td>
      <td class="p-3 align-top" style="border-bottom:0">
        ${vurgulu ? `<span class="inline-flex items-center gap-1 mb-1 px-2 py-0.5 rounded-full bg-error-container text-on-error-container font-label-sm text-label-sm font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-error animate-ping"></span>Acil</span><br>` : ""}
        <select data-alan="durum" class="rounded-full px-2.5 py-1 font-label-sm text-label-sm font-semibold border-0 cursor-pointer outline-none ${SIP_PILL[s.durum] || ""}" aria-label="Durum">${secenekler(SIP_DURUM, s.durum)}</select></td>
      <td class="p-3 align-top text-right whitespace-nowrap" style="border-bottom:0">
        <button type="button" data-islem="detay" title="Detay" class="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high transition-colors">${sipIkon("receipt_long")}</button><button type="button" data-islem="video" title="Video & timelapse" class="relative p-1.5 rounded-lg text-primary hover:bg-surface-container-high transition-colors">${sipIkon("videocam")}${medyaSay ? `<span class="absolute top-0 right-0 min-w-[14px] h-3.5 px-0.5 rounded-full bg-primary text-on-primary text-[9px] leading-none font-bold flex items-center justify-center ring-2 ring-white">${medyaSay}</span>` : ""}</button><button type="button" data-islem="irsaliye" title="İrsaliye / paketleme fişi yazdır" class="p-1.5 rounded-lg text-outline hover:text-on-surface transition-colors">${sipIkon("print")}</button></td>
    </tr>`;
  }

  function sipSayfalamaCiz(toplam, bas, adet, sayfaSay) {
    $("#sipSayfaBilgi").textContent = toplam ? `Toplam ${toplam} kayıttan ${bas + 1} - ${bas + adet} arası listeleniyor` : "Kayıt yok";
    const dugme = (etiket, sayfa, aktif, kapali) => `<button type="button" data-sayfa="${sayfa}" ${kapali ? "disabled" : ""} class="w-8 h-8 rounded-lg flex items-center justify-center font-label-sm text-label-sm transition-colors disabled:opacity-40 ${aktif ? "bg-primary text-on-primary font-bold shadow-sm" : "bg-white text-on-surface-variant hover:bg-surface-container-high"}">${etiket}</button>`;
    const sayfalar = [];
    for (let i = 1; i <= sayfaSay; i++) {
      if (i === 1 || i === sayfaSay || Math.abs(i - sipSayfa) <= 1) sayfalar.push(i);
      else if (sayfalar[sayfalar.length - 1] !== "…") sayfalar.push("…");
    }
    $("#sipSayfaNav").innerHTML = toplam ? dugme(sipIkon("chevron_left"), sipSayfa - 1, false, sipSayfa <= 1)
      + sayfalar.map((p) => p === "…" ? `<span class="px-1 text-outline font-label-sm text-label-sm">…</span>` : dugme(p, p, p === sipSayfa, false)).join("")
      + dugme(sipIkon("chevron_right"), sipSayfa + 1, false, sipSayfa >= sayfaSay) : "";
  }

  function sipCiz() {
    sipHizliCiz();
    const tablo = $("#siparisTablo");
    const bos = (metin) => { tablo.innerHTML = `<tr><td class="p-8 text-center text-outline font-body-sm text-body-sm" style="border-bottom:0">${metin}</td></tr>`; sipSayfalamaCiz(0, 0, 0, 1); };
    // Silinmiş siparişleri seçimden çıkar
    for (const id of [...sipSecili]) if (!sipBul(id)) sipSecili.delete(id);
    sipTopluCiz();
    if (!sipVeri.length) return bos(`Henüz sipariş yok. "+ Yeni Sipariş Oluştur" ile ekle.`);
    const liste = sipFiltreli();
    if (!liste.length) return bos("Filtreye uyan sipariş yok.");
    const boy = Number($("#sipSayfaBoy").value) || 25;
    const sayfaSay = Math.max(1, Math.ceil(liste.length / boy));
    sipSayfa = Math.min(Math.max(1, sipSayfa), sayfaSay);
    const bas = (sipSayfa - 1) * boy, parca = liste.slice(bas, bas + boy);
    const hepsi = parca.length && parca.every((s) => sipSecili.has(s.id));
    const th = (metin, ek = "") => `<th class="p-3 font-label-sm text-label-sm ${ek}" style="border-bottom:0">${metin}</th>`;
    tablo.innerHTML = `<thead><tr class="bg-surface-container-low text-outline font-label-sm text-label-sm uppercase tracking-wider">
        <th class="p-3 w-10" style="border-bottom:0"><input type="checkbox" id="sipHepsi" ${hepsi ? "checked" : ""} class="w-4 h-4 rounded accent-primary cursor-pointer" aria-label="Bu sayfadakilerin hepsini seç"></th>
        ${th("Sipariş No & Tarih")}${th("Müşteri & Kanal")}${th("3D Model & Filament")}${th("Yazıcı & İlerleme")}${th("Tutar & Ödeme")}${th("Durum")}${th("İşlemler", "text-right")}</tr></thead>
      <tbody class="text-on-surface font-body-sm text-body-sm">${parca.map(sipSatirHtml).join("")}</tbody>`;
    sipSayfalamaCiz(liste.length, bas, parca.length, sayfaSay);
  }

  // Toplu işlem çubuğu ve işlemleri
  function sipTopluCiz() {
    const bar = $("#sipTopluBar");
    bar.hidden = !(sipTopluAcik || sipSecili.size);
    $("#sipTopluSay").textContent = sipSecili.size ? `${sipSecili.size} sipariş seçili` : "Tablodan sipariş seç";
  }
  async function sipToplu(islem) {
    const ids = [...sipSecili];
    if (islem === "temizle") { sipSecili.clear(); sipTopluAcik = false; return sipCiz(); }
    if (!ids.length) return alert("Önce tablodan sipariş seç.");
    if (islem === "csv") return sipCsvIndir(sipVeri.filter((s) => sipSecili.has(s.id)));
    const simdi = new Date().toISOString();
    let sorgu;
    if (islem === "durum") {
      const durum = $("#sipTopluDurum").value;
      if (!durum) return alert("Önce yeni durumu seç.");
      sorgu = sb.from("siparisler").update({ durum, updated_at: simdi }).in("id", ids);
      const { error } = await sorgu;
      if (error) return alert("Güncellenemedi: " + error.message);
      if (durum === "basiliyor") await sb.from("siparisler").update({ baski_baslangic: simdi }).in("id", ids).is("baski_baslangic", null);
    } else if (islem === "sil") {
      if (!confirm(`${ids.length} sipariş silinsin mi? (Bağlı videolar da silinir.)`)) return;
      const silinecek = sipVeri.filter((s) => sipSecili.has(s.id));
      const { error } = await sb.from("siparisler").delete().in("id", ids);
      if (error) return alert("Silinemedi: " + error.message);
      const yollar = silinecek.flatMap(sipMedya).map((m) => m.yol);
      if (yollar.length) await sb.storage.from(SIP_DEPO).remove(yollar);
      sipSecili.clear();
    } else {
      const alanlar = { odendi: { odendi: true }, acil: { acil: true }, acilDegil: { acil: false } }[islem];
      if (!alanlar) return;
      const { error } = await sb.from("siparisler").update({ ...alanlar, updated_at: simdi }).in("id", ids);
      if (error) return alert("Güncellenemedi: " + error.message + sipSqlIpucu(error));
    }
    siparisYukle();
  }

  // Yazdırılabilir irsaliye / paketleme fişi (yeni pencerede, tarayıcının yazdır penceresiyle)
  function sipIrsaliye(s) {
    const w = window.open("", "_blank");
    if (!w) return alert("Açılır pencere engellendi; tarayıcıda bu siteye izin ver.");
    const satir = (a, b) => `<tr><th>${a}</th><td>${b}</td></tr>`;
    w.document.write(`<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>İrsaliye #SIP-${s.id}</title>
      <style>body{font:14px/1.5 system-ui,sans-serif;margin:32px;color:#0d1c2e}h1{font-size:20px;margin:0 0 4px}.alt{color:#444654}
      table{border-collapse:collapse;width:100%;margin-top:16px}th,td{text-align:left;padding:8px;border-bottom:1px solid #dce9ff;vertical-align:top}th{width:180px;color:#444654;font-weight:600}</style></head>
      <body><h1>Sevk İrsaliyesi / Paketleme Fişi</h1><div class="alt">#SIP-${s.id} • ${esc(new Date().toLocaleDateString("tr-TR"))}</div><table>
      ${satir("Alıcı", esc(s.musteri_adi || "-"))}${satir("Telefon", esc(s.musteri_telefon || "-"))}
      ${satir("Teslimat adresi", esc(s.teslimat_adresi || "-"))}${satir("Ürün", `${esc(s.urun_adi)} × ${s.adet}`)}
      ${satir("Renk / filament", esc(s.renk || "-"))}${satir("Tutar", s.fiyat_tl != null ? esc(tl(s.fiyat_tl)) : "-")}
      ${satir("Ödeme", `${s.odendi ? "Ödendi" : "Ödenmedi"}${s.odeme_yontemi ? ` (${esc(SIP_ODEME[s.odeme_yontemi] || s.odeme_yontemi)})` : ""}`)}
      ${satir("Kargo", esc([s.kargo_firmasi, s.takip_no].filter(Boolean).join(" • ") || "-"))}${satir("Fatura no", esc(s.fatura_no || "-"))}
      ${satir("Not", esc(s.musteri_notu || "-"))}</table></body></html>`);
    w.document.close();
    w.focus();
    w.print();
  }

  // Bildirim zili: gerçek sipariş verisinden hesaplanan uyarılar.
  function sipBildirimler() {
    const simdi = Date.now(), liste = [];
    for (const s of sipVeri) {
      if (s.durum === "iptal") continue;
      if (s.durum === "teslim") { if (!s.odendi) liste.push({ s, ikon: "payments", renk: "text-error", metin: "Teslim edildi ama ödeme alınmadı" }); continue; }
      if (s.termin && s.durum !== "kargoda") {
        const kalan = new Date(s.termin).getTime() - simdi;
        if (kalan < 0) liste.push({ s, ikon: "alarm", renk: "text-error", metin: `Termin geçti (${sipZaman(s.termin)})` });
        else if (kalan < 864e5) liste.push({ s, ikon: "alarm", renk: "text-error", metin: `Termin yaklaşıyor (${sipZaman(s.termin)})` });
      }
      if (s.durum === "yeni" && simdi - new Date(s.created_at).getTime() > 2 * 864e5) liste.push({ s, ikon: "hourglass_top", renk: "text-secondary", metin: "2 günden uzun süredir baskı bekliyor" });
      if (s.durum === "basiliyor" && sipIlerleme(s) >= 99) liste.push({ s, ikon: "print", renk: "text-tertiary", metin: "Tahmini baskı süresi doldu, kontrol et" });
    }
    return liste;
  }
  function bildirimCiz() {
    const liste = sipBildirimler();
    $("#bildirimNokta").hidden = !liste.length;
    $("#bildirimDugme").title = liste.length ? `${liste.length} bildirim` : "Bildirim yok";
    $("#bildirimMenu").innerHTML = `<div class="px-4 py-3 border-b border-surface-container-high flex items-center justify-between"><span class="font-label-md text-label-md font-semibold text-on-surface">Bildirimler</span><span class="font-label-sm text-label-sm text-outline">${liste.length}</span></div>
      <div class="max-h-80 overflow-y-auto">${liste.length ? liste.slice(0, 30).map((b) => `<button type="button" data-bildirim-sip="${b.s.id}" class="w-full text-left px-4 py-2.5 flex items-start gap-2.5 hover:bg-surface-container-low transition-colors border-b border-surface-container-low">${sipIkon(b.ikon, `text-[18px] ${b.renk} mt-0.5`)}<span class="min-w-0"><span class="block font-label-md text-label-md text-on-surface">${esc(b.metin)}</span><span class="block font-label-sm text-label-sm text-outline truncate">#SIP-${b.s.id} • ${esc(b.s.urun_adi)}</span></span></button>`).join("") : `<div class="px-4 py-6 text-center font-body-sm text-body-sm text-outline">Her şey yolunda, bildirim yok.</div>`}</div>`;
  }
  $("#bildirimDugme").addEventListener("click", (e) => { e.stopPropagation(); $("#bildirimMenu").hidden = !$("#bildirimMenu").hidden; });
  $("#bildirimMenu").addEventListener("click", (e) => {
    const b = e.target.closest("[data-bildirim-sip]");
    if (!b) return;
    $("#bildirimMenu").hidden = true;
    document.querySelector('[data-sekme="siparis"]').click();
    sipCekmeAc(Number(b.dataset.bildirimSip));
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#bildirimKap")) $("#bildirimMenu").hidden = true; });

  // Sipariş detay çekmecesi (mockup'taki sağdan açılan panel).
  function sipCekmeAc(id) {
    sipCekmeId = id;
    sipCekmeCiz();
    $("#sipCekmece").hidden = false;
    $("#sipCekmeIcerik").scrollTop = 0;
    document.body.style.overflow = "hidden";
  }
  function sipCekmeKapat() {
    sipCekmeId = null;
    $("#sipCekmece").hidden = true;
    if (medyaSipId == null) document.body.style.overflow = "";
  }
  function sipCekmeCiz() {
    const s = sipBul(sipCekmeId);
    if (!s) return sipCekmeKapat();
    const p = s.products || {};
    const kanal = esc(SIP_KANAL[s.kanal] || s.kanal);
    const durumAd = esc(SIP_DURUM[s.durum] || s.durum);
    const adim = Math.max(0, SIP_AKIS.indexOf(s.durum));
    const baskiYuzde = sipIlerleme(s);
    const genelYuzde = s.durum === "iptal" ? 0 : s.durum === "basiliyor" && baskiYuzde != null ? baskiYuzde : Math.round((adim / (SIP_AKIS.length - 1)) * 100);
    const toplamDk = sipToplamDk(s), kalan = sipKalanDk(s), canli = sipCanli(s);
    const tahmin = toplamDk ? sure(toplamDk) : "-";
    const tahminGram = p.weight_g ? `${p.weight_g * s.adet} g` : "-";
    const birim = s.fiyat_tl != null && s.adet ? s.fiyat_tl / s.adet : null;
    const terminGecti = s.termin && sipAcikMi(s) && new Date(s.termin) < new Date();
    const sekme = (hedef, ikon, ad, aktif) => `<button type="button" data-git="${hedef}" aria-selected="${aktif}" class="px-3.5 py-2 -mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent text-outline font-medium hover:text-on-surface transition-colors aria-selected:border-primary aria-selected:text-primary aria-selected:font-semibold">${sipIkon(ikon)}${ad}</button>`;
    const girdi = (alan, deger, ek = "") => `<input type="text" data-cekme-alan="${alan}" value="${esc(deger || "")}" class="w-full font-label-md text-label-md text-on-surface" style="padding:4px 8px" ${ek}>`;

    $("#sipCekmeBaslik").innerHTML = `
      <div class="flex items-start justify-between gap-4">
        <div class="flex flex-col gap-2 min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-headline-md text-headline-md font-bold text-on-surface tracking-tight">#SIP-${s.id}</span>
            ${s.acil && sipAcikMi(s) ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-error-container text-on-error-container font-label-sm text-label-sm font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-error animate-ping"></span>Acil Sipariş</span>` : ""}
            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label-sm text-label-sm font-semibold ${SIP_PILL[s.durum] || ""}">${s.durum === "basiliyor" ? `<span class="w-2 h-2 rounded-full bg-tertiary-container animate-pulse"></span>` : ""}${durumAd}${s.durum === "basiliyor" && baskiYuzde != null ? ` (%${baskiYuzde})` : ""}</span>
            <span class="px-2 py-0.5 rounded-full bg-secondary-fixed text-on-secondary-fixed font-label-sm text-label-sm font-semibold">${kanal}</span>
          </div>
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-label-sm text-outline">
            <span class="flex items-center gap-1">${sipIkon("calendar_today", "text-[15px] text-primary")}Sipariş Tarihi: <strong class="text-on-surface font-medium">${esc(new Date(s.created_at).toLocaleString("tr-TR", { dateStyle: "long", timeStyle: "short" }))}</strong></span>
            ${s.termin ? `<span class="flex items-center gap-1">${sipIkon("alarm", "text-[15px] text-error")}Termin: <strong class="${terminGecti ? "text-error" : "text-on-surface"} font-semibold">${esc(new Date(s.termin).toLocaleString("tr-TR", { dateStyle: "long", timeStyle: "short" }))}</strong></span>` : ""}
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button type="button" data-yazdir title="İrsaliye & etiket bas" class="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-container-low text-on-surface hover:bg-surface-container font-label-sm text-label-sm font-semibold transition-colors">${sipIkon("print", "text-[16px]")}<span class="hidden sm:inline">Yazdır / İrsaliye</span></button>
          <button type="button" data-video title="Video & timelapse" class="w-8 h-8 rounded-lg bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface flex items-center justify-center transition-colors">${sipIkon("movie_filter")}</button>
          ${p.url ? `<a href="${url(p.url)}" target="_blank" rel="noopener" title="Modeli aç" class="w-8 h-8 rounded-lg bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface flex items-center justify-center transition-colors no-underline">${sipIkon("open_in_new")}</a>` : ""}
          <button type="button" data-kapat title="Kapat" class="w-8 h-8 rounded-lg bg-surface-container-low text-on-surface-variant hover:bg-error-container hover:text-on-error-container flex items-center justify-center transition-colors ml-1">${sipIkon("close", "text-[20px]")}</button>
        </div>
      </div>
      <div class="sekmeler flex items-center gap-1 mt-4 border-b border-surface-container-high overflow-x-auto text-label-md">
        ${sekme("sipUretimK", "precision_manufacturing", "Üretim & 3D Yazıcı", true)}${sekme("sipMusteriK", "person", "Müşteri & Fatura", false)}${sekme("sipKalemK", "payments", "Sipariş Özeti", false)}${sekme("sipKargoK", "local_shipping", "Kargo & Takip", false)}${sekme("sipZamanK", "history", "Zaman Çizelgesi", false)}
      </div>`;

    const mini = (baslik, deger, alt, renk = "text-on-surface") => `<div class="p-2.5 rounded-lg bg-surface-container-low"><span class="block text-label-sm text-outline">${baslik}</span><span class="font-label-md text-label-md font-semibold ${renk} mt-0.5 block">${deger}</span><span class="text-[11px] text-outline font-medium">${alt}</span></div>`;
    const miniGirdi = (baslik, alan, birim) => `<label class="p-2.5 rounded-lg bg-surface-container-low block"><span class="block text-label-sm text-outline">${baslik}</span><input type="number" min="1" data-cekme-alan="${alan}" value="${s[alan] ?? ""}" placeholder="${birim}" class="w-full mt-0.5 font-label-md text-label-md font-semibold" style="padding:3px 6px"><span class="text-[11px] text-outline font-medium">gerçek, toplam</span></label>`;
    const bilgi = (etiket, icerik) => `<div class="flex justify-between items-center gap-3"><span class="text-outline shrink-0">${etiket}</span><span class="text-on-surface text-right min-w-0 flex-1 flex justify-end">${icerik}</span></div>`;
    const olay = (nokta, baslik, saat, aciklama) => `<div class="relative"><span class="absolute -left-6 top-1 w-2.5 h-2.5 rounded-full ${nokta}"></span>
        <div class="flex items-center justify-between gap-3"><span class="font-label-md text-label-md font-semibold text-on-surface">${baslik}</span><span class="text-label-sm font-mono text-outline">${saat}</span></div>
        ${aciklama ? `<p class="text-label-sm text-outline mt-0.5">${aciklama}</p>` : ""}</div>`;

    $("#sipCekmeIcerik").innerHTML = `
      <div id="sipUretimK" class="p-5 rounded-2xl bg-white border border-surface-container shadow-sm scroll-mt-4">
        <div class="flex items-center justify-between gap-2 pb-3 border-b border-surface-container-high">
          <div class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full ${s.durum === "basiliyor" ? "bg-tertiary animate-pulse" : "bg-outline-variant"}"></span><span class="font-headline-sm text-headline-sm font-bold text-on-surface">${s.durum === "basiliyor" ? "Aktif 3D Baskı Süreci" : "Üretim Süreci"}</span></div>
          <span class="px-2.5 py-1 rounded-md bg-primary/10 text-primary font-label-sm text-label-sm font-semibold tracking-wide uppercase">${esc(s.yazici || (canli ? sipYaziciSatiri(s).ad : "Yazıcı atanmadı"))}${canli ? " • CANLI" : ""}</span>
        </div>
        <div class="flex flex-col sm:flex-row items-center gap-4 mt-4">
          <div class="relative w-24 h-24 rounded-xl bg-surface-container-high overflow-hidden shrink-0 flex items-center justify-center shadow-inner">${sipGorsel(s, "text-[40px]")}<div class="absolute bottom-1 right-1 px-1 py-0.5 rounded bg-on-background/80 text-white font-label-sm text-[10px]">${s.adet} Adet</div></div>
          <div class="flex-1 w-full">
            <div class="flex items-baseline justify-between gap-3"><h4 class="font-headline-sm text-headline-sm font-bold text-on-surface">${esc(s.urun_adi)} x${s.adet}</h4><span class="font-headline-sm text-headline-sm font-bold text-secondary">${s.durum === "iptal" ? "İptal" : `%${genelYuzde}`}</span></div>
            <div class="w-full bg-surface-container-high h-2.5 rounded-full mt-2 overflow-hidden"><div class="bg-secondary-container h-full rounded-full transition-all duration-500" style="width:${genelYuzde}%"></div></div>
            <div class="flex items-center justify-between text-label-sm text-outline mt-1.5"><span>${kalan != null ? `Kalan Süre: <strong class="text-on-surface font-semibold">${esc(sure(kalan))}</strong> (Toplam: ${esc(tahmin)})` : `Durum: <strong class="text-on-surface font-semibold">${durumAd}</strong>`}</span><span>Adım: <strong class="text-on-surface font-semibold">${adim + 1} / ${SIP_AKIS.length}</strong></span></div>
          </div>
        </div>
        ${canli ? `<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 pt-4 border-t border-surface-container-high">
          ${mini("Nozül &amp; Tabla", `${canli.nozul ?? "-"}°C / ${canli.tabla ?? "-"}°C`, `hedef ${canli.nozul_hedef ?? "-"} / ${canli.tabla_hedef ?? "-"}°C`)}
          ${mini("Katman", canli.katman != null ? `${canli.katman} / ${canli.toplam_katman ?? "?"}` : "-", esc(YAZICI_DURUM[canli.durum] || canli.durum || ""), "text-primary")}
          ${mini("AMS Filament", esc((canli.ams || []).slice(0, 2).map((t) => `${t.tur}${t.kalan != null ? ` %${t.kalan}` : ""}`).join(", ") || "-"), `${(canli.ams || []).length} dolu yuva`, "text-tertiary")}
          ${mini("Yazıcıdaki dosya", esc(canli.dosya || "-"), "köprüden canlı")}
        </div>` : ""}
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4 pt-4 border-t border-surface-container-high">
          <label class="p-2.5 rounded-lg bg-surface-container-low block"><span class="block text-label-sm text-outline">Yazıcı</span><input type="text" list="sipYazicilar" maxlength="60" data-cekme-alan="yazici" value="${esc(s.yazici || "")}" placeholder="ör. Bambu P1S #1" class="w-full mt-0.5 font-label-md text-label-md font-semibold" style="padding:3px 6px"><span class="text-[11px] text-outline font-medium">atama</span></label>
          <label class="p-2.5 rounded-lg bg-surface-container-low block"><span class="block text-label-sm text-outline">İlerleme ${s.ilerleme != null ? `<button type="button" data-ilerleme-oto class="text-primary font-semibold">(otomatik yap)</button>` : "(otomatik)"}</span><input type="range" min="0" max="100" step="1" data-cekme-alan="ilerleme" value="${baskiYuzde ?? 0}" class="w-full mt-1.5 accent-primary" aria-label="İlerleme yüzdesi"><span class="text-[11px] text-outline font-medium">${canli ? "yazıcıdan canlı" : s.ilerleme != null ? "elle girildi" : s.baski_baslangic ? "baskı başlangıcından" : "başlangıç yok"}</span></label>
          ${mini("Tahmini süre", esc(tahmin), "MakerWorld profili")}
          ${mini("Filament", esc(tahminGram), esc(s.renk || "renk belirtilmedi"), "text-primary")}
          ${miniGirdi("Gerçek süre (dk)", "gercek_sure_dk", "dk")}
          ${miniGirdi("Gerçek filament (g)", "gercek_gram", "g")}
        </div>
        <div class="flex flex-wrap items-center gap-2 mt-4">
          <button type="button" data-video class="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-primary text-on-primary font-label-md text-label-md font-semibold hover:bg-primary/90 shadow-sm transition-all">${sipIkon("videocam")}Video &amp; Timelapse (${sipMedya(s).length})</button>
          <label class="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-container-high text-on-surface font-label-md text-label-md font-semibold">Durum:
            <select data-cekme-alan="durum" class="bg-transparent border-0 p-0 font-label-md text-label-md font-semibold text-on-surface outline-none cursor-pointer">${secenekler(SIP_DURUM, s.durum)}</select></label>
          <label class="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-container-high text-error font-label-md text-label-md font-semibold cursor-pointer"><input type="checkbox" data-cekme-alan="acil" ${s.acil ? "checked" : ""} class="w-4 h-4 accent-primary"> ⚡ Acil</label>
        </div>
      </div>

      <div id="sipMusteriK" class="grid grid-cols-1 md:grid-cols-2 gap-4 scroll-mt-4">
        <div class="p-4 rounded-xl bg-white border border-surface-container shadow-sm">
          <div class="flex items-center justify-between mb-3"><div class="flex items-center gap-2">${sipIkon("person", "text-primary text-[20px]")}<span class="font-headline-sm text-[16px] font-bold text-on-surface">Müşteri Bilgileri</span></div><span class="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-sm text-label-sm font-medium">${s.musteri_tc ? "Bireysel" : "Belirtilmedi"}</span></div>
          <div class="space-y-2 text-label-md">
            ${bilgi("İsim:", girdi("musteri_adi", s.musteri_adi, 'maxlength="120" autocomplete="off"'))}
            ${bilgi("T.C. Kimlik:", s.musteri_tc ? `<span class="font-mono">${esc(tcMaske(s.musteri_tc))}</span> <button type="button" data-tc-goster class="ml-2 text-primary font-label-sm text-label-sm font-semibold">düzenle</button>` : `<input type="text" maxlength="11" inputmode="numeric" data-cekme-alan="musteri_tc" placeholder="11 hane" class="w-36 font-mono" style="padding:3px 6px">`)}
            ${bilgi("Telefon:", girdi("musteri_telefon", s.musteri_telefon, 'maxlength="30" inputmode="tel" autocomplete="off"'))}
            ${bilgi("E-Posta:", girdi("musteri_eposta", s.musteri_eposta, 'maxlength="200" inputmode="email" autocomplete="off"'))}
          </div>
        </div>
        <div class="p-4 rounded-xl bg-white border border-surface-container shadow-sm">
          <div class="flex items-center justify-between mb-3"><div class="flex items-center gap-2">${sipIkon("local_shipping", "text-secondary text-[20px]")}<span class="font-headline-sm text-[16px] font-bold text-on-surface">Teslimat &amp; Fatura</span></div>${s.fatura_no ? `<span class="px-2 py-0.5 rounded bg-tertiary-fixed/30 text-tertiary font-label-sm text-label-sm font-semibold">e-Arşiv Düzenlendi</span>` : `<span class="px-2 py-0.5 rounded bg-surface-container text-outline font-label-sm text-label-sm font-semibold">Fatura yok</span>`}</div>
          <div class="space-y-2 text-label-md">
            <label class="block"><span class="text-outline block text-label-sm">Teslimat Adresi:</span><textarea data-cekme-alan="teslimat_adresi" rows="2" maxlength="500" class="w-full mt-0.5 font-label-md text-label-md text-on-surface" style="padding:4px 8px">${esc(s.teslimat_adresi || "")}</textarea></label>
            <div class="pt-1 border-t border-surface-container-high">${bilgi("Fatura No:", girdi("fatura_no", s.fatura_no, 'maxlength="50"'))}</div>
            ${bilgi("Ödeme:", `<select data-cekme-alan="odeme_yontemi" class="font-label-md text-label-md" style="padding:3px 6px"><option value="">Belirtilmedi</option>${secenekler(SIP_ODEME, s.odeme_yontemi)}</select>`)}
          </div>
        </div>
      </div>

      <div id="sipKalemK" class="p-5 rounded-2xl bg-white border border-surface-container shadow-sm scroll-mt-4">
        <div class="flex items-center justify-between pb-3 border-b border-surface-container-high">
          <div class="flex items-center gap-2">${sipIkon("receipt", "text-primary text-[20px]")}<span class="font-headline-sm text-headline-sm font-bold text-on-surface">Sipariş Kalemleri ve Tutar</span></div>
          <label class="flex items-center gap-1.5 px-2.5 py-0.5 rounded font-label-sm text-label-sm font-semibold cursor-pointer ${s.odendi ? "bg-tertiary-fixed/20 text-tertiary" : "bg-error-container text-on-error-container"}"><input type="checkbox" data-cekme-alan="odendi" ${s.odendi ? "checked" : ""} class="w-3.5 h-3.5 accent-primary"> ${s.odendi ? "Ödendi" : "Ödenmedi"}${s.odeme_yontemi ? ` (${esc(SIP_ODEME[s.odeme_yontemi] || s.odeme_yontemi)})` : ""}</label>
        </div>
        <div class="py-3 flex items-center justify-between gap-4 border-b border-surface-container-high">
          <div class="flex items-center gap-3"><div class="w-8 h-8 rounded-lg bg-surface-container flex items-center justify-center font-bold text-primary text-label-md shrink-0">${s.adet}x</div>
            <div><span class="font-label-md text-label-md font-semibold text-on-surface block">${esc(s.urun_adi)}</span><span class="text-label-sm text-outline">${[s.renk ? esc(s.renk) : "", birim != null ? `${tl(birim)} / adet` : ""].filter(Boolean).join(" · ") || "-"}</span></div></div>
          <span class="font-label-md text-label-md font-bold text-on-surface shrink-0">${s.fiyat_tl != null ? tl(s.fiyat_tl) : "-"}</span>
        </div>
        <div class="py-2.5 flex items-center justify-between gap-4 text-label-md border-b border-surface-container-high"><div class="flex items-center gap-2 text-on-surface-variant">${sipIkon("storefront", "text-[16px] text-secondary")}<span>Satış kanalı</span></div><span class="font-semibold text-on-surface">${kanal}</span></div>
        ${p.cost_tl != null ? `<div class="py-2.5 flex items-center justify-between gap-4 text-label-md"><div class="flex items-center gap-2 text-outline">${sipIkon("calculate", "text-[16px]")}<span>Tahmini maliyet (${s.adet} adet)</span></div><span class="font-semibold text-on-surface">${tl(p.cost_tl * s.adet)}</span></div>` : ""}
        <div class="pt-3.5 mt-2 border-t-2 border-dashed border-surface-container-high flex items-center justify-between"><span class="font-headline-sm text-headline-sm font-bold text-on-surface">Genel Toplam (KDV Dahil)</span><span class="font-headline-md text-headline-md font-bold text-primary">${s.fiyat_tl != null ? tl(s.fiyat_tl) : "-"}</span></div>
        ${s.musteri_notu ? `<div class="mt-3 p-3 rounded-lg bg-surface-container-low text-label-md text-on-surface">${sipIkon("sticky_note_2", "text-[16px] text-primary align-middle")} ${esc(s.musteri_notu)}</div>` : ""}
      </div>

      <div id="sipKargoK" class="p-5 rounded-2xl bg-white border border-surface-container shadow-sm scroll-mt-4">
        <div class="flex items-center justify-between pb-3 mb-3 border-b border-surface-container-high">
          <div class="flex items-center gap-2">${sipIkon("local_shipping", "text-secondary text-[20px]")}<span class="font-headline-sm text-headline-sm font-bold text-on-surface">Kargo &amp; Takip</span></div>
          <span class="px-2.5 py-0.5 rounded font-label-sm text-label-sm font-semibold ${s.takip_no ? "bg-primary-fixed text-on-primary-fixed-variant" : "bg-surface-container text-outline"}">${s.takip_no ? "Takip no girildi" : "Henüz kargoya verilmedi"}</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-label-md">
          <label class="block"><span class="text-outline block text-label-sm">Kargo firması</span><input type="text" list="sipKargolar" maxlength="50" data-cekme-alan="kargo_firmasi" value="${esc(s.kargo_firmasi || "")}" class="w-full mt-0.5" style="padding:4px 8px"></label>
          <label class="block"><span class="text-outline block text-label-sm">Takip no</span><input type="text" maxlength="60" data-cekme-alan="takip_no" value="${esc(s.takip_no || "")}" class="w-full mt-0.5 font-mono" style="padding:4px 8px"></label>
          <label class="block sm:col-span-2"><span class="text-outline block text-label-sm">Termin (teslim için son tarih)</span><input type="datetime-local" data-cekme-alan="termin" value="${sipYerelZaman(s.termin)}" class="mt-0.5" style="padding:4px 8px"></label>
        </div>
      </div>

      <div id="sipZamanK" class="p-5 rounded-2xl bg-white border border-surface-container shadow-sm scroll-mt-4">
        <div class="flex items-center justify-between mb-4"><div class="flex items-center gap-2">${sipIkon("timeline", "text-primary text-[20px]")}<span class="font-headline-sm text-headline-sm font-bold text-on-surface">Sipariş Zaman Çizelgesi</span></div><span class="font-label-sm text-label-sm text-outline">Kayıt geçmişi</span></div>
        <div class="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-surface-container-high">
          ${olay("bg-tertiary ring-4 ring-tertiary-fixed/30", `Şu an: ${durumAd}`, s.durum === "basiliyor" && baskiYuzde != null ? `%${baskiYuzde}` : "", s.durum === "teslim" ? "Sipariş tamamlandı." : SIP_ILERI[s.durum] ? `Sonraki adım: ${SIP_ILERI[s.durum]}` : "")}
          ${s.updated_at && s.updated_at !== s.created_at ? olay("bg-primary", "Son güncelleme", esc(sipZaman(s.updated_at)), "") : ""}
          ${s.baski_baslangic ? olay("bg-primary", `Baskı başladı${s.yazici ? ` (${esc(s.yazici)})` : ""}`, esc(sipZaman(s.baski_baslangic)), toplamDk ? `Tahmini toplam süre ${esc(tahmin)}.` : "") : ""}
          ${olay("bg-outline-variant", `Sipariş alındı (${kanal})`, esc(sipZaman(s.created_at)), "Panelden kaydedildi.")}
        </div>
      </div>`;

    $("#sipCekmeIleri").hidden = !SIP_ILERI[s.durum];
    $("#sipCekmeIleriYazi").textContent = SIP_ILERI[s.durum] || "";
    $("#sipCekmeIptal").hidden = !sipAcikMi(s);
    $("#sipCekmeTakip").hidden = !s.takip_no;
  }

  // ------------------------------------------------------------ sipariş videoları (timelapse penceresi)
  const SIP_DEPO = "siparis", SIP_MEDYA_EN_BUYUK = 50 * 1024 * 1024;
  const SIP_MEDYA_TUR = { timelapse: "Timelapse", klip: "Klip", hata: "Hata klibi" };
  let medyaSipId = null, medyaSekme = "bu", medyaSecili = null, medyaBagli = false;
  const medyaUrl = new Map();   // yol → geçici imzalı bağlantı (1 saat)
  const sipMedya = (s) => Array.isArray(s?.medya) ? s.medya : [];
  const mb = (b) => `${((b || 0) / 1048576).toFixed(1)} MB`;
  const sureYaz = (sn) => isFinite(sn) ? `${String(Math.floor(sn / 60)).padStart(2, "0")}:${String(Math.floor(sn % 60)).padStart(2, "0")}` : "00:00";
  const medyaYaz = (m, hata) => { $("#medyaMesaj").textContent = m; $("#medyaMesaj").style.color = hata ? "var(--bad)" : "var(--ok)"; };

  function medyaTumu() { return sipVeri.flatMap((x) => sipMedya(x).map((m) => ({ ...m, sipId: x.id }))); }
  function medyaListe() {
    if (medyaSekme === "tum") return medyaTumu();
    if (medyaSekme === "hata") return medyaTumu().filter((m) => m.tur === "hata");
    return sipMedya(sipBul(medyaSipId)).map((m) => ({ ...m, sipId: medyaSipId }));
  }
  function medyaSeciliOge() { return medyaTumu().find((m) => m.yol === medyaSecili) || null; }
  async function medyaUrlleri(liste) {
    const eksik = [...new Set(liste.map((m) => m.yol))].filter((y) => !medyaUrl.has(y));
    if (!eksik.length) return;
    const { data, error } = await sb.storage.from(SIP_DEPO).createSignedUrls(eksik, 3600);
    if (error) return medyaYaz("Videolara erişilemedi: " + error.message + sipSqlIpucu(error), true);
    for (const r of data || []) if (r.signedUrl) medyaUrl.set(r.path, r.signedUrl);
  }

  async function medyaAc(id) {
    medyaBagla();
    medyaSipId = id; medyaSekme = "bu"; medyaUrl.clear();
    medyaSecili = sipMedya(sipBul(id))[0]?.yol || null;
    const s = sipBul(id);
    $("#medyaAciklama").value = s ? `${s.urun_adi} baskıda 🖨️\nSipariş için DM at!` : "";
    $("#medyaZaman").value = sipYerelZaman(new Date(Date.now() + 36e5).toISOString());
    medyaYaz("");
    $("#medyaPencere").hidden = false;
    document.body.style.overflow = "hidden";
    await yaziciGetir().catch(() => {});
    await medyaCiz();
  }
  function medyaKapat() {
    const v = $("#medyaOynatici");
    v.pause(); v.removeAttribute("src"); v.dataset.yol = ""; v.load();
    medyaSipId = null;
    $("#medyaPencere").hidden = true;
    if (sipCekmeId == null) document.body.style.overflow = "";
  }

  async function medyaCiz() {
    const s = sipBul(medyaSipId);
    if (!s) return medyaKapat();
    const bu = sipMedya(s), tum = medyaTumu(), hata = tum.filter((m) => m.tur === "hata");
    const toplam = (l) => l.reduce((t, m) => t + (m.boyut || 0), 0);
    const liste = medyaListe();
    await medyaUrlleri([...liste.slice(0, 60), ...(medyaSecili ? [{ yol: medyaSecili }] : [])]);
    if (!medyaSecili && liste[0]) medyaSecili = liste[0].yol;
    const secili = medyaSeciliOge();

    $("#medyaBaslik").textContent = `${s.yazici || "Yazıcı"} – Video & Timelapse Yöneticisi`;
    $("#medyaAltBilgi").innerHTML = `<span>Bu siparişin kayıtları: <strong class="text-on-surface font-semibold">${bu.length} dosya (${mb(toplam(bu))})</strong></span><span>•</span><span class="text-tertiary font-medium">Aktif İş: ${esc(s.urun_adi)} x${s.adet} (#SIP-${s.id})</span>`;
    const sekme = (k, ad, n, nokta = "") => `<button type="button" data-medya-sekme="${k}" class="px-3 py-1.5 rounded-lg font-label-sm text-label-sm shrink-0 flex items-center gap-1 transition-colors ${medyaSekme === k ? "bg-primary text-on-primary font-semibold shadow-sm" : "text-on-surface-variant hover:bg-surface-container"}">${nokta}${ad} (${n})</button>`;
    $("#medyaSekmeler").innerHTML = sekme("bu", "Bu Siparişe Ait Kayıtlar", bu.length) + sekme("tum", "Tüm Yazıcı Arşivi", tum.length) + sekme("hata", "Hata Klipleri", hata.length, `<span class="w-1.5 h-1.5 rounded-full bg-error"></span>`)
      + sekme("sd", "Yazıcı SD Kartı", medyaSd.dosyalar ? medyaSd.dosyalar.length : "?", sipIkon("sd_card", "text-[14px]"));
    $("#medyaKlasor").textContent = medyaSekme === "sd" ? "yazıcı: /timelapse/" : medyaSekme === "bu" ? `siparis/${s.id}/` : "siparis/";
    const kart = (m) => {
      const aktif = m.yol === medyaSecili, u = medyaUrl.get(m.yol);
      return `<div data-medya="${esc(m.yol)}" class="p-2.5 rounded-xl ${aktif ? "bg-surface-container-low/50 border-2 border-primary/40" : "bg-white border border-surface-container"} flex flex-col justify-between hover:shadow-md transition-shadow relative overflow-hidden group cursor-pointer">
        <div class="relative w-full aspect-video rounded-lg overflow-hidden bg-black mb-2">${u ? `<video src="${url(u)}#t=1" preload="metadata" muted playsinline class="w-full h-full object-cover pointer-events-none group-hover:scale-105 transition-transform"></video>` : ""}
          <span class="absolute top-1 left-1 px-1.5 py-0.5 rounded ${aktif ? "bg-primary text-on-primary" : m.tur === "hata" ? "bg-error text-on-error" : "bg-tertiary text-on-tertiary"} font-label-sm text-[10px] font-bold">${aktif ? "Oynatılıyor" : esc(SIP_MEDYA_TUR[m.tur] || "Video")}</span></div>
        <div><div class="flex items-center justify-between gap-2"><span class="font-label-md text-label-md font-bold text-on-surface truncate">${esc(m.ad)}</span><span class="text-[11px] font-mono text-outline shrink-0">${mb(m.boyut)}</span></div>
          <span class="inline-block mt-1 px-1.5 rounded bg-surface-container-high text-primary font-label-sm text-[11px]">${m.sipId !== medyaSipId ? `#SIP-${m.sipId}` : esc(SIP_MEDYA_TUR[m.tur] || "Video")}</span>
          <div class="flex items-center justify-between mt-2 pt-2 border-t border-surface-container-high text-[11px] text-outline"><span>${esc(sipZaman(m.tarih))}</span>
            <div class="flex items-center gap-1"><button type="button" data-medya-indir="${esc(m.yol)}" title="İndir" class="p-1 rounded text-primary hover:bg-surface-container-high">${sipIkon("download", "text-[16px]")}</button><button type="button" data-medya-sil="${esc(m.yol)}" data-medya-sip="${m.sipId}" title="Sil" class="p-1 rounded text-outline hover:text-error">${sipIkon("delete", "text-[16px]")}</button></div></div></div></div>`;
    };
    if (medyaSekme === "sd") medyaSdCiz();
    else $("#medyaKutuphane").innerHTML = liste.length ? liste.map(kart).join("")
      : `<div class="col-span-full p-6 text-center font-body-sm text-body-sm text-outline">${medyaSekme === "bu" ? 'Bu siparişe ait video yok. Sağ üstteki "Video yükle" ile ekle ya da yazıcının SD kartından aktar.' : "Kayıt yok."}</div>`;

    const v = $("#medyaOynatici");
    const u = secili && medyaUrl.get(secili.yol);
    if (u) {
      if (v.dataset.yol !== secili.yol) { v.crossOrigin = "anonymous"; v.src = u; v.dataset.yol = secili.yol; $("#medyaCozunurluk").textContent = "—"; }
      $("#medyaBos").hidden = true;
    } else { v.pause(); v.removeAttribute("src"); v.dataset.yol = ""; v.load(); $("#medyaBos").hidden = false; }
    $("#mBuyukOynat").hidden = !u;
    $("#medyaEtiket").textContent = secili ? `${SIP_MEDYA_TUR[secili.tur] || "Video"} • ${secili.ad} • ${mb(secili.boyut)}` : "Video seçilmedi";
    const baskasi = secili && secili.sipId !== s.id && !bu.some((m) => m.yol === secili.yol);
    $("#medyaSipariseEkle").disabled = !baskasi;
    $("#medyaSipariseEkle").classList.toggle("opacity-50", !baskasi);
    $("#medyaSipariseEkleYazi").textContent = baskasi ? `Siparişe Ekle (#SIP-${s.id})` : `Bu siparişte (#SIP-${s.id})`;
    $("#medyaToplam").textContent = `${bu.length} Dosya (${mb(toplam(bu))})`;
    $("#medyaToplamBoyut").textContent = mb(toplam(bu));
    const y = medyaYazici();
    $("#medyaDepo").innerHTML = `Supabase "siparis" alanı: <strong class="text-on-surface font-medium">${tum.length} dosya, ${mb(toplam(tum))}</strong> • Yazıcı köprüsü: `
      + (yaziciBagli(y) ? `<strong class="text-tertiary font-semibold">bağlı (${esc(y.ad)}, ${esc(saniyeOnce(y.goruldu))})</strong>` : `<strong class="text-outline font-semibold">bağlı değil</strong>`);
    medyaYaziciCiz();
    medyaKontrolCiz();
  }

  // ---- yazıcı köprüsü: canlı kamera klibi ve SD karttaki timelapse'ler
  let medyaKlipSn = 30;
  const medyaSd = { durum: "", dosyalar: null };   // durum: "" | "yukleniyor" | hata metni
  function medyaYazici() { const s = sipBul(medyaSipId); return (s && sipYaziciSatiri(s)) || sipYazicilar[0] || null; }

  function medyaYaziciCiz() {
    // Köprü kameraya yalnızca istek anında bağlanır (canlı görüntü yavaşlamasın); d.kamera=false son denemede hata demek.
    const y = medyaYazici(), bagli = yaziciBagli(y), d = y?.durum || {}, kamera = bagli && d.kamera !== false;
    const rozetSinif = "px-2 py-0.5 rounded font-mono text-[11px] font-bold whitespace-nowrap shrink-0";
    const rozet = !bagli ? `<span class="${rozetSinif} bg-surface-container-high text-outline">BAĞLI DEĞİL</span>`
      : kamera ? `<span class="${rozetSinif} bg-tertiary-fixed/30 text-tertiary">İSTEKTE KAYIT</span>` : `<span class="${rozetSinif} bg-error-container text-on-error-container">KAMERA HATASI</span>`;
    const durumSatiri = d.durum ? `<br><strong class="text-on-surface">${esc(YAZICI_DURUM[d.durum] || d.durum)}${d.yuzde != null && ["RUNNING", "PAUSE"].includes(d.durum) ? ` • %${esc(d.yuzde)}` : ""}${d.katman != null && d.toplam_katman ? ` • Katman ${esc(d.katman)}/${esc(d.toplam_katman)}` : ""}</strong>` : "";
    const aciklama = bagli
      ? `Butona basınca kamera ${medyaKlipSn} saniye kaydedilir ve klip bu siparişe eklenir. Kamera yalnızca kayıt sırasında bağlanır; Bambu Handy/Studio canlı görüntüsü yavaşlamaz.${d.kamera === false && d.kamera_hatasi ? `<br><span class="text-error">Son deneme: ${esc(d.kamera_hatasi)}</span>` : ""}${durumSatiri}`
      : y ? `Köprü kapalı (son sinyal ${esc(saniyeOnce(y.goruldu))}). Evdeki bilgisayarda <code>python -m urun_bulucu.kopru</code> çalışıyor olmalı.`
        : `Yazıcı köprüsü kurulmadı. Evdeki bilgisayarda <code>python -m urun_bulucu.kopru</code> çalışınca bu bölüm canlanır (README: "Yazıcı köprüsü"). Şimdilik timelapse'i Bambu Studio / Handy'den indirip "Video yükle" ile ekle.`;
    const sn = (n) => `<button type="button" data-klip-sn="${n}" ${bagli ? "" : "disabled"} class="py-1.5 rounded-lg font-label-sm text-label-sm text-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${medyaKlipSn === n ? "border-2 border-primary bg-primary/10 font-bold text-primary" : "border border-surface-container-high bg-surface-container-low text-on-surface hover:bg-surface-container"}">Sonraki ${n}sn</button>`;
    $("#medyaYaziciKart").innerHTML = `
      <div class="flex items-center justify-between gap-2 pb-2.5 mb-3 border-b border-surface-container-high"><div class="flex items-center gap-2">${sipIkon("video_camera_front", "text-primary text-[20px]")}<h4 class="font-headline-sm text-[15px] font-bold text-on-surface">Yazıcıdan Anlık Video Çek</h4></div>${rozet}</div>
      <p class="font-body-sm text-[12px] text-outline mb-3">${aciklama}</p>
      <div class="space-y-2 mb-3"><span class="block text-label-sm font-semibold text-on-surface">Süre seçin:</span><div class="grid grid-cols-3 gap-1.5">${sn(15)}${sn(30)}${sn(60)}</div></div>
      <button type="button" id="medyaKlipCek" ${kamera ? "" : "disabled"} class="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl font-label-md text-label-md font-semibold transition-all ${kamera ? "bg-primary text-on-primary hover:bg-primary/95 shadow-sm" : "bg-surface-container-high text-outline cursor-not-allowed"}">${sipIkon(bagli ? "bolt" : "link_off")}<span>${!bagli ? "Köprü bağlı değil" : kamera ? "Kaydı Başlat & Siparişe Ekle" : "Kamera bağlanamadı"}</span></button>`;
    $("#medyaSdYenile").disabled = !bagli;
  }

  async function medyaKlipCek() {
    const s = sipBul(medyaSipId), y = medyaYazici(), dugme = $("#medyaKlipCek");
    if (!s || dugme.disabled) return;
    dugme.disabled = true;
    // Köprü isteği ~1-3 sn'de alır, kamera bağlanır (~2 sn), sonra seçilen süre kaydedilir.
    const sn = medyaKlipSn, bitis = Date.now() + (sn + 5) * 1000;
    const sayac = setInterval(() => {
      const kalan = Math.ceil((bitis - Date.now()) / 1000);
      medyaYaz(kalan > 0 ? `🔴 Kaydediliyor… ~${kalan} sn` : "Klip hazırlanıyor ve yükleniyor…");
    }, 500);
    try {
      const sonuc = await yaziciIstek("klip", { siparis_id: s.id, saniye: sn, yazici: y?.ad ?? null });
      clearInterval(sayac);
      medyaSecili = sonuc.yol || medyaSecili; medyaSekme = "bu";
      medyaYaz(`Klip eklendi ✓ (${Number(sonuc.kare) || "?"} kare, ${Number(sonuc.sure) || sn} sn)`);
      await siparisYukle();
      if (medyaSipId != null) await medyaCiz();
    } catch (e) { clearInterval(sayac); medyaYaz("Klip alınamadı: " + e.message, true); medyaYaziciCiz(); }
  }

  async function medyaSdYenile() {
    const y = medyaYazici();
    medyaSekme = "sd"; medyaSd.durum = "yukleniyor";
    await medyaCiz();
    try {
      const sonuc = await yaziciIstek("sd_listele", { yazici: y?.ad ?? null });
      medyaSd.dosyalar = Array.isArray(sonuc.dosyalar) ? sonuc.dosyalar : [];
      medyaSd.durum = "";
    } catch (e) { medyaSd.durum = e.message; }
    if (medyaSipId != null) await medyaCiz();
  }

  async function medyaSdAktar(ad, dugme) {
    const s = sipBul(medyaSipId), y = medyaYazici();
    if (!s) return;
    dugme.disabled = true; dugme.textContent = "Aktarılıyor…";
    medyaYaz(`${ad} indiriliyor ve MP4'e çevriliyor… (büyük dosyada birkaç dakika sürebilir)`);
    try {
      const sonuc = await yaziciIstek("sd_aktar", { siparis_id: s.id, dosya: ad, yazici: y?.ad ?? null });
      medyaSecili = sonuc.yol || null; medyaSekme = "bu";
      medyaYaz("Timelapse siparişe eklendi ✓");
      await siparisYukle();
      if (medyaSipId != null) await medyaCiz();
    } catch (e) { medyaYaz("Aktarılamadı: " + e.message, true); dugme.disabled = false; dugme.textContent = "Tekrar dene"; }
  }

  function medyaSdCiz() {
    const eklenen = new Set(sipMedya(sipBul(medyaSipId)).map((m) => m.kaynak).filter(Boolean));
    const bilgi = (metin) => { $("#medyaKutuphane").innerHTML = `<div class="col-span-full p-6 text-center font-body-sm text-body-sm text-outline">${metin}</div>`; };
    if (medyaSd.durum === "yukleniyor") return bilgi(`${sipIkon("sync", "text-[18px] animate-spin align-middle")} SD kart okunuyor… (köprü birkaç saniyede bir bakar)`);
    if (medyaSd.durum) return bilgi(`<span class="text-error">${esc(medyaSd.durum)}</span>`);
    if (!medyaSd.dosyalar) return bilgi(yaziciBagli(medyaYazici()) ? '"MicroSD\'yi Yenile" ile yazıcının SD kartındaki timelapse\'leri listele.' : "SD karta erişmek için yazıcı köprüsü çalışıyor olmalı.");
    if (!medyaSd.dosyalar.length) return bilgi("SD kartta timelapse yok. Bambu Studio'da baskıyı gönderirken \"Timelapse\" kutusunu işaretle.");
    $("#medyaKutuphane").innerHTML = medyaSd.dosyalar.map((d) => `<div class="p-3 rounded-xl bg-white border border-surface-container flex flex-col gap-2">
        <div class="flex items-center gap-2 min-w-0">${sipIkon("sd_card", "text-[20px] text-primary shrink-0")}<span class="font-label-md text-label-md font-bold text-on-surface truncate" title="${esc(d.ad)}">${esc(d.ad)}</span></div>
        <div class="flex items-center justify-between text-[11px] text-outline"><span>${d.tarih ? esc(sipZaman(d.tarih)) : "-"}</span><span class="font-mono">${mb(Number(d.boyut) || 0)}</span></div>
        ${eklenen.has(d.ad) ? `<span class="px-2 py-1.5 rounded-lg bg-tertiary-fixed/30 text-tertiary font-label-sm text-label-sm font-semibold text-center">Bu siparişte ✓</span>`
          : `<button type="button" data-sd-aktar="${esc(d.ad)}" class="px-2 py-1.5 rounded-lg bg-primary text-on-primary font-label-sm text-label-sm font-semibold hover:bg-primary/95 disabled:opacity-60">Siparişe aktar (MP4)</button>`}
      </div>`).join("");
  }

  function medyaKontrolCiz() {
    const v = $("#medyaOynatici");
    const ikon = v.paused ? "play_arrow" : "pause";
    $("#mOynat").innerHTML = sipIkon(ikon, "text-[20px]");
    $("#mBuyukOynat").classList.toggle("opacity-0", !v.paused);
    document.querySelectorAll("[data-hiz]").forEach((b) => {
      const aktif = Number(b.dataset.hiz) === v.playbackRate;
      b.className = `px-2 py-0.5 rounded font-mono ${aktif ? "bg-primary text-white font-bold" : "bg-white/15 text-white font-medium hover:bg-white/25"}`;
    });
    $("#mDongu").classList.toggle("text-tertiary-fixed", v.loop);
  }

  async function medyaYukle(dosya) {
    const s = sipBul(medyaSipId);
    if (!s || !dosya) return;
    if (dosya.size > SIP_MEDYA_EN_BUYUK) return medyaYaz("Video 50 MB'tan büyük; Bambu Studio'da daha düşük kalitede dışa aktarıp tekrar dene.", true);
    const mov = /quicktime/.test(dosya.type) || /\.mov$/i.test(dosya.name);
    if (!mov && !/mp4/.test(dosya.type) && !/\.mp4$/i.test(dosya.name)) return medyaYaz("Yalnızca MP4 veya MOV yüklenebilir.", true);
    const yol = `${s.id}/${Date.now()}.${mov ? "mov" : "mp4"}`;
    medyaYaz("Yükleniyor…");
    const yk = await sb.storage.from(SIP_DEPO).upload(yol, dosya, { contentType: mov ? "video/quicktime" : "video/mp4", upsert: false });
    if (yk.error) return medyaYaz("Yüklenemedi: " + yk.error.message + sipSqlIpucu(yk.error), true);
    const oge = { yol, ad: dosya.name.slice(0, 120), boyut: dosya.size, tur: $("#medyaTur").value, tarih: new Date().toISOString() };
    if (!(await sipGuncelle(s.id, "medya", [...sipMedya(s), oge]))) { await sb.storage.from(SIP_DEPO).remove([yol]); return medyaYaz("Kaydedilemedi.", true); }
    medyaSecili = yol; medyaSekme = "bu";
    medyaYaz("Yüklendi ✓");
    await siparisYukle();
    await medyaCiz();
  }

  async function medyaSil(yol, sipId) {
    const s = sipBul(sipId);
    if (!s || !confirm("Bu video silinsin mi?")) return;
    if (!(await sipGuncelle(s.id, "medya", sipMedya(s).filter((m) => m.yol !== yol)))) return;
    const baskasi = sipVeri.some((x) => x.id !== s.id && sipMedya(x).some((m) => m.yol === yol));
    if (!baskasi) await sb.storage.from(SIP_DEPO).remove([yol]);
    medyaUrl.delete(yol);
    if (medyaSecili === yol) medyaSecili = null;
    medyaYaz("Silindi.");
    await siparisYukle();
    await medyaCiz();
  }

  async function medyaIndir(yol) {
    const m = medyaTumu().find((x) => x.yol === yol);
    const { data, error } = await sb.storage.from(SIP_DEPO).createSignedUrl(yol, 600, { download: m?.ad || true });
    if (error) return medyaYaz("İndirilemedi: " + error.message, true);
    const a = document.createElement("a");
    a.href = data.signedUrl; a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // Oynatıcıdaki kareyi JPEG olarak indirir (depolamadan CORS ile gelen video gerekir).
  function medyaKareKaydet() {
    const v = $("#medyaOynatici");
    if (!v.videoWidth) return medyaYaz("Önce bir video seç ve oynat.", true);
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    try {
      c.getContext("2d").drawImage(v, 0, 0);
      c.toBlob((blob) => {
        if (!blob) return medyaYaz("Kare alınamadı.", true);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `SIP-${medyaSipId}-kare-${Math.floor(v.currentTime)}sn.jpg`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        medyaYaz("Kare kaydedildi ✓");
      }, "image/jpeg", 0.92);
    } catch (_) { medyaYaz("Tarayıcı bu videodan kare almaya izin vermedi.", true); }
  }

  async function medyaWhatsapp() {
    const s = sipBul(medyaSipId), m = medyaSeciliOge();
    if (!s || !m) return medyaYaz("Önce bir video seç.", true);
    const { data, error } = await sb.storage.from(SIP_DEPO).createSignedUrl(m.yol, 7 * 86400);
    if (error) return medyaYaz("Bağlantı oluşturulamadı: " + error.message, true);
    let tel = (s.musteri_telefon || "").replace(/\D/g, "");
    if (tel.startsWith("0")) tel = "9" + tel; else if (tel.length === 10) tel = "90" + tel;
    const mesaj = `Merhaba, #SIP-${s.id} numaralı siparişinizin (${s.urun_adi}) baskı videosu: ${data.signedUrl} (bağlantı 7 gün geçerli)`;
    window.open(`https://wa.me/${tel}?text=${encodeURIComponent(mesaj)}`, "_blank", "noopener");
    medyaYaz(tel ? "WhatsApp açıldı ✓" : "Telefon girilmemiş; WhatsApp'ta kişiyi sen seç.");
  }

  async function medyaSipariseEkle() {
    const s = sipBul(medyaSipId), m = medyaSeciliOge();
    if (!s || !m || sipMedya(s).some((x) => x.yol === m.yol)) return;
    const { sipId, ...oge } = m;
    if (await sipGuncelle(s.id, "medya", [...sipMedya(s), oge])) { medyaYaz(`#SIP-${s.id} siparişine eklendi ✓`); await siparisYukle(); await medyaCiz(); }
  }

  // Seçili videoyu 'instagram' alanına kopyalar ve Reels olarak planlar (GitHub 15 dakikada bir paylaşır).
  async function medyaPlanla() {
    const s = sipBul(medyaSipId), m = medyaSeciliOge(), dugme = $("#medyaPlanla");
    if (!s || !m) return medyaYaz("Önce bir video seç.", true);
    const zaman = new Date($("#medyaZaman").value), aciklama = $("#medyaAciklama").value.trim();
    if (isNaN(zaman)) return medyaYaz("Paylaşım zamanını seç.", true);
    if (aciklama.length > 2200 || etiketSayisi(aciklama) > 30) return medyaYaz("Açıklama en fazla 2200 karakter ve 30 etiket olabilir.", true);
    dugme.disabled = true;
    medyaYaz("Video Instagram alanına kopyalanıyor…");
    try {
      const { data: blob, error } = await sb.storage.from(SIP_DEPO).download(m.yol);
      if (error) return medyaYaz("Video alınamadı: " + error.message, true);
      const mov = /\.mov$/i.test(m.yol);
      // Düzenleyici {sayı}/{sayı}.mp4 bekler (ürünsüz sipariş: 0). "_k": köprü zaten kırptı, ikinci kez kırpılmaz.
      const yol = `${Number(s.product_id) || 0}/${Date.now()}${m.kirpildi ? "_k" : ""}.${mov ? "mov" : "mp4"}`;
      const yk = await sb.storage.from(IG_DEPO).upload(yol, blob, { contentType: mov ? "video/quicktime" : "video/mp4", upsert: false });
      if (yk.error) return medyaYaz("Kopyalanamadı: " + yk.error.message + igSqlIpucu(yk.error), true);
      const kayit = { product_id: s.product_id ?? null, video_path: yol, caption: aciklama, scheduled_at: zaman.toISOString() };
      if (!$("#medyaDuzenle").checked) kayit.video_edit = false;
      const { error: hata } = await sb.from("instagram_posts").insert(kayit);
      if (hata) { await sb.storage.from(IG_DEPO).remove([yol]); return medyaYaz("Planlanamadı: " + hata.message + igSqlIpucu(hata), true); }
      medyaYaz(zaman <= new Date() ? "Planlandı ✓ İlk kontrolde (15 dk içinde) paylaşılacak." : `Planlandı ✓ ${zaman.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })}`);
    } finally { dugme.disabled = false; }
  }

  function medyaBagla() {
    if (medyaBagli) return;
    medyaBagli = true;
    const pencere = $("#medyaPencere"), v = $("#medyaOynatici");
    pencere.addEventListener("click", async (e) => {
      if (e.target.closest("[data-medya-kapat]")) return medyaKapat();
      const sekme = e.target.closest("[data-medya-sekme]");
      if (sekme) {
        medyaSekme = sekme.dataset.medyaSekme;
        if (medyaSekme === "sd" && !medyaSd.dosyalar && !medyaSd.durum && yaziciBagli(medyaYazici())) return medyaSdYenile();
        return medyaCiz();
      }
      const klipSn = e.target.closest("[data-klip-sn]");
      if (klipSn && !klipSn.disabled) { medyaKlipSn = Number(klipSn.dataset.klipSn); return medyaYaziciCiz(); }
      if (e.target.closest("#medyaKlipCek")) return medyaKlipCek();
      const sdAktar = e.target.closest("[data-sd-aktar]");
      if (sdAktar && !sdAktar.disabled) return medyaSdAktar(sdAktar.dataset.sdAktar, sdAktar);
      const indir = e.target.closest("[data-medya-indir]");
      if (indir) return medyaIndir(indir.dataset.medyaIndir);
      const sil = e.target.closest("[data-medya-sil]");
      if (sil) return medyaSil(sil.dataset.medyaSil, Number(sil.dataset.medyaSip));
      const kart = e.target.closest("[data-medya]");
      if (kart) { medyaSecili = kart.dataset.medya; await medyaCiz(); v.play().catch(() => {}); return; }
      const format = e.target.closest("[data-format]");
      if (format) {
        const dikey = format.dataset.format === "dikey";
        $("#medyaDuzenle").checked = dikey;
        pencere.querySelectorAll("[data-format]").forEach((b) => {
          const aktif = b === format;
          b.className = `flex flex-col items-center justify-center p-2.5 rounded-lg text-center ${aktif ? "border-2 border-primary bg-primary/5" : "border border-surface-container-high bg-surface-container-low hover:bg-surface-container"}`;
        });
      }
    });
    $("#medyaCekmeceye").addEventListener("click", () => { const id = medyaSipId; medyaKapat(); if (sipCekmeId == null && id != null) sipCekmeAc(id); });
    $("#medyaSdYenile").addEventListener("click", medyaSdYenile);
    $("#medyaDosya").addEventListener("change", async (e) => { const f = e.target.files[0]; e.target.value = ""; await medyaYukle(f); });
    $("#medyaIndir").addEventListener("click", () => medyaSecili ? medyaIndir(medyaSecili) : medyaYaz("Önce bir video seç.", true));
    $("#medyaKare").addEventListener("click", medyaKareKaydet);
    $("#medyaWhatsapp").addEventListener("click", medyaWhatsapp);
    $("#medyaSipariseEkle").addEventListener("click", medyaSipariseEkle);
    $("#medyaPlanla").addEventListener("click", medyaPlanla);
    $("#medyaTumunuIndir").addEventListener("click", async () => {
      const liste = sipMedya(sipBul(medyaSipId));
      if (!liste.length) return medyaYaz("Bu siparişte video yok.", true);
      for (const m of liste) { await medyaIndir(m.yol); await new Promise((r) => setTimeout(r, 600)); }
    });
    // Oynatıcı kontrolleri
    const oynatDurdur = () => { if (!v.src) return; v.paused ? v.play().catch(() => {}) : v.pause(); };
    $("#mOynat").addEventListener("click", oynatDurdur);
    $("#mBuyukOynat").addEventListener("click", oynatDurdur);
    v.addEventListener("click", oynatDurdur);
    $("#mGeri").addEventListener("click", () => { v.currentTime = Math.max(0, v.currentTime - 10); });
    $("#mIleri").addEventListener("click", () => { v.currentTime = Math.min(v.duration || 0, v.currentTime + 10); });
    document.querySelectorAll("[data-hiz]").forEach((b) => b.addEventListener("click", () => { v.playbackRate = Number(b.dataset.hiz); medyaKontrolCiz(); }));
    $("#mDongu").addEventListener("click", () => { v.loop = !v.loop; medyaKontrolCiz(); });
    $("#mTamEkran").addEventListener("click", () => { const k = v.closest("[data-oynatici]"); (document.fullscreenElement ? document.exitFullscreen() : k.requestFullscreen?.())?.catch?.(() => {}); });
    $("#mCubuk").addEventListener("input", (e) => { if (v.duration) v.currentTime = (Number(e.target.value) / 100) * v.duration; });
    v.addEventListener("timeupdate", () => {
      const yuzde = v.duration ? (v.currentTime / v.duration) * 100 : 0;
      $("#mCubuk").value = yuzde;
      $("#mYuzde").textContent = `%${Math.round(yuzde)}`;
      $("#mSure").textContent = `${sureYaz(v.currentTime)} / ${sureYaz(v.duration)}`;
    });
    v.addEventListener("loadedmetadata", () => {
      $("#medyaCozunurluk").textContent = v.videoWidth ? `${v.videoWidth}×${v.videoHeight} • ${sureYaz(v.duration)}` : "—";
      $("#mSure").textContent = `00:00 / ${sureYaz(v.duration)}`;
    });
    ["play", "pause", "ratechange"].forEach((o) => v.addEventListener(o, medyaKontrolCiz));
  }

  function sipCsvIndir(liste) {
    const hucre = (v) => { const t = String(v ?? ""); return `"${(/^[=+\-@]/.test(t) ? "'" + t : t).replace(/"/g, '""')}"`; };
    const satirlar = [["id", "tarih", "urun", "renk", "adet", "tutar_tl", "kanal", "durum", "odendi", "odeme_yontemi", "acil", "termin", "yazici",
      "musteri_adi", "telefon", "eposta", "teslimat_adresi", "kargo_firmasi", "takip_no", "fatura_no", "gercek_sure_dk", "gercek_gram", "not"],
      ...liste.map((s) => [s.id, s.created_at, s.urun_adi, s.renk, s.adet, s.fiyat_tl, s.kanal, s.durum, s.odendi ? "evet" : "hayir",
        s.odeme_yontemi, s.acil ? "evet" : "", s.termin, s.yazici, s.musteri_adi, s.musteri_telefon, s.musteri_eposta, s.teslimat_adresi,
        s.kargo_firmasi, s.takip_no, s.fatura_no, s.gercek_sure_dk, s.gercek_gram, s.musteri_notu])];
    const blob = new Blob(["﻿" + satirlar.map((r) => r.map(hucre).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `siparisler-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // Veriyi çeker (sekme açık olmasa da: bildirim zili için başlangıçta da çağrılır).
  async function sipVeriGetir() {
    const { data, error } = await sb.from("siparisler").select("*, products(url, image_url, price_tl, cost_tl, print_time_min, weight_g)").order("created_at", { ascending: false }).limit(500);
    if (error) throw error;
    sipVeri = data;
    bildirimCiz();
    return data;
  }

  async function siparisYukle() {
    sipFormBagla();
    if (!sipUrunAdi.size) sipUrunleriYukle().catch(() => {});
    try { await Promise.all([sipVeriGetir(), yaziciGetir().catch(() => {})]); }
    catch (error) { $("#siparisTablo").innerHTML = `<tr><td class="hata">${esc(error.message + sipSqlIpucu(error))}</td></tr>`; $("#siparisOzet").innerHTML = ""; return; }
    sipOzetCiz();
    sipCiz();
    if (sipCekmeId != null) sipCekmeCiz();
  }

  // Dakikada bir: süreye bağlı ilerleme ve bildirimler tazelenir (çekmece açıksa yazılanı bozmamak için çizilmez).
  setInterval(() => {
    if (!sipVeri.length) return;
    bildirimCiz();
    if (!$("#siparisSekmesi").hidden && sipCekmeId == null && medyaSipId == null) { sipOzetCiz(); sipCiz(); }
  }, 60000);

  // 10 saniyede bir: yazıcı köprüsünün canlı durumu (yalnızca Siparişler sekmesi ya da video penceresi açıkken).
  setInterval(async () => {
    const sekmeAcik = !$("#siparisSekmesi").hidden;
    if (!sekmeAcik && medyaSipId == null) return;
    await yaziciGetir().catch(() => {});
    if (medyaSipId != null) { medyaYaziciCiz(); return; }
    sipEntegrasyonCiz();
    if (!sipVeri.some(sipCanli)) return;
    if (sipCekmeId == null) sipCiz();
    else if (!$("#sipCekmece").contains(document.activeElement)) sipCekmeCiz();   // yazılan alanı bozma
  }, 10000);

  // ------------------------------------------------------------ tüm ürünler
  let tumZaman;
  async function tumYukle() {
    const gun = Number($("#tumGun").value), sira = $("#tumSira").value, ara = $("#tumAra").value.trim();
    const artan = ["print_time_min", "cost_tl"].includes(sira);
    let q = sb.from("products").select("id,name,url,category,score,print_time_min,cost_tl,price_tl,hourly_profit_tl,downloads,likes,trend_rank,image_url,last_seen")
      .gte("last_seen", new Date(Date.now() - gun * 864e5).toISOString())
      .order(sira, { ascending: artan, nullsFirst: false }).limit(200);
    if (ara) q = q.ilike("name", `%${ara.replace(/[%_]/g, "")}%`);
    if ($("#tumKategori").value) q = q.eq("category", $("#tumKategori").value);
    const { data, error } = await q;
    if (error) throw error;
    await planIdleriYukle();
    if ($("#tumKategori").options.length === 1) {
      const kats = await sb.from("products").select("category").not("category", "is", null).limit(1000);
      [...new Set((kats.data || []).map((r) => r.category))].sort().forEach((k) => $("#tumKategori").add(new Option(k, k)));
    }
    $("#tumBilgi").textContent = `${data.length} ürün${data.length === 200 ? " (ilk 200)" : ""}`;
    $("#tumTablo").innerHTML = `<tr><th>Ürün</th><th>Kategori</th><th class="sayi">Puan</th><th class="sayi">Baskı</th><th class="sayi">Maliyet → fiyat</th><th class="sayi">Saatlik</th><th class="sayi">İndirme</th><th></th></tr>` +
      data.map((p) => `<tr>
        <td><a href="${url(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>${p.trend_rank ? " 🔥" : ""}</td>
        <td>${esc(p.category || "-")}</td><td class="sayi">${p.score ?? "-"}</td><td class="sayi">${sure(p.print_time_min)}</td>
        <td class="sayi">${p.cost_tl == null ? "-" : `${Math.round(p.cost_tl)} → ${Math.round(p.price_tl)}`}</td>
        <td class="sayi">${tl(p.hourly_profit_tl)}</td><td class="sayi">${(p.downloads || 0).toLocaleString("tr-TR")}</td>
        <td><button type="button" class="ikincil" data-plan="${p.id}">${planIdleri.has(p.id) ? "✓ Planda" : "📋 Plana ekle"}</button></td></tr>`).join("");
    $("#tumTablo").querySelectorAll("[data-plan]").forEach((b) => b.addEventListener("click", () => planaEkleCikar(Number(b.dataset.plan), b)));
  }
  $("#tumAra").addEventListener("input", () => { clearTimeout(tumZaman); tumZaman = setTimeout(() => tumYukle().catch((e) => alert(e.message)), 400); });
  ["#tumGun", "#tumSira", "#tumKategori"].forEach((s) => $(s).addEventListener("change", () => tumYukle().catch((e) => alert(e.message))));

  // ------------------------------------------------------------ baskı planı
  try { const s = localStorage.getItem("gunlukSaat"); if (s) $("#gunlukSaat").value = s; } catch (e) { /* tarayıcı depolaması kapalı */ }
  $("#gunlukSaat").addEventListener("change", () => { try { localStorage.setItem("gunlukSaat", $("#gunlukSaat").value); } catch (e) { /* yok say */ } planYukle(); });
  $("#bitenleriGoster").addEventListener("change", () => planYukle());

  async function planYukle() {
    let q = sb.from("print_plan").select("product_id, quantity, done, products(name, url, print_time_min, weight_g, cost_tl, price_tl, filaments)").order("added_at");
    if (!$("#bitenleriGoster").checked) q = q.eq("done", false);
    const { data, error } = await q;
    if (error) { $("#planTablo").innerHTML = `<tr><td class="hata">${esc(error.message)}</td></tr>`; return; }
    const satirlar = data.filter((r) => r.products);
    const bekleyen = satirlar.filter((r) => !r.done);
    const dk = bekleyen.reduce((t, r) => t + (r.products.print_time_min || 0) * r.quantity, 0);
    const gram = bekleyen.reduce((t, r) => t + (r.products.weight_g || 0) * r.quantity, 0);
    const maliyet = bekleyen.reduce((t, r) => t + (r.products.cost_tl || 0) * r.quantity, 0);
    const ciro = bekleyen.reduce((t, r) => t + (r.products.price_tl || 0) * r.quantity, 0);
    const gunluk = Math.max(1, Number($("#gunlukSaat").value) || 8);
    const sureBilinmeyen = bekleyen.filter((r) => r.products.print_time_min == null).length;
    $("#planOzet").innerHTML = `
      <div>Toplam baskı<b>${sure(dk)}</b></div>
      <div>Kaç gün<b>~${Math.ceil(dk / 60 / gunluk) || 0} gün</b></div>
      <div>Filament<b>${Math.round(gram).toLocaleString("tr-TR")} g</b></div>
      <div>Maliyet<b>${tl(maliyet)}</b></div>
      <div>Satılırsa ciro<b>${tl(ciro)}</b></div>
      <div>Ürün adedi<b>${bekleyen.reduce((t, r) => t + r.quantity, 0)}</b></div>`;
    if (sureBilinmeyen) $("#planOzet").insertAdjacentHTML("beforeend", `<div style="grid-column:1/-1">${sureBilinmeyen} ürünün baskı süresi bilinmiyor; toplam eksik olabilir.</div>`);

    const filament = new Map();
    for (const r of bekleyen) for (const f of r.products.filaments || []) {
      const k = `${f.type}|${f.color || "-"}`;
      filament.set(k, { type: f.type, color: f.color, grams: (filament.get(k)?.grams || 0) + (f.grams || 0) * r.quantity });
    }
    const filamentler = [...filament.values()].sort((a, b) => b.grams - a.grams);
    $("#filamentTablo").innerHTML = filamentler.length
      ? `<tr><th>Renk</th><th>Tür</th><th class="sayi">Gram (fire hariç)</th></tr>` + filamentler.map((f) => `<tr>
          <td><span style="display:inline-block;width:14px;height:14px;border-radius:4px;border:1px solid var(--line);vertical-align:-2px;background:${/^#[0-9A-F]{6}$/i.test(f.color || "") ? f.color : "transparent"}"></span> ${esc(f.color || "belirtilmemiş")}</td>
          <td>${esc(f.type)}</td><td class="sayi">${Math.round(f.grams).toLocaleString("tr-TR")} g</td></tr>`).join("")
      : `<tr><td class="muted">Planda filament bilgisi olan ürün yok.</td></tr>`;

    $("#planTablo").innerHTML = satirlar.length
      ? `<tr><th>Ürün</th><th class="sayi">Adet</th><th class="sayi">Süre</th><th>Basıldı</th><th></th></tr>` + satirlar.map((r) => `<tr data-pid="${r.product_id}">
          <td><a href="${url(r.products.url)}" target="_blank" rel="noopener">${esc(r.products.name)}</a></td>
          <td class="sayi"><span class="sayac"><button type="button" data-adet="-1" aria-label="Azalt">−</button><output>${r.quantity}</output><button type="button" data-adet="1" aria-label="Artır">+</button></span></td>
          <td class="sayi">${sure(r.products.print_time_min == null ? null : r.products.print_time_min * r.quantity)}</td>
          <td><input type="checkbox" data-bitti ${r.done ? "checked" : ""} aria-label="Basıldı"></td>
          <td><button type="button" class="ikincil" data-sil>Çıkar</button></td></tr>`).join("")
      : `<tr><td class="muted">Plan boş. Günlük listede veya Tüm ürünler sekmesinde "📋 Plana ekle"ye bas.</td></tr>`;

    $("#planTablo").querySelectorAll("tr[data-pid]").forEach((tr) => {
      const pid = Number(tr.dataset.pid);
      const guncelle = async (degisim) => {
        const { error } = await sb.from("print_plan").update({ ...degisim, updated_at: new Date().toISOString() }).eq("product_id", pid);
        if (error) alert("Kaydedilemedi: " + error.message);
        if (!error && degisim.done) {
          // Basıldı işaretlenince "Bastım" işareti de konur (varsa diğer işaretler korunur).
          const m = isaretler.get(pid) || {};
          await sb.from("product_marks").upsert({ product_id: pid, printed: true, video: !!m.video, sold_count: m.sold_count || 0, note: m.note || null, updated_at: new Date().toISOString() });
        }
        planYukle();
      };
      tr.querySelectorAll("[data-adet]").forEach((b) => b.addEventListener("click", () => {
        const yeni = Math.min(100, Math.max(1, Number(tr.querySelector("output").textContent) + Number(b.dataset.adet)));
        guncelle({ quantity: yeni });
      }));
      tr.querySelector("[data-bitti]").addEventListener("change", (e) => guncelle({ done: e.target.checked }));
      tr.querySelector("[data-sil]").addEventListener("click", async () => {
        const { error } = await sb.from("print_plan").delete().eq("product_id", pid);
        if (error) alert(error.message); else { planIdleri.delete(pid); planYukle(); }
      });
    });
  }

  // ------------------------------------------------------------ tasarımcılar
  async function tasarimciYukle() {
    const { data, error } = await sb.from("designers").select("*").order("followed", { ascending: false }).order("hit_days", { ascending: false }).limit(200);
    if (error) { $("#tasarimciTablo").innerHTML = `<tr><td class="hata">${esc(error.message)}</td></tr>`; return; }
    $("#tasarimciTablo").innerHTML = data.length
      ? `<tr><th>Tasarımcı</th><th class="sayi">İlk 10'da (gün)</th><th>Son</th><th>Takip</th></tr>` + data.map((t) => `<tr>
          <td><a href="https://makerworld.com/en/@${encodeURIComponent(t.handle || "")}" target="_blank" rel="noopener">${esc(t.name || t.handle || t.uid)}</a></td>
          <td class="sayi">${t.hit_days}</td><td>${esc(t.last_hit_date || "-")}</td>
          <td><label><input type="checkbox" data-uid="${t.uid}" data-kaynak="${esc(t.source_id)}" ${t.followed ? "checked" : ""}> takip</label></td></tr>`).join("")
      : `<tr><td class="muted">Henüz tasarımcı kaydı yok; günlük analiz çalıştıkça dolar.</td></tr>`;
    $("#tasarimciTablo").querySelectorAll("[data-uid]").forEach((c) => c.addEventListener("change", async () => {
      const { error } = await sb.from("designers").update({ followed: c.checked }).eq("source_id", c.dataset.kaynak).eq("uid", Number(c.dataset.uid));
      if (error) { alert("Kaydedilemedi: " + error.message); c.checked = !c.checked; }
    }));
  }

  async function grafikCiz(pid, kart) {
    const kap = kart.querySelector(".grafik");
    const { data, error } = await sb.from("product_snapshots").select("snap_date, downloads, likes").eq("product_id", pid).order("snap_date");
    if (error || !data.length) { kap.innerHTML = `<p class="muted">${error ? esc(error.message) : "Henüz kayıt yok."}</p>`; return; }
    if (data.length < 2) { kap.innerHTML = `<p class="muted">Tek günlük kayıt var (${data[0].snap_date}: ${data[0].downloads.toLocaleString("tr-TR")} indirme). Grafik birkaç gün sonra oluşur.</p>`; return; }
    const stil = getComputedStyle(document.documentElement);
    const renk = stil.getPropertyValue("--accent").trim(), yazi = stil.getPropertyValue("--muted").trim(), cizgi = stil.getPropertyValue("--line").trim();
    grafikler.set(pid, new Chart(kap.querySelector("canvas"), {
      type: "line",
      data: { labels: data.map((r) => r.snap_date.slice(5)), datasets: [{ label: "İndirme", data: data.map((r) => r.downloads), borderColor: renk, backgroundColor: renk, pointRadius: 2, tension: 0.25 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: yazi }, grid: { color: cizgi } }, y: { ticks: { color: yazi }, grid: { color: cizgi } } } },
    }));
  }

  async function performansYukle() {
    const { data, error } = await sb.from("product_marks")
      .select("*, products(name, url, category, price_tl, cost_tl)").order("updated_at", { ascending: false });
    if (error) { $("#isaretTablo").innerHTML = `<tr><td class="hata">${esc(error.message)}</td></tr>`; return; }
    const satirlar = data.filter((m) => isaretVar(m) && m.products);
    if (!satirlar.length) {
      $("#kategoriTablo").innerHTML = `<tr><td class="muted">Henüz işaret yok. Günlük listede "Bastım / Videosunu çektim / Sattım" işaretlerini kullan.</td></tr>`;
      $("#isaretTablo").innerHTML = "";
      return;
    }
    const kat = new Map();
    for (const m of satirlar) {
      const k = m.products.category || "-";
      const t = kat.get(k) || { basilan: 0, video: 0, satis: 0, ciro: 0, kar: 0 };
      t.basilan += m.printed ? 1 : 0; t.video += m.video ? 1 : 0; t.satis += m.sold_count;
      t.ciro += m.sold_count * (m.products.price_tl || 0);
      t.kar += m.sold_count * ((m.products.price_tl || 0) - (m.products.cost_tl || 0));
      kat.set(k, t);
    }
    $("#kategoriTablo").innerHTML = `<tr><th>Kategori</th><th class="sayi">Basılan</th><th class="sayi">Video</th><th class="sayi">Satış</th><th class="sayi">Tahmini ciro</th><th class="sayi">Tahmini kâr</th></tr>` +
      [...kat].sort((a, b) => b[1].kar - a[1].kar).map(([k, t]) =>
        `<tr><td>${esc(k)}</td><td class="sayi">${t.basilan}</td><td class="sayi">${t.video}</td><td class="sayi">${t.satis}</td><td class="sayi">${tl(t.ciro)}</td><td class="sayi">${tl(t.kar)}</td></tr>`).join("");
    $("#isaretTablo").innerHTML = `<tr><th>Ürün</th><th>Kategori</th><th>Bastım</th><th>Video</th><th class="sayi">Satış</th><th>Not</th></tr>` +
      satirlar.map((m) => `<tr><td><a href="${url(m.products.url)}" target="_blank" rel="noopener">${esc(m.products.name)}</a></td>
        <td>${esc(m.products.category || "-")}</td><td>${m.printed ? "✓" : ""}</td><td>${m.video ? "✓" : ""}</td>
        <td class="sayi">${m.sold_count}</td><td>${esc(m.note || "")}</td></tr>`).join("");
  }

  // ------------------------------------------------------------ başlat
  async function baslat() {
    try {
      goster("#uygulama");
      sipVeriGetir().catch(() => {});   // bildirim zili için (siparisler tablosu yoksa sessizce geçer)
      if (await gunleriYukle()) await listeYukle();
    } catch (e) {
      durumYaz("Veri alınamadı: " + (e.message || e), true);
    }
  }
  $("#gun").addEventListener("change", () => listeYukle().catch((e) => durumYaz(e.message, true)));
  $("#kategori").addEventListener("change", kartlariCiz);
  $("#isaretsiz").addEventListener("change", kartlariCiz);

  let basladi = false;
  sb.auth.onAuthStateChange((olay, oturum) => {
    if (oturum) $("#kullaniciEposta").textContent = oturum.user?.email || "";
    if (oturum && !basladi) { basladi = true; baslat(); }
    if (!oturum) { basladi = false; goster("#girisEkrani"); }
  });
})();
