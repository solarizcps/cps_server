# -*- coding: utf-8 -*-
"""CPS single-instance startup guard regression tests."""
from __future__ import annotations

import contextlib
import importlib
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import tools.cps_single_instance as guard  # noqa: E402


def _reload_guard() -> None:
    importlib.reload(guard)


def _free_local_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture(autouse=True)
def _reset_guard_state():
    for port in list(guard._active_handles):
        guard.release_cps_single_instance(port)
    guard._fallback_held.clear()
    yield
    for port in list(guard._active_handles):
        guard.release_cps_single_instance(port)
    guard._fallback_held.clear()


def test_t1_port_empty_and_mutex_acquired():
    port = _free_local_port()
    guard.acquire_cps_single_instance_or_raise(port)
    assert port in guard._active_handles
    guard.release_cps_single_instance(port)
    assert port not in guard._active_handles


def test_t2_port_occupied_blocks_and_releases_mutex():
    port = _free_local_port()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(1)
    try:
        with pytest.raises(guard.CpsSingleInstanceError, match='already in use'):
            guard.acquire_cps_single_instance_or_raise(port)
        assert port not in guard._active_handles
    finally:
        listener.close()


def test_t3_second_mutex_acquire_blocks():
    port = _free_local_port()
    guard.acquire_cps_single_instance_or_raise(port)
    try:
        with pytest.raises(guard.CpsSingleInstanceError, match='mutex already held'):
            guard.acquire_cps_single_instance_or_raise(port)
    finally:
        guard.release_cps_single_instance(port)


def test_t4_reloader_child_skips_guard():
    port = _free_local_port()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(1)
    try:
        with patch.object(guard, 'is_reloader_child', return_value=True):
            guard.acquire_cps_single_instance_or_raise(port)
        assert port not in guard._active_handles
    finally:
        listener.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='WinAPI mutex failure injection')
def test_t5_mutex_creation_failure_fail_closed():
    port = _free_local_port()

    def _fail_mutex(_port: int) -> int:
        raise guard.CpsSingleInstanceError('CreateMutexW failed for test (winerror=5)')

    with patch.object(guard, '_acquire_mutex_windows', side_effect=_fail_mutex):
        with pytest.raises(guard.CpsSingleInstanceError, match='CreateMutexW failed'):
            guard.acquire_cps_single_instance_or_raise(port)
    assert port not in guard._active_handles


def test_t6_port_probe_refused_allows_unexpected_raises():
    port = _free_local_port()

    def _refused(_addr: tuple[str, int], _timeout: float) -> None:
        raise ConnectionRefusedError('refused')

    guard.acquire_cps_single_instance_or_raise(port, connect_fn=_refused)
    guard.release_cps_single_instance(port)

    def _weird(_addr: tuple[str, int], _timeout: float) -> None:
        raise OSError('probe exploded')

    with pytest.raises(guard.CpsSingleInstanceError, match='Port probe failed'):
        guard.acquire_cps_single_instance_or_raise(port, connect_fn=_weird)


def test_t7_different_ports_do_not_block_each_other():
    port_a = _free_local_port()
    port_b = _free_local_port()
    while port_b == port_a:
        port_b = _free_local_port()
    guard.acquire_cps_single_instance_or_raise(port_a)
    guard.acquire_cps_single_instance_or_raise(port_b)
    guard.release_cps_single_instance(port_a)
    guard.release_cps_single_instance(port_b)


def test_t8_import_safety_no_guard_on_import():
    _reload_guard()
    assert guard._active_handles == {}


def test_t9_live_8080_second_start_blocked_via_subprocess():
    if sys.platform != 'win32':
        pytest.skip('live 8080 subprocess check targets DESKTOP CPS host')
    script = f"""import sys
sys.path.insert(0, r'{APP}')
from tools.cps_single_instance import acquire_cps_single_instance_or_raise, CpsSingleInstanceError
try:
    acquire_cps_single_instance_or_raise(8080)
    raise SystemExit(0)
except CpsSingleInstanceError:
    raise SystemExit(42)
"""
    proc = subprocess.run(
        [sys.executable, '-c', script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 42, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    'env_setup,should_skip',
    [
        ({'WERKZEUG_RUN_MAIN': 'true'}, True),
        ({'WERKZEUG_RUN_MAIN': 'false'}, False),
        ({'WERKZEUG_RUN_MAIN': ''}, False),
        ({}, False),
    ],
)
def test_t10_reloader_env_variations(monkeypatch, env_setup, should_skip):
    port = _free_local_port()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(1)
    monkeypatch.delenv('WERKZEUG_RUN_MAIN', raising=False)
    for key, value in env_setup.items():
        monkeypatch.setenv(key, value)
    try:
        if should_skip:
            guard.acquire_cps_single_instance_or_raise(port)
            assert port not in guard._active_handles
        else:
            with pytest.raises(guard.CpsSingleInstanceError, match='already in use'):
                guard.acquire_cps_single_instance_or_raise(port)
    finally:
        listener.close()


def test_is_reloader_child_only_true_string():
    with patch.dict(os.environ, {'WERKZEUG_RUN_MAIN': 'true'}, clear=False):
        assert guard.is_reloader_child() is True
    with patch.dict(os.environ, {'WERKZEUG_RUN_MAIN': 'True'}, clear=False):
        assert guard.is_reloader_child() is False
    with patch.dict(os.environ, {'WERKZEUG_RUN_MAIN': 'false'}, clear=False):
        assert guard.is_reloader_child() is False
