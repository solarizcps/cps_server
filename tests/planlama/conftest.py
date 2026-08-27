# -*- coding: utf-8 -*-
"""Conftest for tests/planlama — sys.path, Google dummy key, ATP DB write guard."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

# repo_root/app
_APP_DIR = str(Path(__file__).resolve().parents[2] / 'app')
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# Ensure a dummy Google key is present so UNCONFIGURED is not raised at import time.
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_DUMMY_KEY_conftest_00000000000000')

from tools.atp_test_db_guard import (  # noqa: E402
    bind_temp_db_path,
    create_empty_temp_db,
    install_atp_test_db_guard,
    is_canonical_path,
    uninstall_atp_test_db_guard,
)


@pytest.fixture(scope='session', autouse=True)
def atp_planlama_db_guard_session():
    """Session guard: block canonical writes; bind unique temp CPS_MOCK_DB_PATH."""
    saved = {
        'CPS_TEST_DB_GUARD': os.environ.get('CPS_TEST_DB_GUARD'),
        'CPS_MOCK_DB_PATH': os.environ.get('CPS_MOCK_DB_PATH'),
    }
    import config

    saved['Config_MOCK_DB_PATH'] = config.Config.MOCK_DB_PATH

    existing_mock = (saved['CPS_MOCK_DB_PATH'] or '').strip()
    if existing_mock and is_canonical_path(existing_mock):
        pytest.fail(
            f'CPS_MOCK_DB_PATH already points to canonical before tests: {existing_mock!r}'
        )

    os.environ['CPS_TEST_DB_GUARD'] = '1'
    install_atp_test_db_guard()

    temp_dir, temp_db = create_empty_temp_db(prefix='atp_planlama_pytest_')
    bind_temp_db_path(temp_db)

    ctx = {'temp_dir': temp_dir, 'temp_db': temp_db}
    try:
        yield ctx
    finally:
        config.Config.MOCK_DB_PATH = saved['Config_MOCK_DB_PATH']
        if saved['CPS_MOCK_DB_PATH'] is None:
            os.environ.pop('CPS_MOCK_DB_PATH', None)
        else:
            os.environ['CPS_MOCK_DB_PATH'] = saved['CPS_MOCK_DB_PATH']

        if saved['CPS_TEST_DB_GUARD'] is None:
            os.environ.pop('CPS_TEST_DB_GUARD', None)
        else:
            os.environ['CPS_TEST_DB_GUARD'] = saved['CPS_TEST_DB_GUARD']

        uninstall_atp_test_db_guard()
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope='session', autouse=True)
def atp_temp_db_session(atp_planlama_db_guard_session):  # noqa: PT004
    """Override app/conftest.py heavy temp-db copy — planlama uses ATP guard instead."""
    return atp_planlama_db_guard_session
