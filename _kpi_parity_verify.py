"""
PHASE=ATP_TOP_HEADER_KPI_VISUAL_PARITY_V1
Verify KPI/header visual parity + functional smoke (no DB writes).
"""
import json
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'
TARGET = BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24'


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
    page.goto(TARGET, wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(1500)


def run(pw, label, w, h, errs):
    safe_print(f"\n{'='*60}\nVIEWPORT: {label}\n{'='*60}")

    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={'width': w, 'height': h})
    page = ctx.new_page()
    console_errs = []
    bad_net = []

    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    def on_resp(resp):
        if resp.status >= 400 and 'favicon' not in resp.url:
            bad_net.append(f'{resp.status} {resp.url}')

    page.on('response', on_resp)

    try:
        login(page)

        css_href = page.eval_on_selector(
            'link[href*="planlama_arac_takip.css"]', 'e => e.href')
        if 'v=48' in css_href:
            safe_print('  [T0 PASS] CSS v=48')
        else:
            errs.append(f'T0 FAIL({label}): css={css_href}')

        page.wait_for_selector('#atpKpiBand', timeout=10000)
        page.wait_for_timeout(800)

        kpi_vals = page.evaluate("""() => {
            var ids = ['atpKpiAktif','atpKpiHareket','atpKpiIs','atpKpiTamam','atpKpiDevam','atpKpiSorun'];
            return ids.map(function(id) {
                var el = document.getElementById(id);
                return el ? el.textContent.trim() : null;
            });
        }""")
        if kpi_vals and all(v and v != '—' for v in kpi_vals):
            safe_print(f'  [T1 PASS] KPI API values: {kpi_vals}')
        else:
            errs.append(f'T1 FAIL({label}): kpi={kpi_vals}')

        metrics = page.evaluate("""() => {
            var cards = document.querySelectorAll('#atpKpiBand .kpi');
            var band = document.getElementById('atpKpiBand');
            var heights = [];
            cards.forEach(function(c) {
                var r = c.getBoundingClientRect();
                heights.push(Math.round(r.height));
            });
            var br = band ? band.getBoundingClientRect() : null;
            var dateBar = document.getElementById('atpDateBar');
            var gap = 0;
            if (dateBar && br) {
                gap = Math.round(br.top - dateBar.getBoundingClientRect().bottom);
            }
            return {heights: heights, bandPad: band ? getComputedStyle(band).padding : '', gap: gap};
        }""")
        safe_print(f'  [T2 INFO] kpi heights={metrics["heights"]} gap={metrics["gap"]}px')

        if metrics['heights'] and max(metrics['heights']) <= 68 and min(metrics['heights']) >= 44:
            safe_print('  [T2 PASS] KPI card heights balanced')
        else:
            errs.append(f'T2 FAIL({label}): heights={metrics["heights"]}')

        page.click('#atpBtnPlanaIsEkle')
        page.wait_for_selector('#atpMultiBackdrop.open', timeout=8000)
        multi_open = page.locator('#atpMultiBackdrop.open').count() > 0
        if multi_open:
            safe_print('  [T3 PASS] Multi popup opens')
            page.click('#atpMultiClose')
            page.wait_for_timeout(300)
        else:
            errs.append(f'T3 FAIL({label}): multi popup')

        rota = page.locator('.plan-rota-summary, .prs-wrap, [class*="plan-rota"]').count()
        chevron = page.locator('.vcard-chevron, .vcard-toggle, [class*="chevron"]').count()
        if rota > 0 or chevron > 0:
            safe_print(f'  [T4 PASS] Route panel present (rota={rota}, chevron={chevron})')
        else:
            safe_print('  [T4 INFO] Route elements not visible (may be collapsed)')

        page.screenshot(path=str(ROOT / f'_kpi_parity_{w}.png'), full_page=False)

        net_errs = [e for e in console_errs if 'favicon' not in e.lower()]
        if not net_errs:
            safe_print('  [T5 PASS] console=0')
        else:
            errs.append(f'T5 console({label}): {net_errs[:3]}')

        if not bad_net:
            safe_print('  [T6 PASS] network 404/500=0')
        else:
            errs.append(f'T6 network({label}): {bad_net[:3]}')

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
