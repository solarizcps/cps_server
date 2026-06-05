# -*- coding: utf-8 -*-
"""
019 - ENJ_TIME_SETUP_SNAPSHOT FAZ-TS1
Saatlik uretim satirlarina setup/kapasite snapshot kolonlari.
Idempotent: PRAGMA kontrolu ile var olan kolonu skip eder.
"""
import os
import sqlite3


def db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")


def kolon_var_mi(con, tablo, kolon):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(" + tablo + ")")
    return any(r[1] == kolon for r in cur.fetchall())


def _ensure_schema_migrations(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version           TEXT PRIMARY KEY,
            uygulama_zamani   TEXT DEFAULT (datetime('now', 'localtime')),
            aciklama          TEXT
        )
    """)


def run():
    con = sqlite3.connect(db_path(), timeout=10)
    _ensure_schema_migrations(con)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?", ("019",)
    )
    if cur.fetchone()[0]:
        print("[SKIP] Migration 019 zaten uygulanmis")
        con.close()
        return

    yeni = [
        ("setup_id_a", "INTEGER"),
        ("setup_id_b", "INTEGER"),
        ("kalip_id_a_snapshot", "INTEGER"),
        ("kalip_id_b_snapshot", "INTEGER"),
        ("kalip_kod_a_snapshot", "TEXT"),
        ("kalip_kod_b_snapshot", "TEXT"),
        ("aktif_goz_a_snapshot", "INTEGER"),
        ("aktif_goz_b_snapshot", "INTEGER"),
        ("kalip_basi_cift_a_snapshot", "INTEGER"),
        ("kalip_basi_cift_b_snapshot", "INTEGER"),
        ("tur_kapasitesi_a_snapshot", "INTEGER"),
        ("tur_kapasitesi_b_snapshot", "INTEGER"),
        ("snapshot_zamani", "TEXT"),
        ("snapshot_kaynak", "TEXT"),
    ]
    eklenen = atlanan = 0
    for kol, tip in yeni:
        if kolon_var_mi(con, "enj_saatlik_kayit", kol):
            print("  [SKIP] " + kol + " zaten var")
            atlanan += 1
        else:
            con.execute(
                "ALTER TABLE enj_saatlik_kayit ADD COLUMN " + kol + " " + tip
            )
            print("  [ADD]  " + kol + " eklendi")
            eklenen += 1

    cur.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, aciklama)
        VALUES (?, ?)
        """,
        ("019", "ENJ_TIME_SETUP_SNAPSHOT TS1 saatlik setup snapshot kolonlari"),
    )
    con.commit()
    con.close()
    print("\nSonuc: " + str(eklenen) + " eklendi, " + str(atlanan) + " atlandi")


if __name__ == "__main__":
    run()
