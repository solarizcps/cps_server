# -*- coding: utf-8 -*-
"""FAZ-YONETIM-CARI360-OMURGA-ILISKI-MERKEZI-1 — browser/API doğrulama."""
from __future__ import annotations

import os
import sqlite3
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'app', 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(ROOT, 'backup', 'faz_yonetim_cari360_omurga_iliski_1_browser', 'screenshots')
os.makedirs(OUT, exist_ok=True)
R: dict[str, bool] = {}


def mark(n, ok, note=''):
    R[n] = bool(ok)
    print(('PASS' if ok else 'FAIL'), n, ('— ' + note) if note else '')


def login(u, p):
    s = requests.Session()
    s.get(f'{BASE}/giris', timeout=20)
    s.post(f'{BASE}/giris', data={'kullanici': u, 'sifre': p}, timeout=20, allow_redirects=True)
    return s


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    admin_pw = con.execute("SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()[0]
    # sample: PZM-2026-0006 / cari 7 / siparis 54
    sip = con.execute(
        "SELECT id, cari_id, siparis_no FROM nexgen_planlama_siparis WHERE id=54"
    ).fetchone()
    con.close()
    if not sip:
        print('FAIL no sample siparis 54')
        return 1
    cid = int(sip['cari_id'])
    sid = int(sip['id'])

    for _ in range(25):
        try:
            if requests.get(f'{BASE}/giris', timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(0.4)
    else:
        print('FAIL server')
        return 1

    sa = login('admin', admin_pw)

    # backfill via siparisler API (soft repair)
    r = sa.get(f'{BASE}/nexgen/api/cari360/{cid}/siparisler', headers={'Accept': 'application/json'}, timeout=30)
    d = r.json()
    mark('api_siparisler', r.status_code == 200 and d.get('ok'))
    row = next((x for x in (d.get('liste') or []) if x.get('id') == sid), None)
    mark('siparis_54_listede', bool(row), str(row and row.get('siparis_no')))
    mark('detay_url', bool(row and row.get('detay_url') and f'siparis={sid}' in row['detay_url']))
    mark('plan_batch_alanlari', bool(row and 'plan_sayisi' in row and 'batch_sayisi' in row))

    con = sqlite3.connect(DB)
    bagli = con.execute(
        'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem '
        'WHERE planlama_siparis_id=? AND uretim_plan_id IS NOT NULL',
        (sid,),
    ).fetchone()[0]
    con.close()
    mark('kalem_plan_bagli', bagli >= 1, f'bagli={bagli}')

    r = sa.get(f'{BASE}/nexgen/api/cari360/{cid}/uretim', headers={'Accept': 'application/json'}, timeout=30)
    d = r.json()
    mark('api_uretim', r.status_code == 200 and d.get('ok'), f'count={(d or {}).get("count")}')
    uret = (d.get('liste') or [])
    hit_u = [x for x in uret if x.get('siparis_id') == sid]
    mark('uretim_siparis_54', len(hit_u) >= 1)
    mark('uretim_batch', bool(hit_u and (hit_u[0].get('batch_sayisi') or 0) >= 0))

    r = sa.get(f'{BASE}/nexgen/api/cari360/{cid}/sevkiyatlar', headers={'Accept': 'application/json'}, timeout=30)
    d = r.json()
    mark('api_sevk', r.status_code == 200 and d.get('ok'))
    sevk54 = [x for x in (d.get('liste') or []) if x.get('siparis_id') == sid]
    mark('sevk_siparis_link', bool(sevk54 and sevk54[0].get('siparis_url')))

    # regression other tabs
    for name, path in (
        ('ozet', f'/nexgen/api/cari360/{cid}/ozet'),
        ('urun', f'/nexgen/api/cari360/{cid}/urunler'),
        ('gorusme', f'/nexgen/api/cari360/{cid}/gorusme'),
    ):
        rr = sa.get(f'{BASE}{path}', headers={'Accept': 'application/json'}, timeout=30)
        mark('reg_' + name, rr.status_code == 200 and rr.json().get('ok'))

    # pages
    for name, path in (
        ('page_cari360', f'/nexgen/cari360/{cid}?tab=siparisler'),
        ('page_uretim', f'/nexgen/cari360/{cid}?tab=uretim'),
        ('page_pazarlama', f'/nexgen/pazarlama?siparis={sid}'),
    ):
        rr = sa.get(f'{BASE}{path}', timeout=30)
        mark(name, rr.status_code == 200)

    # browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        mark('browser', False, 'no playwright')
        failed = [k for k, v in R.items() if not v]
        print('SUMMARY', f'{len(R)-len(failed)}/{len(R)}')
        return 1 if failed else 0

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(f'{BASE}/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', 'admin')
        page.fill('input[name="sifre"]', admin_pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')

        page.goto(f'{BASE}/nexgen/cari360/{cid}?tab=siparisler', wait_until='networkidle')
        page.wait_for_timeout(1000)
        html = page.content()
        mark('browser_siparis_pazarlama_link', 'Pazarlama' in html and f'siparis={sid}' in html)
        mark('browser_uretim_sekme', 'data-tab="uretim"' in html)
        page.screenshot(path=os.path.join(OUT, 'cari360_siparisler.png'), full_page=True)

        page.goto(f'{BASE}/nexgen/cari360/{cid}?tab=uretim', wait_until='networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(OUT, 'cari360_uretim.png'), full_page=True)
        mark('browser_uretim_tablo', 'ckart-uretim-tablo' in page.content())

        page.goto(f'{BASE}/nexgen/pazarlama?siparis={sid}', wait_until='networkidle')
        page.wait_for_timeout(2000)
        page.screenshot(path=os.path.join(OUT, 'pazarlama_deeplink.png'), full_page=True)
        mark('browser_pazarlama_deeplink', 'Cari 360' in page.content() or 'pzm-detay' in page.content())
        page.close()
        b.close()

    failed = [k for k, v in R.items() if not v]
    print('OUT', OUT)
    print('SUMMARY', f'{len(R)-len(failed)}/{len(R)} PASS')
    if failed:
        print('FAILED', failed)
        return 1
    print('ALL_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
