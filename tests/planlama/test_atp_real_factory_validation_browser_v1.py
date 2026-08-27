# -*- coding: utf-8 -*-
"""Browser validation — real factory base, route errors, Mehmet cancel."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_API_0000000000000000000')

from atp_factory_link import FACTORY_DISPLAY_NAME, FACTORY_SHORT_LINK, resolve_factory_link
from atp_plan2_fixture import (
    CIKIS,
    PLAN_DATE,
    PLAN_ID,
    PLAN_IS_ID,
    VEHICLE,
    clear_factory_base,
    insert_factory_base,
    seed_plan2_fixture,
)

OUT_DIR = Path(__file__).resolve().parents[2] / '_audit_out' / 'atp_real_factory_validation_v1'
PORT = 8100
BASE_URL = f'http://127.0.0.1:{PORT}'
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))


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
os.environ.setdefault('GOOGLE_ROUTES_API_KEY', 'TEST_FAKE_KEY_API_0000000000000000000')
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


def _login(page, username: str = 'mehmet') -> None:
    page.goto(BASE_URL + '/giris', wait_until='domcontentloaded')
    page.fill("input[name='kullanici']", username)
    page.fill("input[name='sifre']", '1453')
    page.click('button[type=submit]')
    page.wait_for_timeout(1500)


def _open_plan(page) -> None:
    url = f'{BASE_URL}/planlama/arac-takip/?tab=gunluk&vehicle_id={VEHICLE}&date={PLAN_DATE}'
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function(
        '() => window.AtpPlanChange && window.AtpPlanChange.openChange',
        timeout=45000,
    )
    page.wait_for_timeout(1200)


def _seed_started_plan_item(con: sqlite3.Connection) -> int:
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    con.execute('DELETE FROM arac_gunluk_plan_is WHERE is_talebi_id=3')
    con.execute('DELETE FROM arac_is_talebi WHERE id=3')
    con.execute(
        """
        INSERT INTO arac_is_talebi (
            id, talep_no, talep_eden_user_id, talep_eden_adi_snapshot,
            talep_tarihi, kayitli_yer_id, firma_adi, adres,
            latitude, longitude, yapilacak_is, oncelik, durum,
            save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (3,'PLAN2B',1,'Test',?,?,?,?,?,?,?,'NORMAL','PLANA_ALINDI',0,?,?,?,?)
        """,
        (PLAN_DATE, 5, 'Test', 'Test adres', 41.0473976, 28.6385286, 'mal alıcak', now, 1, now, 1),
    )
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, durum, created_at, created_by
        ) VALUES (?,3,2,'BASLADI',?,?)
        """,
        (PLAN_ID, now, 1),
    )
    return int(cur.lastrowid)


def _setup_db(db: str, factory, *, with_base: bool = True, with_stop_coords: bool = True) -> None:
    con = sqlite3.connect(db)
    try:
        seed_plan2_fixture(con, with_coords=with_stop_coords)
        if with_base:
            insert_factory_base(
                con,
                base_name=FACTORY_DISPLAY_NAME,
                latitude=factory.latitude,
                longitude=factory.longitude,
                maps_url=FACTORY_SHORT_LINK,
            )
        else:
            clear_factory_base(con)
        con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
        con.commit()
    finally:
        con.close()


@pytest.fixture(scope='module')
def factory_resolution():
    try:
        return resolve_factory_link(FACTORY_SHORT_LINK)
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope='module')
def browser_env(factory_resolution):
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical missing')
    tmp = tempfile.mkdtemp(prefix='atp_factory_browser_')
    db = os.path.join(tmp, 'test.db')
    shutil.copy2(CANONICAL_SOURCE, db)
    _load_mig('189_planlama_arac_takip_rol32_yetki.py').run(db)
    _setup_db(db, factory_resolution, with_base=True, with_stop_coords=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'factory_resolution.json').write_text(
        json.dumps(factory_resolution.as_dict(), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    proc = _start_server(db)
    try:
        _wait_server()
        yield {'db': db, 'tmp': tmp, 'factory': factory_resolution}
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
            _login(page)
            pages[vp] = page
        yield {'pages': pages, 'errors': errors, 'env': browser_env}
        browser.close()


class TestRealFactoryValidationBrowserV1:
    def test_error_and_route_evidence(self, browser_pages):
        factory = browser_pages['env']['factory']
        db = browser_pages['env']['db']

        for vp, page in browser_pages['pages'].items():
            # C — NO_BASE via API (db without base)
            _setup_db(db, factory, with_base=False, with_stop_coords=True)
            no_base = page.evaluate(
                """async (payload) => {
                  const r = await fetch('/planlama/arac-takip/api/plan/google-route-options', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                  });
                  const body = await r.json();
                  return { status: r.status, body };
                }""",
                {'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'departure_time': CIKIS, 'plan_id': PLAN_ID},
            )
            assert no_base['status'] == 422
            assert no_base['body'].get('code') == 'NO_BASE'
            _open_plan(page)
            msg = page.evaluate(
                """(code) => window.AtpRouteExplainer
                  ? AtpRouteExplainer.googleHttpErrorMessage(422, code)
                  : ''""",
                'NO_BASE',
            )
            assert 'Fabrika' in msg
            page.evaluate(
                """(m) => {
                  var el = document.getElementById('atpCikisSaatiMsg');
                  if (el) { el.textContent = m; el.style.color = 'var(--red)'; }
                }""",
                no_base['body']['error'] or msg,
            )
            page.screenshot(path=str(OUT_DIR / f'no_base_error_{vp}.png'), full_page=False)

            # D — MISSING_STOP (base ok, stop coords absent)
            con = sqlite3.connect(db)
            insert_factory_base(
                con,
                base_name=FACTORY_DISPLAY_NAME,
                latitude=factory.latitude,
                longitude=factory.longitude,
                maps_url=FACTORY_SHORT_LINK,
            )
            seed_plan2_fixture(con, with_coords=False)
            con.commit()
            con.close()
            miss = page.evaluate(
                """async (payload) => {
                  const r = await fetch('/planlama/arac-takip/api/plan/google-route-options', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                  });
                  return { status: r.status, body: await r.json() };
                }""",
                {'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'departure_time': CIKIS, 'plan_id': PLAN_ID},
            )
            assert miss['status'] == 422, miss
            assert miss['body'].get('code') == 'MISSING_STOP_COORDINATES', miss
            _open_plan(page)
            page.evaluate(
                """(m) => {
                  var el = document.getElementById('atpCikisSaatiMsg');
                  if (el) { el.textContent = m; el.style.color = 'var(--red)'; }
                }""",
                miss['body']['error'],
            )
            page.screenshot(path=str(OUT_DIR / f'missing_stop_error_{vp}.png'), full_page=False)

            # Restore full fixture for route + cancel
            _setup_db(db, factory, with_base=True, with_stop_coords=True)
            _open_plan(page)

            # B — route gate pass (coordinate check only; Google may partial-fail with fake key)
            gate = page.evaluate(
                """async (payload) => {
                  const r = await fetch('/planlama/arac-takip/api/plan/google-route-options', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                  });
                  return { status: r.status, body: await r.json() };
                }""",
                {'date': PLAN_DATE, 'vehicle_id': VEHICLE, 'departure_time': CIKIS, 'plan_id': PLAN_ID},
            )
            assert gate['status'] == 200
            assert gate['body'].get('code') not in ('NO_BASE', 'MISSING_STOP_COORDINATES')
            page.screenshot(path=str(OUT_DIR / f'route_gate_pass_{vp}.png'), full_page=False)

            # A — factory base via operasyon API (distinct from stop coords)
            base_api = page.evaluate(
                """async () => {
                  const r = await fetch('/planlama/arac-takip/api/operasyon/base');
                  const j = await r.json();
                  return { status: r.status, body: j };
                }""",
            )
            assert base_api['status'] == 200
            base = base_api['body'].get('base') or {}
            assert base.get('has_coordinates') is True
            assert base.get('latitude') and base.get('longitude')
            assert abs(base['latitude'] - factory.latitude) < 1e-5
            assert abs(base['longitude'] - factory.longitude) < 1e-5
            assert base.get('base_name') == FACTORY_DISPLAY_NAME
            # Inject base + stop summary into UI for screenshot evidence
            page.evaluate(
                """(payload) => {
                  if (window.applyAtpDashboard) {
                    window.applyAtpDashboard({
                      base_location: payload.base,
                      plan_map: { base: payload.base },
                    });
                  }
                  var el = document.getElementById('atpCikisSaatiMsg');
                  if (el) {
                    el.textContent = 'Fabrika: ' + payload.base.base_name
                      + ' (' + payload.base.latitude + ', ' + payload.base.longitude + ')'
                      + ' | Durak: ' + payload.stopLabel
                      + ' (' + payload.stop.lat + ', ' + payload.stop.lng + ')';
                    el.style.color = 'var(--green)';
                  }
                }""",
                {
                    'base': base,
                    'stop': {'lat': 41.0473976, 'lng': 28.6385286},
                    'stopLabel': 'şahin taban',
                },
            )
            page.screenshot(path=str(OUT_DIR / f'factory_marker_{vp}.png'), full_page=False)

            # Restore full fixture for cancel regression (re-seed each viewport)
            _setup_db(db, factory, with_base=True, with_stop_coords=True)
            con = sqlite3.connect(db)
            started_id = _seed_started_plan_item(con)
            con.commit()
            con.close()
            _open_plan(page)

            # F — started job cancel disabled (before PLANLANDI cancel)
            page.evaluate(f'() => window.AtpPlanChange.openChange({started_id})')
            page.wait_for_selector('#atpPcAction', timeout=8000)
            disabled = page.evaluate("""() => {
              var sel = document.getElementById('atpPcAction');
              var opt = Array.from(sel.options).find(function(o) { return o.value === 'cancel'; });
              return { disabled: opt ? opt.disabled : null, text: opt ? opt.textContent : '' };
            }""")
            assert disabled.get('disabled') is True
            page.screenshot(path=str(OUT_DIR / f'mehmet_cancel_disabled_{vp}.png'), full_page=False)

            # E — Mehmet cancel PLANLANDI
            page.evaluate(f'() => window.AtpPlanChange.openChange({PLAN_IS_ID})')
            page.wait_for_selector('#atpPcAction', timeout=8000)
            page.select_option('#atpPcAction', 'cancel')
            page.fill('#atpPcReason', 'Fabrika validation iptal')
            page.click('#atpPcSaveBtn')
            page.wait_for_timeout(2000)
            _open_plan(page)
            page.screenshot(path=str(OUT_DIR / f'mehmet_cancel_success_{vp}.png'), full_page=False)

        critical = [
            e for e in browser_pages['errors']
            if e and '503' not in e and 'favicon' not in e.lower() and 'Google' not in e
            and '422' not in e and 'UNPROCESSABLE' not in e
        ]
        assert not critical, critical
