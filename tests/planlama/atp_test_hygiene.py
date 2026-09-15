# -*- coding: utf-8 -*-
"""ATP planlama test process hygiene — cwd/env restore helpers."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'

_ENV_KEYS = (
    'CPS_MOCK_DB_PATH',
    'CPS_TEST_DB_GUARD',
    'CPS_ATP_TEST_SKIP_FILOM',
)


def repo_root() -> Path:
    return _REPO_ROOT


def app_dir() -> Path:
    return _APP_DIR


def ensure_app_on_syspath() -> None:
    app_s = str(_APP_DIR)
    if app_s not in sys.path:
        sys.path.insert(0, app_s)


def capture_env_state() -> dict[str, Any]:
    import config

    return {
        'cwd': str(_REPO_ROOT),
        'env': {k: os.environ.get(k) for k in _ENV_KEYS},
        'Config_MOCK_DB_PATH': config.Config.MOCK_DB_PATH,
    }


def restore_env_state(saved: dict[str, Any]) -> None:
    import config

    try:
        os.chdir(saved['cwd'])
    except OSError:
        os.chdir(str(_REPO_ROOT))

    for key, value in saved['env'].items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    config.Config.MOCK_DB_PATH = saved['Config_MOCK_DB_PATH']


@contextmanager
def isolated_env(**overrides: str | None) -> Iterator[None]:
    saved = capture_env_state()
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        restore_env_state(saved)


@contextmanager
def restore_cwd_on_exit() -> Iterator[None]:
    saved = os.getcwd()
    try:
        yield
    finally:
        try:
            os.chdir(saved)
        except OSError:
            os.chdir(str(_REPO_ROOT))
