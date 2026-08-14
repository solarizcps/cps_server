# -*- coding: utf-8 -*-
"""Browser / ad-hoc test safety — canonical DB write forbidden, runtime parity."""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator

from tools.nexgen_tmp_db import (
    assert_live_db_unchanged,
    browser_test_server_context,
    canonical_db_path,
    db_fingerprint,
    find_free_port,
    sha256_file,
    sistem_kur_usd_snapshot,
    wait_flask_health,
    cleanup_tmp,
)
from tools.test_db_guard import (
    LiveHttpWriteError,
    bootstrap_adhoc_script_guards,
    allow_http_base_url,
    guard_is_active,
    http_guard_is_active,
    uninstall_all_test_guards,
)
from tools.test_db_http_guard import install_live_http_write_guard


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTES_PY = os.path.join(REPO_ROOT, 'app', 'modules', 'nexgen', 'routes.py')
LIVE_PORT = 8080
LIVE_BASE = f'http://127.0.0.1:{LIVE_PORT}'


def repo_git_head(repo_root: str | None = None) -> str:
    root = repo_root or REPO_ROOT
    try:
        out = subprocess.check_output(
            ['git', '-C', root, 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return 'UNKNOWN'


def _win_pid_on_port(port: int) -> list[int]:
    pids: list[int] = []
    try:
        out = subprocess.check_output(
            ['netstat', '-ano'],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        for line in out.splitlines():
            if f':{port}' not in line or 'LISTENING' not in line.upper():
                continue
            parts = line.split()
            if parts:
                try:
                    pids.append(int(parts[-1]))
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(set(pids))


def _process_info(pid: int) -> dict[str, Any]:
    info: dict[str, Any] = {'pid': pid}
    if sys.platform == 'win32':
        try:
            out = subprocess.check_output(
                ['wmic', 'process', 'where', f'ProcessId={pid}', 'get',
                 'CommandLine,CreationDate,ExecutablePath', '/format:list'],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            for line in out.splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    info[k.strip().lower()] = v.strip()
        except Exception as exc:
            info['error'] = str(exc)
    else:
        try:
            cmd = open(f'/proc/{pid}/cmdline', 'rb').read().decode('utf-8', errors='replace')
            info['commandline'] = cmd.replace('\x00', ' ')
        except Exception as exc:
            info['error'] = str(exc)
    return info


def inspect_live_flask_runtime(port: int = LIVE_PORT) -> dict[str, Any]:
    pids = _win_pid_on_port(port)
    proc = _process_info(pids[0]) if pids else {}
    routes_mtime = os.path.getmtime(ROUTES_PY) if os.path.isfile(ROUTES_PY) else None
    create_ts = None
    cdate = proc.get('creationdate') or proc.get('creation_date')
    if cdate and len(cdate) >= 14:
        try:
            create_ts = datetime.strptime(cdate[:14], '%Y%m%d%H%M%S').timestamp()
        except ValueError:
            pass
    stale = False
    stale_reason = ''
    if not pids:
        stale = True
        stale_reason = f'no LISTENING process on :{port}'
    elif routes_mtime and create_ts and create_ts < routes_mtime - 1:
        stale = True
        stale_reason = (
            f'Flask PID {pids[0]} started before routes.py last modified '
            f'(proc={datetime.fromtimestamp(create_ts)!s}, routes={datetime.fromtimestamp(routes_mtime)!s})'
        )
    guard_marker = "'TAMAMLANDI'"
    disk_has_guard = False
    if os.path.isfile(ROUTES_PY):
        with open(ROUTES_PY, encoding='utf-8') as fh:
            disk_has_guard = guard_marker in fh.read()
    return {
        'git_head': repo_git_head(),
        'port': port,
        'pids': pids,
        'pid': pids[0] if pids else None,
        'process': proc,
        'routes_py_mtime': routes_mtime,
        'process_create_ts': create_ts,
        'disk_has_tamamlandi_guard': disk_has_guard,
        'stale': stale,
        'stale_reason': stale_reason,
        'live_base': f'http://127.0.0.1:{port}',
    }


def assert_live_flask_runtime_fresh(port: int = LIVE_PORT) -> dict[str, Any]:
    rt = inspect_live_flask_runtime(port)
    if rt['stale']:
        raise RuntimeError(
            'STALE FLASK RUNTIME — browser E2E aborted. '
            f"{rt['stale_reason']}. "
            'Restart local Flask from current checkout, then rerun test.'
        )
    if not rt.get('disk_has_tamamlandi_guard'):
        raise RuntimeError(
            'routes.py missing TAMAMLANDI guard marker — disk/code mismatch'
        )
    return rt


def assert_post_blocked_on_live() -> None:
    """Verify HTTP write guard blocks POST to live :8080."""
    import urllib.request

    bootstrap_adhoc_script_guards()
    req = urllib.request.Request(
        LIVE_BASE + '/nexgen/api/pazarlama/mpr-olustur',
        data=b'{"talep_id":1}',
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=3)
        raise RuntimeError('POST to live :8080 was NOT blocked — guard failure')
    except LiveHttpWriteError:
        return
    except Exception as exc:
        if LiveHttpWriteError.__name__ in type(exc).__name__:
            return
        # urllib may wrap — check message
        if 'LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST' in str(exc):
            return
        raise RuntimeError(f'Unexpected error during guard probe: {exc}') from exc


@contextmanager
def readonly_browser_context(
    *,
    port: int = LIVE_PORT,
    require_live_flask: bool = True,
) -> Iterator[dict[str, Any]]:
    """Read-only browser regression: isolated temp DB + free port.

    Canonical app/mock_data.db is never written. Live :8080 is inspected
    only for runtime HEAD/PID parity (stale guard), not browser traffic.
    """
    live = bootstrap_adhoc_script_guards()
    install_live_http_write_guard(live_port=port, allowed_base_urls=())
    runtime = assert_live_flask_runtime_fresh(port) if require_live_flask else inspect_live_flask_runtime(port)
    fp_before = db_fingerprint(live)
    kur_before = sistem_kur_usd_snapshot(live)
    biz_before = canonical_order760_snapshot(live)

    with browser_test_server_context(live_db=live, prefix='readonly_browser_') as srv:
        allow_http_base_url(srv['base_url'])
        ctx: dict[str, Any] = {
            'mode': 'READ_ONLY',
            'live_db': live,
            'tmp_db': srv['tmp_db'],
            'base_url': srv['base_url'],
            'isolated_port': srv['port'],
            'sha_before': fp_before['sha256'],
            'biz_before': biz_before,
            'fp_before': fp_before,
            'runtime': runtime,
            'git_head': runtime.get('git_head'),
        }
        try:
            yield ctx
        finally:
            fp_after = db_fingerprint(live)
            kur_after = sistem_kur_usd_snapshot(live)
            biz_after = canonical_order760_snapshot(live)
            ctx['sha_after'] = fp_after['sha256']
            ctx['biz_after'] = biz_after
            ctx['fp_after'] = fp_after
            assert_live_db_unchanged(live, fp_before, kur_before, fp_after, kur_after)
            if biz_after != biz_before:
                raise RuntimeError(
                    f'BUSINESS SNAPSHOT CHANGED: before={biz_before} after={biz_after}'
                )
            uninstall_all_test_guards()


@contextmanager
def mutating_isolated_browser_context(
    *,
    seed_fn: Callable[[str], None] | None = None,
    prefix: str = 'mutating_prevention_',
) -> Iterator[dict[str, Any]]:
    """Mutating HTTP tests — temp DB + isolated port only."""
    live = bootstrap_adhoc_script_guards()
    fp_before = db_fingerprint(live)
    kur_before = sistem_kur_usd_snapshot(live)

    tmp_dir = tempfile.mkdtemp(prefix=prefix)
    tmp_db = os.path.join(tmp_dir, 'mock_data_tmp.db')
    shutil.copy2(live, tmp_db)
    if seed_fn:
        seed_fn(tmp_db)

    port = find_free_port(exclude={LIVE_PORT})
    base_url = f'http://127.0.0.1:{port}'
    app_dir = os.path.join(REPO_ROOT, 'app')
    env = os.environ.copy()
    env['CPS_MOCK_DB_PATH'] = tmp_db
    env['CPS_PORT'] = str(port)
    env['CPS_TEST_ENDPOINT'] = '1'
    env['FLASK_DEBUG'] = '0'

    proc = subprocess.Popen(
        [sys.executable, 'app.py'],
        cwd=app_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    allow_http_base_url(base_url)
    info: dict[str, Any] = {
        'mode': 'MUTATING',
        'live_db': live,
        'tmp_db': tmp_db,
        'tmp_dir': tmp_dir,
        'port': port,
        'base_url': base_url,
        'sha_before': fp_before['sha256'],
        'proc': proc,
    }
    try:
        wait_flask_health(base_url + '/giris', proc, 90.0)
        yield info
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
        cleanup_tmp({'tmp_dir': tmp_dir})
        fp_after = db_fingerprint(live)
        kur_after = sistem_kur_usd_snapshot(live)
        info['sha_after'] = fp_after['sha256']
        assert_live_db_unchanged(live, fp_before, kur_before, fp_after, kur_after)
        uninstall_all_test_guards()


def seed_tamamlandi_retry_case(tmp_db: str, siparis_id: int = 99001) -> None:
    """Isolated DB: TAMAMLANDI + one BITTI plan — safe mutation target."""
    con = sqlite3.connect(tmp_db)
    try:
        con.execute(
            "UPDATE nexgen_planlama_siparis SET durum='TAMAMLANDI' WHERE id=?",
            (siparis_id,),
        )
        row = con.execute(
            'SELECT id FROM nexgen_planlama_siparis WHERE id=?', (siparis_id,)
        ).fetchone()
        if not row:
            con.execute(
                """
                INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum, talep_referansi)
                VALUES (?, 'PZM-TEST-99001', 11, 'TEST', 'TAMAMLANDI',
                        '__PZM_V2__{"v":2,"kalem_sayisi":1}')
                """,
                (siparis_id,),
            )
        con.commit()
    finally:
        con.close()


def canonical_order760_snapshot(live_db: str | None = None) -> dict[str, Any]:
    live = canonical_db_path(live_db)
    con = sqlite3.connect(f'file:{live}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        plans = {
            r['id']: dict(r)
            for r in con.execute(
                'SELECT id, plan_kodu, durum FROM nexgen_uretim_plan '
                'WHERE planlama_siparis_id=760 ORDER BY id'
            )
        }
        kalem = con.execute(
            'SELECT uretim_plan_id FROM nexgen_planlama_siparis_kalem WHERE id=501'
        ).fetchone()
        sip = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE id=760'
        ).fetchone()
        return {
            'plan194': plans.get(194, {}).get('durum'),
            'plan195': plans.get(195, {}).get('durum'),
            'plan196': plans.get(196, {}).get('durum'),
            'plan_count': len(plans),
            'pointer501': kalem['uretim_plan_id'] if kalem else None,
            'order760': sip['durum'] if sip else None,
        }
    finally:
        con.close()


def format_runtime_report(rt: dict[str, Any]) -> str:
    proc = rt.get('process') or {}
    cmd = proc.get('commandline') or proc.get('executablepath') or 'UNKNOWN'
    return (
        f"GIT_HEAD={rt.get('git_head')} "
        f"PID={rt.get('pid')} "
        f"CMD={cmd[:120]} "
        f"STALE={rt.get('stale')}"
    )
