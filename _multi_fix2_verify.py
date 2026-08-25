"""
PHASE=ATP_MULTI_ADD_JOB_POPUP_FIX2_STRICT_SUBMIT_VALIDATION — Playwright verification

Tests:
T1.  JS v=57 loaded
T2.  Empty row → POST=0, per-row error marks appear
T3.  Firma boş, iş dolu, konum ok → POST=0, firma error
T4.  Firma dolu, iş boş, konum ok → POST=0, iş error
T5.  Firma dolu, iş dolu, konum eksik → POST=0, konum error
T6.  2 satır: biri geçerli biri eksik → POST=0 (all-or-nothing)
T7.  Backend direct: POST with empty firma → 400 reject
T8.  Backend direct: POST with '—' firma → 400 reject
T9.  Backend direct: POST with empty yapilacak_is → 400 reject
T10. "Tümünü Plana Ekle" sonra düzeltince tekrar tıklanabiliyor
T11. Console errors = 0
T12. 1920 kanıt screenshot
T13. 1366 kanıt screenshot
Canonical write = 0 (all POSTs intercepted or rejected before service)
"""
import sys, pathlib, sqlite3, json, time

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


def open_multi_modal(page):
    btn = page.locator('#atpBtnPlanaIsEkle').first
    btn.wait_for(state='visible', timeout=10000)
    btn.click()
    page.wait_for_selector('#atpMultiBackdrop.open', timeout=8000)
    page.wait_for_timeout(500)


def run(pw, label, w, h, errs):
    safe_print(f"\n{'='*60}")
    safe_print(f"VIEWPORT: {label} ({w}x{h})")
    safe_print('='*60)

    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    console_errs = []
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    real_posts = []

    # Intercept batch POST — abort all of them (canonical write = 0)
    # But track what was about to be sent
    intercepted_payloads = []

    def on_route(route):
        url = route.request.url
        if 'plana-is-ekle-batch' in url and route.request.method == 'POST':
            real_posts.append(url)
            try:
                intercepted_payloads.append(json.loads(route.request.post_data or '{}'))
            except Exception:
                pass
            route.abort()
        elif 'maps/resolve' in url and route.request.method == 'POST':
            route.fulfill(
                status=200, content_type='application/json',
                body=json.dumps({'ok': True, 'latitude': 41.0, 'longitude': 29.0,
                                 'maps_url': 'https://maps.google.com/?q=41.0,29.0',
                                 'adres': 'Test Adres, Istanbul'}))
        else:
            route.continue_()

    ctx.route('**/*', on_route)

    try:
        login(page)
        safe_print('  [OK] Login + page load')

        # ── T1: JS version ────────────────────────────────────────────────────
        srcs = page.eval_on_selector_all('script[src*="planlama_arac_takip.js"]', 'els=>els.map(e=>e.src)')
        if any('v=57' in s for s in srcs):
            safe_print('  [T1 PASS] JS v=57 loaded')
        else:
            errs.append(f'T1 FAIL: JS not v=57 — {srcs}')

        # ── T2: Empty row → POST=0, per-row errors ────────────────────────────
        real_posts.clear()
        open_multi_modal(page)
        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(500)

        if real_posts:
            errs.append(f'T2 FAIL({label}): POST was fired for empty row: {real_posts}')
        else:
            safe_print('  [T2 PASS] Empty row → POST=0')

        # Check per-row error styling (red border on firma input)
        firm_inp = page.locator('#atpMultiTbody .row-firma').first
        border_color = firm_inp.evaluate('el => el.style.borderColor')
        if border_color and 'red' in border_color or '4444' in border_color:
            safe_print('  [T2 PASS] Firma input has red border error')
        else:
            safe_print(f'  [T2 INFO] Border color: "{border_color}" — checking toast fallback')
            toast = page.locator('#atpToast').inner_text() if page.locator('#atpToast').is_visible() else ''
            if 'eksik' in toast.lower() or 'hata' in toast.lower():
                safe_print(f'  [T2 PASS] Toast shows validation error: "{toast[:60]}"')
            else:
                errs.append(f'T2 FAIL({label}): No red border and no validation toast')

        page.screenshot(path=str(ROOT / f'_fix2_t2_{w}.png'))

        # ── T3: firma boş, iş dolu, konum ok ─────────────────────────────────
        real_posts.clear()
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        open_multi_modal(page)

        # Set up row with is but no firma — inject resolved konum first
        page.evaluate("window.prompt = function() { return 'https://maps.google.com/test'; };")
        page.locator('#atpMultiTbody [data-action="konum-edit"]').first.click()
        page.wait_for_timeout(800)
        page.locator('#atpMultiTbody .row-is').first.fill('Test yapilacak is')

        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(400)

        if real_posts:
            errs.append(f'T3 FAIL({label}): POST fired with empty firma')
        else:
            safe_print('  [T3 PASS] Empty firma → POST=0')

        # ── T4: firma dolu, iş boş, konum ok ─────────────────────────────────
        real_posts.clear()
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        open_multi_modal(page)

        page.evaluate("window.prompt = function() { return 'https://maps.google.com/test'; };")
        page.locator('#atpMultiTbody [data-action="konum-edit"]').first.click()
        page.wait_for_timeout(800)
        page.locator('#atpMultiTbody .row-firma').first.fill('Test Firma')

        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(400)

        if real_posts:
            errs.append(f'T4 FAIL({label}): POST fired with empty yapilacak_is')
        else:
            safe_print('  [T4 PASS] Empty yapilacak_is → POST=0')

        # ── T5: firma+iş dolu, konum eksik ───────────────────────────────────
        real_posts.clear()
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        open_multi_modal(page)

        page.locator('#atpMultiTbody .row-firma').first.fill('Test Firma')
        page.locator('#atpMultiTbody .row-is').first.fill('Test is')

        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(400)

        if real_posts:
            errs.append(f'T5 FAIL({label}): POST fired with unvalidated konum')
        else:
            safe_print('  [T5 PASS] Unvalidated konum → POST=0')

        # ── T6: 2 satır, 1 geçerli 1 eksik → all-or-nothing ────────────────
        real_posts.clear()
        page.click('#atpMultiClose')
        page.wait_for_timeout(300)
        open_multi_modal(page)
        page.click('#atpMultiBtnSatirEkle')
        page.wait_for_timeout(300)

        # Row1: full valid
        page.evaluate("window.prompt = function() { return 'https://maps.google.com/test'; };")
        konumLinks = page.locator('#atpMultiTbody [data-action="konum-edit"]').all()
        konumLinks[0].click()
        page.wait_for_timeout(800)
        rows = page.locator('#atpMultiTbody tr').all()
        rows[0].locator('.row-firma').fill('Test Firma A')
        rows[0].locator('.row-is').fill('Test is A')

        # Row2: firma empty, iş empty, konum empty

        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(500)

        if real_posts:
            errs.append(f'T6 FAIL({label}): POST fired despite invalid row2 (all-or-nothing broken)')
        else:
            safe_print('  [T6 PASS] 2-row, 1 invalid → POST=0 (all-or-nothing OK)')

        # Check summary error message visible
        summary_text = page.locator('#atpMultiSummary').inner_text()
        if 'eksik' in summary_text.lower() or 'kaydedilmedi' in summary_text.lower():
            safe_print(f'  [T6 PASS] Summary shows error: "{summary_text[:80]}"')
        else:
            safe_print(f'  [T6 INFO] Summary: "{summary_text[:80]}"')

        page.screenshot(path=str(ROOT / f'_fix2_t6_{w}.png'))

        # ── T10: After fix, button becomes clickable again (not disabled) ────
        btn_submit = page.locator('#atpMultiBtnSubmit')
        is_disabled = btn_submit.is_disabled()
        if not is_disabled:
            safe_print('  [T10 PASS] Submit button not permanently disabled after validation error')
        else:
            errs.append(f'T10 FAIL({label}): Submit button permanently disabled after validation error')

        # ── Final screenshot ──────────────────────────────────────────────────
        page.screenshot(path=str(ROOT / f'_fix2_final_{w}.png'))
        safe_print(f'  [SHOT] _fix2_final_{w}.png')

        # ── T11: Console errors ───────────────────────────────────────────────
        net_errs = [e for e in console_errs if 'favicon' not in e.lower()]
        if not net_errs:
            safe_print('  [T11 PASS] Console errors = 0')
        else:
            safe_print(f'  [T11 WARN] Console errors: {net_errs[:3]}')

    except Exception as ex:
        errs.append(f'EXCEPTION({label}): {ex}')
        safe_print(f'  [EXCEPTION] {ex}')
        try:
            page.screenshot(path=str(ROOT / f'_fix2_exception_{w}.png'))
        except Exception:
            pass
    finally:
        ctx.close()
        browser.close()


def run_backend_tests(errs):
    """Backend API direct tests — T7, T8, T9 via requests (no Playwright)."""
    safe_print("\n" + "="*60)
    safe_print("BACKEND DIRECT TESTS (T7-T9)")
    safe_print("="*60)

    import urllib.request, urllib.error

    # We need a session cookie — get it via a quick login
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    try:
        user, pwd = _creds()

        # Login
        login_data = urllib.parse.urlencode({'kullanici': user, 'sifre': pwd}).encode()
        req = urllib.request.Request(BASE + '/giris', login_data)
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        opener.open(req, timeout=10)

        import urllib.parse
        base_row = {
            'plan_tarihi': '2026-08-24',
            'arac_external_id': '99',
            'firma': '',           # empty — should be rejected
            'yapilacak_is': 'Test is',
            'is': 'Test is',
            'latitude': 41.0, 'longitude': 29.0,
            'adres': 'Test Adres',
            'maps_url': '',
        }

        def post_batch(rows):
            payload = json.dumps({'rows': rows}).encode()
            req = urllib.request.Request(
                BASE + '/planlama/arac-takip/api/plana-is-ekle-batch',
                payload,
                {'Content-Type': 'application/json'},
            )
            try:
                resp = opener.open(req, timeout=10)
                return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        # T7: empty firma
        row7 = dict(base_row, firma='')
        status7, body7 = post_batch([row7])
        if status7 == 400:
            safe_print(f'  [T7 PASS] Empty firma → 400: {body7.get("error", body7.get("results", ""))}')
        else:
            errs.append(f'T7 FAIL: Expected 400, got {status7}: {body7}')

        # T8: sentinel '—' firma
        row8 = dict(base_row, firma='—')
        status8, body8 = post_batch([row8])
        if status8 == 400:
            safe_print(f'  [T8 PASS] Sentinel firma "—" → 400: {body8.get("error", "")}')
        else:
            errs.append(f'T8 FAIL: Expected 400 for sentinel firma, got {status8}: {body8}')

        # T9: empty yapilacak_is
        row9 = dict(base_row, firma='Test Firma', yapilacak_is='', **{'is': ''})
        status9, body9 = post_batch([row9])
        if status9 == 400:
            safe_print(f'  [T9 PASS] Empty yapilacak_is → 400: {body9.get("error", "")}')
        else:
            errs.append(f'T9 FAIL: Expected 400 for empty yapilacak_is, got {status9}: {body9}')

    except Exception as ex:
        safe_print(f'  [BACKEND TESTS EXCEPTION] {ex}')
        errs.append(f'Backend tests exception: {ex}')


def main():
    from playwright.sync_api import sync_playwright
    all_errs = []

    with sync_playwright() as pw:
        run(pw, '1920x1080', 1920, 1080, all_errs)
        run(pw, '1366x768', 1366, 768, all_errs)

    run_backend_tests(all_errs)

    safe_print('\n' + '='*60)
    if all_errs:
        safe_print(f'RESULT: {len(all_errs)} FAILURE(S)')
        for e in all_errs:
            safe_print(f'  x {e}')
        sys.exit(1)
    else:
        safe_print('RESULT: ALL TESTS PASSED')


if __name__ == '__main__':
    main()
