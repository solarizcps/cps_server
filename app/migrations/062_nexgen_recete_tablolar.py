# -*- coding: utf-8 -*-
"""
Migration 062 — NexGen FAZ-4A: Reçete / Formül Tabloları
=========================================================
Yapılacaklar:
  [1] nexgen_formul          — Ana formül kaydı
  [2] nexgen_renk_varyant    — Renk boyutu (Beyaz, Siyah, ...)
  [3] nexgen_uretim_varyant  — Boyut boyutu (SMALL, LARGE, STANDART)
  [4] nexgen_recete_kalem    — Hammadde + oran (uretim_varyant_id'e bağlı)
  [5] Index'ler
  [6] schema_migrations version=62

Tasarım kararları:
  - Reçete kalemleri nexgen_uretim_varyant'a bağlıdır (4. katman).
    Böylece aynı renk varyantında SMALL ve LARGE farklı reçete tutabilir.
  - miktar_kg → 100 KG compound başına hammadde KG miktarı (baz=100)
    Hesap: hedef_kg / 100 × miktar_kg
  - Aktif formül doğrudan değiştirilemez; değişiklik klon+yeni taslak ile yapılır.
  - Stok hareketi, fiyat, üretim kaydı bu migration'da YOK (FAZ-5).
  - Small/Large hammadde özelliği değildir; ürün/compound boyutudur.

İdempotent: Tekrar çalıştırılabilir (CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 062 — NexGen FAZ-4A: Reçete Tabloları")
    print("=" * 65)

    # ── Güvenlik kontrolü ─────────────────────────────────────────
    hrt_say = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    fiyat_say = cur.execute("SELECT COUNT(*) FROM nexgen_hammadde_fiyat").fetchone()[0]
    print(f"\n[KONTROL] stok_hareket={hrt_say}  hammadde_fiyat={fiyat_say}  — migration bunları değiştirmez")

    # ── 1) nexgen_formul ──────────────────────────────────────────
    print("\n[1] nexgen_formul tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_formul (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Kimlik
            kod              TEXT    NOT NULL UNIQUE,   -- "FOR-001"
            ad               TEXT    NOT NULL,           -- "A Formül"
            aciklama         TEXT,

            -- Yaşam döngüsü
            durum            TEXT    NOT NULL DEFAULT 'TASLAK',
            -- TASLAK → ONAY_BEKLIYOR → AKTIF → ARSIV
            -- Aktif formül doğrudan değiştirilemez; klon+taslak gerekir.

            -- Onay akışı
            onay_durumu      TEXT    NOT NULL DEFAULT 'BEKLIYOR',
            -- BEKLIYOR / ONAY_BEKLIYOR / ONAYLANDI / REDDEDILDI
            olusturan_id     INTEGER,
            onaylayan_id     INTEGER,
            onay_tarihi      TEXT,
            onay_notu        TEXT,   -- ret gerekçesi veya onay notu

            notlar           TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
            guncelleme_tarihi TEXT
        )
    """)
    con.commit()
    print("  OK nexgen_formul")

    # ── 2) nexgen_renk_varyant ────────────────────────────────────
    print("\n[2] nexgen_renk_varyant tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_renk_varyant (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,

            formul_id        INTEGER NOT NULL
                                 REFERENCES nexgen_formul(id),

            -- Tanımlayıcı
            kod              TEXT    NOT NULL,  -- "FOR-001-B"
            ad               TEXT    NOT NULL,  -- "A Formül Beyaz"
            renk             TEXT    NOT NULL,
            -- BEYAZ / SİYAH / SARI / HAM / DIGER

            notlar           TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),

            UNIQUE (formul_id, renk)
        )
    """)
    con.commit()
    print("  OK nexgen_renk_varyant")

    # ── 3) nexgen_uretim_varyant ──────────────────────────────────
    print("\n[3] nexgen_uretim_varyant tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_varyant (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,

            renk_varyant_id  INTEGER NOT NULL
                                 REFERENCES nexgen_renk_varyant(id),

            -- Boyut
            boyut            TEXT    NOT NULL DEFAULT 'STANDART',
            -- SMALL / LARGE / STANDART

            ad               TEXT    NOT NULL,  -- "A Formül Beyaz Small"

            -- Onay (her boyut varyantı bağımsız onaylanabilir)
            onay_durumu      TEXT    NOT NULL DEFAULT 'BEKLIYOR',
            -- BEKLIYOR / ONAY_BEKLIYOR / ONAYLANDI / REDDEDILDI
            onaylayan_id     INTEGER,
            onay_tarihi      TEXT,
            onay_notu        TEXT,

            -- Klonlama takibi (FAZ-5+ kullanımı için, şimdi NULL)
            kaynak_varyant_id INTEGER
                                 REFERENCES nexgen_uretim_varyant(id),

            notlar           TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),

            UNIQUE (renk_varyant_id, boyut)
        )
    """)
    con.commit()
    print("  OK nexgen_uretim_varyant")

    # ── 4) nexgen_recete_kalem ────────────────────────────────────
    print("\n[4] nexgen_recete_kalem tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_recete_kalem (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,

            uretim_varyant_id   INTEGER NOT NULL
                                    REFERENCES nexgen_uretim_varyant(id),
            stok_kart_id        INTEGER NOT NULL
                                    REFERENCES nexgen_stok_kart(id),

            -- Sıra (görüntüleme)
            sira                INTEGER NOT NULL DEFAULT 1,

            -- Miktar: 100 KG compound başına kaç KG hammadde
            -- Hesap: hedef_kg / 100 × miktar_kg
            miktar_kg           REAL    NOT NULL CHECK (miktar_kg > 0),

            -- Açıklama: alternatif, not, tercih bilgisi
            aciklama            TEXT,  -- örn: "DCP veya BIBP, tercih DCP"

            aktif               INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi    TEXT    NOT NULL DEFAULT (datetime('now')),

            UNIQUE (uretim_varyant_id, stok_kart_id)
        )
    """)
    con.commit()
    print("  OK nexgen_recete_kalem")

    # ── 5) Index'ler ──────────────────────────────────────────────
    print("\n[5] Index'ler:")
    indexler = [
        ("idx_nf_kod",      "nexgen_formul(kod)"),
        ("idx_nf_durum",    "nexgen_formul(durum)"),
        ("idx_nrv_formul",  "nexgen_renk_varyant(formul_id)"),
        ("idx_nuv_renk",    "nexgen_uretim_varyant(renk_varyant_id)"),
        ("idx_nuv_boyut",   "nexgen_uretim_varyant(boyut)"),
        ("idx_nrk_varyant", "nexgen_recete_kalem(uretim_varyant_id)"),
        ("idx_nrk_stok",    "nexgen_recete_kalem(stok_kart_id)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
        print(f"  {idx_ad} → {idx_hedef}")
    con.commit()

    # ── 6) schema_migrations ──────────────────────────────────────
    print("\n[6] schema_migrations:")
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
        "VALUES (62, 'nexgen recete tablolari FAZ-4A')"
    )
    con.commit()
    print("  version=62 (INSERT OR IGNORE)")

    # ── Doğrulama ─────────────────────────────────────────────────
    hrt_say2   = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    fiyat_say2 = cur.execute("SELECT COUNT(*) FROM nexgen_hammadde_fiyat").fetchone()[0]

    tablolar = ['nexgen_formul', 'nexgen_renk_varyant',
                'nexgen_uretim_varyant', 'nexgen_recete_kalem']

    print("\n" + "=" * 65)
    print("ÖZET:")
    for tbl in tablolar:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
        say  = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {len(cols)} kolon, {say} satır")
    print(f"  nexgen_stok_hareket  ÖNCE={hrt_say}  SONRA={hrt_say2}  "
          f"— {'OK' if hrt_say == hrt_say2 else 'DIKKAT DEGISTI'}")
    print(f"  nexgen_hammadde_fiyat ÖNCE={fiyat_say}  SONRA={fiyat_say2}  "
          f"— {'OK' if fiyat_say == fiyat_say2 else 'DIKKAT DEGISTI'}")
    print("=" * 65)

    con.close()
    print("Migration 062 tamamlandı.")


if __name__ == '__main__':
    run()
