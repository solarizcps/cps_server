# -*- coding: utf-8 -*-
"""NexGen test DB isolation — never write the live mock_data.db."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def isolated_nexgen_db(source_db: str | None = None, prefix: str = "nexgen_tmp_"):
    """Copy source DB to temp; point nexgen.routes.DB_PATH (+ Config) at copy.

    Never restores onto source. Raises if source SHA changes.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(tools_dir)
    source_db = source_db or os.path.join(app_dir, "mock_data.db")
    if not os.path.isfile(source_db):
        raise FileNotFoundError(source_db)

    sha_before = sha256_file(source_db)
    tmp_dir = tempfile.mkdtemp(prefix=prefix)
    tmp_db = os.path.join(tmp_dir, "mock_data_tmp.db")
    shutil.copy2(source_db, tmp_db)

    import config as cfg_mod
    import modules.nexgen.routes as nx_routes

    old_db_path = nx_routes.DB_PATH
    old_cfg = cfg_mod.Config.MOCK_DB_PATH
    nx_routes.DB_PATH = tmp_db
    cfg_mod.Config.MOCK_DB_PATH = tmp_db

    info = {
        "tmp_db": tmp_db,
        "tmp_dir": tmp_dir,
        "source_db": source_db,
        "sha_before": sha_before,
        "sha_after": None,
        "main_db_changed": None,
    }
    try:
        yield info
    finally:
        nx_routes.DB_PATH = old_db_path
        cfg_mod.Config.MOCK_DB_PATH = old_cfg
        sha_after = sha256_file(source_db)
        info["sha_after"] = sha_after
        info["main_db_changed"] = sha_after != sha_before
        if info["main_db_changed"]:
            raise RuntimeError(
                f"MAIN DB SHA CHANGED during test! before={sha_before} after={sha_after}"
            )


def cleanup_tmp(info: dict) -> None:
    tmp_dir = info.get("tmp_dir")
    if tmp_dir and os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
