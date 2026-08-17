# -*- coding: utf-8 -*-
"""UI visibility regression — proses step'ler TD içinde tam görünür olmalı."""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

SIPS = {
    '33786': 4,
    '33785': 4,
    '33857': 4,
    '33888': 4,
    '33918': 6,
}

passed, failed = [], []


def ok(l, _=''):
    passed.append(l)
    print(f'  PASS  {l}')


def fail(l, r=''):
    failed.append(l)
    print(f'  FAIL  {l}' + (f' — {r}' if r else ''))


def check(l, c, r=''):
    (ok if c else fail)(l, r)


def measure_visibility(page):
    page.goto('http://127.0.0.1:8080/planlama/uretim-plan', timeout=20000)
    page.wait_for_selector('#upTable tbody tr', timeout=20000)
    page.click('.up-tab[data-donem="3_ay"]')
    time.sleep(2.5)
    return page.evaluate(
        """() => {
            const prosesTh = document.querySelector('#upTable thead tr:first-child th.up-col-proses');
            const prosesColW = prosesTh ? Math.round(prosesTh.getBoundingClientRect().width) : 0;
            const wrap = document.querySelector('.up-tbl-wrap');
            const pageW = document.documentElement.clientWidth;
            const bodyScrollW = document.body.scrollWidth;
            const out = { prosesColW, pageW, bodyScrollW, pageOverflow: bodyScrollW > pageW + 2, rows: {} };
            for (const tr of document.querySelectorAll('#upTable tbody tr')) {
                const sipEl = tr.querySelector('.up-sip-no');
                if (!sipEl) continue;
                const sip = sipEl.textContent.trim();
                const td = tr.querySelector('.up-proses-dinamik');
                const flow = td ? td.querySelector('.up-proses-flow') : null;
                if (!td || !flow) { out.rows[sip] = { error: 'missing' }; continue; }
                const tdRect = td.getBoundingClientRect();
                const steps = [...flow.querySelectorAll('.up-proses-step')];
                const vis = steps.map(s => {
                    const r = s.getBoundingClientRect();
                    const fullyVisible = r.left >= tdRect.left - 0.5 && r.right <= tdRect.right + 0.5;
                    return { kod: s.getAttribute('data-proses-kod'), fullyVisible,
                             left: Math.round(r.left), right: Math.round(r.right) };
                });
                out.rows[sip] = {
                    tdW: Math.round(tdRect.width),
                    domCount: steps.length,
                    fullyVisible: vis.filter(x => x.fullyVisible).length,
                    steps: vis,
                    flowScrollW: flow.scrollWidth,
                };
            }
            return out;
        }"""
    )


def login(page):
    page.goto('http://127.0.0.1:8080/giris', timeout=15000)
    page.fill('[name=kullanici]', 'mehmet')
    page.fill('[name=sifre]', '1453')
    page.click('button[type=submit]')
    page.wait_for_load_state('domcontentloaded')
    time.sleep(0.8)


print('=' * 60)
print('UI — Proses Visibility Lock (1920 viewport)')
print('=' * 60)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    fail('playwright kurulu', 'pip install playwright')
    sys.exit(1)

metrics = None
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    login(page)
    metrics = measure_visibility(page)
    page.evaluate('window.scrollTo(0,0)')
    shot = Path(__file__).resolve().parents[1] / '_shot_up_ref_v8.png'
    page.screenshot(path=str(shot), full_page=False)
    print(f'  Screenshot: {shot}')
    browser.close()

if metrics:
    print(f"  Proses kolon genişliği (th): {metrics['prosesColW']}px")
    check('Sayfa horizontal overflow yok', not metrics['pageOverflow'],
          f"bodyScroll={metrics['bodyScrollW']} pageW={metrics['pageW']}")
    check('Proses kolon >= 420px', metrics['prosesColW'] >= 420, f"got={metrics['prosesColW']}")

    for sip, expected in SIPS.items():
        row = metrics['rows'].get(sip)
        if not row or row.get('error'):
            fail(f'{sip} visible {expected}/{expected}', 'satır yok')
            continue
        vis = row['fullyVisible']
        check(f'{sip} visible {vis}/{expected}',
              vis == expected and row['domCount'] == expected,
              f"dom={row['domCount']} tdW={row.get('tdW')} flowScroll={row.get('flowScrollW')}")

try:
    r = subprocess.run(['git', 'diff', '--check'], cwd=str(Path(__file__).resolve().parents[1]),
                       capture_output=True, text=True, timeout=30)
    check('git diff --check', r.returncode == 0)
except Exception as ex:
    fail('git diff --check', str(ex)[:80])

print()
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    sys.exit(1)
