# -*- coding: utf-8 -*-
"""
180_arac_plan_ziyaret_durum.py
===============================
GPS P3 — plan kalem ziyaret geofence durumu + olay CHECK genişletmesi.
Temp DB only in this phase.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 180


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _rebuild_plan_olay_check(con: sqlite3.Connection) -> None:
    """Extend olay_turu CHECK with geofence visit types."""
    if not _table_exists(con, 'arac_plan_olay'):
        return
    rows = con.execute('SELECT * FROM arac_plan_olay').fetchall()
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_plan_olay)').fetchall()]
    con.execute('DROP TABLE arac_plan_olay')
    con.execute("""
        CREATE TABLE arac_plan_olay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            plan_is_id INTEGER,
            arac_external_id TEXT,
            olay_turu TEXT NOT NULL,
            mesaj TEXT NOT NULL,
            metadata_json TEXT,
            olay_zamani TEXT,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id),
            FOREIGN KEY (plan_is_id) REFERENCES arac_gunluk_plan_is(id),
            CHECK (olay_turu IN (
                'GECIKME','ROTA_SAPMA','TAMAMLANAMADI','YARINA_AKTAR','NOT',
                'GEOFENCE_GIRIS','GEOFENCE_CIKIS',
                'ROTA_SAPMA_BASLADI','ROTA_GERI_DONDU',
                'KONUMA_VARILDI','KONUMDAN_AYRILDI','ZIYARET_SONUC_BEKLIYOR',
                'AMBIGUOUS_STOP'
            ))
        )
    """)
    con.execute(
        'CREATE INDEX idx_arac_plan_olay_plan ON arac_plan_olay(plan_id, created_at)',
    )
    if rows:
        placeholders = ','.join('?' * len(cols))
        col_list = ','.join(cols)
        for row in rows:
            data = {cols[i]: row[i] for i in range(len(cols))}
            con.execute(
                f'INSERT INTO arac_plan_olay ({col_list}) VALUES ({placeholders})',
                tuple(data[c] for c in cols),
            )


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_plan_ziyaret_durum')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, 'arac_plan_is_ziyaret_durum'):
            con.execute("""
                CREATE TABLE arac_plan_is_ziyaret_durum (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    plan_is_id INTEGER NOT NULL,
                    arac_external_id TEXT NOT NULL,
                    kayitli_yer_id INTEGER,
                    state TEXT NOT NULL DEFAULT 'OUTSIDE',
                    geofence_radius_m REAL NOT NULL DEFAULT 200,
                    exit_radius_m REAL NOT NULL DEFAULT 250,
                    consecutive_inside INTEGER NOT NULL DEFAULT 0,
                    consecutive_outside INTEGER NOT NULL DEFAULT 0,
                    arrived_at TEXT,
                    departed_at TEXT,
                    dwell_seconds INTEGER,
                    last_gps_snapshot_id INTEGER,
                    result_status TEXT,
                    updated_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id),
                    FOREIGN KEY (plan_is_id) REFERENCES arac_gunluk_plan_is(id),
                    UNIQUE (plan_is_id)
                )
            """)
            con.execute(
                'CREATE INDEX idx_arac_ziyaret_plan ON arac_plan_is_ziyaret_durum(plan_id)',
            )
            con.execute(
                'CREATE INDEX idx_arac_ziyaret_vehicle ON arac_plan_is_ziyaret_durum(arac_external_id, updated_at)',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_plan_is_ziyaret_durum')

        _rebuild_plan_olay_check(con)

        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else None)
