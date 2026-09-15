# -*- coding: utf-8 -*-
"""
191_arac_plan_olay_auto_tamamlandi.py
=======================================
ATP P0 — AUTO_TAMAMLANDI audit event tipini olay_turu CHECK constraint'ine ekler.
Ana gorev durumu TAMAMLANDI olarak kalir; AUTO_TAMAMLANDI yalnizca audit/event kaydina girer.
Temp DB only — canonical DB'ye uygulanmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 191


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
    """AUTO_TAMAMLANDI audit event tipini olay_turu CHECK'e ekle."""
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
                'AMBIGUOUS_STOP',
                'AUTO_TAMAMLANDI'
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
    log(f'[{MIGRATION_VERSION}] arac_plan_olay_auto_tamamlandi')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    try:
        _rebuild_plan_olay_check(con)
        con.commit()
        log(f'[{MIGRATION_VERSION}] AUTO_TAMAMLANDI CHECK constraint eklendi. DONE')
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else None
    run(db)
