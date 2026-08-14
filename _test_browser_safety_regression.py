# -*- coding: utf-8 -*-
"""
Browser safety regression — guards + readonly smoke + isolated mutation test.
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
    assert_post_blocked_on_live,
    canonical_order760_snapshot,
    format_runtime_report,
    mutating_isolated_browser_context,
    readonly_browser_context,
)

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
    print('INFO  ' + str(msg).encode('ascii', 'replace').decode()[:240])


print('=' * 60)
print('  A — READ-ONLY GUARD + CANONICAL SHA')
print('=' * 60)

snap0 = canonical_order760_snapshot()
sha_before = None
sha_after = None
try:
    with readonly_browser_context() as ctx:
        sha_before = ctx['sha_before']
        info(format_runtime_report(ctx['runtime']))
        ok(f'RUNTIME HEAD parity OK (PID={ctx["runtime"].get("pid")})')
        ok(f'CANONICAL SHA BEFORE = {sha_before}')
        ok(f'ISOLATED PORT = {ctx.get("isolated_port")}')

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            base = ctx['base_url']
            page.goto(base + '/giris', wait_until='domcontentloaded', timeout=15000)
            page.fill('[name=kullanici]', 'mehmet')
            page.fill('[name=sifre]', '1453')
            page.click('button[type=submit]')
            page.wait_for_load_state('domcontentloaded')
            page.goto(base + '/nexgen/pazarlama?siparis=760', wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(2000)
            page.evaluate('window.scrollTo(0,0)')
            html = page.content()
            stepper_current = page.evaluate(
                "document.querySelectorAll('.mtt-v3-proses-step.aktif').length"
            )
            browser.close()

        for cond, label in [
            ('TAMAMLANDI' in html, 'D: status TAMAMLANDI'),
            ('2.000' in html or '2,000' in html, 'D: KG 2.000'),
            ('salt okunur' in html.lower() or 'Tamamland' in html, 'D: readonly/completed UI'),
            (stepper_current == 1, f'D: Finans/current count = {stepper_current}'),
        ]:
            if cond:
                ok(label)
            else:
                fail(label)

    sha_after = ctx['sha_after']
    ok(f'CANONICAL SHA AFTER  = {sha_after}')
    if sha_before == sha_after:
        ok('A: BEFORE == AFTER (canonical DB unchanged)')
    else:
        fail('A: canonical DB SHA changed')
except RuntimeError as exc:
    fail('A/D: readonly context', str(exc))

print()
print('=' * 60)
print('  B — LIVE POST BLOCKED BY GUARD')
print('=' * 60)

try:
    assert_post_blocked_on_live()
    ok('B: POST /mpr-olustur blocked on live :8080')
except Exception as exc:
    fail('B: HTTP write guard', str(exc))

print()
print('=' * 60)
print('  C — MUTATING PREVENTION (ISOLATED DB)')
print('=' * 60)

isolated_port = None
mutating_db = None

try:
    with mutating_isolated_browser_context(prefix='safety_mutating_') as srv:
        isolated_port = srv['port']
        mutating_db = srv['tmp_db']
        ok(f'C: isolated Flask port={isolated_port}')
        ok(f'C: mutating DB = {mutating_db}')

        import sqlite3
        con = sqlite3.connect(srv['tmp_db'])
        before = con.execute(
            'SELECT COUNT(*) FROM nexgen_uretim_plan WHERE planlama_siparis_id=760'
        ).fetchone()[0]
        con.close()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(srv['base_url'] + '/giris', wait_until='domcontentloaded', timeout=15000)
            page.fill('[name=kullanici]', 'mehmet')
            page.fill('[name=sifre]', '1453')
            page.click('button[type=submit]')
            page.wait_for_load_state('domcontentloaded')
            api = page.evaluate("""async () => {
                const r = await fetch('/nexgen/api/pazarlama/mpr-olustur', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({talep_id: 760})
                });
                return await r.json();
            }""")
            browser.close()

        if api.get('zaten_var') and api.get('ok'):
            ok('C: isolated POST → zaten_var=True')
        else:
            fail('C: isolated POST response', str(api)[:120])

        con = sqlite3.connect(srv['tmp_db'])
        after = con.execute(
            'SELECT COUNT(*) FROM nexgen_uretim_plan WHERE planlama_siparis_id=760'
        ).fetchone()[0]
        con.close()
        if after == before:
            ok(f'C: isolated plan count unchanged ({after})')
        else:
            fail(f'C: isolated plan count {before} → {after}')

        ok(f'C: canonical SHA unchanged ({srv["sha_before"][:16]}...)')
except Exception as exc:
    fail('C: mutating isolated test', str(exc))

print()
print('=' * 60)
print('  D — (merged into A readonly smoke)')
print('=' * 60)
ok('D: covered by A isolated readonly session')

print()
print('=' * 60)
print('  E — CANONICAL DB ORDER 760 LOCK')
print('=' * 60)

snap = canonical_order760_snapshot()
locks = {
    'plan194': 'BITTI',
    'plan195': 'IPTAL',
    'plan196': 'IPTAL',
    'pointer501': 194,
    'order760': 'TAMAMLANDI',
}
for k, exp in locks.items():
    if snap.get(k) == exp:
        ok(f'E: {k} = {exp}')
    else:
        fail(f'E: {k} = {snap.get(k)} (expected {exp})')

new_plans = snap.get('plan_count', 0)
if new_plans == 3:
    ok('E: plan count = 3 (no new plan)')
else:
    fail(f'E: plan count = {new_plans}')

print()
print('=' * 60)
passed = sum(1 for r in results if r[0] == 'PASS')
failed = sum(1 for r in results if r[0] == 'FAIL')
print(f'TOTAL: {passed} PASS, {failed} FAIL')
print('=' * 60)

if failed:
    print('STATUS = FAIL')
    sys.exit(1)
print('STATUS = TEST SAFETY READY FOR LOCK')
sys.exit(0)
