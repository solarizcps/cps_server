# -*- coding: utf-8 -*-
"""Temp DB isolation for release-history Flask route tests."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

APP = Path(__file__).resolve().parents[2] / "app"
CANONICAL_DB = APP / "mock_data.db"

_SESSION_GUARD_ACTIVE = False
_SESSION_SHA_BEFORE: str | None = None
_SESSION_MTIME_BEFORE: float | None = None
_SESSION_TEMP_DIR: str | None = None
_SESSION_TEMP_DB: str | None = None


@contextmanager
def session_canonical_guard() -> Iterator[dict]:
    """Install guard + one session temp DB for all route tests in a pytest session."""
    global _SESSION_GUARD_ACTIVE, _SESSION_SHA_BEFORE, _SESSION_MTIME_BEFORE
    global _SESSION_TEMP_DIR, _SESSION_TEMP_DB

    if not CANONICAL_DB.is_file():
        yield {"active": False, "canonical_present": False}
        return

    from tools.atp_test_db_guard import bind_temp_db_path, install_atp_test_db_guard, uninstall_atp_test_db_guard
    from tools.nexgen_tmp_db import sha256_file

    _SESSION_SHA_BEFORE = sha256_file(str(CANONICAL_DB))
    _SESSION_MTIME_BEFORE = CANONICAL_DB.stat().st_mtime
    os.environ["CPS_TEST_DB_GUARD"] = "1"
    install_atp_test_db_guard(str(CANONICAL_DB))
    _SESSION_TEMP_DIR = tempfile.mkdtemp(prefix="cps_rh_session_")
    _SESSION_TEMP_DB = os.path.join(_SESSION_TEMP_DIR, "mock_data_session.db")
    shutil.copy2(CANONICAL_DB, _SESSION_TEMP_DB)
    bind_temp_db_path(_SESSION_TEMP_DB)

    from release_history_test_guard import assert_temp_db_bound

    assert_temp_db_bound()
    _SESSION_GUARD_ACTIVE = True
    info = {
        "active": True,
        "canonical_present": True,
        "temp_dir": _SESSION_TEMP_DIR,
        "temp_db": _SESSION_TEMP_DB,
        "sha_before": _SESSION_SHA_BEFORE,
        "mtime_before": _SESSION_MTIME_BEFORE,
    }
    try:
        yield info
    finally:
        sha_after = sha256_file(str(CANONICAL_DB))
        mtime_after = CANONICAL_DB.stat().st_mtime
        uninstall_atp_test_db_guard()
        if _SESSION_TEMP_DIR:
            shutil.rmtree(_SESSION_TEMP_DIR, ignore_errors=True)
        _SESSION_TEMP_DIR = None
        _SESSION_TEMP_DB = None
        _SESSION_GUARD_ACTIVE = False
        if os.environ.get("CPS_MOCK_DB_PATH") is not None:
            os.environ.pop("CPS_MOCK_DB_PATH", None)
        if os.environ.get("CPS_TEST_DB_GUARD") == "1":
            os.environ.pop("CPS_TEST_DB_GUARD", None)
        if sha_after != _SESSION_SHA_BEFORE:
            raise AssertionError(
                "canonical DB SHA changed during release-history route test session: "
                f"before={_SESSION_SHA_BEFORE} after={sha_after}"
            )
        if mtime_after != _SESSION_MTIME_BEFORE:
            raise AssertionError(
                "canonical DB mtime changed during release-history route test session: "
                f"before={_SESSION_MTIME_BEFORE} after={mtime_after}"
            )


@contextmanager
def isolated_route_db(*, prefix: str = "cps_rh_route_") -> Iterator[dict]:
    """Verify session temp DB binding; per-test canonical SHA must stay stable."""
    if not CANONICAL_DB.is_file():
        yield {"active": False, "canonical_present": False}
        return

    from tools.atp_test_db_guard import is_canonical_path

    import config

    if not _SESSION_GUARD_ACTIVE or not _SESSION_TEMP_DB:
        raise RuntimeError(
            "session_canonical_guard must be active before route_db_isolation."
        )

    from release_history_test_guard import assert_port_8080_closed, assert_temp_db_bound

    assert_port_8080_closed()
    assert_temp_db_bound()
    if is_canonical_path(config.Config.MOCK_DB_PATH):
        raise RuntimeError(
            f"Route test must not bind canonical DB (path={config.Config.MOCK_DB_PATH!r})."
        )
    if os.path.normcase(os.path.normpath(config.Config.MOCK_DB_PATH)) != os.path.normcase(
        os.path.normpath(_SESSION_TEMP_DB)
    ):
        from tools.atp_test_db_guard import bind_temp_db_path

        bind_temp_db_path(_SESSION_TEMP_DB)

    info = {
        "active": True,
        "canonical_present": True,
        "temp_dir": _SESSION_TEMP_DIR,
        "temp_db": _SESSION_TEMP_DB,
    }
    yield info
