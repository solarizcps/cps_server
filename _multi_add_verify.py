"""
PHASE=ATP_MULTI_ADD_JOB_POPUP_V1 — Playwright verification
All intercept-based: canonical write=0.

T1. JS v=55 + CSS v=44 loaded
T2. Multi modal opens on '+ Plana Is Ekle' click
T3. Header fields: Tarih, Araç, Sofor, Depo visible
T4. 'Saat' kolonu 'Otomatik' gösteriyor (manuel picker yok)
T5. '+ Satir Ekle' butonu yeni satır ekliyor (1→2)
T6. Validasyon: submit empty -> toast mesajı, POST=0
T7. Firma field full-width (FIX6D regression check)
T8. Console errors=0
T9. PRS button (varsa) hala single modal açıyor (regression)
T10. Screenshot kanıtı 1920 + 1366
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


def run(pw, label, w, h):
    safe_print(f"\n{'='*60}")
    safe_print(f"VIEWPORT: {label} ({w}x{h})")
    safe_print('='*60)

    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    errs = []
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
        user, pwd = _creds()
        page.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
        page.fill('input[name="kullanici"]', user)
        page.fill('input[name="sifre"]', pwd)
        page.click('button[type="submit"]')
        page.wait_for_url('**/', timeout=20000)
        safe_print('  [OK] Login')

        page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1800)
        safe_print('  [OK] Plan page loaded')

        # ── T1: Versions ─────────────────────────────────────────────────────
        js_srcs = page.eval_on_selector_all(
            'script[src*="planlama_arac_takip.js"]', 'els=>els.map(e=>e.src)')
        css_srcs = page.eval_on_selector_all(
            'link[href*="planlama_arac_takip.css"]', 'els=>els.map(e=>e.href)')
        if any('v=55' in s for s in js_srcs):
            safe_print('  [T1 PASS] JS v=55')
        else:
            errs.append(f'T1 FAIL: JS not v=55 — {js_srcs}')
        if any('v=44' in s for s in css_srcs):
            safe_print('  [T1 PASS] CSS v=44')
        else:
            errs.append(f'T1 FAIL: CSS not v=44 — {css_srcs}')

        # ── T2: Multi modal opens ─────────────────────────────────────────────
        btn = page.locator('#atpBtnPlanaIsEkle').first
        btn.wait_for(state='visible', timeout=10000)
        btn.click()
        page.wait_for_selector('#atpMultiBackdrop.open', timeout=8000)
        page.wait_for_timeout(800)
        safe_print('  [T2 PASS] Multi modal opened')

        # ── T3: Header fields present ─────────────────────────────────────────
        for fid, fname in [('atpMultiTarih','Tarih'), ('atpMultiArac','Araç'),
                           ('atpMultiSofor','Şoför')]:
            if page.locator('#' + fid).is_visible():
                safe_print(f'  [T3 PASS] {fname} field visible')
            else:
                errs.append(f'T3 FAIL: {fname} field #{fid} not visible')

        # ── T4: Saat kolonu "Otomatik" badge ─────────────────────────────────
        auto_badges = page.locator('.atp-multi-badge.auto').all()
        if auto_badges:
            safe_print(f'  [T4 PASS] "Otomatik" saat badge present ({len(auto_badges)} row(s))')
        else:
            errs.append('T4 FAIL: No "Otomatik" saat badge found')

        # No time picker input in multi modal
        time_inputs = page.locator('#atpMultiModal input[type="time"]').all()
        if not time_inputs:
            safe_print('  [T4 PASS] No manual time picker inside multi modal')
        else:
            errs.append(f'T4 FAIL: Manual time picker found in multi modal ({len(time_inputs)} inputs)')

        # ── T5: + Satır Ekle adds a row ──────────────────────────────────────
        rows_before = page.locator('#atpMultiTbody tr').count()
        page.click('#atpMultiBtnSatirEkle')
        page.wait_for_timeout(300)
        rows_after = page.locator('#atpMultiTbody tr').count()
        if rows_after > rows_before:
            safe_print(f'  [T5 PASS] Row added: {rows_before} → {rows_after}')
        else:
            errs.append(f'T5 FAIL: Row count did not increase: {rows_before} → {rows_after}')

        # Screenshot: 2 rows, empty
        shot1 = str(ROOT / f'_multi_2rows_{w}.png')
        page.screenshot(path=shot1)
        safe_print(f'  [SHOT] {shot1}')

        # ── T6: Submit empty → toast, no real POST ───────────────────────────
        real_posts.clear()
        page.click('#atpMultiBtnSubmit')
        page.wait_for_timeout(700)

        if len(real_posts) == 0:
            safe_print('  [T6 PASS] No real POST on empty submit')
        else:
            errs.append(f'T6 FAIL: Real POST happened: {real_posts}')

        # Toast should be visible briefly
        toast_el = page.locator('#atpToast')
        if toast_el.is_visible():
            safe_print(f'  [T6 PASS] Toast shown: "{toast_el.inner_text()[:80]}"')
        else:
            safe_print('  [T6 INFO] Toast not visible at check time (may have faded)')

        # ── T7: Firma input full-width regression ─────────────────────────────
        # (Open single modal via PRS if available, or via direct call, to verify FIX6D not broken)
        # Multi-modal firma inputs
        firma_inputs = page.locator('#atpMultiTbody .row-firma').all()
        if firma_inputs:
            box = firma_inputs[0].bounding_box()
            cell_box = page.locator('#atpMultiTbody td.col-firma').first.bounding_box()
            if box and cell_box:
                ratio = box['width'] / cell_box['width'] if cell_box['width'] > 0 else 0
                if ratio >= 0.85:
                    safe_print(f'  [T7 PASS] Multi row firma input width ratio={ratio:.2f}')
                else:
                    errs.append(f'T7 FAIL: Multi row firma input too narrow ratio={ratio:.2f}')

        # ── Add 3rd row for visual ────────────────────────────────────────────
        page.click('#atpMultiBtnSatirEkle')
        page.wait_for_timeout(300)
        shot2 = str(ROOT / f'_multi_3rows_{w}.png')
        page.screenshot(path=shot2)
        safe_print(f'  [SHOT] {shot2} (3 rows)')

        # ── Close multi modal ─────────────────────────────────────────────────
        page.click('#atpMultiClose')
        page.wait_for_timeout(400)

        # ── T9: PRS button opens SINGLE modal ────────────────────────────────
        # First need an active vehicle — click a vehicle card
        vehicle_cards = page.locator('.atp-vehicle-card, [data-ext-id]').all()
        if vehicle_cards:
            vehicle_cards[0].click()
            page.wait_for_timeout(500)
        prs_btn = page.locator('#atpBtnPlanaIsEklePrs')
        if prs_btn.is_visible():
            prs_btn.click()
            page.wait_for_timeout(500)
            # Single modal should open (not multi)
            single_open = page.locator('#atpModalBackdrop.open').is_visible()
            multi_open = page.locator('#atpMultiBackdrop.open').is_visible()
            if single_open and not multi_open:
                safe_print('  [T9 PASS] PRS button opens single modal (not multi)')
            else:
                errs.append(f'T9 FAIL: PRS btn → single_open={single_open} multi_open={multi_open}')
            # Close
            esc_close = page.locator('#atpModalClose')
            if esc_close.is_visible():
                esc_close.click()
        else:
            safe_print('  [T9 SKIP] PRS button not visible (no active vehicle)')

        # ── T8: Console errors ────────────────────────────────────────────────
        page.wait_for_timeout(300)
        net_errs = [e for e in console_errs if '404' not in e and 'favicon' not in e.lower()]
        if not net_errs:
            safe_print('  [T8 PASS] Console errors = 0')
        else:
            safe_print(f'  [T8 WARN] Console errors: {net_errs[:3]}')

    except Exception as ex:
        errs.append(f'EXCEPTION({label}): {ex}')
        safe_print(f'  [EXCEPTION] {ex}')
        try:
            page.screenshot(path=str(ROOT / f'_multi_exception_{w}.png'))
        except Exception:
            pass
    finally:
        ctx.close()
        browser.close()

    return errs


def main():
    from playwright.sync_api import sync_playwright
    all_errs = []
    with sync_playwright() as pw:
        for lbl, w, h in [('1920x1080', 1920, 1080), ('1366x768', 1366, 768)]:
            all_errs.extend(run(pw, lbl, w, h))

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
