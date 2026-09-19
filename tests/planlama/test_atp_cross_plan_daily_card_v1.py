# -*- coding: utf-8 -*-
"""Cross-plan daily vehicle card merge (TEMP DB)."""
from __future__ import annotations

import importlib.util
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = ROOT / 'app' / 'migrations'
PLAN_DATE = '2026-09-19'
VID = '990XPLAN01'


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_db(restore: str):
    import tempfile
    from tools.atp_test_db_guard import bind_temp_db_path

    tmpdir = tempfile.mkdtemp(prefix='cross_card_')
    db_path = str(Path(tmpdir) / 't.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '182_arac_plan_change_v1.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA foreign_keys=OFF')
    con.execute(
        """
        CREATE TABLE arac_gunluk_plan_n (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_tarihi TEXT NOT NULL,
            arac_provider TEXT NOT NULL DEFAULT 'TURKCELL_FILOM',
            arac_external_id TEXT NOT NULL,
            arac_plaka_snapshot TEXT NOT NULL,
            sofor_id INTEGER,
            sofor_adi_snapshot TEXT,
            durum TEXT NOT NULL DEFAULT 'AKTIF',
            created_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER NOT NULL
        )
        """
    )
    con.execute('INSERT INTO arac_gunluk_plan_n SELECT * FROM arac_gunluk_plan')
    con.execute('DROP TABLE arac_gunluk_plan')
    con.execute('ALTER TABLE arac_gunluk_plan_n RENAME TO arac_gunluk_plan')
    con.commit()
    con.close()
    bind_temp_db_path(db_path)
    try:
        yield db_path
    finally:
        bind_temp_db_path(restore)


@pytest.fixture
def temp_db(atp_planlama_db_guard_session):
    session_db = atp_planlama_db_guard_session['temp_db']
    with _temp_db(session_db) as db_path:
        yield db_path


def test_single_vehicle_card_two_plans_global_order(temp_db):
    from modules.planlama.arac_takip_repo import (
        assign_to_plan,
        build_daily_plan_aggregate,
        create_is_talebi,
        ensure_seed_locations,
    )

    ensure_seed_locations(1)
    for i in range(3):
        t = create_is_talebi(
            1,
            {
                'tarih': PLAN_DATE,
                'is': f'N{i}',
                'firma': f'N{i}',
                'latitude': 41.0 + i * 0.01,
                'longitude': 29.0,
                'oncelik': 'NORMAL',
                'save_to_master': False,
            },
        )
        assign_to_plan(1, t['id'], PLAN_DATE, VID, '34 X', None, 'S1', '09:00', None)
    con = sqlite3.connect(temp_db)
    pid1 = con.execute(
        'SELECT id FROM arac_gunluk_plan WHERE arac_external_id=?', (VID,),
    ).fetchone()[0]
    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,NULL,NULL,'AKTIF',datetime('now'),1,datetime('now'),1)
        """,
        (PLAN_DATE, VID, '34 X'),
    )
    pid2 = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    row = con.execute(
        'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY id DESC LIMIT 1',
        (pid1,),
    ).fetchone()
    con.execute('UPDATE arac_gunluk_plan_is SET plan_id=? WHERE id=?', (pid2, row[0]))
    con.commit()
    con.close()
    agg = build_daily_plan_aggregate(PLAN_DATE)
    assert agg['plan_count'] == 2
    assert agg['planned_vehicle_count'] == 1
    assert len(agg['vehicles']) == 1
    v = agg['vehicles'][0]
    assert v['progress_total'] == 3
    display = [t['display_order_no'] for t in agg['items'] if t.get('display_order_no')]
    assert display == [1, 2, 3]
