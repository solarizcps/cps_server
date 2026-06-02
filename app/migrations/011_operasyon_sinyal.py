"""
Migration 011 - operasyon_sinyal tablosu

D6.1-A sprint - SADECE altyapi. Runtime hook YOK, AI logic YOK, INSERT YOK.

Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS
Tek yonlu: Mevcut tablolara DOKUNMAZ.
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mock_data.db"
)


def run(db_path=None):
    db_path = db_path or DB_PATH
    print(f"[MIG-011] DB: {db_path}")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row

    # === 1. Pre-check ===
    existing = c.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='operasyon_sinyal'"
    ).fetchone()[0]
    print(f"[MIG-011] Onceki operasyon_sinyal: {'VAR' if existing else 'YOK'}")

    mig_existing = c.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?", ("011",)
    ).fetchone()[0]
    print(f"[MIG-011] schema_migrations[011]: {'VAR' if mig_existing else 'YOK'}")

    # === 2. CREATE TABLE ===
    c.execute("""
        CREATE TABLE IF NOT EXISTS operasyon_sinyal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            sinyal_tipi TEXT NOT NULL,
            seviye TEXT NOT NULL,

            emir_no TEXT,
            proses_adi TEXT,
            proses_kodu TEXT,
            personel_id INTEGER,
            personel_ad TEXT,

            mesaj TEXT NOT NULL,
            aksiyon_onerisi TEXT,

            kaynak TEXT NOT NULL,
            rule_id TEXT,

            durum TEXT DEFAULT 'AKTIF',
            gorulen_kullanici_id INTEGER,
            gorulen_zaman TEXT,
            cozulen_zaman TEXT,
            cozulen_aciklama TEXT,

            tekrar_sayisi INTEGER DEFAULT 1,
            son_tetiklenme TEXT,

            meta_json TEXT,
            olusturma TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("[MIG-011] CREATE TABLE OK")

    # === 3. CREATE INDEX ===
    c.execute("CREATE INDEX IF NOT EXISTS idx_os_tipi_durum ON operasyon_sinyal(sinyal_tipi, durum)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_os_emir ON operasyon_sinyal(emir_no)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_os_kaynak ON operasyon_sinyal(kaynak)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_os_olusturma ON operasyon_sinyal(olusturma)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_os_seviye ON operasyon_sinyal(seviye)")
    print("[MIG-011] 5 INDEX OK")

    # === 4. schema_migrations kaydet ===
    c.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
    """, (
        "011",
        "011_operasyon_sinyal - D6.1-A operasyon_sinyal tablosu (21 kolon dahil id + 5 index, SEED YOK)"
    ))
    print("[MIG-011] schema_migrations kaydedildi")

    c.commit()

    # === 5. VERIFY ===
    print("\n[VERIFY]")
    cols = c.execute("PRAGMA table_info(operasyon_sinyal)").fetchall()
    print(f"  Kolon sayisi: {len(cols)} (beklenen 21, id dahil)")
    for col in cols:
        print(f"    cid={col[0]:2} name={col[1]!r:30} type={col[2]:8} default={col[4]!r}")

    idx = c.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='operasyon_sinyal' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    print(f"\n  Index sayisi: {len(idx)} (beklenen 5)")
    for i in idx:
        print(f"    {i[0]}")

    cnt = c.execute("SELECT COUNT(*) FROM operasyon_sinyal").fetchone()[0]
    print(f"\n  Kayit sayisi: {cnt} (beklenen 0 - SEED YOK)")

    mig = c.execute(
        "SELECT version, uygulama_zamani, aciklama FROM schema_migrations WHERE version='011'"
    ).fetchone()
    print(f"\n  schema_migrations[011]: {dict(mig) if mig else 'YOK'}")

    c.close()
    print("\n[MIG-011] TAMAMLANDI")


if __name__ == "__main__":
    run()