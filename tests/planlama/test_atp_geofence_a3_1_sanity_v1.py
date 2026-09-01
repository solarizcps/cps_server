# -*- coding: utf-8 -*-
"""A3.1 short real-app sanity — isolated temp DB, no canonical access."""
from __future__ import annotations

import io
import json
import os
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

RUNTIME_ROOT = Path(r'C:\Solariz_CPS_SERVER_u3_runtime\atp_geofence_a3_1_sanity')
OUT_DIR = _REPO / '_audit_out' / 'atp_geofence_a3_1_full_regression_closure_v1'

os.environ['CPS_TEST_DB_GUARD'] = '1'
from tools.atp_test_db_guard import install_atp_test_db_guard  # noqa: E402

install_atp_test_db_guard(str(_APP / 'mock_data.db'))

from atp_geofence_a3_common import (  # noqa: E402
    A3_VEHICLE,
    m_offset,
    poll_fixture,
    prepare_isolated_a3_db,
    seed_a3_plan,
)


def _pick_port() -> int:
    import socket
    for p in (8090, 8091):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    raise RuntimeError('8090/8091 busy')


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


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('SANITY_RESULT=SKIP playwright missing')
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    db = str(RUNTIME_ROOT / 'mock_data_a3_1_sanity.db')
    prepare_isolated_a3_db(db)
    meta = seed_a3_plan(db)
    pd = meta['plan_date']
    pid1, pid2 = meta['plan_is_ids'][0], meta['plan_is_ids'][1]
    lat, lng = meta['base_lat'], meta['base_lng']
    t2_lat, t2_lng = meta['coords'][1]
    port = _pick_port()
    proc = _start_server(db, port)
    base = f'http://127.0.0.1:{port}'
    evidence: list = []
    fail = 0
    console_errors: list[str] = []
    page_errors: list[str] = []
    post_urls: list[str] = []
    static_404: list[str] = []

    try:
        _wait_server(port)
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel='msedge', headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 768})
            page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: page_errors.append(str(e)))
            page.on('request', lambda r: post_urls.append(r.url) if r.method == 'POST' else None)
            page.on('response', lambda r: static_404.append(r.url) if r.status == 404 and '/static/' in r.url else None)

            page.goto(base + '/giris', wait_until='domcontentloaded')
            page.fill("input[name='kullanici']", 'mehmet')
            page.fill("input[name='sifre']", '1453')
            page.click('button[type=submit]')
            page.wait_for_timeout(1500)

            replay = 20

            def open_daily() -> None:
                page.goto(
                    f'{base}/planlama/arac-takip/?tab=gunluk&vehicle_id={A3_VEHICLE}&date={pd}',
                    wait_until='domcontentloaded',
                )
                page.wait_for_timeout(1200)

            def check(step: str, expect_sub: str | None, item_id: int) -> None:
                nonlocal fail
                open_daily()
                label = page.locator(f'tr[data-plan-item="{item_id}"] .visit-text').first.inner_text().strip()
                api = page.evaluate(
                    """async ([d, pid]) => {
                      const r = await fetch('/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(d));
                      const j = await r.json();
                      return (j.items || []).find(x => String(x.plan_item_id) === String(pid)) || {};
                    }""",
                    [pd, item_id],
                )
                evidence.append({
                    'step': step, 'api_state': api.get('visit_state'),
                    'dom_label': label, 'expect_sub': expect_sub,
                })
                ok = True
                if step == 'OUTSIDE':
                    ok = api.get('visit_state') == 'OUTSIDE'
                elif expect_sub and expect_sub not in label:
                    ok = False
                elif api.get('visit_state') == 'APPROACHING' and 'Yaklaşıyor' not in label:
                    ok = False
                if not ok:
                    fail += 1
                    print(f'FAIL {step} api={api.get("visit_state")} dom={label!r}')
                else:
                    print(f'PASS {step} api={api.get("visit_state")} dom={label!r}')

            poll_fixture(*m_offset(lat, lng, 800), f'{pd} 11:{replay:02d}:00'); replay += 1
            check('OUTSIDE', None, pid1)
            poll_fixture(*m_offset(lat, lng, 450), f'{pd} 11:{replay:02d}:00'); replay += 1
            check('APPROACHING', 'Yaklaşıyor', pid1)
            poll_fixture(*m_offset(lat, lng, 190), f'{pd} 11:{replay:02d}:00'); replay += 1
            poll_fixture(*m_offset(lat, lng, 180), f'{pd} 11:{replay:02d}:00'); replay += 1
            check('ARRIVED', 'Vardı', pid1)
            poll_fixture(*m_offset(lat, lng, 310), f'{pd} 11:{replay:02d}:00'); replay += 1
            poll_fixture(*m_offset(lat, lng, 320), f'{pd} 11:{replay:02d}:00'); replay += 1
            check('DEPARTED_PENDING', 'Sonuç bekleniyor', pid1)
            poll_fixture(*m_offset(t2_lat, t2_lng, 190), f'{pd} 11:{replay:02d}:00'); replay += 1
            open_daily()
            api2 = page.evaluate(
                """async ([d, pid]) => {
                  const r = await fetch('/planlama/arac-takip/api/today-operations?date=' + encodeURIComponent(d));
                  const j = await r.json();
                  return (j.items || []).find(x => String(x.plan_item_id) === String(pid)) || {};
                }""",
                [pd, pid2],
            )
            if api2.get('visit_state') in ('ARRIVED', 'DEPARTED_PENDING'):
                fail += 1
                print(f'FAIL OUT_OF_SEQUENCE api={api2.get("visit_state")}')
            else:
                print(f'PASS OUT_OF_SEQUENCE api={api2.get("visit_state")}')
            from modules.planlama.arac_plan_change_service import apply_plan_job_change
            apply_plan_job_change(pid1, 1, {'action': 'complete', 'reason': 'a3_1 sanity'})
            poll_fixture(*m_offset(t2_lat, t2_lng, 450), f'{pd} 11:{replay:02d}:00'); replay += 1
            check('NEXT_TASK', 'Yaklaşıyor', pid2)
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)

    unintended_post = [u for u in post_urls if '127.0.0.1' in u and '/api/' in u and 'today-operations' not in u]
    map_noise = (
        'tile', 'leaflet', 'google', 'favicon', 'net::err', 'ors', 'openstreetmap',
    )
    actionable_console = [
        e for e in console_errors
        if not any(n in e.lower() for n in map_noise)
    ]
    report = {
        'evidence': evidence,
        'console_error_count': len(console_errors),
        'actionable_console_error_count': len(actionable_console),
        'page_error_count': len(page_errors),
        'static_404_count': len(static_404),
        'unintended_post_count': len(unintended_post),
        'fail_checks': fail,
    }
    (OUT_DIR / 'sanity_evidence.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(
        f'SANITY console={len(console_errors)} actionable={len(actionable_console)} '
        f'page={len(page_errors)} static404={len(static_404)} post={len(unintended_post)} fail={fail}',
    )
    passed = fail == 0 and not page_errors and not static_404 and not unintended_post
    print(f'SANITY_RESULT={"PASS" if passed else "FAIL"}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
