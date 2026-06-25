# -*- coding: utf-8 -*-
"""
Migration 084 — NexGen FAZ-3C: Planlama sipariş header + MPR satır bağlantısı
===============================================================================
[1] nexgen_planlama_siparis tablosu
[2] nexgen_uretim_plan.planlama_siparis_id INTEGER (NULL)
[3] Backfill: siparis_no bazında header + plan FK
[4] schema_migrations version=84

NOT: Stok hareketi yapılmaz. İdempotent.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo,),
    ).fetchone() is not None


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n=== Migration 084: nexgen_planlama_siparis + plan FK ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # [1] Header tablosu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_no          TEXT NOT NULL UNIQUE,
            cari_id             INTEGER,
            cari_unvan          TEXT,
            termin_tarihi       TEXT,
            talep_referansi     TEXT,
            durum               TEXT NOT NULL DEFAULT 'TALEP',
            notlar              TEXT,
            olusturan_id        INTEGER,
            olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi   TEXT
        )
    """)
    con.commit()
    print("  OK    nexgen_planlama_siparis")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nps_siparis_no
        ON nexgen_planlama_siparis(siparis_no)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nps_cari
        ON nexgen_planlama_siparis(cari_id)
    """)
    con.commit()

    # [2] planlama_siparis_id kolonu
    if not _kolon_var(cur, 'nexgen_uretim_plan', 'planlama_siparis_id'):
        cur.execute(
            "ALTER TABLE nexgen_uretim_plan "
            "ADD COLUMN planlama_siparis_id INTEGER "
            "REFERENCES nexgen_planlama_siparis(id)"
        )
        con.commit()
        print("  OK    planlama_siparis_id eklendi")
    else:
        print("  SKIP  planlama_siparis_id zaten var")

    # [3] Backfill
    if _tablo_var(cur, 'nexgen_planlama_siparis'):
        gruplar = cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(np.siparis_no), ''), np.plan_kodu) AS grp_siparis_no,
                MIN(np.id) AS ilk_plan_id,
                MAX(np.cari_id) AS cari_id,
                MAX(COALESCE(c.unvan, np.musteri_adi)) AS cari_unvan,
                MAX(np.termin_tarihi) AS termin_tarihi,
                MAX(np.notlar) AS notlar,
                MIN(np.created_by) AS olusturan_id,
                MIN(np.created_at) AS olusturma_tarihi
            FROM nexgen_uretim_plan np
            LEFT JOIN nexgen_cari c ON c.id = np.cari_id
            WHERE np.planlama_siparis_id IS NULL
            GROUP BY COALESCE(NULLIF(TRIM(np.siparis_no), ''), np.plan_kodu)
        """).fetchall()

        hdr_eklenen = 0
        plan_guncellenen = 0
        for g in gruplar:
            sip_no = g['grp_siparis_no']
            if not sip_no:
                continue
            mevcut = cur.execute(
                "SELECT id FROM nexgen_planlama_siparis WHERE siparis_no=?",
                (sip_no,),
            ).fetchone()
            if mevcut:
                hdr_id = mevcut['id']
            else:
                cur.execute("""
                    INSERT INTO nexgen_planlama_siparis
                        (siparis_no, cari_id, cari_unvan, termin_tarihi,
                         durum, notlar, olusturan_id, olusturma_tarihi)
                    VALUES (?, ?, ?, ?, 'TALEP', ?, ?, ?)
                """, (
                    sip_no,
                    g['cari_id'],
                    g['cari_unvan'],
                    g['termin_tarihi'],
                    g['notlar'],
                    g['olusturan_id'],
                    g['olusturma_tarihi'],
                ))
                hdr_id = cur.lastrowid
                hdr_eklenen += 1

            cur.execute("""
                UPDATE nexgen_uretim_plan
                SET planlama_siparis_id = ?
                WHERE planlama_siparis_id IS NULL
                  AND COALESCE(NULLIF(TRIM(siparis_no), ''), plan_kodu) = ?
            """, (hdr_id, sip_no))
            plan_guncellenen += cur.rowcount

        con.commit()
        print(f"  OK    backfill header: {hdr_eklenen} yeni, plan baglanti: {plan_guncellenen}")

    hdr_cnt = cur.execute("SELECT COUNT(*) FROM nexgen_planlama_siparis").fetchone()[0]
    bagli = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE planlama_siparis_id IS NOT NULL"
    ).fetchone()[0]
    toplam = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]
    print(f"  CHECK header: {hdr_cnt}, plan bagli: {bagli}/{toplam}")

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(84)")
        con.commit()
        print("  OK    schema_migrations version=84")
    except Exception as e:
        print(f"  WARN  schema_migrations: {e}")

    con.close()
    print("=== Migration 084 tamamlandi ===\n")


if __name__ == '__main__':
    run()
