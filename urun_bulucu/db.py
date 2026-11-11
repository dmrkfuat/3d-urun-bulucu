"""Veri saklama: Supabase (anahtar varsa) veya yerel SQLite.

İki depo da aynı fonksiyonları sunar. Aynı model (kaynak + kaynaktaki id)
iki kez eklenmez; tekrar görüldüğünde sayıları güncellenir.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from .config import Ayarlar

KAYNAKLAR = [
    {"id": "thingiverse", "name": "Thingiverse", "base_url": "https://www.thingiverse.com",
     "access_method": "kaldırıldı", "notes": "Kasım 2026'da Cloudflare bot kontrolü nedeniyle çıkarıldı; eski kayıtlar duruyor"},
    {"id": "printables", "name": "Printables", "base_url": "https://www.printables.com",
     "access_method": "beklemede", "notes": "Resmi API yok; Cloudflare bot kontrolü var"},
    {"id": "makerworld", "name": "MakerWorld", "base_url": "https://makerworld.com",
     "access_method": "site JSON uçları (resmi olmayan)",
     "notes": "Anahtar gerekmez; robots.txt izinli, şartlarda otomatik erişim yasağı yok (Kasım 2026)"},
    {"id": "etsy_manuel", "name": "Etsy (elle girilen talep listesi)", "base_url": "https://www.etsy.com",
     "access_method": "manuel", "notes": "talep/etsy_talep.csv"},
]

URUN_ALANLARI = [
    "source_id", "external_id", "name", "url", "category", "creator", "downloads", "likes",
    "makes", "views", "published_at", "license", "license_flag", "print_time_min", "material",
    "image_url", "tags", "features",
    "weight_g", "color_count", "cost_tl", "price_tl", "hourly_profit_tl", "trend_rank",
    "creator_uid", "creator_handle", "filaments",
]
# Sonradan eklenen sütunlar (eski SQLite dosyalarına otomatik eklenir).
YENI_SUTUNLAR = {
    "weight_g": "integer", "color_count": "integer", "cost_tl": "real", "price_tl": "real",
    "hourly_profit_tl": "real", "trend_rank": "integer",
    "creator_uid": "integer", "creator_handle": "text", "filaments": "text",
}
JSON_ALANLARI = {"tags", "features", "score_detail", "filaments"}


class Depo(Protocol):
    ad: str

    def urunleri_kaydet(self, urunler: list[dict]) -> dict[tuple[str, str], int]: ...
    def anliklari_kaydet(self, gun: date, urunler: list[dict]) -> None: ...
    def onceki_anliklar(self, ids: list[int], en_gec: date, en_erken: date) -> dict[int, dict]: ...
    def puanlari_kaydet(self, urunler: list[dict]) -> None: ...
    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None: ...
    # tasarımcılar
    def tasarimcilar(self, source_id: str, uids: list[int]) -> dict[int, dict]: ...
    def tasarimcilari_kaydet(self, satirlar: list[dict]) -> None: ...
    def takip_edilenler(self, limit: int) -> list[dict]: ...
    # e-ticaret araması
    def pazar_kontrol_tarihleri(self, ids: list[int]) -> dict[int, str]: ...
    def pazar_kaydet(self, satirlar: list[dict]) -> None: ...
    def pazar_kayitlari(self, ids: list[int]) -> dict[int, dict]: ...
    # pazar keşfi (çok satanlar → MakerWorld)
    def kesif_son_tarih(self) -> str | None: ...
    def kesif_onceki(self, anahtarlar: list[str], en_erken: str) -> dict[str, dict]: ...
    def kesif_kaydet(self, satirlar: list[dict]) -> None: ...
    def kesif_ilanlari(self) -> list[dict]: ...
    # Trendyol 3D mağaza analizi
    def ty_son_tarih(self) -> str | None: ...
    def ty_gecmis(self, en_erken: str) -> list[dict]: ...
    def ty_kaydet(self, satirlar: list[dict]) -> None: ...


TY_ALANLARI = ["tarih", "urun_id", "url", "ad", "marka", "magaza_id", "magaza", "kategori", "fiyat",
               "degerlendirme", "yorum", "puan", "favori", "gorsel"]
TASARIMCI_ALANLARI = ["source_id", "uid", "name", "handle", "hit_days", "last_hit_date", "followed",
                      "auto_followed", "last_design_id", "last_checked"]
PAZAR_ALANLARI = ["product_id", "checked_at", "found_count", "min_price", "max_price", "currency", "results"]
KESIF_ALANLARI = ["kesif_tarihi", "anahtar", "ad", "ilan_sayisi", "siteler", "fiyat_min", "fiyat_medyan",
                  "fiyat_max", "gorsel", "sorgu", "lens_yapildi", "mw_sorgu", "ilanlar", "eslesmeler",
                  "diger_kaynaklar"]
KESIF_JSON = {"siteler", "ilanlar", "eslesmeler", "diger_kaynaklar"}


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- SQLite
SQLITE_SEMA = """
create table if not exists sources (
  id text primary key, name text not null, base_url text, access_method text, notes text
);
create table if not exists products (
  id integer primary key autoincrement,
  source_id text not null references sources(id),
  external_id text not null,
  name text not null, url text not null, category text, creator text,
  downloads integer default 0, likes integer default 0, makes integer default 0, views integer default 0,
  published_at text, license text, license_flag text, print_time_min integer, material text,
  image_url text, tags text default '[]', features text default '[]',
  weight_g integer, color_count integer, cost_tl real, price_tl real, hourly_profit_tl real,
  trend_rank integer,
  score real, score_detail text,
  first_seen text not null, last_seen text not null,
  unique (source_id, external_id)
);
create table if not exists product_snapshots (
  product_id integer not null references products(id) on delete cascade,
  snap_date text not null, downloads integer, likes integer,
  primary key (product_id, snap_date)
);
create table if not exists weekly_picks (
  id integer primary key autoincrement,
  pick_date text not null, rank integer not null,
  product_id integer not null references products(id),
  score real, reason text, video_idea text, instagram_caption text,
  unique (pick_date, rank)
);
create table if not exists designers (
  source_id text not null, uid integer not null, name text, handle text,
  hit_days integer not null default 0, last_hit_date text,
  followed integer not null default 0, auto_followed integer not null default 0,
  last_design_id integer, last_checked text,
  primary key (source_id, uid)
);
create table if not exists print_plan (
  product_id integer primary key references products(id) on delete cascade,
  quantity integer not null default 1, done integer not null default 0,
  added_at text, updated_at text
);
create table if not exists market_discovery (
  id integer primary key autoincrement,
  kesif_tarihi text not null, anahtar text not null, ad text not null,
  ilan_sayisi integer not null default 0, siteler text not null default '{}',
  fiyat_min real, fiyat_medyan real, fiyat_max real, gorsel text, sorgu text,
  lens_yapildi integer not null default 0, mw_sorgu text,
  ilanlar text not null default '[]', eslesmeler text not null default '[]',
  diger_kaynaklar text not null default '[]',
  unique (kesif_tarihi, anahtar)
);
create table if not exists market_checks (
  product_id integer primary key references products(id) on delete cascade,
  checked_at text not null, found_count integer not null default 0,
  min_price real, max_price real, currency text, results text not null default '[]'
);
create table if not exists trendyol_products (
  id integer primary key autoincrement,
  tarih text not null, urun_id integer not null, url text not null, ad text not null,
  marka text, magaza_id integer, magaza text, kategori text, fiyat real,
  degerlendirme integer not null default 0, yorum integer not null default 0, puan real,
  favori integer not null default 0, gorsel text,
  unique (tarih, urun_id)
);
"""


class SqliteDepo:
    ad = "SQLite (yerel dosya)"

    def __init__(self, yol: Path) -> None:
        yol.parent.mkdir(parents=True, exist_ok=True)
        self.yol = yol
        self.con = sqlite3.connect(yol)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SQLITE_SEMA)
        mevcut = {r["name"] for r in self.con.execute("pragma table_info(products)")}
        for sutun, tur in YENI_SUTUNLAR.items():
            if sutun not in mevcut:
                self.con.execute(f"alter table products add column {sutun} {tur}")
        if "instagram_caption" not in {r["name"] for r in self.con.execute("pragma table_info(weekly_picks)")}:
            self.con.execute("alter table weekly_picks add column instagram_caption text")
        self.con.executemany(
            "insert or ignore into sources (id, name, base_url, access_method, notes) "
            "values (:id, :name, :base_url, :access_method, :notes)",
            KAYNAKLAR,
        )
        self.con.commit()

    def urunleri_kaydet(self, urunler: list[dict]) -> dict[tuple[str, str], int]:
        simdi = _simdi()
        alanlar = ", ".join(URUN_ALANLARI)
        yer = ", ".join(f":{a}" for a in URUN_ALANLARI)
        guncelle = ", ".join(f"{a}=excluded.{a}" for a in URUN_ALANLARI if a not in ("source_id", "external_id"))
        sql = (
            f"insert into products ({alanlar}, first_seen, last_seen) values ({yer}, :simdi, :simdi) "
            f"on conflict (source_id, external_id) do update set {guncelle}, last_seen=excluded.last_seen"
        )
        for u in urunler:
            satir = {a: (json.dumps(u.get(a), ensure_ascii=False) if a in JSON_ALANLARI else u.get(a))
                     for a in URUN_ALANLARI}
            satir["simdi"] = simdi
            self.con.execute(sql, satir)
        self.con.commit()
        return self._idler(urunler)

    def _idler(self, urunler: list[dict]) -> dict[tuple[str, str], int]:
        sonuc = {}
        for u in urunler:
            r = self.con.execute(
                "select id from products where source_id=? and external_id=?",
                (u["source_id"], u["external_id"]),
            ).fetchone()
            sonuc[(u["source_id"], u["external_id"])] = r["id"]
        return sonuc

    def anliklari_kaydet(self, gun: date, urunler: list[dict]) -> None:
        self.con.executemany(
            "insert into product_snapshots (product_id, snap_date, downloads, likes) values (?,?,?,?) "
            "on conflict (product_id, snap_date) do update set downloads=excluded.downloads, likes=excluded.likes",
            [(u["id"], gun.isoformat(), u["downloads"], u["likes"]) for u in urunler],
        )
        self.con.commit()

    def onceki_anliklar(self, ids: list[int], en_gec: date, en_erken: date) -> dict[int, dict]:
        if not ids:
            return {}
        yer = ",".join("?" * len(ids))
        satirlar = self.con.execute(
            f"select product_id, snap_date, downloads, likes from product_snapshots "
            f"where product_id in ({yer}) and snap_date <= ? and snap_date >= ? order by snap_date",
            [*ids, en_gec.isoformat(), en_erken.isoformat()],
        ).fetchall()
        # en_gec'e en yakın (en yeni) anlık kalsın
        return {r["product_id"]: dict(r) for r in satirlar}

    def puanlari_kaydet(self, urunler: list[dict]) -> None:
        self.con.executemany(
            "update products set score=?, score_detail=?, price_tl=?, hourly_profit_tl=? where id=?",
            [(u["score"], json.dumps(u["score_detail"], ensure_ascii=False), u.get("price_tl"),
              u.get("hourly_profit_tl"), u["id"]) for u in urunler],
        )
        self.con.commit()

    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None:
        self.con.execute("delete from weekly_picks where pick_date=?", (gun.isoformat(),))
        self.con.executemany(
            "insert into weekly_picks (pick_date, rank, product_id, score, reason, video_idea, instagram_caption) "
            "values (?,?,?,?,?,?,?)",
            [(gun.isoformat(), s["rank"], s["product_id"], s["score"], s["reason"], s["video_idea"],
              s.get("instagram_caption")) for s in secimler],
        )
        self.con.commit()

    # --- tasarımcılar ---
    def tasarimcilar(self, source_id: str, uids: list[int]) -> dict[int, dict]:
        if not uids:
            return {}
        yer = ",".join("?" * len(uids))
        satirlar = self.con.execute(
            f"select * from designers where source_id=? and uid in ({yer})", [source_id, *uids]).fetchall()
        return {r["uid"]: _bool(dict(r), "followed", "auto_followed") for r in satirlar}

    def tasarimcilari_kaydet(self, satirlar: list[dict]) -> None:
        alanlar = ", ".join(TASARIMCI_ALANLARI)
        yer = ", ".join(f":{a}" for a in TASARIMCI_ALANLARI)
        self.con.executemany(
            f"insert or replace into designers ({alanlar}) values ({yer})",
            [{a: s.get(a) for a in TASARIMCI_ALANLARI} for s in satirlar],
        )
        self.con.commit()

    def takip_edilenler(self, limit: int) -> list[dict]:
        satirlar = self.con.execute(
            "select * from designers where followed=1 order by last_checked is not null, last_checked limit ?",
            (limit,)).fetchall()
        return [_bool(dict(r), "followed", "auto_followed") for r in satirlar]

    # --- e-ticaret araması ---
    def pazar_kontrol_tarihleri(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        yer = ",".join("?" * len(ids))
        return {r["product_id"]: r["checked_at"] for r in self.con.execute(
            f"select product_id, checked_at from market_checks where product_id in ({yer})", ids)}

    def pazar_kayitlari(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        yer = ",".join("?" * len(ids))
        sonuc = {}
        for r in self.con.execute(f"select * from market_checks where product_id in ({yer})", ids):
            d = dict(r)
            d["results"] = json.loads(d.get("results") or "[]")
            sonuc[d["product_id"]] = d
        return sonuc

    def pazar_kaydet(self, satirlar: list[dict]) -> None:
        alanlar = ", ".join(PAZAR_ALANLARI)
        yer = ", ".join(f":{a}" for a in PAZAR_ALANLARI)
        self.con.executemany(
            f"insert or replace into market_checks ({alanlar}) values ({yer})",
            [{**{a: s.get(a) for a in PAZAR_ALANLARI}, "results": json.dumps(s.get("results") or [],
                                                                             ensure_ascii=False)}
             for s in satirlar],
        )
        self.con.commit()

    def kesif_son_tarih(self) -> str | None:
        r = self.con.execute("select max(kesif_tarihi) as t from market_discovery").fetchone()
        return r["t"] if r else None

    def kesif_onceki(self, anahtarlar: list[str], en_erken: str) -> dict[str, dict]:
        if not anahtarlar:
            return {}
        yer = ",".join("?" * len(anahtarlar))
        sonuc: dict[str, dict] = {}
        for r in self.con.execute(f"select * from market_discovery where anahtar in ({yer}) and kesif_tarihi >= ? "
                                  "order by kesif_tarihi", [*anahtarlar, en_erken]):
            d = {k: (json.loads(r[k]) if k in KESIF_JSON and r[k] else r[k]) for k in r.keys()}
            d["lens_yapildi"] = bool(d["lens_yapildi"])
            sonuc[d["anahtar"]] = d   # en yenisi kalır
        return sonuc

    def kesif_kaydet(self, satirlar: list[dict]) -> None:
        for gun in {s["kesif_tarihi"] for s in satirlar}:
            self.con.execute("delete from market_discovery where kesif_tarihi = ?", (gun,))
        alanlar = ", ".join(KESIF_ALANLARI)
        yer = ", ".join(f":{a}" for a in KESIF_ALANLARI)
        self.con.executemany(
            f"insert or replace into market_discovery ({alanlar}) values ({yer})",
            [{a: (json.dumps(s.get(a), ensure_ascii=False) if a in KESIF_JSON else s.get(a)) for a in KESIF_ALANLARI}
             for s in satirlar])
        self.con.commit()

    def kesif_ilanlari(self) -> list[dict]:
        sonuc: list[dict] = []
        for r in self.con.execute("select ilanlar from market_discovery"):
            sonuc += json.loads(r["ilanlar"] or "[]")
        return sonuc

    def ty_son_tarih(self) -> str | None:
        r = self.con.execute("select max(tarih) as t from trendyol_products").fetchone()
        return r["t"] if r else None

    def ty_gecmis(self, en_erken: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "select * from trendyol_products where tarih >= ? order by tarih", (en_erken,))]

    def ty_kaydet(self, satirlar: list[dict]) -> None:
        alanlar = ", ".join(TY_ALANLARI)
        yer = ", ".join(f":{a}" for a in TY_ALANLARI)
        self.con.executemany(f"insert or replace into trendyol_products ({alanlar}) values ({yer})",
                             [{a: s.get(a) for a in TY_ALANLARI} for s in satirlar])
        self.con.commit()


def _bool(satir: dict, *alanlar: str) -> dict:
    for a in alanlar:
        satir[a] = bool(satir.get(a))
    return satir


# ---------------------------------------------------------------- Supabase
class SupabaseDepo:
    ad = "Supabase"

    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self.sb = create_client(url, key)
        self.sb.table("sources").upsert(KAYNAKLAR, on_conflict="id").execute()

    def urunleri_kaydet(self, urunler: list[dict]) -> dict[tuple[str, str], int]:
        simdi = _simdi()
        satirlar = [{**{a: u.get(a) for a in URUN_ALANLARI}, "last_seen": simdi} for u in urunler]
        sonuc: dict[tuple[str, str], int] = {}
        for i in range(0, len(satirlar), 200):
            yanit = (
                self.sb.table("products")
                .upsert(satirlar[i:i + 200], on_conflict="source_id,external_id")
                .execute()
            )
            for r in yanit.data:
                sonuc[(r["source_id"], r["external_id"])] = r["id"]
        return sonuc

    def anliklari_kaydet(self, gun: date, urunler: list[dict]) -> None:
        satirlar = [{"product_id": u["id"], "snap_date": gun.isoformat(),
                     "downloads": u["downloads"], "likes": u["likes"]} for u in urunler]
        if satirlar:
            self.sb.table("product_snapshots").upsert(satirlar, on_conflict="product_id,snap_date").execute()

    def onceki_anliklar(self, ids: list[int], en_gec: date, en_erken: date) -> dict[int, dict]:
        if not ids:
            return {}
        yanit = (
            self.sb.table("product_snapshots")
            .select("product_id,snap_date,downloads,likes")
            .in_("product_id", ids)
            .lte("snap_date", en_gec.isoformat())
            .gte("snap_date", en_erken.isoformat())
            .order("snap_date")
            .execute()
        )
        return {r["product_id"]: r for r in yanit.data}

    def puanlari_kaydet(self, urunler: list[dict]) -> None:
        for u in urunler:
            self.sb.table("products").update(
                {"score": u["score"], "score_detail": u["score_detail"],
                 "price_tl": u.get("price_tl"), "hourly_profit_tl": u.get("hourly_profit_tl")}
            ).eq("id", u["id"]).execute()

    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None:
        self.sb.table("weekly_picks").delete().eq("pick_date", gun.isoformat()).execute()
        if not secimler:
            return
        satirlar = [{"pick_date": gun.isoformat(), "instagram_caption": s.get("instagram_caption"),
                     **{k: s[k] for k in ("rank", "product_id", "score", "reason", "video_idea")}}
                    for s in secimler]
        try:
            self.sb.table("weekly_picks").insert(satirlar).execute()
        except Exception as e:  # noqa: BLE001
            # Instagram SQL güncellemesi henüz çalıştırılmadıysa sütun yoktur; seçimler yine kaydedilsin.
            if "instagram_caption" not in str(e):
                raise
            print("UYARI: weekly_picks.instagram_caption sütunu yok "
                  "(supabase/guncelleme_2026-11-10_instagram.sql); açıklamalar kaydedilmedi.")
            for s in satirlar:
                s.pop("instagram_caption")
            self.sb.table("weekly_picks").insert(satirlar).execute()

    # --- tasarımcılar ---
    def tasarimcilar(self, source_id: str, uids: list[int]) -> dict[int, dict]:
        if not uids:
            return {}
        yanit = self.sb.table("designers").select("*").eq("source_id", source_id).in_("uid", uids).execute()
        return {r["uid"]: r for r in yanit.data}

    def tasarimcilari_kaydet(self, satirlar: list[dict]) -> None:
        if satirlar:
            self.sb.table("designers").upsert(
                [{a: s.get(a) for a in TASARIMCI_ALANLARI} for s in satirlar], on_conflict="source_id,uid"
            ).execute()

    def takip_edilenler(self, limit: int) -> list[dict]:
        yanit = (self.sb.table("designers").select("*").eq("followed", True)
                 .order("last_checked", desc=False, nullsfirst=True).limit(limit).execute())
        return list(yanit.data)

    # --- e-ticaret araması ---
    def pazar_kontrol_tarihleri(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        yanit = self.sb.table("market_checks").select("product_id,checked_at").in_("product_id", ids).execute()
        return {r["product_id"]: r["checked_at"] for r in yanit.data}

    def pazar_kayitlari(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        yanit = self.sb.table("market_checks").select("*").in_("product_id", ids).execute()
        return {r["product_id"]: r for r in yanit.data}

    def pazar_kaydet(self, satirlar: list[dict]) -> None:
        if satirlar:
            self.sb.table("market_checks").upsert(
                [{a: s.get(a) for a in PAZAR_ALANLARI} for s in satirlar], on_conflict="product_id"
            ).execute()

    def kesif_son_tarih(self) -> str | None:
        veri = (self.sb.table("market_discovery").select("kesif_tarihi")
                .order("kesif_tarihi", desc=True).limit(1).execute().data)
        return veri[0]["kesif_tarihi"] if veri else None

    def kesif_onceki(self, anahtarlar: list[str], en_erken: str) -> dict[str, dict]:
        if not anahtarlar:
            return {}
        veri = (self.sb.table("market_discovery").select("*").in_("anahtar", anahtarlar)
                .gte("kesif_tarihi", en_erken).order("kesif_tarihi").execute().data)
        return {r["anahtar"]: r for r in veri}

    def kesif_kaydet(self, satirlar: list[dict]) -> None:
        if satirlar:
            for gun in {s["kesif_tarihi"] for s in satirlar}:   # aynı gün yeniden çalışınca eskiler gider
                self.sb.table("market_discovery").delete().eq("kesif_tarihi", gun).execute()
            self.sb.table("market_discovery").upsert(
                [{a: s.get(a) for a in KESIF_ALANLARI} for s in satirlar], on_conflict="kesif_tarihi,anahtar"
            ).execute()

    def kesif_ilanlari(self) -> list[dict]:
        sonuc: list[dict] = []
        for r in self.sb.table("market_discovery").select("ilanlar").execute().data:
            sonuc += r.get("ilanlar") or []
        return sonuc

    def ty_son_tarih(self) -> str | None:
        veri = self.sb.table("trendyol_products").select("tarih").order("tarih", desc=True).limit(1).execute().data
        return veri[0]["tarih"] if veri else None

    def ty_gecmis(self, en_erken: str) -> list[dict]:
        sonuc: list[dict] = []
        while True:   # Supabase bir yanıtta en çok 1000 satır verir
            parca = (self.sb.table("trendyol_products").select("*").gte("tarih", en_erken)
                     .order("tarih").order("urun_id").range(len(sonuc), len(sonuc) + 999).execute().data)
            sonuc += parca
            if len(parca) < 1000:
                return sonuc

    def ty_kaydet(self, satirlar: list[dict]) -> None:
        for i in range(0, len(satirlar), 200):
            self.sb.table("trendyol_products").upsert(
                [{a: s.get(a) for a in TY_ALANLARI} for s in satirlar[i:i + 200]], on_conflict="tarih,urun_id"
            ).execute()


def depo_olustur(ayarlar: Ayarlar) -> Depo:
    if ayarlar.supabase_var:
        return SupabaseDepo(ayarlar.supabase_url, ayarlar.supabase_key)
    return SqliteDepo(ayarlar.veritabani_yolu)
