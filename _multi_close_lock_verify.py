"""
PHASE=ATP_MULTI_MODAL_CLOSE_FINAL_LOCK_X_CANCEL_ONLY
Verify: only X, Cancel, submit_ok close. Backdrop NEVER closes.
"""
import json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', 'replace').decode('ascii'))


def _creds():
    con = sqlite3.connect(str(ROOT / 'app' / 'mock_data.db'))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return row[0], row[1]


def login(page):
    user, pwd = _creds()
    page.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd)
    page.click('button[type="submit"]')
    page.wait_for_url('**/', timeout=20000)
    page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(1200)


def is_open(page):
    return page.locator('#atpMultiBackdrop.open').count() > 0


def open_multi(page):
    if is_open(page):
        return
    page.locator('#atpBtnPlanaIsEkle').first.click()
    page.wait_for_selector('#atpMultiBackdrop.open', timeout=10000)
    page.wait_for_timeout(500)


def run(pw, label, w, h, errs):
    safe_print(f"\n{'='*60}\nVIEWPORT: {label}\n{'='*60}")

    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    console_errs = []
    posts = []
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    def on_route(route):
        if 'plana-is-ekle' in route.request.url and route.request.method == 'POST':
            posts.append(route.request.url)
            route.abort()
        elif 'maps/resolve' in route.request.url:
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'ok': True, 'latitude': 41.0, 'longitude': 29.0, 'adres': 'Test'}))
        else:
            route.continue_()
    ctx.route('**/*', on_route)

    try:
        login(page)
        src = page.eval_on_selector('script[src*="planlama_arac_takip.js"]', 'e=>e.src')
        if 'v=60' in src:
            safe_print('  [T0 PASS] JS v=60')
        else:
            errs.append(f'T0 FAIL({label}): {src}')

        open_multi(page)
        modal = page.locator('#atpMultiModal').bounding_box()
        backdrop = page.locator('#atpMultiBackdrop').bounding_box()
        mx, my, mw, mh = modal['x'], modal['y'], modal['width'], modal['height']

        def chk(name, still_open_expected=True):
            ok = is_open(page) == still_open_expected
            safe_print(f"  [{name}] {'PASS' if ok else 'FAIL'} open={is_open(page)}")
            if not ok:
                errs.append(f'{name} FAIL({label})')
            return ok

        # T1-T6 internal — must stay open
        for nm, x, y in [
            ('T1_header', mx + 40, my + 18),
            ('T2_footer', mx + 30, my + mh - 20),
            ('T3_table', mx + mw * 0.7, my + 200),
            ('T4_body', mx + mw * 0.5, my + mh * 0.5),
            ('T5_map', mx + mw * 0.2, my + mh * 0.72),
            ('T6_info', mx + mw * 0.75, my + mh * 0.72),
        ]:
            open_multi(page)
            page.mouse.click(x, y)
            page.wait_for_timeout(300)
            chk(nm, True)

        # T7 backdrop — must NOT close (KEY TEST)
        open_multi(page)
        click_x = max(backdrop['x'] + 10, mx - 25)
        click_y = my + mh / 2
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(400)
        chk('T7_backdrop_NO_CLOSE', True)
        page.screenshot(path=str(ROOT / f'_lock_backdrop_{w}.png'))

        # T8 text drag
        open_multi(page)
        f = page.locator('.row-firma').first.bounding_box()
        page.mouse.move(f['x'] + 5, f['y'] + f['height'] / 2)
        page.mouse.down()
        page.mouse.move(click_x, click_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)
        chk('T8_text_drag', True)

        # T9 validation error — must stay open, no POST
        open_multi(page)
        posts.clear()
        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(500)
        chk('T9_validation_stays_open', True)
        if posts:
            errs.append(f'T9 POST leaked({label})')

        # T10 X closes
        open_multi(page)
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        chk('T10_x_closes', False)

        # T11 Cancel closes
        open_multi(page)
        page.click('#atpMultiBtnCancel')
        page.wait_for_timeout(300)
        chk('T11_cancel_closes', False)

        page.screenshot(path=str(ROOT / f'_lock_final_{w}.png'))

        net = [e for e in console_errs if 'favicon' not in e.lower()]
        if not net:
            safe_print('  [T12 PASS] console=0')
        else:
            errs.append(f'console({label}): {net[:2]}')

    except Exception as ex:
        errs.append(f'EXCEPTION({label}): {ex}')
        safe_print(f'  EXCEPTION: {ex}')
    finally:
        ctx.close()
        browser.close()


def main():
    from playwright.sync_api import sync_playwright
    errs = []
    with sync_playwright() as pw:
        run(pw, '1920', 1920, 1080, errs)
        run(pw, '1366', 1366, 768, errs)

    safe_print('\n' + '='*60)
    if errs:
        safe_print(f'FAIL: {len(errs)}')
        for e in errs:
            safe_print(f'  x {e}')
        sys.exit(1)
    safe_print('ALL TESTS PASSED')


if __name__ == '__main__':
    main()
