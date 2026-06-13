"""
Migration 040: crm_gorusme_urun tablosuna teklif detay alanlari ekle.
ALTER TABLE ile mevcut veriyi korur.
"""
import sqlite3, os

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'))

YENI_ALANLAR = [
    ("verilen_fiyat",  "REAL"),
    ("para_birimi",    "TEXT DEFAULT 'USD'"),
    ("eski_fiyat",     "REAL"),
    ("indirim_notu",   "TEXT"),
    ("numune_adet",    "INTEGER"),
    ("numune_beden",   "TEXT"),
    ("istenen_renk",   "TEXT"),
    ("renk_basi_adet", "INTEGER"),
    ("toplam_adet",    "INTEGER"),
    ("teslim_notu",    "TEXT"),
    ("urun_notu",      "TEXT"),
]


def run():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    mevcut = {row[1] for row in cur.execute("PRAGMA table_info(crm_gorusme_urun)").fetchall()}

    eklendi = 0
    for alan, tip in YENI_ALANLAR:
        if alan not in mevcut:
            cur.execute(f"ALTER TABLE crm_gorusme_urun ADD COLUMN {alan} {tip}")
            print(f"  + {alan} ({tip})")
            eklendi += 1
        else:
            print(f"  = {alan} (zaten var)")

    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations(version, aciklama)
        VALUES('040', 'crm_gorusme_urun teklif detay alanlari')
    """)
    conn.commit()
    conn.close()
    print(f"\n[040] {eklendi} yeni alan eklendi.")


if __name__ == '__main__':
    run()
