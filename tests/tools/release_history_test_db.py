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


@contextmanager
def isolated_route_db(*, prefix: str = "cps_rh_route_") -> Iterator[dict]:
    """Copy canonical DB to a temp path and bind CPS_MOCK_DB_PATH for guarded tests."""
    if not CANONICAL_DB.is_file():
        yield {"active": False, "canonical_present": False}
        return

    from tools.atp_test_db_guard import (
        bind_temp_db_path,
        install_atp_test_db_guard,
        uninstall_atp_test_db_guard,
    )
    from tools.nexgen_tmp_db import sha256_file

    import config

    saved = {
        "CPS_TEST_DB_GUARD": os.environ.get("CPS_TEST_DB_GUARD"),
        "CPS_MOCK_DB_PATH": os.environ.get("CPS_MOCK_DB_PATH"),
        "Config_MOCK_DB_PATH": config.Config.MOCK_DB_PATH,
    }
    sha_before = sha256_file(str(CANONICAL_DB))
    mtime_before = CANONICAL_DB.stat().st_mtime

    os.environ["CPS_TEST_DB_GUARD"] = "1"
    install_atp_test_db_guard(str(CANONICAL_DB))

    temp_dir = tempfile.mkdtemp(prefix=prefix)
    temp_db = os.path.join(temp_dir, "mock_data_test.db")
    shutil.copy2(CANONICAL_DB, temp_db)
    bind_temp_db_path(temp_db)

    info = {
        "active": True,
        "canonical_present": True,
        "temp_dir": temp_dir,
        "temp_db": temp_db,
        "sha_before": sha_before,
        "mtime_before": mtime_before,
    }
    try:
        yield info
    finally:
        config.Config.MOCK_DB_PATH = saved["Config_MOCK_DB_PATH"]
        if saved["CPS_MOCK_DB_PATH"] is None:
            os.environ.pop("CPS_MOCK_DB_PATH", None)
        else:
            os.environ["CPS_MOCK_DB_PATH"] = saved["CPS_MOCK_DB_PATH"]
        if saved["CPS_TEST_DB_GUARD"] is None:
            os.environ.pop("CPS_TEST_DB_GUARD", None)
        else:
            os.environ["CPS_TEST_DB_GUARD"] = saved["CPS_TEST_DB_GUARD"]
        uninstall_atp_test_db_guard()
        shutil.rmtree(temp_dir, ignore_errors=True)

        sha_after = sha256_file(str(CANONICAL_DB))
        mtime_after = CANONICAL_DB.stat().st_mtime
        if sha_after != sha_before:
            raise AssertionError(
                f"canonical DB SHA changed during route test isolation: "
                f"before={sha_before} after={sha_after}"
            )
        if mtime_after != mtime_before:
            raise AssertionError(
                f"canonical DB mtime changed during route test isolation: "
                f"before={mtime_before} after={mtime_after}"
            )
