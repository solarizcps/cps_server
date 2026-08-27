# -*- coding: utf-8 -*-
"""Legacy canonical writer guard — static + integration regression."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
CANONICAL = APP / 'mock_data.db'

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tools.nexgen_tmp_db import LiveDbWriteError, canonical_db_path  # noqa: E402

LEGACY_SCRIPTS = {
    'db_test_seed': ROOT / '_db_test_seed.py',
    'faz5c3': ROOT / '_test_faz5c3_kullanilabilir_stok.py',
    'renk': ROOT / '_test_renk_merkezi_canli1.py',
}

FORBIDDEN_CANONICAL_TARGET_PATTERNS = [
    re.compile(r'shutil\.copy2\s*\(\s*_REG_BAK\s*,\s*DB\s*\)', re.I),
    re.compile(r'shutil\.copy2\s*\(\s*TEMP_DB\s*,\s*orig_db', re.I),
    re.compile(r'shutil\.copy2\s*\(\s*bak_db\s*,\s*orig_db', re.I),
    re.compile(r'shutil\.copy2\s*\(\s*orig_db\s*,\s*bak_db', re.I),
    re.compile(r'C:\\\\Solariz_CPS_SERVER\\\\app\\\\mock_data\.db'),
    re.compile(r"r['\"]C:\\\\Solariz_CPS_SERVER\\\\app\\\\mock_data\.db['\"]"),
    re.compile(r"join\([^)]*['\"]mock_data\.db['\"]\)\s*\n\s*shutil\.copy2\([^)]*,\s*DB", re.I),
]

REQUIRED_PATTERNS = [
    (re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]"), 'safe entry point'),
    (re.compile(r'def\s+main\s*\('), 'main()'),
    (re.compile(r'CPS_TEST_DB_GUARD'), 'CPS_TEST_DB_GUARD'),
    (re.compile(r'run_adhoc_with_tmp_db|bootstrap_adhoc_script_guards'), 'guard bootstrap helper'),
]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical_fingerprint() -> dict:
    uri = 'file:' + str(CANONICAL).replace('\\', '/') + '?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    stats = {}
    for t in ('arac_gunluk_plan', 'arac_gunluk_plan_is', 'arac_is_talebi', 'arac_kayitli_yer'):
        stats[t] = {
            'count': con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0],
            'max_id': con.execute(f'SELECT MAX(id) FROM {t}').fetchone()[0],
        }
    con.close()
    with open(CANONICAL, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    return {'integrity': ic, 'stats': stats, 'sha256': sha}


@pytest.fixture(scope='module')
def canonical_before() -> dict:
    return _canonical_fingerprint()


@pytest.mark.parametrize('key', list(LEGACY_SCRIPTS.keys()))
def test_legacy_script_has_safe_entry_and_guard(key: str):
    text = LEGACY_SCRIPTS[key].read_text(encoding='utf-8')
    for pattern, label in REQUIRED_PATTERNS:
        assert pattern.search(text), f'{key}: missing {label}'


@pytest.mark.parametrize('key', list(LEGACY_SCRIPTS.keys()))
def test_legacy_script_no_canonical_restore_swap_patterns(key: str):
    text = LEGACY_SCRIPTS[key].read_text(encoding='utf-8')
    for pattern in FORBIDDEN_CANONICAL_TARGET_PATTERNS:
        assert not pattern.search(text), f'{key}: forbidden pattern {pattern.pattern}'


@pytest.mark.parametrize('key', list(LEGACY_SCRIPTS.keys()))
def test_legacy_script_guard_bootstrap_before_app_import(key: str):
    text = LEGACY_SCRIPTS[key].read_text(encoding='utf-8')
    guard_idx = text.find('CPS_TEST_DB_GUARD')
    app_idx = text.find('import app')
    if app_idx >= 0:
        assert guard_idx >= 0 and guard_idx < app_idx, f'{key}: guard must precede import app'


def test_db_test_seed_blocks_canonical_path(canonical_before):
    mod = _load_module(LEGACY_SCRIPTS['db_test_seed'], 'db_test_seed_guard_test')
    canonical = str(canonical_db_path())
    with pytest.raises((LiveDbWriteError, RuntimeError, SystemExit, ValueError)):
        mod.main(canonical)


def test_db_test_seed_blocks_canonical_argv(canonical_before):
    before = _canonical_fingerprint()
    proc = subprocess.run(
        [sys.executable, str(LEGACY_SCRIPTS['db_test_seed']), str(CANONICAL)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    after = _canonical_fingerprint()
    assert after['sha256'] == before['sha256']


def test_faz5c3_subprocess_env_carries_guard(canonical_before):
    text = LEGACY_SCRIPTS['faz5c3'].read_text(encoding='utf-8')
    assert 'run_guarded_subprocess' in text
    assert 'CPS_TEST_DB_GUARD' in text
    assert 'tmp_db=db' in text or 'tmp_db=DB' in text


def test_renk_no_canonical_swap_in_source(canonical_before):
    text = LEGACY_SCRIPTS['renk'].read_text(encoding='utf-8')
    assert 'orig_db' not in text
    assert '.canli1bak' not in text
    assert 'REAL_DB' not in text or 'temp_db' in text


@pytest.mark.parametrize(
    'script_name',
    ['_test_renk_merkezi_canli1.py'],
)
def test_legacy_script_smoke_does_not_change_canonical(script_name: str, canonical_before):
    before = _canonical_fingerprint()
    env = os.environ.copy()
    env['CPS_TEST_DB_GUARD'] = '1'
    proc = subprocess.run(
        [sys.executable, str(ROOT / script_name)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    after = _canonical_fingerprint()
    assert after['sha256'] == before['sha256'], 'canonical SHA changed during smoke'
    assert after['stats'] == before['stats'], 'canonical ATP counts changed during smoke'
    assert proc.returncode in (0, 1), proc.stdout[-2000:] + proc.stderr[-2000:]
