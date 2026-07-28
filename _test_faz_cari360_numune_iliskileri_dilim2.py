# -*- coding: utf-8 -*-
"""FAZ-CARI360-NUMUNE-ILISKILERI Dilim 2 — gorusme.numune_talep_id."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, 'app', 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(ROOT, 'backup', 'faz_cari360_numune_iliskileri_uygulama_1_dilim2', 'screenshots')
os.makedirs(OUT, exist_ok=True)
RESULTS: dict[str, bool] = {}


def _mark(name: str, ok: bool, note: str = '') -> None:
    RESULTS[name] = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {note}" if note else ''))


def _login(user, pw):
    s = requests.Session()
    s.get(f'{BASE}/giris', timeout=20).raise_for_status()
    s.post(f'{BASE}/giris', data={'kullanici': user, 'sifre': pw}, timeout=20, allow_redirects=True).raise_for_status()
    return s


def _json(s, method, path, **kw):
    headers = kw.pop('headers', {})
    headers.setdefault('Accept', 'application/json')
    if method.upper() == 'POST':
        headers.setdefault('Content-Type', 'application/json')
    r = s.request(method, f'{BASE}{path}', headers=headers, timeout=30, **kw)
    ct = (r.headers.get('content-type') or '').lower()
    data = r.json() if 'application/json' in ct else None
    return r.status_code, data, ct


def main() -> int:
    con = sqlite3.connect(DB)
    cols = {c[1] for c in con.execute('pragma table_info(musteri_operasyon_gorusme)')}
    _mark('mig_col', 'numune_talep_id' in cols)
    admin_pw = con.execute("SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()[0]
    mehmet_pw = con.execute("SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='mehmet'").fetchone()[0]
    cari_id = 1
    numune = con.execute(
        """
        SELECT id, talep_kodu FROM nexgen_numune_talep
        WHERE cari_id=? AND COALESCE(aktif,1)=1 ORDER BY id DESC LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    other_numune = con.execute(
        """
        SELECT id, cari_id FROM nexgen_numune_talep
        WHERE cari_id IS NOT NULL AND cari_id!=? AND COALESCE(aktif,1)=1 LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    old_count = con.execute(
        'SELECT COUNT(*) FROM musteri_operasyon_gorusme WHERE cari_id=? AND aktif=1',
        (cari_id,),
    ).fetchone()[0]
    con.close()
    if not numune:
        print('FAIL no numune')
        return 1

    for _ in range(20):
        try:
            if requests.get(f'{BASE}/giris', timeout=3).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print('FAIL server')
        return 1

    sa = _login('admin', admin_pw)
    stamp = datetime.now().strftime('%H%M%S')

    # Genel görüşme — numune yok
    st, d, ct = _json(
        sa, 'POST', f'/nexgen/api/cari360/{cari_id}/gorusme',
        data=json.dumps({
            'gorusme_tipi': 'Telefon',
            'sonuc_tipi': 'Genel Görüşme',
            'kisa_not': f'Dilim2 genel {stamp}',
            'gorusme_tarihi': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'idempotency_key': f'dilim2-genel-{stamp}',
            'numune_talep_id': None,
        }),
    )
    ok = st == 200 and d and d.get('ok')
    kayit = (d or {}).get('kayit') or {}
    _mark('gorusme_no_numune', ok and kayit.get('kaynak_numune_talep_id') in (None, 0), f'status={st}')
    if ok:
        con = sqlite3.connect(DB)
        row = con.execute(
            'SELECT numune_talep_id FROM musteri_operasyon_gorusme WHERE id=?',
            (kayit['id'],),
        ).fetchone()
        con.close()
        _mark('db_null_numune', row and row[0] is None, str(row))

    # Numuneye bağlı
    st, d, ct = _json(
        sa, 'POST', f'/nexgen/api/cari360/{cari_id}/gorusme',
        data=json.dumps({
            'gorusme_tipi': 'Telefon',
            'sonuc_tipi': 'Genel Görüşme',
            'kisa_not': f'Dilim2 numune bagli {stamp}',
            'gorusme_tarihi': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'idempotency_key': f'dilim2-num-{stamp}',
            'numune_talep_id': int(numune[0]),
        }),
    )
    ok = st == 200 and d and d.get('ok')
    kayit = (d or {}).get('kayit') or {}
    _mark(
        'gorusme_with_numune',
        ok and int(kayit.get('kaynak_numune_talep_id') or 0) == int(numune[0]),
        f'status={st} kayit={kayit.get("kaynak_numune_talep_id")} kod={kayit.get("kaynak_numune_kodu")}',
    )
    _mark('numune_kodu', bool(kayit.get('kaynak_numune_kodu')), kayit.get('kaynak_numune_kodu'))
    _mark('numune_url', '/numune-talep?id=' in str(kayit.get('kaynak_numune_url') or ''))

    # Başka cari numune → 403
    if other_numune:
        st, d, ct = _json(
            sa, 'POST', f'/nexgen/api/cari360/{cari_id}/gorusme',
            data=json.dumps({
                'gorusme_tipi': 'Telefon',
                'sonuc_tipi': 'Genel Görüşme',
                'kisa_not': f'Dilim2 leak {stamp}',
                'gorusme_tarihi': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'idempotency_key': f'dilim2-leak-{stamp}',
                'numune_talep_id': int(other_numune[0]),
            }),
        )
        _mark('other_cari_numune_403', st in (403, 400), f'status={st} {d}')
    else:
        _mark('other_cari_numune_403', True, 'SKIP')

    # Eski liste bozulmadı
    st, d, ct = _json(sa, 'GET', f'/nexgen/api/cari360/{cari_id}/gorusme')
    _mark(
        'list_ok',
        st == 200 and d and d.get('ok') and int(d.get('count') or 0) >= old_count,
        f'count={ (d or {}).get("count") } old={old_count}',
    )

    # Takip regression — açık takip ayarla yeni kayda
    if kayit.get('id'):
        st, d, ct = _json(
            sa, 'POST',
            f'/nexgen/api/cari360/{cari_id}/gorusme/{int(kayit["id"])}',
            data=json.dumps({
                'gorusme_tipi': 'Telefon',
                'sonuc_tipi': 'Genel Görüşme',
                'kisa_not': f'Dilim2 numune bagli {stamp} upd',
                'konu': 'upd',
                'sonraki_takip_tarihi': '2026-08-15',
                'takip_durumu': 'ACIK',
                'numune_talep_id': int(numune[0]),
            }),
        )
        _mark('takip_update', st == 200 and d and d.get('ok'), f'status={st}')

    # Browser
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.goto(f'{BASE}/giris', wait_until='networkidle')
            page.fill('input[name="kullanici"]', 'admin')
            page.fill('input[name="sifre"]', admin_pw)
            page.click('button[type="submit"]')
            page.wait_for_load_state('networkidle')
            page.goto(f'{BASE}/nexgen/cari360/{cari_id}?tab=gorusmeler', wait_until='networkidle')
            page.wait_for_timeout(1200)
            _mark('browser_numune_col', page.locator('th:text("Numune")').count() >= 1)
            page.locator('button:has-text("Yeni Görüşme")').click()
            page.wait_for_timeout(800)
            _mark('browser_numune_select', page.locator('#ckart-g-numune').count() == 1)
            page.screenshot(path=os.path.join(OUT, 'dilim2_gorusme_modal.png'), full_page=True)
            browser.close()
    except Exception as e:
        _mark('browser_numune_col', False, str(e)[:80])
        _mark('browser_numune_select', False)

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
