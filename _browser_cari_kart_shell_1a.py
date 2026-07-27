# -*- coding: utf-8 -*-
"""Browser — 1A düzeltme: 404 yok, Atanmamış, otomatik atama yok."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
SHOT = ROOT / 'backup' / 'faz_cari_kart_shell_yetkililer_ui_1a_shots'
SHOT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get('CKART_BASE', 'http://127.0.0.1:8083')

con = sqlite3.connect(str(APP / 'mock_data.db'))
admin_pw = con.execute(
    "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
).fetchone()[0]
con.close()

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
        if resp.status >= 500:
            bad_net.append((resp.status, u))
        if resp.status == 404 and '/cari360' in u:
            bad_net.append((resp.status, u))

    page.on('response', on_resp)

    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', 'admin')
    page.fill('input[name="sifre"]', admin_pw)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state('networkidle')

    page.goto(f'{BASE}/nexgen/cari360/', wait_until='networkidle')
    page.screenshot(path=str(SHOT / '01_cari360_slash_no404.png'), full_page=False)

    page.goto(f'{BASE}/nexgen/cari360/1', wait_until='networkidle')
    meta = page.locator('.ckart-meta').inner_text()
    assert 'Atanmamış' in meta
    assert 'Erhan' not in meta
    assert 'Mehmet' not in meta
    page.screenshot(path=str(SHOT / '03_cari_kart_atanmamis.png'), full_page=False)

    page.goto(f'{BASE}/nexgen/cari360/15/', wait_until='networkidle')
    page.screenshot(path=str(SHOT / '04_cari360_15_slash.png'), full_page=False)

    browser.close()

real = [e for e in console_errs if 'favicon' not in e.lower()]
print('SHOT', SHOT)
print('CONSOLE', len(real), real[:5])
print('BAD_NET', bad_net[:10])
assert len(real) == 0, real
assert not bad_net, bad_net
print('PASS browser 1A-DUZELTME')
