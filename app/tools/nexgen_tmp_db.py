# -*- coding: utf-8 -*-
"""NexGen test DB isolation — never write the live mock_data.db."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from typing import Any


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def db_fingerprint(path: str) -> dict[str, Any]:
    """SHA / size / mtime / WAL / SHM — restore yok, yalnız ölçüm."""
    st = os.stat(path)
    wal = path + "-wal"
    shm = path + "-shm"
    return {
        "path": os.path.abspath(path),
        "sha256": sha256_file(path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "wal_exists": os.path.isfile(wal),
        "shm_exists": os.path.isfile(shm),
        "wal_size": os.path.getsize(wal) if os.path.isfile(wal) else 0,
        "shm_size": os.path.getsize(shm) if os.path.isfile(shm) else 0,
    }


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


class LiveDbWriteError(RuntimeError):
    """Test ortamında canlı mock_data.db yazım girişimi."""


_GUARD: dict[str, Any] | None = None


def live_db_write_guard_stats() -> dict[str, Any]:
    if not _GUARD:
        return {"active": False, "blocked_connects": 0, "blocked_copies": 0}
    return {
        "active": True,
        "live_path": _GUARD["live"],
        "blocked_connects": _GUARD["blocked_connects"],
        "blocked_copies": _GUARD["blocked_copies"],
        "allowed_ro_connects": _GUARD["allowed_ro_connects"],
    }


def install_live_db_write_guard(live_path: str | None = None) -> dict[str, Any]:
    """sqlite3.connect + shutil.copy* için canlı DB yazım engeli (test-only).

    - RW connect → LiveDbWriteError
    - RO uri (mode=ro) → izinli
    - copy hedefi live → LiveDbWriteError
    Production koduna kalıcı monkeypatch bırakılmaz; uninstall ile çıkar.
    """
    global _GUARD
    if _GUARD is not None:
        return _GUARD

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(tools_dir)
    live = _norm(live_path or os.path.join(app_dir, "mock_data.db"))

    real_connect = sqlite3.connect
    real_copy2 = shutil.copy2
    real_copy = shutil.copy
    real_copyfile = shutil.copyfile

    state: dict[str, Any] = {
        "live": live,
        "blocked_connects": 0,
        "blocked_copies": 0,
        "allowed_ro_connects": 0,
        "real_connect": real_connect,
        "real_copy2": real_copy2,
        "real_copy": real_copy,
        "real_copyfile": real_copyfile,
    }

    def _is_live_target(database: Any) -> bool:
        if database is None:
            return False
        s = str(database)
        try:
            if s.startswith("file:"):
                from urllib.parse import unquote, urlparse

                u = urlparse(s)
                path_part = unquote(u.path)
                # file:///C:/path → /C:/path on Windows
                if os.name == "nt" and path_part.startswith("/") and len(path_part) >= 3 and path_part[2] == ":":
                    path_part = path_part[1:]
                return _norm(path_part) == live
            return _norm(s) == live
        except Exception:
            return False

    def _is_ro_uri(database: Any, kwargs: dict) -> bool:
        s = str(database)
        if kwargs.get("uri") and "mode=ro" in s:
            return True
        if s.startswith("file:") and "mode=ro" in s:
            return True
        return False

    def guarded_connect(*args, **kwargs):
        database = args[0] if args else kwargs.get("database")
        if _is_live_target(database):
            if _is_ro_uri(database, kwargs):
                state["allowed_ro_connects"] += 1
                return real_connect(*args, **kwargs)
            state["blocked_connects"] += 1
            raise LiveDbWriteError(
                f"LIVE DB write connect blocked: {database!r} (live={live})"
            )
        return real_connect(*args, **kwargs)

    def _guard_copy(dst: Any, kind: str):
        try:
            if dst and _norm(str(dst)) == live:
                state["blocked_copies"] += 1
                raise LiveDbWriteError(
                    f"LIVE DB copy-{kind} blocked → {dst!r}"
                )
        except LiveDbWriteError:
            raise
        except Exception:
            pass

    def guarded_copy2(src, dst, *a, **k):
        _guard_copy(dst, "copy2")
        return real_copy2(src, dst, *a, **k)

    def guarded_copy(src, dst, *a, **k):
        _guard_copy(dst, "copy")
        return real_copy(src, dst, *a, **k)

    def guarded_copyfile(src, dst, *a, **k):
        _guard_copy(dst, "copyfile")
        return real_copyfile(src, dst, *a, **k)

    sqlite3.connect = guarded_connect  # type: ignore[assignment]
    shutil.copy2 = guarded_copy2  # type: ignore[assignment]
    shutil.copy = guarded_copy  # type: ignore[assignment]
    shutil.copyfile = guarded_copyfile  # type: ignore[assignment]
    _GUARD = state
    return state


def uninstall_live_db_write_guard() -> None:
    global _GUARD
    if not _GUARD:
        return
    sqlite3.connect = _GUARD["real_connect"]  # type: ignore[assignment]
    shutil.copy2 = _GUARD["real_copy2"]  # type: ignore[assignment]
    shutil.copy = _GUARD["real_copy"]  # type: ignore[assignment]
    shutil.copyfile = _GUARD["real_copyfile"]  # type: ignore[assignment]
    _GUARD = None


def assert_resolved_db_is_tmp(resolved: str, live_path: str) -> None:
    if _norm(resolved) == _norm(live_path):
        raise LiveDbWriteError(
            f"Resolved DB path is LIVE — refuse to continue: {resolved}"
        )
    # tmp / temp klasörü dışında da olabilir ama live olamaz
    if not os.path.isfile(resolved):
        raise FileNotFoundError(resolved)


@contextmanager
def tmp_db_context(source_db: str | None = None, prefix: str = "nexgen_tmp_"):
    """Tek giriş: guard + tmp kopya + Config/routes path + fingerprint kontrolü.

    Config, routes importundan ÖNCE set edilir (mümkünse).
    Ana DB değişirse RuntimeError — restore yapılmaz.
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(tools_dir)
    source_db = os.path.abspath(source_db or os.path.join(app_dir, "mock_data.db"))
    if not os.path.isfile(source_db):
        raise FileNotFoundError(source_db)

    install_live_db_write_guard(source_db)
    fp_before = db_fingerprint(source_db)

    tmp_dir = tempfile.mkdtemp(prefix=prefix)
    tmp_db = os.path.join(tmp_dir, "mock_data_tmp.db")
    # copy source → tmp (hedef live değil; guard izin verir)
    shutil.copy2(source_db, tmp_db)
    assert_resolved_db_is_tmp(tmp_db, source_db)

    import config as cfg_mod

    old_cfg = cfg_mod.Config.MOCK_DB_PATH
    cfg_mod.Config.MOCK_DB_PATH = tmp_db

    # routes henüz import edilmediyse sonra set; edildiyse şimdi set
    nx_routes = None
    old_db_path = None
    try:
        import modules.nexgen.routes as nx_routes  # noqa: WPS433

        old_db_path = nx_routes.DB_PATH
        nx_routes.DB_PATH = tmp_db
    except Exception:
        nx_routes = None

    info = {
        "tmp_db": tmp_db,
        "tmp_dir": tmp_dir,
        "source_db": source_db,
        "fp_before": fp_before,
        "fp_after": None,
        "sha_before": fp_before["sha256"],
        "sha_after": None,
        "main_db_changed": None,
        "guard": live_db_write_guard_stats(),
    }
    try:
        # resolved paths kontrol
        assert_resolved_db_is_tmp(cfg_mod.Config.MOCK_DB_PATH, source_db)
        if nx_routes is not None:
            assert_resolved_db_is_tmp(nx_routes.DB_PATH, source_db)
        yield info
    finally:
        if nx_routes is not None and old_db_path is not None:
            nx_routes.DB_PATH = old_db_path
        cfg_mod.Config.MOCK_DB_PATH = old_cfg
        fp_after = db_fingerprint(source_db)
        info["fp_after"] = fp_after
        info["sha_after"] = fp_after["sha256"]
        info["main_db_changed"] = fp_after["sha256"] != fp_before["sha256"]
        info["guard"] = live_db_write_guard_stats()
        uninstall_live_db_write_guard()
        if info["main_db_changed"]:
            raise RuntimeError(
                "MAIN DB SHA CHANGED during test! "
                f"before={fp_before['sha256']} after={fp_after['sha256']} "
                "(restore yapılmadı)"
            )
        if fp_after["size"] != fp_before["size"]:
            raise RuntimeError(
                f"MAIN DB size changed: {fp_before['size']} → {fp_after['size']}"
            )


# Geriye uyumluluk
isolated_nexgen_db = tmp_db_context


def cleanup_tmp(info: dict) -> None:
    tmp_dir = info.get("tmp_dir")
    if tmp_dir and os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
