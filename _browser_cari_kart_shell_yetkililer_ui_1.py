# -*- coding: utf-8 -*-
"""Browser smoke — Cari Kart shell 1366x768 + console/network."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
SHOT = ROOT / 'backup' / 'faz_cari_kart_shell_yetkililer_ui_1_shots'
SHOT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get('CKART_BASE', 'http://127.0.0.1:8082')

con = sqlite3.connect(str(APP / 'mock_data.db'))
admin_pw = con.execute(
    "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
).fetchone()[0]
cari = con.execute(
    'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
).fetchone()
con.close()
cid = int(cari[0])

from playwright.sync_api import sync_playwright

console_errs = []
bad_net = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    page = context.new_page()

    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    def on_resp(resp):
        u = resp.url
        if '/nexgen/' not in u and '/api/' not in u:
            return
        if resp.status >= 400:
            # beklenen validation 4xx hariç — burada genel sayfa yükü
            if resp.status >= 500 or (resp.status >= 400 and 'cari-yetkili' not in u):
                # sayfa asset 404 ignore
                if any(x in u for x in ('.css', '.js', '.png', '.ico', 'favicon')):
                    return
                if resp.status in (401, 403) and 'cari360' in u:
                    return
                bad_net.append((resp.status, u))

    page.on('response', on_resp)

    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', 'admin')
    page.fill('input[name="sifre"]', admin_pw)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')

    page.goto(f'{BASE}/nexgen/yonetim/', wait_until='networkidle')
    page.screenshot(path=str(SHOT / '01_yonetim_cari_kart_link.png'), full_page=False)
    assert page.locator('a:has-text("Cari Kart")').count() > 0

    page.goto(f'{BASE}/nexgen/cari360/{cid}', wait_until='networkidle')
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOT / '02_cari_kart_genel_1366x768.png'), full_page=False)
    assert page.locator('.ckart-unvan').count() == 1
    assert page.locator('#ckart-panel-genel').count() == 1

    page.goto(f'{BASE}/nexgen/cari360/{cid}?tab=yetkililer', wait_until='networkidle')
    page.wait_for_timeout(600)
    page.screenshot(path=str(SHOT / '03_cari_kart_yetkililer_1366x768.png'), full_page=False)

    # yeni yetkili modal
    if page.locator('#ckart-panel-yetkililer button.ckart-btn-birincil').count():
        page.evaluate("ckartYetkiliYeni()")
        page.wait_for_timeout(200)
        page.screenshot(path=str(SHOT / '04_yetkili_modal.png'), full_page=False)
        page.fill('#ckart-y-ad', f'Browser Yetkili {os.getpid()}')
        page.evaluate("ckartYetkiliKaydet()")
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOT / '05_yetkili_eklendi.png'), full_page=False)

    browser.close()

real_console = [e for e in console_errs if 'favicon' not in e.lower()]
print('SHOT_DIR', SHOT)
print('CONSOLE_ERRORS', len(real_console), real_console[:5])
print('BAD_NET', bad_net[:10])
assert len(real_console) == 0, real_console
# 5xx yok
assert not any(s >= 500 for s, _ in bad_net), bad_net
print('PASS browser 20/21/22 console0 network ok screenshot')
