# -*- coding: utf-8 -*-
"""ATP / planlama test guard — extends nexgen_tmp_db canonical write protection."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from tools.nexgen_tmp_db import (
    CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST,
    LiveDbWriteError,
    canonical_db_path,
    guard_is_active,
    install_live_db_write_guard,
    live_db_write_guard_stats,
    uninstall_live_db_write_guard,
)

_ATP_EXTRA: dict[str, Any] | None = None


def is_test_guard_enabled() -> bool:
    return os.environ.get('CPS_TEST_DB_GUARD', '').strip() == '1'


def resolve_path(path: str | os.PathLike[str]) -> str:
    """Canonical-safe path resolution for guard comparisons."""
    raw = os.fspath(path)
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(raw)))
    except OSError:
        return os.path.normcase(os.path.normpath(os.path.abspath(raw)))


def is_canonical_path(path: str | os.PathLike[str] | None) -> bool:
    if path is None:
        return False
    raw = str(path).strip()
    if not raw or raw == ':memory:':
        return False
    if raw.startswith('file:'):
        from urllib.parse import unquote, urlparse

        u = urlparse(raw)
        part = unquote(u.path)
        if os.name == 'nt' and part.startswith('/') and len(part) >= 3 and part[2] == ':':
            part = part[1:]
        raw = part
    return resolve_path(raw) == resolve_path(canonical_db_path())


def assert_not_canonical_path(path: str | os.PathLike[str], *, action: str = 'write') -> None:
    if is_canonical_path(path):
        raise LiveDbWriteError(
            f'{CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST}: {action} blocked for canonical DB. '
            f'attempted_path={path!r} live={canonical_db_path()!r}. '
            f'Use a unique temp DB via CPS_MOCK_DB_PATH.',
            attempted_path=str(path),
        )


def _forbidden_target_message(path: Any, action: str) -> str:
    return (
        f'{CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST}: {action} blocked for canonical DB. '
        f'attempted_path={path!r} live={canonical_db_path()!r}. '
        f'Canonical may be copy source only — never the destination.'
    )


def _guard_target(path: Any, action: str) -> None:
    if path is None:
        return
    if is_canonical_path(path):
        raise LiveDbWriteError(
            _forbidden_target_message(path, action),
            attempted_path=str(path),
        )


def install_atp_test_db_guard(live_path: str | None = None) -> dict[str, Any] | None:
    """Activate guard when CPS_TEST_DB_GUARD=1; extends nexgen sqlite/shutil hooks."""
    global _ATP_EXTRA
    if not is_test_guard_enabled():
        return None
    if _ATP_EXTRA is not None:
        return _ATP_EXTRA

    base = install_live_db_write_guard(live_path)
    live = base['live']

    real_replace = os.replace
    real_rename = os.rename
    real_path_rename = Path.rename
    real_path_replace = getattr(Path, 'replace', None)

    extra: dict[str, Any] = {
        'live': live,
        'blocked_replaces': 0,
        'real_replace': real_replace,
        'real_rename': real_rename,
        'real_path_rename': real_path_rename,
        'real_path_replace': real_path_replace,
    }

    def guarded_os_replace(src, dst, *args, **kwargs):
        _guard_target(dst, 'os.replace')
        return real_replace(src, dst, *args, **kwargs)

    def guarded_os_rename(src, dst, *args, **kwargs):
        _guard_target(dst, 'os.rename')
        return real_rename(src, dst, *args, **kwargs)

    def guarded_path_rename(self, target):
        _guard_target(target, 'Path.rename')
        return real_path_rename(self, target)

    os.replace = guarded_os_replace  # type: ignore[assignment]
    os.rename = guarded_os_rename  # type: ignore[assignment]
    Path.rename = guarded_path_rename  # type: ignore[assignment]

    if real_path_replace is not None:
        def guarded_path_replace(self, target):
            _guard_target(target, 'Path.replace')
            return real_path_replace(self, target)

        Path.replace = guarded_path_replace  # type: ignore[assignment]

    _ATP_EXTRA = extra
    return extra


def uninstall_atp_test_db_guard() -> None:
    global _ATP_EXTRA
    if _ATP_EXTRA is not None:
        os.replace = _ATP_EXTRA['real_replace']  # type: ignore[assignment]
        os.rename = _ATP_EXTRA['real_rename']  # type: ignore[assignment]
        Path.rename = _ATP_EXTRA['real_path_rename']  # type: ignore[assignment]
        if _ATP_EXTRA.get('real_path_replace') is not None:
            Path.replace = _ATP_EXTRA['real_path_replace']  # type: ignore[assignment]
        _ATP_EXTRA = None
    uninstall_live_db_write_guard()


def atp_guard_is_active() -> bool:
    return is_test_guard_enabled() and guard_is_active()


def guard_stats() -> dict[str, Any]:
    stats = live_db_write_guard_stats()
    stats['test_guard_enabled'] = is_test_guard_enabled()
    stats['atp_extra_active'] = _ATP_EXTRA is not None
    return stats


def create_empty_temp_db(*, prefix: str = 'atp_planlama_') -> tuple[str, str]:
    """Return (temp_dir, temp_db_path) with an empty SQLite file."""
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    temp_db = os.path.join(temp_dir, 'mock_data_test.db')
    con = sqlite3.connect(temp_db)
    con.close()
    assert_not_canonical_path(temp_db, action='create_empty_temp_db')
    return temp_dir, temp_db


def bind_temp_db_path(temp_db: str) -> str:
    """Set CPS_MOCK_DB_PATH + Config.MOCK_DB_PATH to a non-canonical temp DB."""
    assert_not_canonical_path(temp_db, action='bind_temp_db_path')
    resolved = resolve_path(temp_db)
    os.environ['CPS_MOCK_DB_PATH'] = resolved
    import config

    config.Config.MOCK_DB_PATH = resolved
    return resolved
