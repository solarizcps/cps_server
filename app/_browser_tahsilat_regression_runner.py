# -*- coding: utf-8 -*-
"""Tahsilat regression browser runner — mevcut E2E scriptlerini + UI lock testleri."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
USER = 'erhan'
PASS = '147258'
APP_DIR = os.path.dirname(__file__)
SHOT = os.path.join(APP_DIR, '_shot_tahsilat_regression')
os.makedirs(SHOT, exist_ok=True)

REPORT: dict = {'unit': {}, 'browser': {}, 'scripts': {}}


def ok(bucket: str, name: str, passed: bool, note: str = '') -> None:
    REPORT.setdefault(bucket, {})[name] = {'pass': bool(passed), 'note': note}
    print(('PASS' if passed else 'FAIL'), f'[{bucket}]', name, note)


def run_unit_suite() -> int:
    cmd = [
        sys.executable, '-m', 'unittest',
        'tests.nexgen.test_mo_tahsilat_regression',
        'tests.nexgen.test_mo_tahsilat_kur_service',
        'tests.nexgen.test_mo_tahsilat_kayit_tcmb_write',
        'tests.nexgen.test_pzm_cek_vade_gun',
        'tests.nexgen.test_pzm_cek_vade_db_lock',
        'tests.nexgen.test_mo_vade_kontrol_service',
    ]
    root = os.path.dirname(APP_DIR)
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    out = (proc.stdout or '') + (proc.stderr or '')
    passed = proc.returncode == 0
    ok('unit', 'unittest_suite', passed, f'rc={proc.returncode}')
    REPORT['unit']['_output_tail'] = out[-4000:]
    return proc.returncode


def run_script(name: str, script: str) -> int:
    path = os.path.join(APP_DIR, script)
    proc = subprocess.run([sys.executable, path], cwd=APP_DIR, capture_output=True, text=True)
    out = (proc.stdout or '') + (proc.stderr or '')
    passed = proc.returncode == 0
    ok('scripts', name, passed, f'rc={proc.returncode}')
    REPORT['scripts'][f'{name}_output'] = out[-3000:]
    return proc.returncode


def login(page) -> None:
    import re
    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', USER)
    page.fill('input[name="sifre"]', PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r'.*/(nexgen|musteri).*'), timeout=15000)


def dismiss_karar_popup_if_visible(page) -> None:
    """MO Talep Sonucu popup görünürse gerçek Tamam click ile kapat."""
    pop = page.locator('#mp-karar-popup')
    try:
        pop.wait_for(state='visible', timeout=2500)
    except PlaywrightTimeoutError:
        return
    page.locator('#mp-karar-popup-tamam').click()
    pop.wait_for(state='hidden', timeout=5000)


def browser_ui_lock() -> int:
    rc = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        login(page)
        page.goto(f'{BASE}/nexgen/musteri-pazarlama', wait_until='networkidle')
        time.sleep(0.5)
        dismiss_karar_popup_if_visible(page)
        page.locator('.mp-v2-hizli-btn[data-modal="tahsilat"], .mp-hizli-btn[data-modal="tahsilat"]').first.click()
        time.sleep(0.5)

        page.fill('#mp-t-alinan', '250')
        page.locator('#mp-t-alinan').blur()
        time.sleep(0.2)
        v250 = page.input_value('#mp-t-alinan')
        ok('browser', 'para_format_250', '250,00' in v250, v250)

        page.locator('#mp-t-alinan').click()
        page.locator('#mp-t-alinan').fill('')
        page.fill('#mp-t-alinan', '250000')
        page.locator('#mp-t-alinan').blur()
        time.sleep(0.2)
        v250k = page.input_value('#mp-t-alinan')
        ok('browser', 'para_format_250000', '250.000,00' in v250k, v250k)
        raw250k = page.evaluate(
            """() => {
              const el = document.getElementById('mp-t-alinan');
              return el ? (el.dataset.rawValue || '') : '';
            }"""
        )
        ok('browser', 'parse_no_x1000', float(raw250k or 0) == 250000.0, raw250k)

        modal_open = page.locator('#mp-modal-tahsilat').evaluate(
            'el => el && !el.hidden && el.style.display !== "none"'
        )
        ok('browser', 'modal_acik', bool(modal_open), '')

        page.locator('#mp-t-alinan').click()
        page.mouse.down()
        page.mouse.move(20, 20)
        page.mouse.up()
        time.sleep(0.3)
        still_open_drag = page.locator('#mp-modal-tahsilat').evaluate(
            'el => el && !el.hidden && el.style.display !== "none"'
        )
        ok('browser', 'input_drag_kapatmaz', bool(still_open_drag), '')

        page.reload(wait_until='networkidle')
        time.sleep(0.5)
        dismiss_karar_popup_if_visible(page)
        page.locator('.mp-v2-hizli-btn[data-modal="tahsilat"], .mp-hizli-btn[data-modal="tahsilat"]').first.click()
        time.sleep(0.5)
        overlay = page.locator('#mp-modal-tahsilat')
        box = overlay.bounding_box()
        if box:
            page.mouse.click(box['x'] + 5, box['y'] + 5)
            time.sleep(0.3)
        closed_backdrop = page.locator('#mp-modal-tahsilat').evaluate(
            'el => el.hidden || el.style.display === "none"'
        )
        ok('browser', 'backdrop_click_kapatir', bool(closed_backdrop), '')

        page.screenshot(path=os.path.join(SHOT, 'modal_regression.png'), full_page=True)
        browser.close()
        if any(not v['pass'] for v in REPORT.get('browser', {}).values() if isinstance(v, dict) and 'pass' in v):
            rc = 1
    return rc


def main() -> int:
    rc = 0
    if run_unit_suite():
        rc = 1
    if run_script('sevk_ui', '_browser_faz_tahsilat_sevk_ui_1.py'):
        rc = 1
    if run_script('tcmb_try_ui', '_browser_faz_tahsilat_tcmb_try_ui_1.py'):
        rc = 1
    if browser_ui_lock():
        rc = 1

    out = os.path.join(SHOT, 'regression_report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print('REGRESSION_REPORT', out)
    print('SONUC', 'LOCKED' if rc == 0 else 'FAIL')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
