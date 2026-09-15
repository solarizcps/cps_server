# -*- coding: utf-8 -*-
"""tests/ — global ATP canonical DB guard for all pytest subtrees."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_DIR = _REPO_ROOT / 'app'
_PLANLAMA_S = str(_REPO_ROOT / 'tests' / 'planlama')
for _p in (str(_APP_DIR), _PLANLAMA_S):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atp_canonical_forensic import classify_drift, diff_logical, forensic_report  # noqa: E402
from tools.atp_test_db_guard import (  # noqa: E402
    bind_temp_db_path,
    create_empty_temp_db,
    guard_stats,
    install_atp_test_db_guard,
    is_canonical_path,
    uninstall_atp_test_db_guard,
)

_CANONICAL_DB = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
)).resolve()
os.environ.setdefault('CPS_CANONICAL_DB_SOURCE', str(_CANONICAL_DB))
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_DUMMY_KEY_conftest_00000000000000')


@pytest.fixture(scope='session')
def canonical_db_path_session() -> str:
    if not _CANONICAL_DB.is_file() or _CANONICAL_DB.stat().st_size < 1024:
        pytest.fail(f'canonical DB missing or truncated: {_CANONICAL_DB}')
    return str(_CANONICAL_DB)


@pytest.fixture(scope='session')
def canonical_forensic_before(canonical_db_path_session: str):
    return forensic_report(canonical_db_path_session, guard_stats())


@pytest.fixture(scope='session', autouse=True)
def atp_global_db_guard_session(canonical_forensic_before):
    """Session guard for tests/planlama + tests/tools combined runs."""
    saved = {
        'CPS_TEST_DB_GUARD': os.environ.get('CPS_TEST_DB_GUARD'),
        'CPS_MOCK_DB_PATH': os.environ.get('CPS_MOCK_DB_PATH'),
        'CPS_CANONICAL_DB_SOURCE': os.environ.get('CPS_CANONICAL_DB_SOURCE'),
        'CPS_ATP_TEST_SKIP_FILOM': os.environ.get('CPS_ATP_TEST_SKIP_FILOM'),
        'cwd': os.getcwd(),
    }
    import config

    saved['Config_MOCK_DB_PATH'] = config.Config.MOCK_DB_PATH

    existing_mock = (saved['CPS_MOCK_DB_PATH'] or '').strip()
    if existing_mock and is_canonical_path(existing_mock):
        pytest.fail(
            f'CPS_MOCK_DB_PATH already points to canonical before tests: {existing_mock!r}'
        )

    os.environ['CPS_CANONICAL_DB_SOURCE'] = str(_CANONICAL_DB)
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    install_atp_test_db_guard(str(_CANONICAL_DB))

    temp_dir, temp_db = create_empty_temp_db(prefix='atp_pytest_global_')
    bind_temp_db_path(temp_db)

    ctx = {
        'temp_dir': temp_dir,
        'temp_db': temp_db,
        'canonical_before': canonical_forensic_before,
    }
    try:
        yield ctx
    finally:
        canonical_after = forensic_report(str(_CANONICAL_DB), guard_stats())
        drift = diff_logical(
            canonical_forensic_before['logical'],
            canonical_after['logical'],
        )
        root_cause = classify_drift(drift)
        ctx['canonical_after'] = canonical_after
        ctx['drift'] = drift
        ctx['drift_root_cause'] = root_cause

        if root_cause == 'ATP_OR_OTHER_TEST_WRITE':
            pytest.fail(
                'Canonical ATP tables changed during pytest session: '
                f'{drift["atp_tables_changed"]!r}'
            )

        import config

        config.Config.MOCK_DB_PATH = saved['Config_MOCK_DB_PATH']
        for key in (
            'CPS_MOCK_DB_PATH',
            'CPS_TEST_DB_GUARD',
            'CPS_CANONICAL_DB_SOURCE',
            'CPS_ATP_TEST_SKIP_FILOM',
        ):
            val = saved.get(key)
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        os.chdir(str(_REPO_ROOT))

        uninstall_atp_test_db_guard()
        shutil.rmtree(temp_dir, ignore_errors=True)
