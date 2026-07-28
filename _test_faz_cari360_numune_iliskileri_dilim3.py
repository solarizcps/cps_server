# -*- coding: utf-8 -*-
"""FAZ-CARI360-NUMUNE-ILISKILERI Dilim 3 — siparis_kalem.numune_talep_id."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'app', 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(ROOT, 'backup', 'faz_cari360_numune_iliskileri_uygulama_1_dilim3', 'screenshots')
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
    if method.upper() == 'POST':
        headers.setdefault('Content-Type', 'application/json')
    r = s.request(method, f'{BASE}{path}', headers=headers, timeout=45, **kw)
    ct = (r.headers.get('content-type') or '').lower()
    data = r.json() if 'application/json' in ct else None
    return r.status_code, data, ct


def _termin():
    return (date.today() + timedelta(days=21)).isoformat()


def _pick_kalem_seed(con, cari_id: int):
    """Mevcut bir kalemden formul/rf al — yeni taslak için şablon."""
    row = con.execute(
        """
        SELECT k.urun_ailesi, k.formul_id, k.rf_renk_id, k.miktar_l, k.miktar_s, k.miktar_m
        FROM nexgen_planlama_siparis_kalem k
        JOIN nexgen_planlama_siparis s ON s.id = k.planlama_siparis_id
        WHERE s.cari_id=?
        ORDER BY k.id DESC LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    return row


def main() -> int:
    # Apply migration 137 idempotent
    import importlib.util
    mig_path = os.path.join(ROOT, 'app', 'migrations', '137_nexgen_planlama_siparis_kalem_numune.py')
    spec = importlib.util.spec_from_file_location('mig137', mig_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.run(DB)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis_kalem)')}
    _mark('mig_col', 'numune_talep_id' in cols)

    admin_pw = con.execute(
        "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()[0]

    # Hem numune hem kalem seed olan cari seç
    overlap = con.execute(
        """
        SELECT n.cari_id AS cid
        FROM nexgen_numune_talep n
        JOIN nexgen_planlama_siparis s ON s.cari_id = n.cari_id
        JOIN nexgen_planlama_siparis_kalem k ON k.planlama_siparis_id = s.id
        WHERE n.cari_id IS NOT NULL AND COALESCE(n.aktif,1)=1
        GROUP BY n.cari_id
        HAVING COUNT(DISTINCT n.id) >= 1
        ORDER BY COUNT(DISTINCT n.id) DESC
        LIMIT 1
        """
    ).fetchone()
    if not overlap:
        print('FAIL no overlap cari')
        return 1
    cari_id = int(overlap['cid'])
    nums = con.execute(
        """
        SELECT id, talep_kodu, durum FROM nexgen_numune_talep
        WHERE cari_id=? AND COALESCE(aktif,1)=1
        ORDER BY CASE WHEN UPPER(COALESCE(durum,''))='ONAYLANDI' THEN 0 ELSE 1 END, id DESC
        LIMIT 5
        """,
        (cari_id,),
    ).fetchall()
    other = con.execute(
        """
        SELECT id, cari_id FROM nexgen_numune_talep
        WHERE cari_id IS NOT NULL AND cari_id!=? AND COALESCE(aktif,1)=1 LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    seed = _pick_kalem_seed(con, cari_id)
    old_null = con.execute(
        'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem WHERE numune_talep_id IS NULL'
    ).fetchone()[0]
    con.close()

    if not nums or not seed:
        print('FAIL seed data missing', 'cari=', cari_id, 'nums=', len(nums) if nums else 0, 'seed=', bool(seed))
        return 1
    print('SEED cari_id=', cari_id, 'nums=', len(nums), 'seed_formul=', seed['formul_id'])

    n1 = int(nums[0]['id'])
    n2 = int(nums[1]['id']) if len(nums) > 1 else n1

    for _ in range(20):
        try:
            if requests.get(f'{BASE}/giris', timeout=3).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print('FAIL flask not up')
        return 1

    sa = _login('admin', admin_pw)

    # API: cari numune listesi
    st, d, ct = _json(sa, 'GET', f'/nexgen/api/pazarlama/cari-numuneler?cari_id={cari_id}')
    _mark('api_cari_numuneler', st == 200 and 'json' in ct and d and d.get('ok') and len(d.get('liste') or []) > 0)

    # Tek kalem / tek numune
    payload1 = {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': _termin(),
        'anlasma_para_birimi': 'TRY',
        'anlasma_birim_fiyat': 100,
        'vade_gun': 30,
        'kalemler': [{
            'sira_no': 1,
            'urun_ailesi': seed['urun_ailesi'],
            'formul_id': int(seed['formul_id']),
            'rf_renk_id': int(seed['rf_renk_id']),
            'miktar_l': float(seed['miktar_l'] or 0) or 10.0,
            'miktar_s': float(seed['miktar_s'] or 0),
            'miktar_m': float(seed['miktar_m'] or 0),
            'termin_tarihi': _termin(),
            'numune_talep_id': n1,
        }],
    }
    # DÖKME vs TERLIK miktar kuralları
    if str(seed['urun_ailesi']).upper() == 'DOKME':
        payload1['kalemler'][0].update({'miktar_l': 0, 'miktar_s': 0, 'miktar_m': 10.0})
    else:
        payload1['kalemler'][0].update({'miktar_m': 0})
        if not payload1['kalemler'][0]['miktar_l'] and not payload1['kalemler'][0]['miktar_s']:
            payload1['kalemler'][0]['miktar_l'] = 10.0

    st, d, ct = _json(sa, 'POST', '/nexgen/api/pazarlama/taslak-kaydet', json=payload1)
    tid1 = (d or {}).get('talep_id')
    _mark('write_tek_numune', st == 200 and 'json' in ct and d and d.get('ok') and tid1, f'st={st} {d}')

    # Çok kalem / farklı numune (aynı seed, farklı numune id)
    k1 = dict(payload1['kalemler'][0])
    k2 = dict(payload1['kalemler'][0])
    k1['sira_no'] = 1
    k1['numune_talep_id'] = n1
    k1['miktar_l'] = (k1.get('miktar_l') or 0) + 1  # dup engeli
    k2['sira_no'] = 2
    k2['numune_talep_id'] = n2
    if k2.get('miktar_l'):
        k2['miktar_l'] = float(k2['miktar_l']) + 2
    elif k2.get('miktar_m'):
        k2['miktar_m'] = float(k2['miktar_m']) + 2
    payload2 = {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': _termin(),
        'anlasma_para_birimi': 'TRY',
        'anlasma_birim_fiyat': 100,
        'vade_gun': 30,
        'kalemler': [k1, k2],
    }
    st, d, ct = _json(sa, 'POST', '/nexgen/api/pazarlama/taslak-kaydet', json=payload2)
    tid2 = (d or {}).get('talep_id')
    _mark('write_cok_numune', st == 200 and d and d.get('ok') and tid2, f'st={st}')

    # Numunesiz
    k0 = dict(payload1['kalemler'][0])
    k0.pop('numune_talep_id', None)
    k0['miktar_l'] = (k0.get('miktar_l') or 5) + 3 if k0.get('miktar_l') else 0
    k0['miktar_m'] = (k0.get('miktar_m') or 5) + 3 if str(seed['urun_ailesi']).upper() == 'DOKME' else 0
    payload0 = {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': _termin(),
        'anlasma_para_birimi': 'TRY',
        'anlasma_birim_fiyat': 100,
        'vade_gun': 30,
        'kalemler': [k0],
    }
    st, d, ct = _json(sa, 'POST', '/nexgen/api/pazarlama/taslak-kaydet', json=payload0)
    tid0 = (d or {}).get('talep_id')
    _mark('write_numunesiz', st == 200 and d and d.get('ok') and tid0, f'st={st}')

    # Başka cari numunesi reddedilir
    if other:
        bad = dict(payload1)
        bad['kalemler'] = [dict(payload1['kalemler'][0])]
        bad['kalemler'][0]['numune_talep_id'] = int(other['id'])
        bad['kalemler'][0]['miktar_l'] = (bad['kalemler'][0].get('miktar_l') or 0) + 7
        st, d, ct = _json(sa, 'POST', '/nexgen/api/pazarlama/taslak-kaydet', json=bad)
        _mark(
            'reject_other_cari_numune',
            st in (400, 403) and 'json' in ct and not (d or {}).get('ok'),
            f'st={st} d={d}',
        )
    else:
        _mark('reject_other_cari_numune', True, 'SKIP no other')

    # DB doğrula
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if tid1:
        r = con.execute(
            'SELECT numune_talep_id FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
            (tid1,),
        ).fetchone()
        _mark('db_tek_fk', r and int(r['numune_talep_id']) == n1, str(dict(r) if r else None))
    else:
        _mark('db_tek_fk', False)

    if tid2:
        ids = [
            int(x['numune_talep_id'])
            for x in con.execute(
                'SELECT numune_talep_id FROM nexgen_planlama_siparis_kalem '
                'WHERE planlama_siparis_id=? ORDER BY sira_no',
                (tid2,),
            ).fetchall()
            if x['numune_talep_id'] is not None
        ]
        _mark('db_cok_fk', set(ids) == {n1, n2} or (n1 == n2 and set(ids) == {n1}), f'ids={ids}')
    else:
        _mark('db_cok_fk', False)

    if tid0:
        r0 = con.execute(
            'SELECT numune_talep_id FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
            (tid0,),
        ).fetchone()
        _mark('db_numunesiz_null', r0 and r0['numune_talep_id'] is None)
    else:
        _mark('db_numunesiz_null', False)

    still_null = con.execute(
        'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem WHERE numune_talep_id IS NULL'
    ).fetchone()[0]
    _mark('eski_null_korundu', still_null >= old_null, f'old={old_null} now={still_null}')
    con.close()

    # Cari360 sipariş API
    st, d, ct = _json(sa, 'GET', f'/nexgen/api/cari360/{cari_id}/siparisler')
    ok_sip = st == 200 and d and d.get('ok')
    row1 = next((x for x in (d or {}).get('liste') or [] if int(x['id']) == int(tid1 or 0)), None)
    _mark(
        'c360_siparis_numune',
        ok_sip and row1 and int(row1.get('bagli_numune_sayisi') or 0) >= 1
        and any(int(n['id']) == n1 for n in (row1.get('bagli_numuneler') or [])),
        f"row={row1 and {k: row1.get(k) for k in ('id','bagli_numune_sayisi','bagli_numuneler')}}",
    )

    # Cari360 numune API — bağlı sipariş
    st, d, ct = _json(sa, 'GET', f'/nexgen/api/cari360/{cari_id}/numuneler')
    nrow = next((x for x in (d or {}).get('liste') or [] if int(x['id']) == n1), None)
    _mark(
        'c360_numune_bagli_siparis',
        bool(nrow and int(nrow.get('bagli_siparis_sayisi') or 0) >= 1
             and any(int(s['id']) == int(tid1) for s in (nrow.get('bagli_siparisler') or []))),
        f"n={nrow and {k: nrow.get(k) for k in ('id','bagli_siparis_sayisi','bagli_siparisler')}}",
    )

    # Regression sekmeler
    for path, key in [
        (f'/nexgen/api/cari360/{cari_id}/ozet', 'reg_ozet'),
        (f'/nexgen/api/cari360/{cari_id}/uretim', 'reg_uretim'),
        (f'/nexgen/api/cari360/{cari_id}/gorusme', 'reg_gorusme'),
        ('/nexgen/api/pazarlama/talepler?page=1', 'reg_pzm_liste'),
    ]:
        st, d, ct = _json(sa, 'GET', path)
        _mark(key, st == 200 and 'json' in ct and bool(d and d.get('ok')), f'st={st}')

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

        page.goto(f'{BASE}/nexgen/cari360/{cari_id}?tab=siparisler', wait_until='networkidle')
        page.wait_for_timeout(1200)
        _mark('browser_siparis_numune_col', page.locator('th:text("Numune")').count() >= 1)
        page.screenshot(path=os.path.join(OUT, 'dilim3_cari360_siparisler.png'), full_page=True)

        page.goto(f'{BASE}/nexgen/cari360/{cari_id}?tab=numuneler', wait_until='networkidle')
        page.wait_for_timeout(1200)
        _mark('browser_numune_siparis_col', page.locator('th:text("Bağlı Siparişler")').count() >= 1)
        page.screenshot(path=os.path.join(OUT, 'dilim3_cari360_numuneler.png'), full_page=True)

        page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        page.wait_for_timeout(1000)
        _mark('browser_pzm_kaynak', page.locator('#pzm-kalem-numune').count() >= 1)
        page.screenshot(path=os.path.join(OUT, 'dilim3_pazarlama_kaynak_numune.png'), full_page=True)
        browser.close()

    failed = [k for k, v in RESULTS.items() if not v]
    print('OUT', OUT)
    print('SUMMARY', f'{len(RESULTS)-len(failed)}/{len(RESULTS)} PASS')
    if failed:
        print('FAILED', failed)
    return 1 if failed else 0


if __name__ == '__main__':
    # Fix accidental bad import path
    raise SystemExit(main())
