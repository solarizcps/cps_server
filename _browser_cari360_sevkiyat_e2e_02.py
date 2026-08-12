# -*- coding: utf-8 -*-
"""CARI360-SEVKIYATLAR-VISUAL-E2E-02 — DB/API/DOM üçlü doğrulama."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
DB = APP / 'mock_data.db'
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
TMPL = APP / 'templates' / 'nexgen' / 'cari360_kart.html'
ROUTES_SEVK = APP / 'modules' / 'nexgen' / 'mo_sevkiyat_routes.py'
ROUTES_MAIN = APP / 'modules' / 'nexgen' / 'routes.py'

sys.path.insert(0, str(APP))
os.chdir(APP)
import tools.test_db_guard  # noqa: E402  TEST-DB-GUARD autostart
from tools.test_db_http_guard import allow_http_base_url  # noqa: E402

allow_http_base_url(BASE)

import requests  # noqa: E402

SHA_BEFORE = hashlib.sha256(DB.read_bytes()).hexdigest()
RESULTS: list[tuple[str, bool, str]] = []


def mark(name: str, ok: bool, detail: str = '') -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(('PASS' if ok else 'FAIL'), name, ('— ' + detail) if detail else '')
    return bool(ok)


def login() -> requests.Session:
    db_uri = f'file:{DB.resolve()}?mode=ro'
    con = sqlite3.connect(db_uri, uri=True)
    pw = con.execute(
        "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin' AND Aktif=1"
    ).fetchone()[0]
    con.close()
    s = requests.Session()
    s.get(f'{BASE}/giris', timeout=20)
    s.post(f'{BASE}/giris', data={'kullanici': 'admin', 'sifre': pw}, timeout=20)
    return s


def db_shipment(con: sqlite3.Connection, sevkiyat_no: str) -> dict | None:
    row = con.execute(
        """
        SELECT s.id, s.sevkiyat_no, s.sevk_tarihi, s.durum, s.siparis_id, s.cari_id,
               ps.siparis_no
        FROM mo_musteri_sevkiyat s
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = s.siparis_id
        WHERE s.sevkiyat_no=? AND COALESCE(s.aktif,1)=1
        """,
        (sevkiyat_no,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    kalemler = con.execute(
        """
        SELECT urun_adi, renk_ad, miktar_kg
        FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?
        ORDER BY id ASC
        """,
        (d['id'],),
    ).fetchall()
    d['kalemler'] = [dict(k) for k in kalemler]
    d['sevk_kg'] = sum(float(k['miktar_kg'] or 0) for k in d['kalemler'])
    batches = con.execute(
        """
        SELECT DISTINCT b.batch_kodu
        FROM nexgen_uretim_batch b
        JOIN nexgen_uretim_plan p ON p.id = b.plan_id
        WHERE p.planlama_siparis_id=? AND COALESCE(p.durum,'') NOT IN ('IPTAL')
        ORDER BY b.id ASC LIMIT 1
        """,
        (d['siparis_id'],),
    ).fetchone()
    d['batch_kodu'] = batches['batch_kodu'] if batches else ''
    plan = con.execute(
        """
        SELECT id FROM nexgen_uretim_plan
        WHERE planlama_siparis_id=? AND COALESCE(durum,'') NOT IN ('IPTAL')
        ORDER BY id ASC LIMIT 1
        """,
        (d['siparis_id'],),
    ).fetchone()
    d['plan_id'] = int(plan['id']) if plan else None
    return d


def api_sevk(s: requests.Session, cari_id: int) -> dict:
    r = s.get(
        f'{BASE}/nexgen/api/cari360/{cari_id}/sevkiyatlar?page=1&page_size=10',
        headers={'Accept': 'application/json'},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def link_forensic() -> None:
    print('\n=== 1. LINK FORENSIC ===')
    sevk_src = ROUTES_SEVK.read_text(encoding='utf-8')
    main_src = ROUTES_MAIN.read_text(encoding='utf-8')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row

    mark('LF-sevkiyat-route', "@bp.route('/sevkiyat/<int:sevkiyat_id>')" in sevk_src)
    mark('LF-pazarlama-route', "@nexgen_bp.route('/pazarlama')" in main_src)
    mark('LF-uretim-route', "@nexgen_bp.route('/uretim-emirleri')" in main_src)

    d227 = db_shipment(con, 'MSV-2026-0165')
    if d227:
        href = f'/nexgen/sevkiyat/{d227["id"]}'
        mark('LF-sevkiyat-target-exists', True, f'id={d227["id"]}')
        mark('LF-sevkiyat-display', d227['sevkiyat_no'] == 'MSV-2026-0165')
        rs = login()
        code = rs.get(f'{BASE}{href}', timeout=20).status_code
        mark('LF-sevkiyat-http', code in (200, 302, 403), str(code))

        sip_href = f'/nexgen/pazarlama?siparis={d227["siparis_id"]}'
        mark('LF-siparis-target-exists', bool(con.execute(
            'SELECT 1 FROM nexgen_planlama_siparis WHERE id=?', (d227['siparis_id'],)
        ).fetchone()))
        mark('LF-siparis-display', d227['siparis_no'] == 'PZM-2026-0221')
        code2 = rs.get(f'{BASE}{sip_href}', timeout=20).status_code
        mark('LF-siparis-http', code2 in (200, 302, 403), str(code2))

        if d227.get('plan_id'):
            plan_href = f'/nexgen/uretim-emirleri?vurgu={d227["plan_id"]}'
            mark('LF-plan-target-exists', True, f'plan_id={d227["plan_id"]}')
            code3 = rs.get(f'{BASE}{plan_href}', timeout=20).status_code
            mark('LF-plan-http', code3 in (200, 302, 403), str(code3))
    con.close()


def compare_case(s: requests.Session, cari_id: int, sevkiyat_no: str, label: str) -> None:
    print(f'\n=== {label} cari_id={cari_id} ===')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    db = db_shipment(con, sevkiyat_no)
    api = api_sevk(s, cari_id)
    item = next((x for x in (api.get('liste') or []) if x.get('sevkiyat_no') == sevkiyat_no), None)
    con.close()

    if not db:
        mark(f'{label}-db-found', False, sevkiyat_no)
        return
    mark(f'{label}-db-found', True)
    mark(f'{label}-api-ok', api.get('ok') is True)
    mark(f'{label}-api-item', item is not None, sevkiyat_no)

    if not item:
        return

    mark(f'{label}-sevk-no', item.get('sevkiyat_no') == db['sevkiyat_no'])
    mark(f'{label}-siparis-no', item.get('siparis_no') == db['siparis_no'])
    mark(f'{label}-urun', item.get('urun') == (db['kalemler'][0]['urun_adi'] if db['kalemler'] else ''))
    mark(f'{label}-renk', item.get('renk') == (db['kalemler'][0]['renk_ad'] if db['kalemler'] else ''))
    mark(f'{label}-sevk-kg', float(item.get('sevk_kg') or 0) == db['sevk_kg'], f"api={item.get('sevk_kg')} db={db['sevk_kg']}")
    mark(f'{label}-durum', item.get('durum') == db['durum'])
    mark(f'{label}-batch', item.get('batch_kodu') == db['batch_kodu'], item.get('batch_kodu'))
    if db['sevk_tarihi']:
        mark(f'{label}-gercek-sevk', (item.get('gercek_sevk_tarihi') or '').startswith(db['sevk_tarihi'][:10]))
    mark(f'{label}-sevkiyat-url', item.get('sevkiyat_url') == f"/nexgen/sevkiyat/{db['id']}")
    mark(f'{label}-siparis-url', item.get('siparis_url') == f"/nexgen/pazarlama?siparis={db['siparis_id']}")
    if db.get('plan_id'):
        mark(f'{label}-plan-url', item.get('plan_url') == f"/nexgen/uretim-emirleri?vurgu={db['plan_id']}")


def empty_case(s: requests.Session) -> None:
    print('\n=== EMPTY cari_id=16 ===')
    api = api_sevk(s, 16)
    mark('EMPTY-total-count', api.get('total_count') == 0, str(api.get('total_count')))
    mark('EMPTY-liste', len(api.get('liste') or []) == 0)


def pagination_case(s: requests.Session) -> None:
    print('\n=== PAGINATION cari_id=5 ===')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    hdr = con.execute(
        'SELECT COUNT(*) FROM mo_musteri_sevkiyat WHERE cari_id=5 AND COALESCE(aktif,1)=1'
    ).fetchone()[0]
    con.close()
    api = api_sevk(s, 5)
    mark('PG-page-size', api.get('page_size') == 10)
    mark('PG-total-count-header', api.get('total_count') == hdr, f"api={api.get('total_count')} db={hdr}")
    ids = [x['id'] for x in (api.get('liste') or [])]
    mark('PG-one-row-per-header', len(ids) == len(set(ids)), str(ids))
    mark('PG-no-kalem-inflation', api.get('total_count') == 2, str(api.get('total_count')))


def multi_kalem_contract() -> None:
    print('\n=== MULTI-KALEM CONTRACT (in-memory) ===')
    import unittest.mock as mock
    from modules.nexgen.cari360_ops_read_service import load_cari360_sevkiyatlar

    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER DEFAULT 1);
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, sevk_tarihi TEXT, olusturma_tarihi TEXT, aktif INTEGER DEFAULT 1,
            irsaliye_no TEXT, hazirlik_tarihi TEXT, teslim_tarihi TEXT,
            arac_plaka TEXT, sofor TEXT, kargo_firmasi TEXT, kargo_takip_no TEXT,
            teslim_alan TEXT, teslim_durumu TEXT, notlar TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, siparis_kalem_id INTEGER,
            urun_adi TEXT, renk_ad TEXT, formul_ad TEXT, miktar_kg REAL, miktar_adet REAL, notlar TEXT
        );
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, olusturma_tarihi TEXT, durum TEXT
        );
        INSERT INTO nexgen_cari VALUES (99,'T.99','Test',1);
        INSERT INTO nexgen_planlama_siparis VALUES (900,'PZM-T-900',99,'2026-01-01','ONAY');
        INSERT INTO mo_musteri_sevkiyat VALUES
          (9001,'MSV-T-9001',900,99,'SEVK_EDILDI','2026-08-01','2026-08-01',1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
        INSERT INTO mo_musteri_sevkiyat_kalem VALUES
          (1,9001,1,'URUN-A','RENK-A','',1000,NULL,''),
          (2,9001,2,'URUN-B','RENK-B','',500,NULL,'');
    """)
    with mock.patch('modules.nexgen.cari360_ops_read_service._assert_cari', return_value={'id': 99}), mock.patch(
        'modules.nexgen.cari360_ops_read_service.can_view_cari', return_value=True
    ):
        r = load_cari360_sevkiyatlar(con, 99, 1, {'*'}, page=1, page_size=10)
    mark('MK-one-header-row', len(r['liste']) == 1)
    mark('MK-total-count-1', r['total_count'] == 1)
    row = r['liste'][0]
    mark('MK-kalem-count-2', row.get('kalem_sayisi') == 2)
    mark('MK-sevk-kg-sum', float(row.get('sevk_kg') or 0) == 1500, str(row.get('sevk_kg')))
    mark('MK-first-kalem-urun', row.get('urun') == 'URUN-A')
    con.close()


def browser_e2e(s: requests.Session) -> None:
    print('\n=== BROWSER E2E ===')
    from playwright.sync_api import sync_playwright

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    pw = con.execute("SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()[0]
    con.close()
    src = TMPL.read_text(encoding='utf-8')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.goto(f'{BASE}/giris', wait_until='domcontentloaded')
        page.fill('input[name="kullanici"]', 'admin')
        page.fill('input[name="sifre"]', pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle', timeout=30000)

        # CASE A
        page.goto(f'{BASE}/nexgen/cari360/5?tab=sevkiyatlar', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1500)
        body = page.inner_text('#ckart-sevk-tbody')
        mark('DOM-A-msv165', 'MSV-2026-0165' in body)
        mark('DOM-A-siparis', 'PZM-2026-0221' in body)
        mark('DOM-A-urun', 'TERLIK' in body)
        mark('DOM-A-renk', 'TURUNCU' in body)
        mark('DOM-A-batch', 'NG-PRD-2026-00029' in body)
        mark('DOM-A-kg', '3000' in body)
        mark('DOM-A-durum', 'SEVK ED' in body.upper() or 'Sevk Edildi' in body)

        ths = [t.strip().upper() for t in page.locator('#ckart-sevk-tablo th').all_inner_texts() if t.strip()]
        for col, needle in [
            ('Sevkiyat', 'SEVKİYAT / İRSALİYE'),
            ('Tarih', 'TARİH'),
            ('Siparis', 'SİPARİŞ NO'),
            ('Batch', 'BATCH'),
            ('Urun', 'ÜRÜN'),
            ('Renk', 'RENK'),
            ('Kg', 'SEVK KG'),
            ('Durum', 'DURUM'),
        ]:
            mark(f'DOM-A-col-{col}', needle in ths, str(ths))

        row165 = page.locator('#ckart-sevk-tbody tr.ckart-sip-row', has_text='MSV-2026-0165')
        mark('DOM-A-row165', row165.count() == 1)
        expand = row165.locator('.ckart-urt-expand-btn').first if row165.count() else page.locator('#ckart-sevk-tbody .ckart-urt-expand-btn').first
        mark('DOM-A-expand-btn', expand.count() > 0)
        if expand.count():
            expand.click()
            page.wait_for_timeout(500)
            detail = page.locator('#ckart-sevk-tbody tr#sevk-detail-227 .ckart-urt-detail-panel')
            mark('DOM-A-expand-open', detail.count() and detail.first.is_visible())
            dtxt = detail.first.inner_text().upper() if detail.count() else ''
            for blk, needle in [
                ('Sevkiyat', 'SEVKİYAT BİLGİSİ'),
                ('Urun', 'ÜRÜN / KALEM'),
                ('Siparis', 'SİPARİŞ BAĞLANTISI'),
                ('Baglantilar', 'BAĞLANTILAR'),
            ]:
                mark(f'DOM-A-block-{blk}', needle in dtxt)
            mark('DOM-A-link-sevkiyat', page.locator('#ckart-sevk-tbody a[href*="/nexgen/sevkiyat/227"]').count() > 0)
            mark('DOM-A-link-siparis', page.locator('#ckart-sevk-tbody a[href*="pazarlama?siparis=759"]').count() > 0)

        # CSS reuse — no new sevk-specific detail CSS block
        mark('CSS-urt-expand-btn', 'ckart-urt-expand-btn' in src)
        mark('CSS-urt-detail-panel', 'ckart-urt-detail-panel' in src)
        mark('CSS-no-new-sevk-detail-system', '.ckart-sevk-detail-panel' not in src)
        mark('CSS-no-new-sevk-badge-system', '.ckart-sevk-durum-badge' not in src)

        classes = page.evaluate("""() => {
            const btn = document.querySelector('#ckart-sevk-tbody .ckart-urt-expand-btn');
            const panel = document.querySelector('#ckart-sevk-tbody .ckart-urt-detail-panel');
            const badge = document.querySelector('#ckart-sevk-tbody .ckart-urt-dur');
            return {
                btn: btn ? getComputedStyle(btn).fontSize : null,
                panelTitle: panel ? getComputedStyle(panel.querySelector('.ckart-urt-detail-group-title')).fontSize : null,
                badge: badge ? badge.className : null,
            };
        }""")
        mark('CSS-dom-expand-class', 'ckart-urt-expand-btn' in (page.locator('#ckart-sevk-tbody .ckart-urt-expand-btn').first.get_attribute('class') or ''))
        mark('CSS-dom-badge-urt', 'ckart-urt-dur' in (classes.get('badge') or ''))

        # CASE B
        page.goto(f'{BASE}/nexgen/cari360/11?tab=sevkiyatlar', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1200)
        body11 = page.inner_text('#ckart-sevk-tbody')
        mark('DOM-B-msv166', 'MSV-2026-0166' in body11)
        mark('DOM-B-siparis', 'PZM-2026-0222' in body11)
        mark('DOM-B-kg', '2000' in body11)

        # EMPTY
        page.goto(f'{BASE}/nexgen/cari360/16?tab=sevkiyatlar', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1200)
        empty_txt = page.inner_text('#ckart-sevk-tbody')
        mark('DOM-EMPTY-msg', 'Bu cari için sevkiyat kaydı yok.' in empty_txt)

        browser.close()


def main() -> int:
    link_forensic()
    s = login()
    compare_case(s, 5, 'MSV-2026-0165', 'CASE-A')
    compare_case(s, 11, 'MSV-2026-0166', 'CASE-B')
    empty_case(s)
    pagination_case(s)
    multi_kalem_contract()
    try:
        browser_e2e(s)
    except Exception as e:
        mark('BROWSER-E2E', False, str(e)[:200])

    sha_after = hashlib.sha256(DB.read_bytes()).hexdigest()
    print('\n=== SUMMARY ===')
    fails = [r for r in RESULTS if not r[1]]
    print(f'TOTAL={len(RESULTS)} PASS={len(RESULTS)-len(fails)} FAIL={len(fails)}')
    print(f'SHA BEFORE={SHA_BEFORE}')
    print(f'SHA AFTER ={sha_after}')
    if fails:
        for name, _, detail in fails:
            print(' FAIL>', name, detail)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
