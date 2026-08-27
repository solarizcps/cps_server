# -*- coding: utf-8 -*-
"""CPS 8080 launcher — test env must not leak into production child process."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tools.cps_single_instance import CpsSingleInstanceError  # noqa: E402
from tools.cps_startup_env import (  # noqa: E402
    LAUNCH_ENV_KEYS,
    apply_cleared_launch_env,
    child_env_from_parent,
    ensure_port_free_for_launch,
    restore_launch_env,
    spawn_env_probe_command,
    startup_db_mode_log_line,
)

_TEMP_MOCK = r'C:\Users\EXAMPLE\AppData\Local\Temp\atp_probe_\mock_data_test.db'
_CANONICAL = r'C:\Solariz_CPS_SERVER\app\mock_data.db'


def _port8080_pids() -> list[int]:
    out = subprocess.check_output(['netstat', '-ano'], text=True, encoding='utf-8', errors='replace')
    pids: set[int] = set()
    for line in out.splitlines():
        if ':8080' in line and 'LISTENING' in line.upper():
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    return sorted(pids)


@pytest.fixture
def polluted_parent_env(monkeypatch):
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')
    monkeypatch.setenv('CPS_MOCK_DB_PATH', _TEMP_MOCK)
    monkeypatch.setenv('CPS_CANONICAL_DB_SOURCE', _CANONICAL)
    monkeypatch.setenv('FLASK_DEBUG', '1')
    yield


def test_t1_child_env_strips_cps_test_db_guard(polluted_parent_env):
    child = child_env_from_parent(os.environ)
    assert 'CPS_TEST_DB_GUARD' not in child


def test_t2_child_env_strips_cps_mock_db_path(polluted_parent_env):
    child = child_env_from_parent(os.environ)
    assert 'CPS_MOCK_DB_PATH' not in child


def test_t3_child_env_strips_cps_canonical_db_source(polluted_parent_env):
    child = child_env_from_parent(os.environ)
    assert 'CPS_CANONICAL_DB_SOURCE' not in child


def test_t4_child_env_flask_debug_zero(polluted_parent_env):
    child = child_env_from_parent(os.environ)
    assert child.get('FLASK_DEBUG') == '0'


def test_t5_parent_env_restored_after_launch_mutation(polluted_parent_env):
    saved = apply_cleared_launch_env()
    try:
        assert os.environ.get('CPS_TEST_DB_GUARD') is None
        assert os.environ.get('CPS_MOCK_DB_PATH') is None
        assert os.environ.get('CPS_CANONICAL_DB_SOURCE') is None
        assert os.environ.get('FLASK_DEBUG') == '0'
    finally:
        restore_launch_env(saved)
    assert os.environ.get('CPS_TEST_DB_GUARD') == '1'
    assert os.environ.get('CPS_MOCK_DB_PATH') == _TEMP_MOCK
    assert os.environ.get('CPS_CANONICAL_DB_SOURCE') == _CANONICAL
    assert os.environ.get('FLASK_DEBUG') == '1'


def test_t6_port_occupied_blocks_launch_without_starting_second_process():
    with patch('tools.cps_startup_env.port_is_listening', return_value=True):
        with pytest.raises(CpsSingleInstanceError, match='already in use'):
            ensure_port_free_for_launch(8080)


def test_t7_live_8080_pid_unchanged_after_launch_env_tests():
    before = _port8080_pids()
    assert before, 'expected live 8080 listener for host guard test'
    child = child_env_from_parent({
        'CPS_TEST_DB_GUARD': '1',
        'PATH': os.environ.get('PATH', ''),
    })
    proc = subprocess.run(
        spawn_env_probe_command(sys.executable),
        env=child,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert 'CPS_TEST_DB_GUARD' not in proc.stdout or "CPS_TEST_DB_GUARD=None" in proc.stdout
    after = _port8080_pids()
    assert before == after


def test_startup_db_mode_log_line_no_secrets(polluted_parent_env):
    line = startup_db_mode_log_line(str(APP))
    assert _TEMP_MOCK not in line
    assert _CANONICAL not in line
    assert 'test_guard=on' in line


def test_subprocess_probe_inherits_cleared_env_not_parent_pollution(polluted_parent_env):
    child = child_env_from_parent(os.environ)
    proc = subprocess.run(
        spawn_env_probe_command(sys.executable),
        env=child,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    for key in ('CPS_TEST_DB_GUARD', 'CPS_MOCK_DB_PATH', 'CPS_CANONICAL_DB_SOURCE'):
        assert f"{key}='1'" not in proc.stdout
        assert f'{key}={_TEMP_MOCK!r}' not in proc.stdout
    assert 'FLASK_DEBUG=\'0\'' in proc.stdout
