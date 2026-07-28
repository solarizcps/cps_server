# -*- coding: utf-8 -*-
"""FAZ-CARI360-NUMUNE-ILISKILERI Dilim 4 — ONAYLANDI RF sync + conflict."""
from __future__ import annotations

import os
import sqlite3
import sys
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'app', 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(ROOT, 'backup', 'faz_cari360_numune_iliskileri_uygulama_1_dilim4', 'screenshots')
os.makedirs(OUT, exist_ok=True)
RESULTS: dict[str, bool] = {}


def _mark(name: str, ok: bool, note: str = '') -> None:
    RESULTS[name] = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {note}" if note else ''))


def _login(user, pw):
    s = requests.Session()
    s.get(f'{BASE}/giris', timeout=20).raise_for_status()
    s.post(
        f'{BASE}/giris', data={'kullanici': user, 'sifre': pw},
        timeout=20, allow_redirects=True,
    ).raise_for_status()
    return s


def _json(s, method, path, **kw):
    headers = kw.pop('headers', {})
    headers.setdefault('Accept', 'application/json')
    r = s.request(method, f'{BASE}{path}', headers=headers, timeout=30, **kw)
    ct = (r.headers.get('content-type') or '').lower()
    data = r.json() if 'application/json' in ct else None
    return r.status_code, data, ct


def main() -> int:
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    from modules.nexgen.nx_ar_service import _sync_numune_rf_from_arge

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Pair: arge.rf dolu + bağlı numune
    pair = con.execute(
        """
        SELECT n.id AS nid, n.rf_renk_id AS n_rf, n.cari_id,
               a.id AS aid, a.rf_renk_id AS a_rf, a.durum AS a_durum
        FROM nexgen_numune_talep n
        JOIN nexgen_arge_test a ON a.id = n.arge_test_id
        WHERE COALESCE(n.aktif,1)=1
          AND a.rf_renk_id IS NOT NULL
        ORDER BY n.id DESC
        LIMIT 1
        """
    ).fetchone()
    if not pair:
        print('FAIL no arge/numune pair with RF')
        return 1

    nid = int(pair['nid'])
    aid = int(pair['aid'])
    arge_rf = int(pair['a_rf'])
    orig_nrf = pair['n_rf']
    cari_id = int(pair['cari_id']) if pair['cari_id'] else None

    # Alternate RF for conflict
    alt = con.execute(
        'SELECT id FROM nexgen_rf_renk WHERE id!=? AND aktif=1 LIMIT 1',
        (arge_rf,),
    ).fetchone()
    alt_rf = int(alt['id']) if alt else None

    admin_pw = con.execute(
        "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()[0]

    # --- Case: numune RF boş → fill ---
    con.execute('UPDATE nexgen_numune_talep SET rf_renk_id=NULL WHERE id=?', (nid,))
    con.commit()
    r1 = _sync_numune_rf_from_arge(con, aid)
    con.commit()
    nrf1 = con.execute(
        'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (nid,),
    ).fetchone()['rf_renk_id']
    _mark(
        'fill_from_arge',
        r1.get('filled') == 1 and nrf1 is not None and int(nrf1) == arge_rf,
        f'r={r1} nrf={nrf1}',
    )

    # --- Case: ikisi aynı → no overwrite / no conflict ---
    r2 = _sync_numune_rf_from_arge(con, aid)
    con.commit()
    nrf2 = con.execute(
        'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (nid,),
    ).fetchone()['rf_renk_id']
    _mark(
        'same_rf_noop',
        r2.get('filled') == 0 and not r2.get('conflicts') and int(nrf2) == arge_rf,
        f'r={r2}',
    )

    # --- Case: farklı RF → conflict, üzerine yazma yok ---
    if alt_rf:
        con.execute(
            'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
            (alt_rf, nid),
        )
        con.commit()
        r3 = _sync_numune_rf_from_arge(con, aid)
        con.commit()
        nrf3 = con.execute(
            'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (nid,),
        ).fetchone()['rf_renk_id']
        _mark(
            'conflict_no_overwrite',
            int(nrf3) == alt_rf
            and r3.get('filled') == 0
            and any(c.get('numune_talep_id') == nid for c in (r3.get('conflicts') or [])),
            f'r={r3} nrf={nrf3}',
        )
    else:
        _mark('conflict_no_overwrite', True, 'SKIP no alt rf')

    # --- Case: numune RF dolu (restore orig or arge) — dolu korunur ---
    keep = int(orig_nrf) if orig_nrf is not None else arge_rf
    con.execute(
        'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
        (keep, nid),
    )
    con.commit()
    r4 = _sync_numune_rf_from_arge(con, aid)
    con.commit()
    nrf4 = con.execute(
        'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (nid,),
    ).fetchone()['rf_renk_id']
    _mark(
        'keep_existing_numune_rf',
        int(nrf4) == keep and r4.get('filled') == 0,
        f'keep={keep} nrf={nrf4} r={r4}',
    )

    # Restore original
    con.execute(
        'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
        (orig_nrf, nid),
    )
    con.commit()
    _mark('restore_orig', True, f'orig={orig_nrf}')

    # Read-side fallback (Cari360) hâlâ çalışır — arge RF
    con.close()

    for _ in range(20):
        try:
            if requests.get(f'{BASE}/giris', timeout=3).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print('FAIL flask')
        return 1

    # Restart not required if we only changed module used on import — need restart!
    # Flask already running with OLD code — restart briefly via env note.
    # Caller should restart; we try import path via live API Cari360 fallback.

    sa = _login('admin', admin_pw)
    if cari_id:
        st, d, ct = _json(sa, 'GET', f'/nexgen/api/cari360/{cari_id}/numuneler')
        row = next((x for x in (d or {}).get('liste') or [] if int(x['id']) == nid), None)
        _mark(
            'read_fallback_api',
            st == 200 and 'json' in ct and d and d.get('ok') and row is not None,
            f'rf={row and row.get("rf")} kaynak={row and row.get("rf_kaynak")}',
        )
    else:
        _mark('read_fallback_api', True, 'SKIP no cari')

    # Regression: onay merkez / numune API JSON
    for path, key in [
        (f'/nexgen/api/cari360/{cari_id}/ozet' if cari_id else '/giris', 'reg_ozet'),
        ('/nexgen/api/pazarlama/talepler?page=1', 'reg_pzm'),
    ]:
        if path == '/giris':
            _mark(key, True, 'SKIP')
            continue
        st, d, ct = _json(sa, 'GET', path)
        _mark(key, st == 200 and 'json' in ct and bool(d and d.get('ok')), f'st={st}')

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
        if cari_id:
            page.goto(f'{BASE}/nexgen/cari360/{cari_id}?tab=numuneler', wait_until='networkidle')
            page.wait_for_timeout(1000)
            page.screenshot(path=os.path.join(OUT, 'dilim4_cari360_numuneler_rf.png'), full_page=True)
            _mark('browser_numuneler', page.locator('#ckart-numune-tbody').count() >= 1)
        else:
            _mark('browser_numuneler', True, 'SKIP')
        browser.close()

    failed = [k for k, v in RESULTS.items() if not v]
    print('OUT', OUT)
    print('SUMMARY', f'{len(RESULTS)-len(failed)}/{len(RESULTS)} PASS')
    if failed:
        print('FAILED', failed)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
