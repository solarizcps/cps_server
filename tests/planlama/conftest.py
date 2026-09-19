# -*- coding: utf-8 -*-
"""Conftest for tests/planlama — sys.path, Google dummy key, hygiene fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
_PLANLAMA_S = str(_REPO_ROOT / 'tests' / 'planlama')
for _p in (_APP_S := str(_APP_DIR), _PLANLAMA_S):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atp_test_hygiene import capture_env_state, restore_env_state

_CANONICAL_DB = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
)).resolve()
os.environ.setdefault('CPS_CANONICAL_DB_SOURCE', str(_CANONICAL_DB))

# repo_root/app on sys.path — never rely on os.chdir(app)

# Ensure a dummy Google key is present so UNCONFIGURED is not raised at import time.
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_DUMMY_KEY_conftest_00000000000000')


@pytest.fixture(autouse=True)
def atp_restore_process_hygiene(request):
    """Per-test cwd + env restore (success and exception paths)."""
    saved = capture_env_state()
    yield
    restore_env_state(saved)
    try:
        os.chdir(saved['cwd'])
    except OSError:
        os.chdir(str(_REPO_ROOT))

    if request.node is not None:
        request.node._atp_cwd_restored = os.getcwd() == saved['cwd']


@pytest.fixture(autouse=True)
def atp_restore_cwd_to_repo_root():
    """Force repo root cwd after each test — defeats import-time os.chdir(APP) pollution."""
    yield
    os.chdir(str(_REPO_ROOT))


@pytest.fixture(autouse=True)
def atp_reset_google_route_options_app_cache():
    """Mehmet tests reload routes; reset cached minimal Flask app in route-options tests."""
    yield
    for mod in list(sys.modules.values()):
        if getattr(mod, '__file__', '') and mod.__file__ and mod.__file__.endswith(
            'test_google_route_options_api.py',
        ):
            if hasattr(mod, '_APP'):
                mod._APP = None
            if hasattr(mod, '_APP_CLIENT'):
                mod._APP_CLIENT = None


@pytest.fixture(autouse=True)
def atp_ensure_repo_cwd():
    """Start each test from repo root so combined collection order cannot leak app/ cwd."""
    os.chdir(str(_REPO_ROOT))
    yield


@pytest.fixture(autouse=True)
def atp_worktree_canonical_leak_guard():
    """Remove stray worktree test DB copies only — never production canonical mock_data.db."""
    from tools.atp_test_db_guard import (
        is_canonical_path,
        is_production_canonical_path,
        is_test_guard_enabled,
    )

    wt = _APP_DIR / 'mock_data.db'

    def _maybe_unlink() -> None:
        if not wt.is_file():
            return
        if is_production_canonical_path(wt):
            return
        if is_test_guard_enabled() and is_canonical_path(wt):
            return
        if is_canonical_path(wt):
            return
        wt.unlink()

    _maybe_unlink()
    yield
    _maybe_unlink()


@pytest.fixture(autouse=True)
def atp_restore_auth_and_routes():
    """Restore modules.auth + arac_takip_routes after tests that patch yetki_* globals."""
    yield
    import importlib

    import modules.auth as auth_mod

    importlib.reload(auth_mod)
    try:
        import modules.planlama.arac_takip_routes as routes_mod

        importlib.reload(routes_mod)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def atp_rebind_stale_mock_db(atp_temp_db_session):
    """Re-bind session temp DB when a prior module left a deleted CPS_MOCK_DB_PATH."""
    from tools.atp_test_db_guard import bind_temp_db_path

    def _rebind_if_stale() -> None:
        import config

        mock = config.Config.MOCK_DB_PATH
        if mock and not Path(str(mock)).is_file():
            bind_temp_db_path(atp_temp_db_session['temp_db'])

    _rebind_if_stale()
    yield
    _rebind_if_stale()


@pytest.fixture(scope='session')
def atp_planlama_db_guard_session(atp_global_db_guard_session):
    """Alias for ATP R04/R07 tests — uses root tests/conftest session guard."""
    return atp_global_db_guard_session


@pytest.fixture(scope='session')
def atp_temp_db_session(atp_planlama_db_guard_session):
    return atp_planlama_db_guard_session
