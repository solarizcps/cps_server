# -*- coding: utf-8 -*-
"""Migration 191 — kalıp seri master şema testleri (temp DB only)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MIG = _REPO / 'app' / 'migrations' / '191_enj_kalip_seri_master.py'
for _p in [str(_REPO / 'app'), str(_REPO / 'app' / 'migrations')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))


def _load_mig():
    spec = importlib.util.spec_from_file_location('mig191', _MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _col_names(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()}


@pytest.fixture(scope='module')
def mig():
    return _load_mig()


def test_migration_idempotent_on_temp_copy(mig):
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('Canonical DB source yok')
    tmpdir = tempfile.mkdtemp(prefix='mig191_')
    db = str(Path(tmpdir) / 'test.db')
    shutil.copy2(CANONICAL_SOURCE, db)
    con = sqlite3.connect(db)
    mold_before = con.execute('SELECT COUNT(*) FROM enj_kalip').fetchone()[0]
    con.close()

    r1 = mig.run(db)
    assert r1['ok'] is True
    r2 = mig.run(db)
    assert r2.get('skipped') is True

    con = sqlite3.connect(db)
    assert _col_names(con, 'enj_kalip') >= {'aktif_goz_sayisi', 'kapasite_onayli'}
    assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enj_kalip_seri'").fetchone()
    assert con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enj_kalip_seri_uye'").fetchone()
    mold_after = con.execute('SELECT COUNT(*) FROM enj_kalip').fetchone()[0]
    assert mold_before == mold_after
    assert con.execute('SELECT COUNT(*) FROM enj_kalip_seri').fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM enj_kalip_seri_uye').fetchone()[0] == 0
    reg = con.execute("SELECT version FROM schema_migrations WHERE version='191'").fetchone()
    assert reg is not None
    con.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_migration_blocks_canonical_without_flag(mig):
    from migrations._migration_db_guard import canonical_db_path, resolve_db_path
    with pytest.raises(PermissionError):
        resolve_db_path(canonical_db_path(), allow_canonical=False)


def test_migration_rollback_on_injected_failure(mig):
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('Canonical DB source yok')
    tmpdir = tempfile.mkdtemp(prefix='mig191_rb_')
    db = str(Path(tmpdir) / 'test.db')
    shutil.copy2(CANONICAL_SOURCE, db)
    with pytest.raises(RuntimeError):
        mig.run(db, _inject_failure=True)
    con = sqlite3.connect(db)
    assert not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enj_kalip_seri'").fetchone()
    reg = con.execute("SELECT version FROM schema_migrations WHERE version='191'").fetchone()
    assert reg is None
    con.close()
    shutil.rmtree(tmpdir, ignore_errors=True)
