# -*- coding: utf-8 -*-
"""Standard bootstrap for ad-hoc test/browser scripts — DB + HTTP isolation."""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from tools.nexgen_tmp_db import (
    CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST,
    LiveDbWriteError,
    bootstrap_canonical_write_guard,
    browser_test_server_context,
    canonical_db_path,
    connect_sqlite,
    db_fingerprint,
    guard_is_active,
    install_live_db_write_guard,
    sha256_file,
    tmp_db_context,
    uninstall_live_db_write_guard,
)
from tools.test_db_http_guard import (
    LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST,
    LiveHttpWriteError,
    allow_http_base_url,
    http_guard_is_active,
    install_live_http_write_guard,
    uninstall_live_http_write_guard,
)

__all__ = [
    'CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST',
    'LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST',
    'LiveDbWriteError',
    'LiveHttpWriteError',
    'bootstrap_adhoc_script_guards',
    'bootstrap_canonical_write_guard',
    'browser_test_server_context',
    'browser_adhoc_context',
    'canonical_db_path',
    'connect_sqlite',
    'db_fingerprint',
    'guard_is_active',
    'http_guard_is_active',
    'install_live_db_write_guard',
    'install_live_http_write_guard',
    'ensure_adhoc_guard',
    'run_adhoc_with_tmp_db',
    'run_guarded_subprocess',
    'sha256_file',
    'subprocess_isolation_env',
    'tmp_db_context',
    'uninstall_all_test_guards',
    'uninstall_live_db_write_guard',
    'uninstall_live_http_write_guard',
]


def uninstall_all_test_guards() -> None:
    uninstall_live_http_write_guard()
    uninstall_live_db_write_guard()


def bootstrap_adhoc_script_guards(
    script_path: str | None = None,
    *,
    allow_http_bases: tuple[str, ...] = (),
    live_port: int = 8080,
) -> str:
    """SQLite + HTTP guards for _test_* / _browser_* scripts."""
    live = bootstrap_canonical_write_guard()
    install_live_http_write_guard(live_port=live_port, allowed_base_urls=allow_http_bases)
    return live


def ensure_adhoc_guard(live_path: str | None = None) -> str:
    return bootstrap_adhoc_script_guards()


def subprocess_isolation_env(
    *,
    tmp_db: str | None = None,
    isolated_base_url: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Env bundle for guarded child _test_* subprocesses."""
    env = dict(os.environ)
    env['CPS_TEST_DB_GUARD'] = '1'
    env['CPS_ADHOC_AUTO_GUARD'] = '1'
    if tmp_db:
        env['CPS_MOCK_DB_PATH'] = os.path.abspath(tmp_db)
    if isolated_base_url:
        base = isolated_base_url.rstrip('/')
        env['CPS_ISOLATED_BASE_URL'] = base
        env['CPS_ALLOW_HTTP_BASE'] = base
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def run_guarded_subprocess(
    cmd: Sequence[str],
    *,
    cwd: str | None = None,
    tmp_db: str | None = None,
    isolated_base_url: str | None = None,
    env_extra: Mapping[str, str] | None = None,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    tmp = tmp_db or (env_extra or {}).get('CPS_MOCK_DB_PATH')
    base = isolated_base_url or (env_extra or {}).get('CPS_ISOLATED_BASE_URL')
    env = subprocess_isolation_env(tmp_db=tmp, isolated_base_url=base, extra=env_extra)
    return subprocess.run(
        list(cmd),
        cwd=cwd,
        env=env,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
    )


def _apply_env_http_allowlist() -> None:
    allow = os.environ.get('CPS_ALLOW_HTTP_BASE', '').strip()
    if not allow:
        return
    if not http_guard_is_active():
        bootstrap_adhoc_script_guards()
    allow_http_base_url(allow)


def _apply_env_tmp_db_path() -> str | None:
    tmp = os.environ.get('CPS_MOCK_DB_PATH', '').strip()
    if not tmp:
        return None
    import config as _cfg

    _cfg.Config.MOCK_DB_PATH = os.path.abspath(tmp)
    return _cfg.Config.MOCK_DB_PATH


def _autostart_from_env() -> None:
    flag = os.environ.get('CPS_TEST_DB_GUARD', '').strip().lower()
    if flag in ('1', 'true', 'yes', 'on') and not guard_is_active():
        bootstrap_adhoc_script_guards()
    _apply_env_http_allowlist()
    _apply_env_tmp_db_path()


def _autostart_if_adhoc_script() -> None:
    if os.environ.get('CPS_ADHOC_AUTO_GUARD', '1').strip().lower() in ('0', 'false', 'no'):
        return
    argv0 = sys.argv[0] if sys.argv else ''
    base = os.path.basename(argv0)
    if not (base.startswith('_test_') or base.startswith('_browser_')):
        return
    if guard_is_active() and http_guard_is_active():
        return
    bootstrap_adhoc_script_guards(argv0)


@contextmanager
def run_adhoc_with_tmp_db(
    live_path: str | None = None,
    *,
    prefix: str = 'adhoc_',
) -> Iterator[dict[str, Any]]:
    live = bootstrap_adhoc_script_guards(live_path)
    with tmp_db_context(live, prefix=prefix) as info:
        yield info


@contextmanager
def browser_adhoc_context(
    live_path: str | None = None,
    *,
    prefix: str = 'browser_adhoc_',
) -> Iterator[dict[str, Any]]:
    """Isolated Flask + temp DB; allows HTTP writes only to isolated base_url."""
    live = canonical_db_path(live_path)
    bootstrap_adhoc_script_guards(live)
    with browser_test_server_context(live_db=live, prefix=prefix) as srv:
        allow_http_base_url(srv['base_url'])
        srv['canonical_db'] = live
        yield srv


_autostart_from_env()
_autostart_if_adhoc_script()
