"""
Migration 039: crm_urun_gorsel tablosu
Urun gorselleri icin ayri tablo.
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crm_urun_gorsel (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            urun_id      INTEGER NOT NULL REFERENCES crm_urun(id),
            sheet_adi    TEXT NOT NULL,
            excel_satir_no INTEGER NOT NULL,
            dosya_yolu   TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(sheet_adi, excel_satir_no)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_urun_gorsel_urun ON crm_urun_gorsel(urun_id)")

    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations(version, aciklama)
        VALUES('039', 'crm_urun_gorsel tablosu')
    """)

    conn.commit()
    conn.close()
    print("[039] crm_urun_gorsel tablosu olusturuldu.")


if __name__ == '__main__':
    run()
