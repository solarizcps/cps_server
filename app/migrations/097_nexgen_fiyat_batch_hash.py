"""Migration 097 — FAZ-SATINALMA-FIYAT-01D
nexgen_fiyat_batch tablosuna dosya_hash ve override_aciklamasi kolonları ekle.

Bu migration idempotent çalışır:
- Kolon zaten varsa tekrar ekleme yapmaz.
- Veri değiştirmez, yalnızca şema ekler.
"""
import sqlite3
import os
import sys


def run(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        mevcut = {r[1] for r in con.execute(
            "PRAGMA table_info(nexgen_fiyat_batch)"
        ).fetchall()}

        eklendi = []

        if 'dosya_hash' not in mevcut:
            con.execute("ALTER TABLE nexgen_fiyat_batch ADD COLUMN dosya_hash TEXT")
            eklendi.append('dosya_hash')

        if 'override_aciklamasi' not in mevcut:
            con.execute(
                "ALTER TABLE nexgen_fiyat_batch ADD COLUMN override_aciklamasi TEXT"
            )
            eklendi.append('override_aciklamasi')

        if eklendi:
            con.commit()
            print(f"  [097] Eklenen kolonlar: {eklendi}")
        else:
            print("  [097] Kolonlar zaten mevcut — değişiklik yapılmadı")

        # Migration kaydı
        try:
            cols = {r[1] for r in con.execute(
                "PRAGMA table_info(schema_migrations)"
            ).fetchall()}
            if 'aciklama' in cols:
                con.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
                    "VALUES (97, 'fiyat_batch dosya_hash ve override kolonlari')"
                )
            else:
                con.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES (97)"
                )
            con.commit()
        except Exception:
            pass

    finally:
        con.close()


if __name__ == '__main__':
    db = sys.argv[1] if len(sys.argv) > 1 else 'app/mock_data.db'
    run(db)
    print("Migration 097 tamamlandı.")
