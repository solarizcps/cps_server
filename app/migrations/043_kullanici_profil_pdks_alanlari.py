"""
Migration 043 — kullanici_profil tablosuna PDKS eşleştirme alanları ekle

Yeni kolonlar:
  pdks_personel_id    INTEGER NULL  — Azper PDKS personel.id
  pdks_sicilno        TEXT NULL     — Azper PDKS personel.sicilno (TC kimlik)
  pdks_eslesme_durumu TEXT NULL     — ESLESMIS / AD_SOYAD_ADAY / MANUEL
  pdks_eslesme_tarihi TEXT NULL     — ISO tarih string (YYYY-MM-DD HH:MM:SS)

Index'ler:
  idx_kullanici_profil_pdks_personel_id
  idx_kullanici_profil_pdks_sicilno

Mevcut veriye dokunulmaz.
Kolon zaten varsa tekrar eklenmez (idempotent).
"""


def upgrade(conn):
    mevcut = {row[1] for row in conn.execute("PRAGMA table_info(kullanici_profil)")}

    eklemeler = [
        ("pdks_personel_id",    "INTEGER NULL"),
        ("pdks_sicilno",        "TEXT NULL"),
        ("pdks_eslesme_durumu", "TEXT NULL"),
        ("pdks_eslesme_tarihi", "TEXT NULL"),
    ]

    for kolon, tanim in eklemeler:
        if kolon not in mevcut:
            conn.execute(f"ALTER TABLE kullanici_profil ADD COLUMN {kolon} {tanim}")
            print(f"  + {kolon} eklendi")
        else:
            print(f"  ~ {kolon} zaten var, atlandı")

    # Index'ler — SQLite'de IF NOT EXISTS desteklenir
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kullanici_profil_pdks_personel_id
        ON kullanici_profil (pdks_personel_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kullanici_profil_pdks_sicilno
        ON kullanici_profil (pdks_sicilno)
    """)
    print("  + index'ler hazır")

    conn.commit()
    print("Migration 043 tamamlandı.")
