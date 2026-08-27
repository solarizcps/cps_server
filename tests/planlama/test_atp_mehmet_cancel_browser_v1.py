# -*- coding: utf-8 -*-
"""Browser smoke — Mehmet PLANLANDI cancel + started job disabled option."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
OUT_DIR = Path(__file__).resolve().parents[2] / '_audit_out' / 'atp_mehmet_cancel_browser_v1'
PORT = 8098
BASE_URL = f'http://127.0.0.1:{PORT}'
VEHICLE = '45077045'
PLAN_DATE = '2026-08-29'
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))

sys.path.insert(0, str(APP))


def _load_mig(name: str):
    p = MIGS / name
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _start_server(db: str) -> subprocess.Popen:
    code = f"""
import os, sys
sys.path.insert(0, r'{APP}')
os.environ['CPS_MOCK_DB_PATH'] = r'{db}'
os.environ['CPS_TEST_DB_GUARD'] = '1'
import config as cfg
cfg.Config.MOCK_DB_PATH = r'{db}'
import app as flask_app
flask_app.app.run(host='127.0.0.1', port={PORT}, debug=False, use_reloader=False)
"""
    return subprocess.Popen(
        [sys.executable, '-c', code],
        cwd=str(APP),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_server(timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE_URL + '/giris', timeout=2)
            return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError('server did not start')


def _login(page, username: str) -> None:
    page.goto(BASE_URL + '/giris', wait_until='domcontentloaded')
    if '/giris' in page.url:
        page.fill("input[name='kullanici']", username)
        page.fill("input[name='sifre']", '1453')
        page.click('button[type=submit]')
        page.wait_for_timeout(1500)
        if '/giris' in page.url:
            raise RuntimeError(f'login failed for {username}: still on giris')


def _open_plan(page) -> None:
    url = f'{BASE_URL}/planlama/arac-takip/?tab=gunluk&vehicle_id={VEHICLE}&date={PLAN_DATE}'
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function(
        '() => window.AtpPlanChange && window.AtpPlanChange.openChange',
        timeout=45000,
    )
    page.wait_for_timeout(1500)


def _seed_via_api(page, db: str) -> tuple[int, int]:
    con = sqlite3.connect(db)
    loc = con.execute(
        'SELECT id,firma_adi,latitude,longitude,adres FROM arac_kayitli_yer '
        'WHERE aktif=1 AND latitude IS NOT NULL LIMIT 1',
    ).fetchone()
    con.close()
    res = page.evaluate(
        """async (payload) => {
          const r = await fetch('/planlama/arac-takip/api/plana-is-ekle-batch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
          });
          return { status: r.status, body: await r.json() };
        }""",
        {
            'rows': [{
                'plan_tarihi': PLAN_DATE, 'tarih': PLAN_DATE, 'arac_external_id': VEHICLE,
                'sofor_adi': 'ibrahim', 'firma': loc[1], 'yapilacak_is': 'Browser cancel',
                'is': 'Browser cancel', 'oncelik': 'NORMAL', 'location_master_id': loc[0],
                'latitude': loc[2], 'longitude': loc[3], 'adres': loc[4] or 'Test',
                'client_submit_id': f'browser-{uuid.uuid4().hex[:12]}',
            }],
            'plan_tarihi': PLAN_DATE,
            'arac_external_id': VEHICLE,
        },
    )
    assert res['status'] == 200 and res['body'].get('ok'), res
    plan_is_id = int(res['body']['results'][0]['plan_is_id'])
    con = sqlite3.connect(db)
    plan_id = con.execute(
        'SELECT plan_id FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
    ).fetchone()[0]
    con.close()
    return plan_is_id, int(plan_id)


@pytest.fixture(scope='module')
def browser_env():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip('playwright not installed')
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical missing')
    tmp = tempfile.mkdtemp(prefix='atp_mehmet_cancel_browser_')
    db = os.path.join(tmp, 'test.db')
    shutil.copy2(CANONICAL_SOURCE, db)
    con = sqlite3.connect(db)
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()
    _load_mig('189_planlama_arac_takip_rol32_yetki.py').run(db)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    proc = _start_server(db)
    try:
        _wait_server()
        yield {'db': db, 'tmp': tmp}
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope='module')
def browser_pages(browser_env):
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    pages = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for vp, size in (('1920', {'width': 1920, 'height': 1080}), ('1366', {'width': 1366, 'height': 768})):
            page = browser.new_page(viewport=size)
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            _login(page, 'mehmet')
            pages[vp] = page
        yield {'pages': pages, 'errors': errors, 'db': browser_env['db']}
        browser.close()


class TestMehmetCancelBrowserV1:
    def test_planlandi_cancel_and_started_disabled(self, browser_pages):
        db = browser_pages['db']
        con = sqlite3.connect(db)
        con.close()

        for vp, page in browser_pages['pages'].items():
            _open_plan(page)
            plan_is_id, plan_id = _seed_via_api(page, db)
            started_id, _ = _seed_via_api(page, db)
            con = sqlite3.connect(db)
            con.execute("UPDATE arac_gunluk_plan_is SET durum='BASLADI' WHERE id=?", (started_id,))
            con.commit()
            con.close()
            page.evaluate(
                f'() => {{ window.AtpPlanChange.openChange({plan_is_id}); }}',
            )
            page.wait_for_selector('#atpPcAction', timeout=8000)
            page.select_option('#atpPcAction', 'cancel')
            page.fill('#atpPcReason', 'Browser iptal testi')
            page.click('#atpPcSaveBtn')
            page.wait_for_timeout(2500)
            _open_plan(page)
            page.screenshot(path=str(OUT_DIR / f'mehmet_cancel_success_{vp}.png'), full_page=False)

            page.evaluate(
                f'() => {{ window.AtpPlanChange.openChange({started_id}); }}',
            )
            page.wait_for_selector('#atpPcAction', timeout=8000)
            disabled = page.evaluate("""() => {
              var sel = document.getElementById('atpPcAction');
              var opt = Array.from(sel.options).find(function(o) { return o.value === 'cancel'; });
              return { hasCancel: !!opt, disabled: opt ? opt.disabled : null, text: opt ? opt.textContent : '' };
            }""")
            assert disabled.get('hasCancel')
            assert disabled.get('disabled') is True
            assert 'plan dışına alınamaz' in (disabled.get('text') or '').lower()
            page.screenshot(path=str(OUT_DIR / f'mehmet_cancel_disabled_{vp}.png'), full_page=False)

        con = sqlite3.connect(db)
        durum = con.execute(
            'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
        ).fetchone()[0]
        audit = con.execute(
            'SELECT created_by FROM arac_plan_is_degisim WHERE plan_is_id=? ORDER BY id DESC LIMIT 1',
            (plan_is_id,),
        ).fetchone()
        con.close()
        assert durum == 'IPTAL'
        assert audit and audit[0] == 31

        critical = [
            e for e in browser_pages['errors']
            if e and '503' not in e and 'favicon' not in e.lower()
        ]
        assert not critical, critical
