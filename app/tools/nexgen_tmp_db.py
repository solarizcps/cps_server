# -*- coding: utf-8 -*-
"""NexGen test DB isolation — never write the live mock_data.db."""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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


CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST = 'CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST'


def _norm(p: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))
    except OSError:
        return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def canonical_db_path(live_path: str | None = None) -> str:
    """Canonical mock_data.db absolute path."""
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(tools_dir)
    return _norm(live_path or os.path.join(app_dir, 'mock_data.db'))


def _script_context_hint() -> str:
    import inspect

    for frame in inspect.stack()[2:8]:
        fn = frame.filename or ''
        if fn.endswith('nexgen_tmp_db.py') or fn.endswith('test_db_guard.py'):
            continue
        if '_test_' in fn or '_browser_' in fn or os.sep + 'tests' + os.sep in fn:
            return fn
    return '<unknown>'


def _log_canonical_rw_attempt(action: str, database: Any, live: str) -> None:
    """Append-only diagnostic — does not write canonical DB."""
    if os.environ.get('CPS_GUARD_RW_TRACE', '1').strip().lower() in ('0', 'false', 'no'):
        return
    try:
        import inspect

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_path = os.path.join(root, 'backup', 'guard05_rw_trace.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        stack = []
        for frame in inspect.stack()[2:12]:
            fn = frame.filename or ''
            if fn.endswith('nexgen_tmp_db.py') or fn.endswith('test_db_guard.py'):
                continue
            stack.append(f'{fn}:{frame.lineno}')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(
                f'{time.strftime("%Y-%m-%d %H:%M:%S")} pid={os.getpid()} '
                f'action={action} path={database!r} live={live!r} '
                f'script={_script_context_hint()} argv={sys.argv[:2]!r} '
                f'stack={" | ".join(stack[:5])}\n'
            )
    except OSError:
        pass


class LiveDbWriteError(RuntimeError):
    """Test ortamında canlı mock_data.db yazım girişimi."""

    CODE = CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST

    def __init__(self, message: str, *, attempted_path: str | None = None):
        self.attempted_path = attempted_path
        super().__init__(message)


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
    live = canonical_db_path(live_path or os.path.join(app_dir, "mock_data.db"))

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

    def _resolve_db_path(database: Any) -> str | None:
        if database is None:
            return None
        s = str(database)
        try:
            if s.startswith("file:"):
                from urllib.parse import unquote, urlparse

                u = urlparse(s)
                path_part = unquote(u.path)
                if os.name == "nt" and path_part.startswith("/") and len(path_part) >= 3 and path_part[2] == ":":
                    path_part = path_part[1:]
                return _norm(path_part)
            if s == ':memory:':
                return None
            return _norm(s)
        except Exception:
            return None

    def _is_live_target(database: Any) -> bool:
        resolved = _resolve_db_path(database)
        if not resolved:
            return False
        return resolved == live

    def _forbidden_message(database: Any, action: str) -> str:
        ctx = _script_context_hint()
        return (
            f'{CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST}: {action} blocked for canonical DB. '
            f'attempted_path={database!r} live={live!r} script={ctx}. '
            f'Use tools.nexgen_tmp_db.tmp_db_context() or :memory: for writes.'
        )

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
            _log_canonical_rw_attempt('sqlite3.connect', database, live)
            raise LiveDbWriteError(
                _forbidden_message(database, 'sqlite3.connect'),
                attempted_path=str(database),
            )
        return real_connect(*args, **kwargs)

    def _guard_copy(dst: Any, kind: str):
        try:
            if dst and _norm(str(dst)) == live:
                state["blocked_copies"] += 1
                raise LiveDbWriteError(
                    _forbidden_message(dst, f'shutil.{kind}'),
                    attempted_path=str(dst),
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


def connect_sqlite(database: str, *, readonly: bool = False, **kwargs: Any) -> sqlite3.Connection:
    """Test-safe sqlite connect — canonical RW blocked when guard active."""
    if readonly:
        path = os.path.abspath(database)
        uri = f'file:{path}?mode=ro'
        return sqlite3.connect(uri, uri=True, **kwargs)
    return sqlite3.connect(database, **kwargs)


def bootstrap_canonical_write_guard(live_path: str | None = None) -> str:
    """Ad-hoc _test_* / _browser_* script import-time guard."""
    live = canonical_db_path(live_path)
    install_live_db_write_guard(live)
    return live


def guard_is_active() -> bool:
    return _GUARD is not None


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


def sistem_kur_usd_snapshot(db_path: str) -> dict[str, Any]:
    """sistem_kur USD — COUNT + ordered Tarih:Satis aggregate hash (read-only)."""
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM sistem_kur WHERE ParaBirimi='USD'"
        ).fetchone()[0]
        rows = con.execute(
            """
            SELECT Tarih, Satis FROM sistem_kur
            WHERE ParaBirimi='USD'
            ORDER BY Tarih, Satis
            """
        ).fetchall()
        agg = "|".join(f"{r[0]}:{r[1]}" for r in rows)
        return {
            "count": int(count),
            "agg": agg,
            "agg_hash": hashlib.sha256(agg.encode("utf-8")).hexdigest(),
        }
    finally:
        con.close()


def find_free_port(host: str = "127.0.0.1", exclude: set[int] | None = None) -> int:
    """Dinamik local port; 8080 ve exclude set dışında."""
    blocked = set(exclude or set())
    blocked.add(8080)
    for _ in range(64):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            port = int(sock.getsockname()[1])
        if port not in blocked:
            return port
    raise RuntimeError("find_free_port: 8080 dışında boş port bulunamadı")


def wait_flask_health(url: str, proc: subprocess.Popen, timeout_s: float = 60.0) -> None:
    """Flask subprocess hazır olana kadar /giris healthcheck."""
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            raise RuntimeError(f"Flask subprocess erken kapandı: rc={rc}")
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.4)
    raise RuntimeError(f"Flask healthcheck timeout: {url} ({last_err})")


def assert_live_db_unchanged(
    live_db: str,
    fp_before: dict[str, Any],
    kur_before: dict[str, Any],
    fp_after: dict[str, Any],
    kur_after: dict[str, Any],
) -> None:
    if fp_after.get("sha256") != fp_before.get("sha256"):
        raise RuntimeError(
            "LIVE DB SHA CHANGED: "
            f"before={fp_before.get('sha256')} after={fp_after.get('sha256')}"
        )
    if fp_after.get("size") != fp_before.get("size"):
        raise RuntimeError(
            f"LIVE DB size changed: {fp_before.get('size')} → {fp_after.get('size')}"
        )
    if kur_after != kur_before:
        raise RuntimeError(
            f"sistem_kur USD snapshot changed: before={kur_before} after={kur_after}"
        )


@contextmanager
def browser_test_server_context(
    live_db: str | None = None,
    prefix: str = "browser_regression_",
    health_path: str = "/giris",
    health_timeout_s: float = 90.0,
):
    """Temp DB kopyası + ayrı Flask subprocess + live DB fingerprint guard.

    Yield dict: tmp_db, port, base_url, test_env, fp_before, kur_before, ...
    """
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(tools_dir)
    live_db = os.path.abspath(live_db or os.path.join(app_dir, "mock_data.db"))
    if not os.path.isfile(live_db):
        raise FileNotFoundError(live_db)

    fp_before = db_fingerprint(live_db)
    kur_before = sistem_kur_usd_snapshot(live_db)

    tmp_dir = tempfile.mkdtemp(prefix=prefix)
    tmp_db = os.path.join(tmp_dir, "mock_data_tmp.db")
    shutil.copy2(live_db, tmp_db)
    assert_resolved_db_is_tmp(tmp_db, live_db)

    port = find_free_port(exclude={8080})
    if port == 8080:
        raise RuntimeError("Test port 8080 olamaz — aktif dev server ile çakışır")
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["CPS_MOCK_DB_PATH"] = tmp_db
    env["CPS_PORT"] = str(port)
    env["CPS_TEST_ENDPOINT"] = "1"
    env["FLASK_DEBUG"] = "0"

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=app_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    info: dict[str, Any] = {
        "live_db": live_db,
        "tmp_db": tmp_db,
        "tmp_dir": tmp_dir,
        "port": port,
        "base_url": base_url,
        "fp_before": fp_before,
        "fp_after": None,
        "kur_before": kur_before,
        "kur_after": None,
        "live_db_unchanged": None,
        "proc": proc,
        "test_env": {
            "CPS_MOCK_DB_PATH": tmp_db,
            "CPS_PORT": str(port),
            "CPS_BASE": base_url,
            "CPS_TEST_ENDPOINT": "1",
        },
    }
    try:
        wait_flask_health(base_url + health_path, proc, health_timeout_s)
        yield info
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
        cleanup_tmp({"tmp_dir": tmp_dir})
        fp_after = db_fingerprint(live_db)
        kur_after = sistem_kur_usd_snapshot(live_db)
        info["fp_after"] = fp_after
        info["kur_after"] = kur_after
        try:
            assert_live_db_unchanged(live_db, fp_before, kur_before, fp_after, kur_after)
            info["live_db_unchanged"] = True
        except RuntimeError:
            info["live_db_unchanged"] = False
            raise
