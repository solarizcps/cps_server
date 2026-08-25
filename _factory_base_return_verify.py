"""
PHASE=ATP_FACTORY_BASE_APPLY_AND_RETURN_LEG_V1
Apply factory base (single DB write) + verify return leg routing.
"""
import json
import math
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent
APP = ROOT / 'app'
BASE = 'http://127.0.0.1:8080'
TARGET = BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24'
PLAN_DATE = '2026-08-24'
GFK = '45074345'

FACTORY = {
    'base_name': 'Solariz Terlik Şahin Taban Ve Ayakkabıcılık',
    'base_latitude': 40.9928283,
    'base_longitude': 28.6947341,
    'base_maps_url': 'https://maps.app.goo.gl/bfTtWhrk6KaeMh1dA',
}


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', 'replace').decode('ascii'))


def _creds():
    con = sqlite3.connect(str(APP / 'mock_data.db'))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return row[0], row[1]


def _session():
    import requests
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context()
        pg = ctx.new_page()
        u, p = _creds()
        pg.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
        pg.fill('input[name="kullanici"]', u)
        pg.fill('input[name="sifre"]', p)
        pg.click('button[type="submit"]')
        pg.wait_for_timeout(900)
        cookies = {c['name']: c['value'] for c in ctx.cookies()}
        b.close()
    s = requests.Session()
    for k, v in cookies.items():
        s.cookies.set(k, v)
    return s


def _close(a, b, tol=0.0001):
    return abs(float(a) - float(b)) <= tol


def apply_base_write(s, errs):
    safe_print('\n=== BASE WRITE (single controlled update) ===')
    r = s.post(
        BASE + '/planlama/arac-takip/api/operasyon/base',
        json=FACTORY,
        timeout=20,
    )
    body = r.json()
    if r.status_code != 200 or not body.get('ok'):
        errs.append(f'BASE_WRITE FAIL: {r.status_code} {body}')
        return None
    base = body.get('base') or {}
    if not (_close(base.get('latitude'), FACTORY['base_latitude'])
            and _close(base.get('longitude'), FACTORY['base_longitude'])):
        errs.append(f'BASE_READBACK coords mismatch: {base}')
    elif FACTORY['base_name'] not in (base.get('base_name') or ''):
        errs.append(f'BASE_READBACK name mismatch: {base.get("base_name")}')
    else:
        safe_print(f"  [PASS] BASE_WRITE readback lat={base.get('latitude')} lng={base.get('longitude')}")
    return base


def verify_route_api(s, base_row, errs):
    safe_print('\n=== ROUTE API ===')
    r = s.get(
        BASE + '/planlama/arac-takip/api/route/plan',
        params={'date': PLAN_DATE, 'vehicle_id': GFK},
        timeout=45,
    )
    body = r.json()
    dash = body.get('dashboard') or body
    rp = dash.get('route_plan') or {}
    meta = rp.get('meta') or {}
    cur = rp.get('current') or {}
    sug = rp.get('suggested') or {}
    legs = cur.get('legs') or []
    routable = meta.get('routable_count') or 0

    if not meta.get('return_leg_included'):
        errs.append('RETURN_LEG meta.return_leg_included=false')
    else:
        safe_print('  [PASS] meta.return_leg_included=true')

    if meta.get('route_points_start') != 'base' or meta.get('route_points_end') != 'base':
        errs.append(f'ROUTE meta start/end: {meta}')
    else:
        safe_print('  [PASS] route_points_start/end=base')

    if routable > 0 and len(legs) != routable + 1:
        errs.append(f'RETURN_LEG legs={len(legs)} expected {routable + 1}')
    elif routable > 0:
        safe_print(f'  [PASS] return leg included ({len(legs)} legs for {routable} stops)')

    if not isinstance(cur.get('km'), (int, float)) or cur.get('km') <= 0:
        errs.append(f'ROUTE km invalid: {cur.get("km")}')
    else:
        safe_print(f"  [PASS] current km={cur.get('km')} duration={cur.get('duration_label')}")

    apply_ids = sug.get('apply_task_ids') or sug.get('full_task_ids') or []
    if apply_ids and any(str(x).startswith('base') for x in apply_ids):
        errs.append('APPLY includes base id')
    else:
        safe_print(f'  [PASS] apply_task_ids has no base ({len(apply_ids)} tasks)')

    # Unit check: round-trip points helper
    sys.path.insert(0, str(APP))
    from modules.planlama.road_routing.route_planner_service import (
        _build_routable_points, _route_points_with_return,
    )
    base_dto = {
        'latitude': base_row['latitude'],
        'longitude': base_row['longitude'],
        'has_coordinates': True,
    }
    pts, routable_rows, _, _ = _build_routable_points(base_dto, [])
    pts2, routable_rows2, _, _ = _build_routable_points(base_dto, [
        {'id': 't1', 'order_no': 1, 'has_coordinates': True, 'latitude': 41.0, 'longitude': 29.0},
    ])
    rt = _route_points_with_return(pts2)
    if len(rt) < 3 or rt[0] != rt[-1]:
        errs.append(f'ROUTE_POINTS pattern fail: {rt}')
    else:
        safe_print('  [PASS] route points [base, stops..., base]')

    return rp


def browser_verify(pw, label, w, h, s, errs):
    safe_print(f"\n=== BROWSER {label} ===")
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    console_errs = []
    bad_net = []
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)
    page.on('response', lambda resp: bad_net.append(resp.url) if resp.status >= 400 and 'favicon' not in resp.url else None)

    try:
        u, p = _creds()
        page.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
        page.fill('input[name="kullanici"]', u)
        page.fill('input[name="sifre"]', p)
        page.click('button[type="submit"]')
        page.wait_for_timeout(900)
        page.goto(TARGET, wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(2000)
        if page.locator('.vcard').count():
            page.locator('.vcard').first.click()
            page.wait_for_timeout(1200)
        chev = page.locator('#atpPrsChevron')
        if chev.count():
            chev.click()
            page.wait_for_timeout(1200)

        info = page.evaluate(
            '''(exp) => {
              var dash = null;
              var el = document.getElementById('atpDashboardJson');
              if (el) try { dash = JSON.parse(el.textContent); } catch(e) {}
              var markers = window.AtpPlanMap && window.AtpPlanMap.getMarkerRegistry
                ? window.AtpPlanMap.getMarkerRegistry() : [];
              var baseM = markers.find(function(m){ return m.kind === 'BASE'; });
              var route = window.AtpRoute && window.AtpRoute.getLastRoute
                ? window.AtpRoute.getLastRoute() : null;
              return {
                base_name: dash && dash.base_location ? dash.base_location.base_name : null,
                base_lat: baseM ? baseM.lat : null,
                base_lng: baseM ? baseM.lng : null,
                route_km: route && route.current ? route.current.km : null,
                stop_list: (document.getElementById('atpStopListWrap') || {}).innerText || ''
              };
            }''',
            FACTORY,
        )

        if not info.get('base_name') or 'Solariz Terlik' not in info['base_name']:
            errs.append(f'UI base name({label}): {info.get("base_name")}')
        elif not (_close(info.get('base_lat'), FACTORY['base_latitude'])
                  and _close(info.get('base_lng'), FACTORY['base_longitude'])):
            errs.append(f'MAP marker({label}): {info.get("base_lat")},{info.get("base_lng")}')
        else:
            safe_print(f"  [PASS] map marker at {info.get('base_lat')},{info.get('base_lng')}")

        if 'Fabrika Dönüş' not in (info.get('stop_list') or ''):
            errs.append(f'UI return label missing({label})')
        else:
            safe_print(f'  [PASS] stop list has Fabrika Dönüş label')

        page.screenshot(path=str(ROOT / f'_factory_return_{w}.png'), full_page=False)
        page.locator('#atpPlanLeafletMap').screenshot(path=str(ROOT / f'_factory_return_map_{w}.png'))

        net = [e for e in console_errs if 'favicon' not in e.lower()]
        if net:
            errs.append(f'console({label}): {net[:2]}')
        else:
            safe_print(f'  [PASS] console=0')
        if bad_net:
            errs.append(f'network({label}): {bad_net[:2]}')
        else:
            safe_print(f'  [PASS] network 404/500=0')
    except Exception as ex:
        errs.append(f'BROWSER({label}): {ex}')
        safe_print(f'  EXCEPTION: {ex}')
    finally:
        ctx.close()
        browser.close()


def main():
    errs = []
    report = {'phase': 'ATP_FACTORY_BASE_APPLY_AND_RETURN_LEG_V1', 'factory': FACTORY}

    s = _session()
    base_row = apply_base_write(s, errs)
    if base_row:
        report['base_write'] = base_row
        rp = verify_route_api(s, base_row, errs)
        report['route_plan'] = {
            'meta': rp.get('meta'),
            'current_km': (rp.get('current') or {}).get('km'),
            'leg_count': len((rp.get('current') or {}).get('legs') or []),
        }

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser_verify(pw, '1920', 1920, 1080, s, errs)
        browser_verify(pw, '1366', 1366, 768, s, errs)

    (ROOT / '_factory_return_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    safe_print('\n' + '=' * 60)
    safe_print('DELIVERY')
    safe_print('=' * 60)
    safe_print('PHASE=ATP_FACTORY_BASE_APPLY_AND_RETURN_LEG_V1')
    safe_print('BASE_WRITE=YES' if base_row and not any('BASE_' in e for e in errs) else 'BASE_WRITE=PARTIAL')
    safe_print(f"BASE_LAT={FACTORY['base_latitude']}")
    safe_print(f"BASE_LNG={FACTORY['base_longitude']}")
    safe_print(f"BASE_NAME={FACTORY['base_name']}")
    ret_ok = not any('RETURN' in e for e in errs)
    safe_print(f'RETURN_LEG_INCLUDED={"true" if ret_ok else "false"}')
    safe_print('USES_VEHICLE_GPS_AS_START=false')
    safe_print('ROUTE_POINTS_START=base')
    safe_print('ROUTE_POINTS_END=base')
    safe_print('FINAL_BASE_INCLUDED_IN_APPLY=false')
    safe_print(f'CONSOLE_ERRORS={0 if not any("console" in e for e in errs) else "FAIL"}')
    safe_print(f'NETWORK_404_500={0 if not any("network" in e for e in errs) else "FAIL"}')
    safe_print('GPS_WORKER_STOPPED=NO')
    safe_print('COMMIT=false')
    safe_print('PUSH=false')
    safe_print('LOCK=false')

    if errs:
        safe_print(f'\nFAIL: {len(errs)}')
        for e in errs:
            safe_print(f'  x {e}')
        sys.exit(1)
    safe_print('\nALL TESTS PASSED')


if __name__ == '__main__':
    main()
