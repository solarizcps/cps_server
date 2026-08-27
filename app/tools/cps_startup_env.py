# -*- coding: utf-8 -*-
"""CPS production launcher environment — strip test DB guard vars from child process."""
from __future__ import annotations

import os
import socket
from typing import Mapping, MutableMapping

from tools.cps_single_instance import CpsSingleInstanceError

# Vars that must never reach a production CPS HTTP child when parent ran pytest.
TEST_ENV_KEYS: tuple[str, ...] = (
    'CPS_TEST_DB_GUARD',
    'CPS_MOCK_DB_PATH',
    'CPS_CANONICAL_DB_SOURCE',
)

LAUNCH_ENV_KEYS: tuple[str, ...] = TEST_ENV_KEYS + ('FLASK_DEBUG',)


def capture_launch_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    """Snapshot selected process env keys before launcher mutation."""
    src = env if env is not None else os.environ
    return {key: src.get(key) for key in LAUNCH_ENV_KEYS}


def clear_test_env(target: MutableMapping[str, str] | None = None) -> MutableMapping[str, str]:
    """Remove test guard redirection; force FLASK_DEBUG=0 on target mapping."""
    out = dict(target if target is not None else os.environ)
    for key in TEST_ENV_KEYS:
        out.pop(key, None)
    out['FLASK_DEBUG'] = '0'
    return out


def apply_cleared_launch_env(target: MutableMapping[str, str] | None = None) -> dict[str, str | None]:
    """Clear test env on process mapping; return saved snapshot for restore."""
    saved = capture_launch_env(target)
    mapping = target if target is not None else os.environ
    cleared = clear_test_env(mapping)
    if target is None:
        for key in list(os.environ.keys()):
            if key in TEST_ENV_KEYS:
                del os.environ[key]
        os.environ['FLASK_DEBUG'] = '0'
    else:
        mapping.clear()
        mapping.update(cleared)
    return saved


def restore_launch_env(saved: dict[str, str | None], target: MutableMapping[str, str] | None = None) -> None:
    """Restore launcher snapshot onto process or explicit mapping."""
    mapping = target if target is not None else os.environ
    for key in LAUNCH_ENV_KEYS:
        val = saved.get(key)
        if val is None:
            mapping.pop(key, None)
            if target is None:
                os.environ.pop(key, None)
        else:
            mapping[key] = val
            if target is None:
                os.environ[key] = val


def child_env_from_parent(parent: Mapping[str, str]) -> dict[str, str]:
    """Build child process env dict — test guard vars stripped, FLASK_DEBUG=0."""
    return clear_test_env(dict(parent))


def startup_db_mode_log_line(app_dir: str | None = None) -> str:
    """Safe startup log line — basename only, no secrets."""
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    default_app = os.path.dirname(tools_dir)
    base = app_dir or default_app
    db_name = 'mock_data.db'
    guard = os.environ.get('CPS_TEST_DB_GUARD', '')
    mock_override = (os.environ.get('CPS_MOCK_DB_PATH') or '').strip()
    if mock_override:
        db_name = os.path.basename(mock_override)
        mode = 'temp-override'
    else:
        mode = 'mock-default'
    guard_state = 'on' if guard == '1' else 'off'
    return f'CPS DB mode={mode} file={db_name} test_guard={guard_state} app={os.path.basename(base)}'


def port_is_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def ensure_port_free_for_launch(port: int = 8080, host: str = '127.0.0.1') -> None:
    """Refuse launcher start when TCP port already accepts connections."""
    if port_is_listening(host, port):
        raise CpsSingleInstanceError(
            f'Port {host}:{port} already in use — refusing to start a second CPS instance'
        )


def spawn_env_probe_command(python_exe: str) -> list[str]:
    """Harmless child that prints effective guard env (for launcher regression)."""
    code = (
        'import os;'
        'keys=("CPS_TEST_DB_GUARD","CPS_MOCK_DB_PATH","CPS_CANONICAL_DB_SOURCE","FLASK_DEBUG");'
        'print("|".join(f"{k}={os.environ.get(k)!r}" for k in keys))'
    )
    return [python_exe, '-c', code]
