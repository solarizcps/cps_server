# -*- coding: utf-8 -*-
"""
Migration 038 — crm_urun + crm_gorusme_urun tablolari
Fuar sirasinda urun ilgisi takibi icin.
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mock_data.db')

def log(msg, status='OK'):
    print(f"  [{status}] {msg}")

def run():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # crm_urun
    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_urun (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fuar_adi        TEXT    NOT NULL DEFAULT 'GARDA_2026',
            sheet_adi       TEXT    NOT NULL DEFAULT '',
            excel_satir_no  INTEGER NOT NULL DEFAULT 0,
            model_no        TEXT    NOT NULL DEFAULT '',
            kategori        TEXT,
            tip             TEXT,
            urun_cinsi      TEXT,
            asorti          TEXT,
            asorti_dagilimi TEXT,
            birim_fiyat     REAL,
            malzeme_bilgisi TEXT,
            sarfiyat        REAL,
            maliyet         REAL,
            kur             TEXT,
            marj            TEXT,
            aktif           INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    log("crm_urun tablosu olusturuldu/mevcut")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_urun_model   ON crm_urun(model_no)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_urun_fuar    ON crm_urun(fuar_adi)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_urun_sheet   ON crm_urun(sheet_adi, excel_satir_no)")
    log("crm_urun indeksleri olusturuldu/mevcut")

    # crm_gorusme_urun (iliski tablosu)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_gorusme_urun (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            gorusme_id       INTEGER NOT NULL REFERENCES crm_gorusme(id) ON DELETE CASCADE,
            urun_id          INTEGER NOT NULL REFERENCES crm_urun(id)    ON DELETE CASCADE,
            not_text         TEXT,
            fiyat_konusuldu  INTEGER NOT NULL DEFAULT 0,
            numune_istendi   INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    log("crm_gorusme_urun tablosu olusturuldu/mevcut")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_cgu_gorusme ON crm_gorusme_urun(gorusme_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cgu_urun    ON crm_gorusme_urun(urun_id)")
    log("crm_gorusme_urun indeksleri olusturuldu/mevcut")

    # schema_migrations'a kaydet
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations(version, aciklama)
        VALUES('038', 'crm_urun + crm_gorusme_urun tablolari')
    """)

    conn.commit()
    conn.close()
    log("Migration 038 tamamlandi", "DONE")

if __name__ == '__main__':
    run()
