# -*- coding: utf-8 -*-
"""
Migration 041: crm_katalog tablosu + crm_urun.katalog_id kolonu
-----------------------------------------------------------------
- crm_katalog: katalog versiyonlarini tutar (id, ad, fuar_adi, aktif, created_at)
- crm_urun'a katalog_id kolonu eklenir (FK -> crm_katalog.id)
- Mevcut 347 urun "Garda 2026" katalogu ile baglanir
- Hicbir mevcut kayit silinmez, gorseller dokunulmaz
- crm_gorusme_urun baglantilari korunur
"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "mock_data.db")


def upgrade(conn):
    c = conn.cursor()

    # 1) crm_katalog tablosu
    c.execute("""
        CREATE TABLE IF NOT EXISTS crm_katalog (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ad         TEXT NOT NULL,
            fuar_adi   TEXT,
            aciklama   TEXT,
            aktif      INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 2) "Garda 2026" katalogu ekle (zaten yoksa)
    c.execute("SELECT id FROM crm_katalog WHERE ad = 'Garda 2026'")
    row = c.fetchone()
    if row is None:
        c.execute("""
            INSERT INTO crm_katalog (ad, fuar_adi, aciklama, aktif)
            VALUES ('Garda 2026', 'Garda 2026', 'Mevcut katalog - rv3 Excel import', 1)
        """)
    katalog_id = c.execute("SELECT id FROM crm_katalog WHERE ad = 'Garda 2026'").fetchone()[0]

    # 3) crm_urun'a katalog_id kolonu ekle (zaten varsa atla)
    mevcut_kolonlar = [r[1] for r in c.execute("PRAGMA table_info(crm_urun)")]
    if "katalog_id" not in mevcut_kolonlar:
        c.execute("ALTER TABLE crm_urun ADD COLUMN katalog_id INTEGER REFERENCES crm_katalog(id)")

    # 4) Mevcut 347 urunu bu kataloga bagla (katalog_id NULL olanlar)
    c.execute("UPDATE crm_urun SET katalog_id = ? WHERE katalog_id IS NULL", (katalog_id,))
    updated = c.rowcount

    # 5) schema_migrations kaydi
    c.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES ('041', 'crm_katalog versyon sistemi + urun katalog_id baglantisi')
    """)

    conn.commit()

    # Rapor
    total   = c.execute("SELECT COUNT(*) FROM crm_urun").fetchone()[0]
    bagli   = c.execute("SELECT COUNT(*) FROM crm_urun WHERE katalog_id = ?", (katalog_id,)).fetchone()[0]
    print(f"[041] crm_katalog olusturuldu. katalog_id={katalog_id} (Garda 2026, aktif=1)")
    print(f"[041] crm_urun katalog_id guncellendi: {updated} kayit")
    print(f"[041] Toplam crm_urun: {total}, kataloga bagli: {bagli}")
    print(f"[041] Migration tamamlandi.")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    upgrade(conn)
    conn.close()
