# -*- coding: utf-8 -*-
"""A3 browser UI closure — isolated server 8090/8091, Edge screenshots."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
_PLANLAMA = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP))
sys.path.insert(0, str(_PLANLAMA))

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
RUNTIME_ROOT = Path(r'C:\Solariz_CPS_SERVER_u3_runtime')
OUT_DIR = _REPO / '_audit_out' / 'atp_geofence_a3_real_app_replay_ui_closure_v1'

from atp_geofence_a3_common import (  # noqa: E402
    A3_VEHICLE,
    m_offset,
    poll_fixture,
    prepare_isolated_a3_db,
    seed_a3_plan,
)
from tools.atp_test_db_guard import bind_temp_db_path, install_atp_test_db_guard  # noqa: E402


def _pick_port() -> int:
    import socket
    for p in (8090, 8091):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    return 8091


def _prepare_db(runtime: Path) -> str:
    db = str(runtime / 'mock_data_geofence_a3.db')
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    install_atp_test_db_guard(str(_APP / 'mock_data.db'))
    prepare_isolated_a3_db(db)
    return db


def _start_server(db: str, port: int) -> subprocess.Popen:
    code = f"""
import os, sys
sys.path.insert(0, r'{_APP}')
os.environ['CPS_MOCK_DB_PATH'] = r'{db}'
os.environ['CPS_TEST_DB_GUARD'] = '1'
import config as cfg
cfg.Config.MOCK_DB_PATH = r'{db}'
import app as flask_app
flask_app.app.run(host='127.0.0.1', port={port}, debug=False, use_reloader=False)
"""
    return subprocess.Popen(
        [sys.executable, '-c', code],
        cwd=str(_APP),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_server(port: int, timeout: float = 60.0) -> None:
    url = f'http://127.0.0.1:{port}/giris'
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError('server timeout')


def _login(page, base: str, user: str = 'mehmet') -> None:
    page.goto(base + '/giris', wait_until='domcontentloaded')
    if '/giris' in page.url:
        page.fill("input[name='kullanici']", user)
        page.fill("input[name='sifre']", '1453')
        page.click('button[type=submit]')
        page.wait_for_timeout(1500)


def _open_daily(page, base: str, plan_date: str) -> None:
    url = (
        f'{base}/planlama/arac-takip/?tab=gunluk'
        f'&vehicle_id={A3_VEHICLE}&date={plan_date}'
    )
    page.goto(url, wait_until='domcontentloaded')
    try:
        page.wait_for_selector('#atpDailyJobsBody tr[data-plan-item]', timeout=20000)
    except Exception:
        page.wait_for_timeout(3000)


def _visit_label_on_page(page, plan_item_id: int) -> str:
    sel = f'tr[data-plan-item="{plan_item_id}"] .visit-text'
    loc = page.locator(sel)
    if loc.count() == 0:
        return ''
    return (loc.first.inner_text() or '').strip()


def _api_item(page, plan_date: str, plan_item_id: int) -> dict:
    raw = page.evaluate(
        """async ([d, pid]) => {
          const r = await fetch('/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(d));
          const j = await r.json();
          const items = j.items || [];
          return items.find(x => String(x.plan_item_id) === String(pid)) || null;
        }""",
        [plan_date, plan_item_id],
    )
    return raw if isinstance(raw, dict) else {}


def _run_viewport(browser, vp: str, size: dict, port: int, evidence: list, fail_box: list) -> None:
    runtime = RUNTIME_ROOT / f'atp_geofence_a3_{vp}_{datetime.now().strftime("%H%M%S")}'
    runtime.mkdir(parents=True, exist_ok=True)
    db = _prepare_db(runtime)
    meta = seed_a3_plan(db)
    pd = meta['plan_date']
    pid1, pid2 = meta['plan_is_ids'][0], meta['plan_is_ids'][1]
    lat, lng = meta['base_lat'], meta['base_lng']
    t2_lat, t2_lng = meta['coords'][1]
    base = f'http://127.0.0.1:{port}'
    proc = _start_server(db, port)
    try:
        _wait_server(port)
        page = browser.new_page(viewport=size)
        _login(page, base)
        replay_ts = 10

        def snap(slug: str, expect_sub: str | None = None, item_id: int | None = None) -> None:
            iid = item_id or pid1
            _open_daily(page, base, pd)
            label = _visit_label_on_page(page, iid)
            try:
                api_item = _api_item(page, pd, iid)
            except Exception as exc:
                api_item = {'error': str(exc)}
            shot = OUT_DIR / f'{slug}_{vp}.png'
            page.screenshot(path=str(shot), full_page=False)
            evidence.append({
                'step': slug, 'viewport': vp, 'plan_item_id': iid,
                'api_state': api_item.get('visit_state'),
                'dom_label': label, 'expect_sub': expect_sub, 'shot': str(shot),
            })
            if expect_sub and (not label or expect_sub not in label):
                fail_box[0] += 1
                print(f'FAIL {slug}_{vp} dom={label!r}')
            else:
                print(f'PASS {slug}_{vp} dom={label!r} api={api_item.get("visit_state")}')

        poll_fixture(*m_offset(lat, lng, 800), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        snap('01_outside')
        poll_fixture(*m_offset(lat, lng, 450), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        snap('02_approaching', 'Yaklaşıyor')
        poll_fixture(*m_offset(lat, lng, 190), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        poll_fixture(*m_offset(lat, lng, 180), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        snap('03_arrived', 'Vardı')
        poll_fixture(*m_offset(lat, lng, 310), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        poll_fixture(*m_offset(lat, lng, 320), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        snap('04_departed_pending', 'Sonuç bekleniyor')
        poll_fixture(*m_offset(t2_lat, t2_lng, 190), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        api2 = item_from_today_ops_safe(page, pd, pid2)
        snap('05_out_of_sequence_blocked')
        if api2.get('visit_state') in ('ARRIVED', 'DEPARTED_PENDING'):
            fail_box[0] += 1
            print(f'FAIL 05_api_task2_{vp} state={api2.get("visit_state")}')
        else:
            print(f'PASS 05_api_task2_{vp} state={api2.get("visit_state")}')
        from modules.planlama.arac_plan_change_service import apply_plan_job_change
        apply_plan_job_change(pid1, 1, {'action': 'complete', 'reason': 'a3 ui'})
        poll_fixture(*m_offset(t2_lat, t2_lng, 450), f'{pd} 11:{replay_ts:02d}:00')
        replay_ts += 1
        snap('06_next_task_eligible', 'Yaklaşıyor', item_id=pid2)
        page.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def item_from_today_ops_safe(page, plan_date: str, plan_item_id: int) -> dict:
    try:
        return _api_item(page, plan_date, plan_item_id)
    except Exception:
        from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
        for it in get_today_vehicle_operations(plan_date).get('items') or []:
            if int(it.get('plan_item_id') or 0) == int(plan_item_id):
                return it
        return {}


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('SKIP playwright not installed')
        return 0
    if not (_APP / 'mock_data.db').is_file():
        pass  # worktree guard — canonical-free isolated auth seed
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    port = _pick_port()
    evidence: list = []
    fail_box = [0]
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='msedge', headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        _run_viewport(browser, '1920', {'width': 1920, 'height': 1080}, port, evidence, fail_box)
        _run_viewport(browser, '1366', {'width': 1366, 'height': 768}, port, evidence, fail_box)
        browser.close()
    (OUT_DIR / 'browser_evidence.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(f'BROWSER_RESULT fail={fail_box[0]}')
    return 1 if fail_box[0] else 0


if __name__ == '__main__':
    raise SystemExit(main())
