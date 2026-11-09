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
]
# Sonradan eklenen sütunlar (eski SQLite dosyalarına otomatik eklenir).
YENI_SUTUNLAR = {
    "weight_g": "integer", "color_count": "integer", "cost_tl": "real", "price_tl": "real",
    "hourly_profit_tl": "real", "trend_rank": "integer",
}
JSON_ALANLARI = {"tags", "features", "score_detail"}


class Depo(Protocol):
    ad: str

    def urunleri_kaydet(self, urunler: list[dict]) -> dict[tuple[str, str], int]: ...
    def anliklari_kaydet(self, gun: date, urunler: list[dict]) -> None: ...
    def onceki_anliklar(self, ids: list[int], en_gec: date, en_erken: date) -> dict[int, dict]: ...
    def puanlari_kaydet(self, urunler: list[dict]) -> None: ...
    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None: ...


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
  score real, reason text, video_idea text,
  unique (pick_date, rank)
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
            "update products set score=?, score_detail=? where id=?",
            [(u["score"], json.dumps(u["score_detail"], ensure_ascii=False), u["id"]) for u in urunler],
        )
        self.con.commit()

    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None:
        self.con.execute("delete from weekly_picks where pick_date=?", (gun.isoformat(),))
        self.con.executemany(
            "insert into weekly_picks (pick_date, rank, product_id, score, reason, video_idea) "
            "values (?,?,?,?,?,?)",
            [(gun.isoformat(), s["rank"], s["product_id"], s["score"], s["reason"], s["video_idea"])
             for s in secimler],
        )
        self.con.commit()


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
                {"score": u["score"], "score_detail": u["score_detail"]}
            ).eq("id", u["id"]).execute()

    def secimleri_kaydet(self, gun: date, secimler: list[dict]) -> None:
        self.sb.table("weekly_picks").delete().eq("pick_date", gun.isoformat()).execute()
        if secimler:
            self.sb.table("weekly_picks").insert(
                [{"pick_date": gun.isoformat(), **{k: s[k] for k in
                  ("rank", "product_id", "score", "reason", "video_idea")}} for s in secimler]
            ).execute()


def depo_olustur(ayarlar: Ayarlar) -> Depo:
    if ayarlar.supabase_var:
        return SupabaseDepo(ayarlar.supabase_url, ayarlar.supabase_key)
    return SqliteDepo(ayarlar.veritabani_yolu)
