"""
PHASE=ATP_MULTI_ADD_JOB_POPUP_FIX3_NO_INTERNAL_BLANK_CLOSE
Playwright verification — modal must NOT close on internal blank clicks.
"""
import sys, pathlib, sqlite3, json

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', 'replace').decode('ascii'))


def _creds():
    db = ROOT / 'app' / 'mock_data.db'
    if not db.exists():
        return 'admin', 'admin123'
    con = sqlite3.connect(str(db))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return (row[0], row[1]) if row else ('admin', 'admin123')


def login(page):
    user, pwd = _creds()
    page.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd)
    page.click('button[type="submit"]')
    page.wait_for_url('**/', timeout=20000)
    page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24',
              wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(1500)


def is_open(page):
    return page.locator('#atpMultiBackdrop.open').is_visible()


def open_multi(page):
    if page.locator('#atpMultiBackdrop.open').is_visible():
        return
    page.locator('#atpBtnPlanaIsEkle').first.click()
    page.wait_for_selector('#atpMultiBackdrop.open', timeout=8000)
    page.wait_for_timeout(500)


def close_multi(page):
    if not page.locator('#atpMultiBackdrop.open').is_visible():
        return
    page.click('#atpMultiClose')
    page.wait_for_timeout(300)


def run(pw, label, w, h, errs):
    safe_print(f"\n{'='*60}\nVIEWPORT: {label}\n{'='*60}")

    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    console_errs = []
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    real_posts = []

    def on_route(route):
        if 'plana-is-ekle' in route.request.url and route.request.method == 'POST':
            real_posts.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    ctx.route('**/*', on_route)

    try:
        login(page)

        srcs = page.eval_on_selector_all('script[src*="planlama_arac_takip.js"]', 'els=>els.map(e=>e.src)')
        if any('v=59' in s for s in srcs):
            safe_print('  [T0 PASS] JS v=59 loaded')
        else:
            errs.append(f'T0 FAIL({label}): JS not v=59 — {srcs}')

        open_multi(page)

        modal = page.locator('#atpMultiModal')
        backdrop = page.locator('#atpMultiBackdrop')

        # T1: white empty area inside modal (click header padding)
        open_multi(page)
        box = modal.bounding_box()
        # click near top-left inside modal white area (header padding)
        page.mouse.click(box['x'] + 30, box['y'] + 20)
        page.wait_for_timeout(300)
        if is_open(page):
            safe_print('  [T1 PASS] Header blank click — stays open')
        else:
            errs.append(f'T1 FAIL({label}): closed on header blank click')

        # T2: footer blank
        open_multi(page)
        footer = page.locator('.atp-multi-footer')
        footer.click(position={'x': 10, 'y': 10})
        page.wait_for_timeout(300)
        if is_open(page):
            safe_print('  [T2 PASS] Footer blank click — stays open')
        else:
            errs.append(f'T2 FAIL({label}): closed on footer blank click')

        # T3: table empty cell (durum column)
        open_multi(page)
        page.locator('#atpMultiTbody tr').first.locator('.col-durum').click(force=True)
        page.wait_for_timeout(300)
        if is_open(page):
            safe_print('  [T3 PASS] Table cell click — stays open')
        else:
            errs.append(f'T3 FAIL({label}): closed on table cell click')

        # T4: mini map area
        open_multi(page)
        map_el = page.locator('#atpMultiMapMini')
        if map_el.count():
            map_el.click()
            page.wait_for_timeout(300)
            if is_open(page):
                safe_print('  [T4 PASS] Mini map click — stays open')
            else:
                errs.append(f'T4 FAIL({label}): closed on mini map click')
        else:
            safe_print('  [T4 SKIP] no map el')

        # T5: info panel
        open_multi(page)
        page.locator('.atp-multi-info-panel').click()
        page.wait_for_timeout(300)
        if is_open(page):
            safe_print('  [T5 PASS] Info panel click — stays open')
        else:
            errs.append(f'T5 FAIL({label}): closed on info panel click')

        # T6: blur input by clicking modal body blank
        open_multi(page)
        page.locator('#atpMultiTbody .row-firma').first.click()
        page.locator('.atp-multi-top-info').click()
        page.wait_for_timeout(300)
        if is_open(page):
            safe_print('  [T6 PASS] Input blur via internal click — stays open')
        else:
            errs.append(f'T6 FAIL({label}): closed when blurring input via internal click')

        # T7: real backdrop hit-layer click — should close
        open_multi(page)
        hit = page.locator('#atpMultiBackdrop')
        bb = hit.bounding_box()
        mb = modal.bounding_box()
        # click left of modal on gray overlay (hit layer, not modal)
        click_x = max(bb['x'] + 8, mb['x'] - 20)
        click_y = mb['y'] + mb['height'] / 2
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(400)
        if not is_open(page):
            safe_print('  [T7 PASS] Real backdrop click — closes')
        else:
            errs.append(f'T7 FAIL({label}): did not close on real backdrop click')

        # T8: X button
        open_multi(page)
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        if not is_open(page):
            safe_print('  [T8 PASS] X button — closes')
        else:
            errs.append(f'T8 FAIL({label}): X did not close')

        # T9: Cancel
        open_multi(page)
        page.click('#atpMultiBtnCancel')
        page.wait_for_timeout(300)
        if not is_open(page):
            safe_print('  [T9 PASS] Cancel — closes')
        else:
            errs.append(f'T9 FAIL({label}): Cancel did not close')

        # T10: text selection drag from input toward backdrop
        open_multi(page)
        firma = page.locator('#atpMultiTbody .row-firma').first
        firma.click()
        firma.type('TEST', delay=30)
        box_f = firma.bounding_box()
        page.mouse.move(box_f['x'] + 5, box_f['y'] + box_f['height'] / 2)
        page.mouse.down()
        page.mouse.move(click_x, click_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)
        if is_open(page):
            safe_print('  [T10 PASS] Text selection drag — stays open')
        else:
            errs.append(f'T10 FAIL({label}): closed during text selection drag')

        page.screenshot(path=str(ROOT / f'_fix3_final_{w}.png'))

        net_errs = [e for e in console_errs if 'favicon' not in e.lower()]
        if not net_errs:
            safe_print('  [T11 PASS] Console errors = 0')
        else:
            safe_print(f'  [T11 WARN] {net_errs[:2]}')

        if real_posts:
            errs.append(f'POST FAIL({label}): {real_posts}')
        else:
            safe_print('  [T12 PASS] Canonical POST = 0')

    except Exception as ex:
        errs.append(f'EXCEPTION({label}): {ex}')
        safe_print(f'  [EXCEPTION] {ex}')
        try:
            page.screenshot(path=str(ROOT / f'_fix3_exception_{w}.png'))
        except Exception:
            pass
    finally:
        ctx.close()
        browser.close()


def main():
    from playwright.sync_api import sync_playwright
    all_errs = []
    with sync_playwright() as pw:
        run(pw, '1920x1080', 1920, 1080, all_errs)
        run(pw, '1366x768', 1366, 768, all_errs)

    safe_print('\n' + '='*60)
    if all_errs:
        safe_print(f'RESULT: {len(all_errs)} FAILURE(S)')
        for e in all_errs:
            safe_print(f'  x {e}')
        sys.exit(1)
    safe_print('RESULT: ALL TESTS PASSED')


if __name__ == '__main__':
    main()
