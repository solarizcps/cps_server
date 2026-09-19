# -*- coding: utf-8 -*-
"""R2 — production canonical DB guard (fail-closed, symlink-safe, no production pytest)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tools.atp_test_db_guard import (  # noqa: E402
    assert_not_production_canonical_path,
    bind_temp_db_path,
    is_production_canonical_path,
    production_canonical_db_path,
    resolve_path,
)
from tools.nexgen_tmp_db import CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST, LiveDbWriteError  # noqa: E402

_PROD = production_canonical_db_path()


def test_production_canonical_path_is_fixed_solariz_server():
    assert _PROD.endswith('mock_data.db')
    assert 'solariz_cps_server' in _PROD.replace('/', '\\').lower()


def test_bind_temp_db_rejects_production_canonical():
    with pytest.raises(LiveDbWriteError) as exc:
        bind_temp_db_path(_PROD)
    assert CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST in str(exc.value)


def test_assert_not_production_blocks_unlink_target():
    with pytest.raises(LiveDbWriteError):
        assert_not_production_canonical_path(_PROD, action='unlink')


@pytest.mark.skipif(not Path(_PROD).is_file(), reason='production DB not present on this machine')
def test_resolved_mock_equals_production_is_detected():
    variant = _PROD
    if os.name == 'nt':
        # Mixed-case path string still resolves to production.
        parts = variant.split('\\')
        parts[-1] = parts[-1].swapcase() if parts[-1].lower() == 'mock_data.db' else parts[-1]
        variant = '\\'.join(parts)
    assert is_production_canonical_path(variant)
    assert resolve_path(variant) == _PROD


def test_temp_db_under_tmp_is_not_production():
    temp_dir = tempfile.mkdtemp(prefix='atp_guard_r2_')
    temp_db = str(Path(temp_dir) / 'mock_data_test.db')
    sqlite3.connect(temp_db).close()
    assert not is_production_canonical_path(temp_db)
    assert resolve_path(temp_db) != _PROD


def test_subprocess_pytest_fails_when_mock_points_to_production():
    """Session guard must abort before any test DB mutation."""
    if not Path(_PROD).is_file():
        pytest.skip('production DB absent')
    env = os.environ.copy()
    env['CPS_MOCK_DB_PATH'] = _PROD
    env['CPS_TEST_DB_GUARD'] = '1'
    env['CPS_CANONICAL_DB_SOURCE'] = _PROD
    env['GOOGLE_ROUTES_API_KEY'] = env.get(
        'GOOGLE_ROUTES_API_KEY', 'TEST_DUMMY_KEY_guard_r2_00000000000000',
    )
    cmd = [
        sys.executable, '-m', 'pytest',
        str(ROOT / 'tests' / 'planlama' / 'test_atp_emergency_route_priority_v1.py::test_one_emergency_first_even_if_last_in_list'),
        '-q', '--tb=no',
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    combined = ((proc.stdout or '') + (proc.stderr or '')).lower()
    assert (
        'production canonical' in combined
        or 'canonical before tests' in combined
        or 'cps_mock_db_path' in combined
        or 'blocked for production' in combined
        or 'error' in combined
    )
