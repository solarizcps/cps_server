# -*- coding: utf-8 -*-
"""Browser validation — WhatsApp plan message, window.open intercept, no real WA send."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'app'
MIGS = APP / 'migrations'
OUT_DIR = Path(__file__).resolve().parents[2] / '_audit_out' / 'atp_whatsapp_browser_v1'
PORT = 8093
BASE_URL = f'http://127.0.0.1:{PORT}'
PLAN_DATE = '2026-08-28'
VEHICLE = '45077045'
CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))

sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'tests' / 'planlama'))

from atp_plan2_fixture import PLAKA, SOFOR, insert_factory_base, seed_plan2_fixture


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


def _login(page, username: str = 'mehmet') -> None:
    page.goto(BASE_URL + '/giris', wait_until='domcontentloaded')
    page.fill("input[name='kullanici']", username)
    page.fill("input[name='sifre']", '1453')
    page.click('button[type=submit]')
    page.wait_for_timeout(1500)
    if '/giris' in page.url:
        raise RuntimeError(f'login failed for {username}')


def _open_plan(page) -> None:
    url = f'{BASE_URL}/planlama/arac-takip/?tab=gunluk&vehicle_id={VEHICLE}&date={PLAN_DATE}'
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_selector('#atpBtnWhatsapp', timeout=45000)
    page.wait_for_timeout(1200)


@pytest.fixture(scope='module')
def browser_env():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip('playwright not installed')

    live = str(CANONICAL_SOURCE.resolve())
    if not os.path.isfile(live):
        pytest.skip(f'canonical missing: {live}')

    tmp = tempfile.mkdtemp(prefix='atp_whatsapp_browser_')
    db = os.path.join(tmp, 'mock_data_test.db')
    shutil.copy2(live, db)
    _load_mig('189_planlama_arac_takip_rol32_yetki.py').run(db)
    con = sqlite3.connect(db)
    seed_plan2_fixture(con, with_coords=True)
    insert_factory_base(
        con, base_name='Solariz Fabrika', latitude=40.9928503, longitude=28.6944178,
        maps_url='https://maps.example/factory',
    )
    con.execute('DELETE FROM user_permission_override WHERE KullaniciId=31')
    con.commit()
    con.close()

    proc = _start_server(db)
    try:
        _wait_server()
        yield {'db': db, 'proc': proc, 'tmp': tmp}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def browser_pages(browser_env):
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    opened: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pages = {}
        for name, size in (('1920', {'width': 1920, 'height': 1080}), ('1366', {'width': 1366, 'height': 768})):
            page = browser.new_page(viewport=size)
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            page.add_init_script(
                """
                window.__waOpened = [];
                window.open = function(url) {
                  window.__waOpened.push(url);
                  const el = document.createElement('pre');
                  el.id = 'atp-wa-test-preview';
                  el.style.cssText = 'position:fixed;bottom:0;left:0;right:0;max-height:40vh;overflow:auto;background:#111;color:#0f0;z-index:99999;padding:8px;font-size:11px;';
                  try {
                    const text = decodeURIComponent((url.split('text=')[1] || ''));
                    el.textContent = text;
                  } catch (e) { el.textContent = url; }
                  document.body.appendChild(el);
                  return null;
                };
                """
            )
            pages[name] = page
        yield {'pages': pages, 'errors': errors, 'opened': opened}
        browser.close()


class TestWhatsAppBrowserV1:
    def test_whatsapp_button_intercept(self, browser_pages):
        decoded_messages = {}
        for vp, page in browser_pages['pages'].items():
            _login(page)
            _open_plan(page)
            page.click('#atpBtnWhatsapp')
            page.wait_for_timeout(2000)
            preview = page.locator('#atp-wa-test-preview')
            preview.wait_for(state='attached', timeout=15000)
            text = preview.inner_text()
            decoded_messages[vp] = text
            assert PLAKA in text
            assert SOFOR in text
            assert 'google.com/maps?q=' in text
            assert 'Solariz Fabrika' in text
            assert 'Tahmini dönüş:' in text
            assert '08:51' not in text
            page.screenshot(path=str(OUT_DIR / f'whatsapp_{vp}.png'), full_page=True)

        assert decoded_messages['1920'] == decoded_messages['1366']
        evidence = OUT_DIR / 'whatsapp_decoded_messages.json'
        import json
        evidence.write_text(
            json.dumps(decoded_messages, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        fatal = [e for e in browser_pages['errors'] if 'CANONICAL_DB_WRITE_FORBIDDEN' in e]
        assert not fatal
