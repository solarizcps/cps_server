# -*- coding: utf-8 -*-
"""
Migration 027: Seed missing kullanici_profil entries for personel_kullanici records.

Background:
  personel_kullanici has 24 entries. Only 11 were previously bridged to kullanici_profil.
  The remaining 12 (excluding 'test test') have no kullanici_profil record, so they do not
  appear in Personel 360. This migration creates the missing profil entries.

  NOTE: Records with legacy_id (ids 1-16) also have production data recorded under their
  legacy_id in uretim_kayit. The production query fix (routes.py) handles combining
  both pk.id and legacy_id production data — this migration only creates the profile bridge.

Safe: idempotent — INSERT OR IGNORE, no updates to existing records.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
MIGRATION_VERSION = '027'


def run(con: sqlite3.Connection):
    con.row_factory = sqlite3.Row

    # Tüm personel_kullanici kayıtlarını çek
    pk_rows = con.execute("""
        SELECT pk.id, pk.kullanici_adi, pk.ad, pk.AdSoyad, pk.legacy_id
        FROM personel_kullanici pk
        LEFT JOIN kullanici_profil kp
            ON kp.kaynak = 'personel_kullanici' AND kp.kaynak_id = pk.id
        WHERE kp.id IS NULL
          AND LOWER(COALESCE(pk.kullanici_adi, '')) NOT LIKE '%test%'
          AND COALESCE(pk.kullanici_adi, pk.ad, pk.AdSoyad) IS NOT NULL
        ORDER BY pk.id
    """).fetchall()

    seeded = 0
    for r in pk_rows:
        gercek_ad = (r['AdSoyad'] or r['ad'] or r['kullanici_adi'] or '').strip()
        if not gercek_ad:
            continue

        # INSERT OR IGNORE — mevcut kayıtlara dokunmaz
        con.execute("""
            INSERT OR IGNORE INTO kullanici_profil
                (kaynak, kaynak_id, gercek_ad, profil_tipi, aktif)
            VALUES (?, ?, ?, 'SAHA_PERSONEL', 1)
        """, ('personel_kullanici', r['id'], gercek_ad))
        seeded += 1
        print(f"  SEED: pk_id={r['id']:>3}  ad='{gercek_ad}'  legacy_id={r['legacy_id']}")

    print(f"\n  Toplam seed: {seeded} kisi")
    return seeded


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")

    # Zaten uygulandıysa atla
    already = con.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    if already:
        print(f"Migration {MIGRATION_VERSION} already applied. Skipping.")
        con.close()
        return

    print(f"=== Migration {MIGRATION_VERSION}: Seed missing personel profiles ===")
    try:
        seeded = run(con)
        con.execute("INSERT INTO schema_migrations (version) VALUES (?)", (MIGRATION_VERSION,))
        con.commit()
        print(f"\nMigration {MIGRATION_VERSION} applied successfully. {seeded} profil eklendi.")
    except Exception as e:
        con.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        con.close()


if __name__ == '__main__':
    main()
