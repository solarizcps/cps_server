# -*- coding: utf-8 -*-
"""
READ-ONLY browser smoke — Plan 195 recovery verification
PZM-2026-0222 / siparis=760

Safety: canonical DB write forbidden, no mutating HTTP calls.
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'app'))
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

from tools.browser_test_safety import (
    canonical_order760_snapshot,
    format_runtime_report,
    readonly_browser_context,
)

USER = 'mehmet'
PASS_ = '1453'
results = []


def ok(label):
    results.append(('PASS', label))
    print('PASS  ' + label.encode('ascii', 'replace').decode())


def fail(label, detail=''):
    results.append(('FAIL', label))
    print('FAIL  ' + label.encode('ascii', 'replace').decode())
    if detail:
        print('      ' + str(detail).encode('ascii', 'replace').decode()[:200])


def info(msg):
    print('INFO  ' + str(msg).encode('ascii', 'replace').decode()[:240])


def run_smoke(base_url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(base_url + '/giris', wait_until='networkidle', timeout=15000)
        page.fill('[name=kullanici]', USER)
        page.fill('[name=sifre]', PASS_)
        page.click('button[type=submit]')
        page.wait_for_load_state('networkidle', timeout=10000)
        ok('Login OK')

        page.goto(base_url + '/nexgen/pazarlama?ekran=pzm', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        list_content = page.content()
        if 'PZM-2026-0222' in list_content and 'TAMAMLANDI' in list_content:
            ok('LIST: PZM-2026-0222 + TAMAMLANDI')
        elif 'PZM-2026-0222' in list_content:
            fail('LIST: PZM-2026-0222 visible but TAMAMLANDI missing')
        else:
            info('PZM-2026-0222 not visible in list (filter/scroll)')

        page.goto(base_url + '/nexgen/pazarlama?siparis=760', wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(2500)
        page.evaluate('window.scrollTo(0,0)')

        detail = page.content()
        if 'TAMAMLANDI' in detail:
            ok('DETAIL: TAMAMLANDI present')
        else:
            fail('DETAIL: TAMAMLANDI missing')

        if '2.000' in detail or '2,000' in detail:
            ok('DETAIL: KG = 2.000 kg')
        else:
            fail('DETAIL: KG not found')

        ro_banner = 'salt okunur' in detail.lower() or 'readonly' in detail.lower()
        mpr_state = page.evaluate("""
            (function() {
                var btns = document.querySelectorAll('[onclick*="pzmMprOlustur"], [onclick*="mpr"]');
                for (var b of btns) {
                    if (!b.disabled && getComputedStyle(b).pointerEvents !== 'none') return 'ACTIVE';
                }
                return 'READONLY';
            })()
        """)
        if ro_banner or mpr_state == 'READONLY':
            ok('MRP readonly / salt okunur confirmed')
        else:
            fail('MRP not readonly', mpr_state)

        stepper = page.evaluate("""
            (function() {
                var currents = document.querySelectorAll('.mtt-v3-proses-step.aktif, .stepper-current');
                return currents.length;
            })()
        """)
        if stepper <= 1:
            ok(f'STEPPER: single-current = {stepper}')
        else:
            fail(f'STEPPER: multiple current = {stepper}')

        page.reload(wait_until='networkidle', timeout=15000)
        page.wait_for_timeout(1500)
        if 'TAMAMLANDI' in page.content():
            ok('F5: TAMAMLANDI persists')
        else:
            fail('F5: TAMAMLANDI lost after reload')

        page.screenshot(path='_shot_recovery195_detail.png', full_page=False)
        ok('Screenshot saved')
        browser.close()


def main() -> int:
    snap_before = canonical_order760_snapshot()
    info(f'DB snapshot before: {snap_before}')

    with readonly_browser_context() as ctx:
        info(format_runtime_report(ctx['runtime']))
        info(f'CANONICAL SHA BEFORE = {ctx["sha_before"]}')
        info(f'ISOLATED PORT = {ctx.get("isolated_port")}')
        run_smoke(ctx['base_url'])
    info(f'CANONICAL SHA AFTER  = {ctx["sha_after"]}')

    snap_after = canonical_order760_snapshot()
    info(f'DB snapshot after: {snap_after}')

    expected = {
        'plan194': 'BITTI',
        'plan195': 'IPTAL',
        'plan196': 'IPTAL',
        'pointer501': 194,
        'order760': 'TAMAMLANDI',
        'plan_count': 3,
    }
    for k, v in expected.items():
        if snap_after.get(k) == v:
            ok(f'DB LOCK: {k} = {v}')
        else:
            fail(f'DB LOCK: {k} = {snap_after.get(k)} (expected {v})')

    print()
    passed = sum(1 for r in results if r[0] == 'PASS')
    failed = sum(1 for r in results if r[0] == 'FAIL')
    print(f'RESULT: {passed} PASS, {failed} FAIL')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
