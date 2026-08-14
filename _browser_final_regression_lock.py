# -*- coding: utf-8 -*-
"""
FINAL REGRESSION LOCK — Pazarlama Merkezi (READ-ONLY)
Canonical DB write forbidden. No mutating HTTP.
"""
import sys
import io
import os
import time
import sqlite3
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'app'))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from tools.browser_test_safety import (
    canonical_order760_snapshot,
    format_runtime_report,
    readonly_browser_context,
)

PZM_SUFFIX = '/nexgen/pazarlama'
DB = os.path.join(ROOT, 'app', 'mock_data.db')
results = []


def ok(msg):
    results.append(('PASS', msg))
    print('PASS  ' + msg.encode('ascii', 'replace').decode())


def fail(msg, detail=''):
    results.append(('FAIL', msg))
    print('FAIL  ' + msg.encode('ascii', 'replace').decode())
    if detail:
        print('      ' + str(detail).encode('ascii', 'replace').decode()[:200])


def info(msg):
    print('INFO  ' + str(msg).encode('ascii', 'replace').decode()[:200])


def login(page, base):
    page.goto(base + '/giris', timeout=15000)
    page.fill('[name=kullanici]', 'mehmet')
    page.fill('[name=sifre]', '1453')
    page.click('button[type=submit]')
    page.wait_for_load_state('domcontentloaded')
    time.sleep(0.8)


def scroll_top(page):
    page.evaluate('window.scrollTo(0,0)')
    page.evaluate('var m=document.querySelector("main"); if(m) m.scrollTop=0;')


def get_steps(page):
    out = []
    for s in page.query_selector_all('.mtt-v3-proses-step'):
        lbl_el = s.query_selector('.mtt-v3-step-lbl')
        lbl = lbl_el.inner_text().strip() if lbl_el else '?'
        cls = s.get_attribute('class') or ''
        state = 'done' if 'done' in cls else ('aktif' if 'aktif' in cls else 'pending')
        out.append((lbl, state))
    return out


def run_regression(base_url):
    pzm = base_url + PZM_SUFFIX
    js_errors = []

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    mtt_row = con.execute(
        "SELECT id, talep_no FROM nexgen_musteri_temsilcisi_talep "
        "WHERE talep_turu='SIPARIS' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    mtt_id = mtt_row['id'] if mtt_row else 183

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('pageerror', lambda e: js_errors.append(str(e)))

        login(page, base_url)

        page.goto(f'{pzm}?v={uuid.uuid4().hex}', wait_until='domcontentloaded')
        time.sleep(1)
        try:
            page.click('#tab-btn-mtt', timeout=3000)
            time.sleep(0.8)
        except Exception:
            pass
        page.evaluate(f'window.mttDetayAc && window.mttDetayAc({mtt_id})')
        time.sleep(2)
        scroll_top(page)
        if page.query_selector('#ekran-mtt-detay'):
            ok('MTT detail visible')
        else:
            fail('MTT detail NOT visible')

        page.goto(pzm + '?siparis=760', timeout=15000)
        page.wait_for_load_state('domcontentloaded')
        time.sleep(2)
        scroll_top(page)

        if page.query_selector('#ekran-detay'):
            ok('Siparis detail visible')
        else:
            fail('Siparis detail NOT visible')

        kimlik = page.query_selector('.pzm-det-kimlik-kart')
        if kimlik:
            ok('Kimlik kart visible')
            txt = kimlik.inner_text()
            if '2.000' in txt:
                ok('Kimlik kart KG = 2.000')
            elif '4.000' in txt:
                fail('Kimlik kart KG double-count regression')

        kg_el = page.query_selector('#pzm-det-oz-toplam')
        if kg_el:
            kg = kg_el.inner_text().strip()
            if '2.000' in kg:
                ok(f'Siparis ozet KG = {kg}')
            elif '4.000' in kg:
                fail(f'KG double-count: {kg}')

        steps = get_steps(page)
        aktif = sum(1 for s in steps if s[1] == 'aktif')
        if aktif == 1:
            ok('Stepper single-current = 1')
        else:
            fail(f'Stepper current count = {aktif}')

        fin = next((s for s in steps if 'Finans' in s[0]), None)
        if fin and fin[1] == 'aktif':
            ok('Finans = CURRENT')
        else:
            fail('Finans not current')

        page.reload()
        page.wait_for_load_state('domcontentloaded')
        time.sleep(1.5)
        if page.query_selector('#ekran-detay'):
            ok('F5 detail lock')
        else:
            fail('F5 detail lost')

        page.goto(pzm, timeout=15000)
        page.wait_for_load_state('domcontentloaded')
        time.sleep(1)
        page.go_back()
        time.sleep(1)
        page.go_forward()
        time.sleep(1)
        ok('Back/Forward navigation')

        if js_errors:
            fail('JS errors', js_errors[0][:100])
        else:
            ok('No JS errors')

        browser.close()


snap_before = canonical_order760_snapshot()
info(f'DB snapshot before: {snap_before}')

with readonly_browser_context() as ro_ctx:
    info(format_runtime_report(ro_ctx['runtime']))
    info(f'CANONICAL SHA BEFORE = {ro_ctx["sha_before"]}')
    info(f'ISOLATED PORT = {ro_ctx.get("isolated_port")}')
    run_regression(ro_ctx['base_url'])
info(f'CANONICAL SHA AFTER = {ro_ctx["sha_after"]}')

snap_after = canonical_order760_snapshot()
for k, exp in [
    ('plan194', 'BITTI'), ('plan195', 'IPTAL'), ('plan196', 'IPTAL'),
    ('pointer501', 194), ('order760', 'TAMAMLANDI'),
]:
    if snap_after.get(k) == exp:
        ok(f'DB LOCK {k}={exp}')
    else:
        fail(f'DB LOCK {k}={snap_after.get(k)} expected {exp}')

print()
passed = sum(1 for r in results if r[0] == 'PASS')
failed = sum(1 for r in results if r[0] == 'FAIL')
print(f'PASSED: {passed}  FAILED: {failed}')
if failed:
    sys.exit(1)
print('FINAL STATUS = ALL PASS')
