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
