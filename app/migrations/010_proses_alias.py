"""
Migration 010 - proses_alias tablosu

Amac: Saha varyantlarini standart proses koduna baglayan alias tablosu.
D6.0.1 sprint - SADECE altyapi. Runtime hook YOK, backfill YOK.

Idempotent: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE
Tek yonlu: Mevcut tablolara DOKUNMAZ.
"""
import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mock_data.db"
)

# === SEED VERI - 6 typo grubu, 15 kayit ===
SEED = [
    # (saha_adi, standart_kod, standart_adi, kategori)
    # Asagi is indirme
    ("As\u0307agi\u0307 is\u0307 indirme",   "90", "Asagi Is Indirme",    "TRANSFER"),  # placeholder, asagi gerek
    ("a\u015fa\u011f\u0131 i\u015f indirme",   "90", "Asagi Is Indirme",    "TRANSFER"),
    ("A\u015fa\u011f\u0131 i\u015f indirme",   "90", "Asagi Is Indirme",    "TRANSFER"),
    # Atki rivet takma (4 varyant)
    ("At\u0131k\u0131 rivet takma", "71", "Atki Rivet Takma",    "ATKI"),  # placeholder
    ("Atk\u0131 rivet takma",   "71", "Atki Rivet Takma",    "ATKI"),
    ("atk\u0131 Rivet Takma",   "71", "Atki Rivet Takma",    "ATKI"),
    ("atk\u0131 rivet takma",   "71", "Atki Rivet Takma",    "ATKI"),
    # Atki Silme (3 varyant)
    ("Atki Silme",                              "70", "Atki Silme",          "ATKI"),
    ("Atk\u0131 Silme",                         "70", "Atki Silme",          "ATKI"),
    ("atk\u0131 silme",                         "70", "Atki Silme",          "ATKI"),
    # Capak
    ("Capak",                                   "60", "Capak",                "ATKI"),
    ("\u00c7apak",                              "60", "Capak",                "ATKI"),
    # Govde basildi
    ("G\u00f6vde bas\u0131ld\u0131",            "80", "Govde Baski",          "GOVDE"),
    ("g\u00f6vde bas\u0131ld\u0131",            "80", "Govde Baski",          "GOVDE"),
    # Tampon Baski
    ("Tampon Baski",                            "72", "Atki Tampon Baski",    "ATKI"),
    ("Tampon Bask\u0131",                       "72", "Atki Tampon Baski",    "ATKI"),
    ("tampon bask\u0131",                       "72", "Atki Tampon Baski",    "ATKI"),
]

# Yukaridaki placeholder satirlari temizle - dogrudan dogru karakter dizesi:
SEED = [
    ("A\u015fa\u011f\u0131 i\u015f indirme",    "90", "Asagi Is Indirme",     "TRANSFER"),
    ("a\u015fa\u011f\u0131 i\u015f indirme",    "90", "Asagi Is Indirme",     "TRANSFER"),
    ("Atk\u0131 rivet takma",                   "71", "Atki Rivet Takma",     "ATKI"),
    ("atk\u0131 Rivet Takma",                   "71", "Atki Rivet Takma",     "ATKI"),
    ("atk\u0131 rivet takma",                   "71", "Atki Rivet Takma",     "ATKI"),
    ("Atki Silme",                              "70", "Atki Silme",           "ATKI"),
    ("Atk\u0131 Silme",                         "70", "Atki Silme",           "ATKI"),
    ("atk\u0131 silme",                         "70", "Atki Silme",           "ATKI"),
    ("Capak",                                   "60", "Capak",                "ATKI"),
    ("\u00c7apak",                              "60", "Capak",                "ATKI"),
    ("G\u00f6vde bas\u0131ld\u0131",            "80", "Govde Baski",          "GOVDE"),
    ("g\u00f6vde bas\u0131ld\u0131",            "80", "Govde Baski",          "GOVDE"),
    ("Tampon Baski",                            "72", "Atki Tampon Baski",    "ATKI"),
    ("Tampon Bask\u0131",                       "72", "Atki Tampon Baski",    "ATKI"),
    ("tampon bask\u0131",                       "72", "Atki Tampon Baski",    "ATKI"),
]


def run(db_path=None):
    db_path = db_path or DB_PATH
    print(f"[MIG-010] DB: {db_path}")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row

    # === 1. Pre-check ===
    existing = c.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='proses_alias'"
    ).fetchone()[0]
    print(f"[MIG-010] Onceki proses_alias: {'VAR' if existing else 'YOK'}")

    # schema_migrations'da 010 var mi
    mig_existing = c.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?", ("010",)
    ).fetchone()[0]
    print(f"[MIG-010] schema_migrations[010]: {'VAR' if mig_existing else 'YOK'}")

    # === 2. CREATE TABLE (idempotent) ===
    c.execute("""
        CREATE TABLE IF NOT EXISTS proses_alias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saha_adi TEXT UNIQUE NOT NULL,
            standart_kod TEXT NOT NULL,
            standart_adi TEXT NOT NULL,
            kategori TEXT,
            guven_skoru INTEGER DEFAULT 0,
            karar_kaynak TEXT,
            onayli_mi INTEGER DEFAULT 0,
            olusturma TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("[MIG-010] CREATE TABLE OK")

    # === 3. CREATE INDEX ===
    c.execute("CREATE INDEX IF NOT EXISTS idx_pa_saha ON proses_alias(saha_adi)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pa_kod ON proses_alias(standart_kod)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pa_onayli ON proses_alias(onayli_mi)")
    print("[MIG-010] 3 INDEX OK")

    # === 4. SEED INSERT OR IGNORE ===
    before = c.execute("SELECT COUNT(*) FROM proses_alias").fetchone()[0]
    inserted = 0
    for saha_adi, standart_kod, standart_adi, kategori in SEED:
        cur = c.execute("""
            INSERT OR IGNORE INTO proses_alias
                (saha_adi, standart_kod, standart_adi, kategori,
                 guven_skoru, karar_kaynak, onayli_mi)
            VALUES (?, ?, ?, ?, 100, 'auto_typo', 1)
        """, (saha_adi, standart_kod, standart_adi, kategori))
        if cur.rowcount > 0:
            inserted += 1
    after = c.execute("SELECT COUNT(*) FROM proses_alias").fetchone()[0]
    print(f"[MIG-010] SEED: onceki={before}, yeni eklenen={inserted}, simdiki={after}")

    # === 5. schema_migrations kaydet (idempotent) ===
    c.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (
        "010",
        "010_proses_alias - D6.0.1 proses_alias tablosu + 6 typo grubu seed (15 satir, guven=100, onayli=1)"
    ))
    print("[MIG-010] schema_migrations kaydedildi")

    c.commit()

    # === 6. POST-VERIFY ===
    print("\n[VERIFY]")
    cnt = c.execute("SELECT COUNT(*) FROM proses_alias").fetchone()[0]
    print(f"  Toplam kayit: {cnt} (beklenen >=15)")

    onayli = c.execute("SELECT COUNT(*) FROM proses_alias WHERE onayli_mi=1").fetchone()[0]
    print(f"  Onayli: {onayli}")

    distinct_kod = c.execute("SELECT COUNT(DISTINCT standart_kod) FROM proses_alias").fetchone()[0]
    print(f"  Distinct standart_kod: {distinct_kod} (beklenen 6)")

    distinct_kat = c.execute("SELECT COUNT(DISTINCT kategori) FROM proses_alias").fetchone()[0]
    print(f"  Distinct kategori: {distinct_kat} (beklenen 3: ATKI, GOVDE, TRANSFER)")

    # Kategori bazinda dagilim
    print("\n  Kategori bazinda:")
    for r in c.execute("SELECT kategori, COUNT(*) FROM proses_alias GROUP BY kategori").fetchall():
        print(f"    {r[0]}: {r[1]} kayit")

    # Standart_kod bazinda
    print("\n  Standart_kod bazinda:")
    for r in c.execute("""SELECT standart_kod, standart_adi, COUNT(*) varyant_sayisi
                          FROM proses_alias
                          GROUP BY standart_kod, standart_adi
                          ORDER BY standart_kod""").fetchall():
        print(f"    {r[0]} {r[1]}: {r[2]} varyant")

    c.close()
    print("\n[MIG-010] TAMAMLANDI")


if __name__ == "__main__":
    run()