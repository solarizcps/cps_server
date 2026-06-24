# -*- coding: utf-8 -*-
"""
Migration 076 — NexGen FAZ-3A: RF Renk Formul Semasi
====================================================
Yeni tablolar:
  [1] nexgen_rf_renk              — global RF renk havuzu (RF-001 BEYAZ)
  [2] nexgen_rf_kalem             — RF BOYA kalemleri (100 KG baz)
  [3] nexgen_rf_formul_uygunluk   — formul + RF onayli kombinasyon

Degisiklik:
  [4] nexgen_arge_test.rf_renk_id — nullable FK (uygulama katmani)

Idempotent: Tekrar calistirilabilir.
KURAL: nexgen_stok_hareket, tablet, batch, recete_kalem DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 076: nexgen RF renk semasi ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # ── 1) nexgen_rf_renk ─────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_rf_renk (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            rf_kod               TEXT    NOT NULL UNIQUE,
            ad                   TEXT    NOT NULL,
            durum                TEXT    NOT NULL DEFAULT 'ONAYLI',
            kaynak_arge_test_id  INTEGER UNIQUE,
            ilk_talep_cari_id    INTEGER,
            aciklama             TEXT,
            olusturan_id         INTEGER,
            olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
            onaylayan_id         INTEGER,
            onay_tarihi          TEXT,
            aktif                INTEGER NOT NULL DEFAULT 1
        )
    """)
    con.commit()
    print("  OK    nexgen_rf_renk")

    # ── 2) nexgen_rf_kalem ────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_rf_kalem (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            rf_renk_id       INTEGER NOT NULL,
            stok_kart_id     INTEGER NOT NULL,
            miktar_kg        REAL    NOT NULL CHECK (miktar_kg >= 0),
            sira             INTEGER NOT NULL DEFAULT 1,
            aciklama         TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (rf_renk_id, stok_kart_id)
        )
    """)
    con.commit()
    print("  OK    nexgen_rf_kalem")

    # ── 3) nexgen_rf_formul_uygunluk ──────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_rf_formul_uygunluk (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            rf_renk_id           INTEGER NOT NULL,
            formul_id            INTEGER NOT NULL,
            kaynak_arge_test_id  INTEGER UNIQUE,
            durum                TEXT    NOT NULL DEFAULT 'ONAYLI',
            ilk_talep_cari_id    INTEGER,
            shore_hedef          REAL,
            shore_sonuc          REAL,
            renk_sonucu          INTEGER,
            numune_sonucu        INTEGER,
            aciklama             TEXT,
            olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
            onay_tarihi          TEXT,
            aktif                INTEGER NOT NULL DEFAULT 1,
            UNIQUE (rf_renk_id, formul_id)
        )
    """)
    con.commit()
    print("  OK    nexgen_rf_formul_uygunluk")

    # ── 4) nexgen_arge_test.rf_renk_id ────────────────────────
    arge_cols = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_arge_test)"
    ).fetchall()]
    if 'rf_renk_id' not in arge_cols:
        cur.execute("ALTER TABLE nexgen_arge_test ADD COLUMN rf_renk_id INTEGER")
        con.commit()
        print("  OK    nexgen_arge_test.rf_renk_id eklendi")
    else:
        print("  SKIP  rf_renk_id zaten var - atlaniyor")

    # ── 5) Index'ler ──────────────────────────────────────────
    indexler = [
        ("idx_nrf_kod",           "nexgen_rf_renk(rf_kod)"),
        ("idx_nrf_durum",         "nexgen_rf_renk(durum)"),
        ("idx_nrf_kaynak_test",   "nexgen_rf_renk(kaynak_arge_test_id)"),
        ("idx_nrfk_rf",           "nexgen_rf_kalem(rf_renk_id)"),
        ("idx_nrfk_stok",         "nexgen_rf_kalem(stok_kart_id)"),
        ("idx_nrfu_formul_durum", "nexgen_rf_formul_uygunluk(formul_id, durum)"),
        ("idx_nrfu_rf",           "nexgen_rf_formul_uygunluk(rf_renk_id)"),
        ("idx_nrfu_kaynak_test",  "nexgen_rf_formul_uygunluk(kaynak_arge_test_id)"),
        ("idx_arge_rf_renk",      "nexgen_arge_test(rf_renk_id)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(indexler)} index")

    # ── 6) schema_migrations ──────────────────────────────────
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(76)")
        con.commit()
        print("  OK    schema_migrations version=76")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    # ── Dogrulama ─────────────────────────────────────────────
    for tbl in ('nexgen_rf_renk', 'nexgen_rf_kalem', 'nexgen_rf_formul_uygunluk'):
        cnt = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        cols = len(cur.execute(f"PRAGMA table_info({tbl})").fetchall())
        print(f"  CHECK {tbl}: {cols} kolon, {cnt} satir")

    arge_cols2 = [c[1] for c in cur.execute(
        "PRAGMA table_info(nexgen_arge_test)"
    ).fetchall()]
    print(f"  CHECK rf_renk_id in arge_test: {'rf_renk_id' in arge_cols2}")

    con.close()
    print("=== Migration 076 tamamlandi ===\n")


if __name__ == '__main__':
    run()
