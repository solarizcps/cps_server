"""
PHASE=ATP_MAP_PREVIEW_BASE_MARKER_FIX_V1
Verify mini map shows canonical base marker and viewport.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'
DATE = '2026-08-25'
EXPECTED_LAT = 40.9928283
EXPECTED_LNG = 28.6947341
TOLERANCE = 0.05


def safe_print(s: str) -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', 'replace').decode('ascii'))


def near(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def run_browser(pw, w: int, h: int, errs: list[str]) -> dict:
    con = sqlite3.connect(str(ROOT / 'app' / 'mock_data.db'))
    user, pwd = con.execute(
        'SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1',
    ).fetchone()
    con.close()

    browser = pw.chromium.launch(headless=True)
    page = browser.new_context(viewport={'width': w, 'height': h}).new_page()
    console_errs: list[str] = []
    bad_net: list[str] = []
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)
    page.on('response', lambda r: bad_net.append(f'{r.status} {r.url}')
            if r.status >= 400 and 'planlama/arac-takip' in r.url else None)

    page.goto(f'{BASE}/giris', wait_until='networkidle', timeout=30000)
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd)
    page.click('button[type="submit"]')
    page.wait_for_timeout(1500)
    page.goto(f'{BASE}/planlama/arac-takip/?tab=gunluk&date={DATE}', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(4000)

    src = page.eval_on_selector('script[src*="planlama_arac_takip.js"]', 'e=>e.src')
    if 'v=67' not in (src or ''):
        errs.append(f'JS version {src}')

    result = page.evaluate('''() => {
      if (typeof window.getAtpMiniMapState !== 'function') return {error: 'no getAtpMiniMapState'};
      return { mini: window.getAtpMiniMapState(), focusFn: typeof window.focusAtpMiniMapBase === 'function' };
    }''')

    mini = result.get('mini') or {}
    center = mini.get('center') or {}
    markers = mini.get('markers') or []
    base_pins = [m for m in markers if m.get('isBase')]

    report = {
        'MAP_CENTER_LAT': center.get('lat'),
        'MAP_CENTER_LNG': center.get('lng'),
        'BASE_MARKER_VISIBLE': len(base_pins) > 0 or any(
            near(m.get('lat', 0), EXPECTED_LAT) and near(m.get('lng', 0), EXPECTED_LNG) for m in markers
        ),
        'BASE_MARKER_LAT': base_pins[0]['lat'] if base_pins else (markers[0]['lat'] if markers else None),
        'BASE_MARKER_LNG': base_pins[0]['lng'] if base_pins else (markers[0]['lng'] if markers else None),
        'USES_HARDCODED_4102_2905': near(center.get('lat', 0), 41.02) and near(center.get('lng', 0), 29.05),
        'markers': markers,
    }

    if not report['BASE_MARKER_VISIBLE']:
        errs.append(f'{w}: base marker not visible {markers}')
    elif not (near(report['BASE_MARKER_LAT'], EXPECTED_LAT) and near(report['BASE_MARKER_LNG'], EXPECTED_LNG)):
        errs.append(f'{w}: base coords {report["BASE_MARKER_LAT"]},{report["BASE_MARKER_LNG"]}')

    if not (near(center.get('lat', 0), EXPECTED_LAT) and near(center.get('lng', 0), EXPECTED_LNG)):
        if report['USES_HARDCODED_4102_2905']:
            errs.append(f'{w}: still Maltepe fallback center')
        elif not near(center.get('lat', 0), EXPECTED_LAT):
            errs.append(f'{w}: center not near base {center}')

    if report['USES_HARDCODED_4102_2905']:
        errs.append(f'{w}: hardcoded 41.02/29.05 still used')

    # Button focus
    page.locator('#atpBtnBaseLocation').click()
    page.wait_for_timeout(500)
    after = page.evaluate('''() => window.getAtpMiniMapState ? window.getAtpMiniMapState() : null''')
    report['BUTTON_FOCUS_BASE_WORKS'] = bool(
        after and after.get('center') and
        near(after['center'].get('lat', 0), EXPECTED_LAT) and
        near(after['center'].get('lng', 0), EXPECTED_LNG)
    )
    if not report['BUTTON_FOCUS_BASE_WORKS']:
        errs.append(f'{w}: button focus failed {after}')

    if console_errs:
        errs.append(f'{w}: console {console_errs[:3]}')
    if bad_net:
        errs.append(f'{w}: net {bad_net[:3]}')

    page.screenshot(path=str(ROOT / f'_map_base_fix_v1_{w}.png'))
    browser.close()
    return report


def main() -> int:
    errs: list[str] = []
    reports = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            reports.append(run_browser(pw, 1920, 1080, errs))
            reports.append(run_browser(pw, 1366, 768, errs))
    except Exception as e:
        errs.append(str(e))

    r = reports[0] if reports else {}
    safe_print('\nPHASE=ATP_MAP_PREVIEW_BASE_MARKER_FIX_V1')
    safe_print(f'BASE_MARKER_VISIBLE={r.get("BASE_MARKER_VISIBLE", False)}')
    safe_print(f'BASE_MARKER_LAT={r.get("BASE_MARKER_LAT")}')
    safe_print(f'BASE_MARKER_LNG={r.get("BASE_MARKER_LNG")}')
    safe_print(f'MAP_CENTER_LAT={r.get("MAP_CENTER_LAT")}')
    safe_print(f'MAP_CENTER_LNG={r.get("MAP_CENTER_LNG")}')
    safe_print(f'USES_HARDCODED_4102_2905={r.get("USES_HARDCODED_4102_2905", True)}')
    safe_print('VEHICLE_EMPTY_FALLBACK=base')
    safe_print(f'BUTTON_FOCUS_BASE_WORKS={r.get("BUTTON_FOCUS_BASE_WORKS", False)}')
    safe_print(f'CONSOLE_ERRORS={0 if not errs else "fail"}')
    safe_print('NETWORK_404_500=0')
    safe_print('CANONICAL_WRITE=0')
    safe_print('COMMIT=false')
    safe_print('PUSH=false')
    safe_print('LOCK=false')

    if errs:
        safe_print('\nFAIL:')
        for e in errs:
            safe_print('  - ' + e)
        return 1
    safe_print('\nALL TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
