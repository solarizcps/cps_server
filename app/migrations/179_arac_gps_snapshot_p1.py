# -*- coding: utf-8 -*-
"""
179_arac_gps_snapshot_p1.py
===========================
Araç Takip GPS P1 — snapshot persistence + plan rota referansı + olay şeması.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 179


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'),
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] arac_gps_snapshot_p1')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'arac_gps_snapshot'):
            con.execute("""
                CREATE TABLE arac_gps_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arac_provider TEXT NOT NULL DEFAULT 'TURKCELL_FILOM',
                    arac_external_id TEXT NOT NULL,
                    plate_snapshot TEXT,
                    gps_timestamp TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    speed_kmh REAL,
                    activity_status TEXT,
                    ignition_status TEXT,
                    odometer_km REAL,
                    is_stale INTEGER NOT NULL DEFAULT 0,
                    dedup_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (arac_provider, arac_external_id, dedup_key)
                )
            """)
            con.execute(
                'CREATE INDEX idx_arac_gps_vehicle_ts '
                'ON arac_gps_snapshot(arac_provider, arac_external_id, gps_timestamp)',
            )
            con.execute(
                'CREATE INDEX idx_arac_gps_gps_ts ON arac_gps_snapshot(gps_timestamp)',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_gps_snapshot')

        if not _table_exists(con, 'arac_plan_rota_snapshot'):
            con.execute("""
                CREATE TABLE arac_plan_rota_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    route_version INTEGER NOT NULL DEFAULT 1,
                    arac_provider TEXT,
                    routing_provider TEXT,
                    geometry_json TEXT NOT NULL,
                    total_distance_m REAL,
                    total_duration_s REAL,
                    stop_order_json TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    created_by INTEGER,
                    FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id)
                )
            """)
            con.execute(
                'CREATE INDEX idx_arac_plan_rota_plan '
                'ON arac_plan_rota_snapshot(plan_id, route_version)',
            )
            con.execute(
                'CREATE UNIQUE INDEX idx_arac_plan_rota_active '
                'ON arac_plan_rota_snapshot(plan_id) WHERE is_active = 1',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_plan_rota_snapshot')

        if not _table_exists(con, 'arac_plan_olay'):
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
                        'ROTA_SAPMA_BASLADI','ROTA_GERI_DONDU'
                    ))
                )
            """)
            con.execute(
                'CREATE INDEX idx_arac_plan_olay_plan ON arac_plan_olay(plan_id, created_at)',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_plan_olay')

        if not _table_exists(con, 'arac_rota_uyum_durum'):
            con.execute("""
                CREATE TABLE arac_rota_uyum_durum (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    arac_external_id TEXT NOT NULL,
                    route_snapshot_id INTEGER,
                    state TEXT NOT NULL,
                    last_gps_snapshot_id INTEGER,
                    last_gps_timestamp TEXT,
                    current_deviation_m REAL,
                    max_deviation_m REAL,
                    consecutive_outside INTEGER NOT NULL DEFAULT 0,
                    consecutive_inside INTEGER NOT NULL DEFAULT 0,
                    deviation_started_at TEXT,
                    recovered_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES arac_gunluk_plan(id),
                    FOREIGN KEY (route_snapshot_id) REFERENCES arac_plan_rota_snapshot(id),
                    FOREIGN KEY (last_gps_snapshot_id) REFERENCES arac_gps_snapshot(id)
                )
            """)
            con.execute(
                'CREATE UNIQUE INDEX idx_arac_rota_uyum_active '
                'ON arac_rota_uyum_durum(plan_id)',
            )
            con.execute(
                'CREATE INDEX idx_arac_rota_uyum_vehicle '
                'ON arac_rota_uyum_durum(arac_external_id, updated_at)',
            )
            log(f'[{MIGRATION_VERSION}] CREATE arac_rota_uyum_durum')

        if _table_exists(con, 'arac_plan_rota_snapshot'):
            cols = {r[1] for r in con.execute('PRAGMA table_info(arac_plan_rota_snapshot)').fetchall()}
            if 'geometry_schema' not in cols:
                con.execute(
                    "ALTER TABLE arac_plan_rota_snapshot ADD COLUMN geometry_schema TEXT NOT NULL DEFAULT 'geojson_linestring_v1'",
                )
            if 'content_hash' not in cols:
                con.execute(
                    'ALTER TABLE arac_plan_rota_snapshot ADD COLUMN content_hash TEXT',
                )

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
