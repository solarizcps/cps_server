# -*- coding: utf-8 -*-
"""FAZ-PZM-ADMIN-SIPARIS-SILME-1A — browser matrix (tam temizlik + UI)."""
import io
import json
import os
import sys
import threading
import time
from datetime import datetime

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)

import sqlite3
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from config import Config
import app as flask_app

BASE = os.environ.get('CPS_BASE_URL', 'http://127.0.0.1:8083')
USE_EMBEDDED = not os.environ.get('CPS_BASE_URL')
_server = None
if USE_EMBEDDED:
    _server = make_server('127.0.0.1', 8083, flask_app.app, threaded=True)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    time.sleep(1.2)

TS = datetime.now().strftime('%Y%m%d_%H%M%S')
SHOT_DIR = os.path.join(_ROOT, 'backup', 'screenshots', f'pzm_admin_silme_1a_{TS}')
os.makedirs(SHOT_DIR, exist_ok=True)

results = []
console_errors = []
network_errors = []
_restore_sql = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def db():
    con = sqlite3.connect(Config.MOCK_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def pw_of(uname):
    con = db()
    try:
        row = con.execute(
            'SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1',
            (uname,),
        ).fetchone()
        return row['Sifre'] if row else None
    finally:
        con.close()


def siparis_row(no):
    con = db()
    try:
        return con.execute(
            'SELECT id, siparis_no, durum FROM nexgen_planlama_siparis WHERE siparis_no=?',
            (no,),
        ).fetchone()
    finally:
        con.close()


def _silinebilir_mi(con, sid, siparis_no):
    """Backend guard ile uyumlu — ticari engel yoksa True."""
    plans = [r['id'] for r in con.execute(
        'SELECT id, durum FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (sid,)
    )]
    for r in con.execute(
        'SELECT durum FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (sid,)
    ):
        if (r['durum'] or '').upper() in ('BITTI', 'SEVK_EDILDI', 'TAMAMLANDI'):
            return False
    if plans:
        ph = ','.join('?' * len(plans))
        for r in con.execute(
            f'SELECT durum FROM nexgen_uretim_batch WHERE plan_id IN ({ph})', plans
        ):
            if (r['durum'] or '').upper() in ('BITTI', 'SEVK_EDILDI', 'TAMAMLANDI'):
                return False
        sh = con.execute(
            f"""SELECT COUNT(*) n FROM nexgen_stok_hareket
                WHERE (referans_tip IN ('URETIM_PLAN','PLAN','MPR_PLAN') AND referans_id IN ({ph}))
                   OR (referans_tip IN ('URETIM_BATCH','BATCH') AND referans_id IN (
                        SELECT id FROM nexgen_uretim_batch WHERE plan_id IN ({ph})))""",
            plans + plans,
        ).fetchone()['n']
        if sh:
            return False
    fb = con.execute(
        "SELECT COUNT(*) n FROM finans_belgesi WHERE IFNULL(aktif,1)=1 AND IFNULL(siparis_no,'')=?",
        (siparis_no,),
    ).fetchone()['n']
    return fb == 0


def pick_sil(durum, prefer_batch=False, exclude=None):
    exclude = set(exclude or [])
    con = db()
    try:
        rows = con.execute(
            """SELECT id, siparis_no FROM nexgen_planlama_siparis
               WHERE durum=? AND siparis_no LIKE 'PZM%' ORDER BY id ASC""",
            (durum,),
        ).fetchall()
        aday = None
        for r in rows:
            if r['siparis_no'] in exclude:
                continue
            if not _silinebilir_mi(con, r['id'], r['siparis_no']):
                continue
            batches = 0
            if prefer_batch:
                batches = con.execute(
                    """SELECT COUNT(*) n FROM nexgen_uretim_batch b
                       JOIN nexgen_uretim_plan p ON p.id=b.plan_id
                       WHERE p.planlama_siparis_id=?""",
                    (r['id'],),
                ).fetchone()['n']
                if batches <= 0:
                    continue
            aday = r['siparis_no']
            if prefer_batch and batches > 0:
                return aday
            if not prefer_batch:
                return aday
        return aday
    finally:
        con.close()


def batch_kodlari(siparis_no):
    con = db()
    try:
        rows = con.execute(
            """SELECT b.batch_kodu FROM nexgen_uretim_batch b
               JOIN nexgen_uretim_plan p ON p.id=b.plan_id
               JOIN nexgen_planlama_siparis s ON s.id=p.planlama_siparis_id
               WHERE s.siparis_no=?""",
            (siparis_no,),
        ).fetchall()
        return [r['batch_kodu'] for r in rows if r['batch_kodu']]
    finally:
        con.close()


def fetch_talep_dict(siparis_no):
    con = db()
    try:
        from modules.nexgen.routes import _pzm_talep_satir_dict
        row = con.execute(
            '''SELECT id, siparis_no, cari_id, cari_unvan, termin_tarihi,
                      durum, notlar, talep_referansi, olusturma_tarihi,
                      olusturan_id, kaynak_modul, anlasma_para_birimi,
                      vade_gun, anlasma_birim_fiyat, musteri_termin,
                      onerilen_termin, teslim_sekli, revizyon_gerekce
               FROM nexgen_planlama_siparis WHERE siparis_no=?''',
            (siparis_no,),
        ).fetchone()
        return _pzm_talep_satir_dict(row, con) if row else None
    finally:
        con.close()


def inject_talepler(route, extra_nos):
    resp = route.fetch()
    data = resp.json()
    liste = data.get('liste') or []
    existing = {x.get('siparis_no') for x in liste}
    for no in extra_nos:
        if no in existing or not no:
            continue
        t = fetch_talep_dict(no)
        if t:
            liste.insert(0, t)
    data['liste'] = liste
    route.fulfill(
        status=resp.status,
        content_type='application/json',
        body=json.dumps(data, ensure_ascii=False),
    )


def login(page, uname, extra_nos=None, require_pazarlama=True):
    pwd = pw_of(uname)
    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', uname)
    page.fill('input[name="sifre"]', pwd or '')
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle')
    if extra_nos:
        page.route(
            '**/nexgen/api/pazarlama/talepler',
            lambda route: inject_talepler(route, extra_nos),
        )
    if require_pazarlama:
        with page.expect_response(
            lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200,
            timeout=45000,
        ):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
    else:
        page.goto(f'{BASE}/nexgen/pazarlama', wait_until='domcontentloaded')
        page.wait_for_timeout(800)
    page.wait_for_timeout(400)


def open_detay(page, siparis_no):
    row = siparis_row(siparis_no)
    if not row:
        return None
    tid = row['id']
    page.wait_for_selector(f'#pzm-tbody tr:has-text("{siparis_no}")', timeout=20000)
    page.locator('#pzm-tbody tr').filter(has_text=siparis_no).first.click()
    page.wait_for_function(
        '() => document.getElementById("ekran-detay")?.style.display !== "none"',
        timeout=20000,
    )
    page.wait_for_timeout(400)
    return tid


def sil_btn_ust(page):
    return page.evaluate(
        """() => {
          const btn = document.getElementById('pzm-detay-btn-sil');
          if (!btn) return {exists: false};
          const r = btn.getBoundingClientRect();
          const alt = document.getElementById('pzm-detay-alt-butonlar');
          const inAlt = !!(alt && alt.contains(btn));
          return {
            exists: true,
            visible: r.width > 0 && r.height > 0 && getComputedStyle(btn).display !== 'none',
            disabled: !!btn.disabled,
            text: (btn.textContent || '').trim(),
            inAltBand: inAlt,
            top: Math.round(r.top),
          };
        }"""
    )


def alt_band_has_sil(page):
    return page.evaluate(
        """() => {
          const alt = document.getElementById('pzm-detay-alt-butonlar');
          if (!alt) return false;
          return Array.from(alt.querySelectorAll('button'))
            .some(b => (b.textContent || '').indexOf('Siparişi Sil') >= 0);
        }"""
    )


def do_delete_flow(page, siparis_no, wrong_first=True):
    page.click('#pzm-detay-btn-sil')
    page.wait_for_function(
        '() => document.getElementById("pzm-sil-panel")?.style.display === "flex"',
        timeout=8000,
    )
    onay = page.locator('#pzm-sil-onay-btn')
    ok('popup açıldı', page.locator('#pzm-sil-panel').is_visible())
    warn = page.locator('#pzm-sil-panel').inner_text()
    ok(
        'popup plan/batch uyarısı',
        'test planlarını ve batch kayıtlarını kalıcı olarak siler' in warn,
        warn[:120].replace('\n', ' '),
    )
    ok('onay başlangıçta pasif', onay.is_disabled())
    if wrong_first:
        page.fill('#pzm-sil-confirm-inp', 'YANLIS-NO')
        page.wait_for_timeout(100)
        ok('yanlış yazıda onay pasif', onay.is_disabled())
    page.fill('#pzm-sil-confirm-inp', siparis_no)
    page.wait_for_timeout(120)
    ok('doğru yazıda onay aktif', not onay.is_disabled(), siparis_no)
    row = siparis_row(siparis_no)
    tid = row['id']
    with page.expect_response(
        lambda r: f'/nexgen/api/pazarlama/talep/{tid}/sil' in r.url and r.request.method == 'POST',
        timeout=30000,
    ) as resp_info:
        onay.click()
    resp = resp_info.value
    data = resp.json()
    page.wait_for_timeout(400)
    return resp.status, data


def api_sil(page, tid, no):
    return page.evaluate(
        """async ({tid, no}) => {
          const r = await fetch('/nexgen/api/pazarlama/talep/' + tid + '/sil', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({siparis_no: no}),
          });
          return {status: r.status, data: await r.json()};
        }""",
        {'tid': tid, 'no': no},
    )


def insert_finans_blok(siparis_no, with_sevkiyat=False):
    con = db()
    try:
        sip = con.execute(
            'SELECT cari_id, cari_unvan FROM nexgen_planlama_siparis WHERE siparis_no=?',
            (siparis_no,),
        ).fetchone()
        cari_id = (sip['cari_id'] if sip and sip['cari_id'] else 1)
        cari_unvan = (sip['cari_unvan'] if sip and sip['cari_unvan'] else 'TEST CARI')
        kod = f'TEST-SIL-{TS}-{"SV" if with_sevkiyat else "FN"}'
        con.execute(
            """INSERT INTO finans_belgesi
               (belge_kodu, belge_tipi, durum, siparis_no, cari_id, cari_unvan,
                islem_tarihi, para_birimi, toplam_tutar, idempotency_key, aktif, sevkiyat_id)
               VALUES (?, 'FATURA', 'BEKLIYOR', ?, ?, ?, date('now'), 'TRY', 0, ?, 1, ?)""",
            (
                kod, siparis_no, cari_id, cari_unvan, kod,
                999001 if with_sevkiyat else None,
            ),
        )
        fid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
        con.commit()
        _restore_sql.append(('DELETE FROM finans_belgesi WHERE id=?', (fid,)))
        return fid
    finally:
        con.close()


def restore_all():
    if not _restore_sql:
        return
    con = db()
    try:
        for sql, args in _restore_sql:
            try:
                con.execute(sql, args)
            except Exception as e:
                print('  [restore warn]', e)
        con.commit()
    finally:
        con.close()
    _restore_sql.clear()


SIL_TASLAK = os.environ.get('PZM_SIL_TASLAK') or pick_sil('TASLAK')
SIL_MPR = os.environ.get('PZM_SIL_MPR') or pick_sil('MPR_BEKLIYOR', exclude=[SIL_TASLAK])
SIL_URETIM = os.environ.get('PZM_SIL_URETIM') or pick_sil(
    'URETIMDE', prefer_batch=True, exclude=[SIL_TASLAK, SIL_MPR]
)
BLOK_FINANS_NO = os.environ.get('PZM_BLOK_FINANS') or pick_sil(
    'TASLAK', exclude=[SIL_TASLAK, SIL_MPR]
)
BLOK_SEVK_NO = os.environ.get('PZM_BLOK_SEVK') or pick_sil(
    'MPR_BEKLIYOR', exclude=[SIL_TASLAK, SIL_MPR, BLOK_FINANS_NO]
)

print('=== FAZ-PZM-ADMIN-SIPARIS-SILME-1A browser ===')
print('SHOT', SHOT_DIR)
print('aday', SIL_TASLAK, SIL_MPR, SIL_URETIM, 'blok', BLOK_FINANS_NO, BLOK_SEVK_NO)

EXTRA = [x for x in (SIL_TASLAK, SIL_MPR, SIL_URETIM, BLOK_FINANS_NO, BLOK_SEVK_NO) if x]
uretim_batches_once = batch_kodlari(SIL_URETIM) if SIL_URETIM else []

try:
    if BLOK_FINANS_NO:
        insert_finans_blok(BLOK_FINANS_NO, with_sevkiyat=False)
    if BLOK_SEVK_NO:
        insert_finans_blok(BLOK_SEVK_NO, with_sevkiyat=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # --- ADMIN ---
        ctx = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx.new_page()
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))
        page.on(
            'response',
            lambda r: network_errors.append(f'{r.status} {r.url}')
            if r.status >= 400 and '/nexgen/' in r.url and '/sil' not in r.url
            else None,
        )

        login(page, 'admin', EXTRA)
        ok('admin sil modal DOM', page.locator('#pzm-sil-panel').count() == 1)

        # 1 TASLAK
        ok(f'TASLAK aday ({SIL_TASLAK})', bool(SIL_TASLAK))
        tid = open_detay(page, SIL_TASLAK)
        st = sil_btn_ust(page)
        ok('TASLAK Sil üst sağda', st.get('exists') and st.get('visible') and not st.get('inAltBand'), str(st))
        ok('TASLAK Sil aktif', st.get('exists') and not st.get('disabled'), str(st))
        ok('Sil alt bantta yok', not alt_band_has_sil(page))
        page.screenshot(path=os.path.join(SHOT_DIR, 'admin_taslak_ust.png'), full_page=True)
        status, data = do_delete_flow(page, SIL_TASLAK)
        ok('TASLAK sil API', status == 200 and data.get('ok') is True, str(data))
        ok('TASLAK DB silindi', siparis_row(SIL_TASLAK) is None)
        ok(
            'silme sonrası liste',
            page.evaluate('() => document.getElementById("ekran-liste")?.style.display !== "none"'),
        )

        # 2 MPR
        with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        ok(f'MPR aday ({SIL_MPR})', bool(SIL_MPR))
        tid = open_detay(page, SIL_MPR)
        st = sil_btn_ust(page)
        ok('MPR Sil üst sağda aktif', st.get('visible') and not st.get('disabled') and not st.get('inAltBand'), str(st))
        ok('Sil alt bantta yok (MPR)', not alt_band_has_sil(page))
        status, data = do_delete_flow(page, SIL_MPR, wrong_first=False)
        ok('MPR sil API', status == 200 and data.get('ok') is True, str(data))
        ok('MPR DB silindi', siparis_row(SIL_MPR) is None)

        # 3 URETIMDE + batch
        with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        ok(f'URETIMDE aday ({SIL_URETIM})', bool(SIL_URETIM), f'batches={uretim_batches_once}')
        tid = open_detay(page, SIL_URETIM)
        st = sil_btn_ust(page)
        ok('URETIMDE Sil aktif (üst)', st.get('visible') and not st.get('disabled'), str(st))
        ok('Sil alt bantta yok (URETIM)', not alt_band_has_sil(page))
        page.screenshot(path=os.path.join(SHOT_DIR, 'admin_uretimde_ust.png'), full_page=True)
        status, data = do_delete_flow(page, SIL_URETIM, wrong_first=False)
        ok('URETIMDE sil API', status == 200 and data.get('ok') is True, str(data))
        ok('URETIMDE DB silindi', siparis_row(SIL_URETIM) is None)
        if uretim_batches_once:
            con = db()
            left = con.execute(
                f"SELECT COUNT(*) n FROM nexgen_uretim_batch WHERE batch_kodu IN ({','.join('?'*len(uretim_batches_once))})",
                uretim_batches_once,
            ).fetchone()['n']
            con.close()
            ok('URETIMDE batch DB temiz', left == 0, f'left={left} kod={uretim_batches_once}')

        # 4 Finans engel
        with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        ok(f'Finans blok aday ({BLOK_FINANS_NO})', bool(BLOK_FINANS_NO))
        tid = open_detay(page, BLOK_FINANS_NO)
        api = api_sil(page, tid, BLOK_FINANS_NO)
        ok(
            'Finans ilişkili engel',
            api.get('status') == 400 and not (api.get('data') or {}).get('ok')
            and 'Finans' in ((api.get('data') or {}).get('hata') or ''),
            str(api),
        )
        ok('Finans sipariş duruyor', siparis_row(BLOK_FINANS_NO) is not None)

        # 5 Sevkiyat engel (finans.sevkiyat_id)
        with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        ok(f'Sevkiyat blok aday ({BLOK_SEVK_NO})', bool(BLOK_SEVK_NO))
        tid = open_detay(page, BLOK_SEVK_NO)
        api = api_sil(page, tid, BLOK_SEVK_NO)
        hata = ((api.get('data') or {}).get('hata') or '')
        ok(
            'Sevkiyat/finans ilişkili engel',
            api.get('status') == 400 and not (api.get('data') or {}).get('ok')
            and ('sevkiyat' in hata.lower() or 'Finans' in hata),
            str(api),
        )
        ok('Sevkiyat sipariş duruyor', siparis_row(BLOK_SEVK_NO) is not None)

        ctx.close()

        # 6 Mehmet
        ctx2 = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx2.new_page()
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))
        login(page, 'mehmet', [BLOK_FINANS_NO] if BLOK_FINANS_NO else EXTRA)
        ok('mehmet sil modal yok', page.locator('#pzm-sil-panel').count() == 0)
        tid = open_detay(page, BLOK_FINANS_NO or BLOK_SEVK_NO)
        st = sil_btn_ust(page)
        ok('mehmet Sil butonu yok', not st.get('exists') or not st.get('visible'), str(st))
        page.screenshot(path=os.path.join(SHOT_DIR, 'mehmet_no_sil.png'), full_page=True)
        ctx2.close()

        # 7 Ali — pazarlama + tablet
        ctx3 = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx3.new_page()
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))
        login(page, 'ali', EXTRA, require_pazarlama=False)
        url = page.url
        if 'pazarlama' in url and page.locator('#pzm-tbody').count():
            ok('ali sil modal yok', page.locator('#pzm-sil-panel').count() == 0)
            st = sil_btn_ust(page)
            ok('ali Sil butonu yok', not st.get('exists') or not st.get('visible'), str(st))
        else:
            ok('ali Sil butonu görünmez', True, f'url={url}')
        # Tablet: silinen batch görünmez
        page.goto(f'{BASE}/nexgen/tablet', wait_until='domcontentloaded')
        page.wait_for_timeout(900)
        body = page.content()
        missing = True
        for bk in uretim_batches_once:
            if bk and bk in body:
                missing = False
                break
        ok(
            'Ali tablet silinen batch yok',
            missing,
            f'batches={uretim_batches_once} url={page.url}',
        )
        page.screenshot(path=os.path.join(SHOT_DIR, 'ali_tablet.png'), full_page=True)
        ctx3.close()
        browser.close()
finally:
    restore_all()


def _console_gercek_hata(msg):
    m = (msg or '').lower()
    if not m or 'favicon' in m:
        return False
    if 'failed to load resource' in m and ('400' in m or '403' in m):
        return False
    return True


real_console = [c for c in console_errors if _console_gercek_hata(c)]
ok('Console 0 hata', len(real_console) == 0, '; '.join(real_console[:5]))
ok('Network 0 hata', len(network_errors) == 0, '; '.join(network_errors[:5]))

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== ÖZET {passed}/{len(results)} PASS, {failed} FAIL ===')
print(f'Silinen: {SIL_TASLAK}, {SIL_MPR}, {SIL_URETIM}')
print(f'Engellenen: finans={BLOK_FINANS_NO}, sevk={BLOK_SEVK_NO}')
sys.exit(0 if failed == 0 else 1)
