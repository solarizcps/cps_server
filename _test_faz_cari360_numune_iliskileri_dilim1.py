# -*- coding: utf-8 -*-
"""FAZ-CARI360-NUMUNE-ILISKILERI-UYGULAMA-1 — Dilim 1 Numuneler sekmesi."""
from __future__ import annotations

import os
import sqlite3
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'app', 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(
    ROOT, 'backup', 'faz_cari360_numune_iliskileri_uygulama_1_dilim1', 'screenshots'
)
os.makedirs(OUT, exist_ok=True)
RESULTS: dict[str, bool] = {}


def _mark(name: str, ok: bool, note: str = '') -> None:
    RESULTS[name] = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {note}" if note else ''))


def _login(user: str, pw: str) -> requests.Session:
    s = requests.Session()
    s.get(f'{BASE}/giris', timeout=20).raise_for_status()
    s.post(f'{BASE}/giris', data={'kullanici': user, 'sifre': pw}, timeout=20, allow_redirects=True).raise_for_status()
    return s


def _json(s, method, path):
    r = s.request(method, f'{BASE}{path}', headers={'Accept': 'application/json'}, timeout=30)
    ct = (r.headers.get('content-type') or '').lower()
    data = r.json() if 'application/json' in ct else None
    return r.status_code, data, ct


def main() -> int:
    con = sqlite3.connect(DB)
    admin_pw = con.execute("SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()[0]
    cari_with = con.execute(
        """
        SELECT cari_id, COUNT(*) n FROM nexgen_numune_talep
        WHERE cari_id IS NOT NULL AND COALESCE(aktif,1)=1
        GROUP BY cari_id ORDER BY n DESC LIMIT 1
        """
    ).fetchone()
    cari_empty = con.execute(
        """
        SELECT c.id FROM nexgen_cari c
        WHERE NOT EXISTS (
          SELECT 1 FROM nexgen_numune_talep n
          WHERE n.cari_id=c.id AND COALESCE(n.aktif,1)=1
        ) ORDER BY c.id LIMIT 1
        """
    ).fetchone()
    rf_numune = con.execute(
        """
        SELECT n.id, n.cari_id, n.rf_renk_id FROM nexgen_numune_talep n
        WHERE n.cari_id IS NOT NULL AND n.rf_renk_id IS NOT NULL AND COALESCE(n.aktif,1)=1
        LIMIT 1
        """
    ).fetchone()
    rf_arge = con.execute(
        """
        SELECT n.id, n.cari_id, a.rf_renk_id
        FROM nexgen_numune_talep n
        JOIN nexgen_arge_test a ON a.id=n.arge_test_id
        WHERE n.cari_id IS NOT NULL AND n.rf_renk_id IS NULL
          AND a.rf_renk_id IS NOT NULL AND COALESCE(n.aktif,1)=1
        LIMIT 1
        """
    ).fetchone()
    null_cari_ids = {
        int(r[0]) for r in con.execute(
            'SELECT id FROM nexgen_numune_talep WHERE cari_id IS NULL LIMIT 20'
        )
    }
    con.close()

    if not cari_with or not cari_empty:
        print('FAIL scenario caris missing')
        return 1
    cid = int(cari_with[0])

    for _ in range(20):
        try:
            if requests.get(f'{BASE}/giris', timeout=3).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print('FAIL server down')
        return 1

    sa = _login('admin', admin_pw)
    st, d, ct = _json(sa, 'GET', f'/nexgen/api/cari360/{cid}/numuneler')
    ok = st == 200 and 'json' in ct and d and d.get('ok')
    _mark('api_ok', ok, f'status={st}')
    if not ok:
        return 1

    liste = d.get('liste') or []
    ozet = d.get('ozet') or {}
    _mark('api_limit_50', len(liste) <= 50, f'len={len(liste)}')
    _mark('api_ozet', all(k in ozet for k in ('toplam', 'aktif', 'onaylanan', 'revizyonda', 'reddedilen')))
    _mark('api_fields', all(
        k in (liste[0] if liste else {}) for k in (
            'talep_kodu', 'tarih', 'talep_eden', 'urun_tipi', 'urun_adi',
            'renk', 'talep_turu', 'rf', 'durum', 'son_guncelleme', 'detay_url',
        )
    ) if liste else False)

    leaked_null = [x for x in liste if int(x['id']) in null_cari_ids]
    _mark('no_null_cari_rows', len(leaked_null) == 0, f'n={len(leaked_null)}')

    # RF from numune table
    if rf_numune:
        st2, d2, _ = _json(sa, 'GET', f'/nexgen/api/cari360/{int(rf_numune[1])}/numuneler')
        row = next((x for x in (d2 or {}).get('liste') or [] if int(x['id']) == int(rf_numune[0])), None)
        _mark(
            'rf_from_numune',
            bool(row and row.get('rf') and row.get('rf_kaynak') == 'numune'),
            f"row={row and {k: row.get(k) for k in ('id','rf','rf_kaynak')}}",
        )
    else:
        _mark('rf_from_numune', True, 'SKIP no sample')

    if rf_arge:
        st3, d3, _ = _json(sa, 'GET', f'/nexgen/api/cari360/{int(rf_arge[1])}/numuneler')
        row = next((x for x in (d3 or {}).get('liste') or [] if int(x['id']) == int(rf_arge[0])), None)
        _mark(
            'rf_from_arge_fallback',
            bool(row and row.get('rf') and row.get('rf_kaynak') == 'arge'),
            f"row={row and {k: row.get(k) for k in ('id','rf','rf_kaynak')}}",
        )
    else:
        _mark('rf_from_arge_fallback', True, 'SKIP no sample')

    st, d, _ = _json(sa, 'GET', f'/nexgen/api/cari360/{int(cari_empty[0])}/numuneler')
    _mark(
        'empty_cari',
        st == 200 and d and d.get('liste') == [] and int((d.get('ozet') or {}).get('toplam') or 0) == 0,
    )

    for path, key in [
        (f'/nexgen/api/cari360/{cid}/ozet', 'reg_ozet'),
        (f'/nexgen/api/cari360/{cid}/siparisler', 'reg_siparis'),
        (f'/nexgen/api/cari360/{cid}/uretim', 'reg_uretim'),
        (f'/nexgen/api/cari360/{cid}/sevkiyatlar', 'reg_sevk'),
        (f'/nexgen/api/cari360/{cid}/gorusme', 'reg_gorusme'),
    ]:
        st, d, ct = _json(sa, 'GET', path)
        _mark(key, st == 200 and 'json' in ct and bool(d and d.get('ok')), f'status={st}')

    # Browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _mark('browser', False, 'NO_PLAYWRIGHT')
        failed = [k for k, v in RESULTS.items() if not v]
        print('SUMMARY', f'{len(RESULTS)-len(failed)}/{len(RESULTS)}')
        return 1 if failed else 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(f'{BASE}/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', 'admin')
        page.fill('input[name="sifre"]', admin_pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.goto(f'{BASE}/nexgen/cari360/{cid}?tab=numuneler', wait_until='networkidle')
        page.wait_for_timeout(1200)
        oz_txt = page.locator('#ckart-numune-ozet').inner_text()
        _mark('browser_ozet', 'Toplam:' in oz_txt and 'Onaylanan:' in oz_txt, oz_txt[:120])
        _mark('browser_cols', page.locator('th:text("Talep Eden")').count() >= 1 and page.locator('th:text("RF")').count() >= 1)
        link = page.locator('#ckart-numune-tbody a.ckart-link').first
        href = link.get_attribute('href') if link.count() else ''
        _mark('browser_ac_href', '/numune-talep?id=' in (href or ''), href)
        if href:
            page.goto(f'{BASE}{href}', wait_until='networkidle')
            page.wait_for_timeout(900)
            c360 = page.locator('#nt-cari360-link')
            h360 = c360.get_attribute('href') if c360.count() else ''
            _mark('browser_back_cari360', f'/cari360/{cid}' in (h360 or ''), h360)
            page.screenshot(path=os.path.join(OUT, 'dilim1_numune_cari360.png'), full_page=True)
        else:
            _mark('browser_back_cari360', False)
        page.goto(f'{BASE}/nexgen/cari360/{cid}?tab=numuneler', wait_until='networkidle')
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(OUT, 'dilim1_cari360_numuneler.png'), full_page=True)
        browser.close()

    failed = [k for k, v in RESULTS.items() if not v]
    print('OUT', OUT)
    print('SUMMARY', f'{len(RESULTS)-len(failed)}/{len(RESULTS)} PASS')
    if failed:
        print('FAILED', failed)
        return 1
    print('ALL_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
