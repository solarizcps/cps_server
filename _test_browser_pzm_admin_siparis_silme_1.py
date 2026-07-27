# -*- coding: utf-8 -*-
"""FAZ-PZM-ADMIN-SIPARIS-SILME-1B — ilişki bazlı koruma (durum allowlist yok)."""
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
SHOT_DIR = os.path.join(_ROOT, 'backup', 'screenshots', f'pzm_admin_silme_1b_{TS}')
os.makedirs(SHOT_DIR, exist_ok=True)

results = []
console_errors = []
network_errors = []
_restore_sql = []

SONUC = frozenset({'BITTI', 'SEVK_EDILDI', 'TAMAMLANDI'})


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
    row = con.execute(
        'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (sid,)
    ).fetchone()
    if row and (row['durum'] or '').upper() in SONUC:
        return False
    plans = [r['id'] for r in con.execute(
        'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (sid,)
    )]
    for r in con.execute(
        'SELECT durum FROM nexgen_uretim_plan WHERE planlama_siparis_id=?', (sid,)
    ):
        if (r['durum'] or '').upper() in SONUC:
            return False
    if plans:
        ph = ','.join('?' * len(plans))
        for r in con.execute(
            f'SELECT durum FROM nexgen_uretim_batch WHERE plan_id IN ({ph})', plans
        ):
            if (r['durum'] or '').upper() in SONUC:
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


def pick_any(exclude=None, prefer_batch=False, durum=None):
    exclude = set(exclude or [])
    con = db()
    try:
        if durum:
            rows = con.execute(
                """SELECT id, siparis_no, durum FROM nexgen_planlama_siparis
                   WHERE durum=? AND siparis_no LIKE 'PZM%' ORDER BY id ASC""",
                (durum,),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT id, siparis_no, durum FROM nexgen_planlama_siparis
                   WHERE siparis_no LIKE 'PZM%'
                     AND upper(IFNULL(durum,'')) NOT IN ('BITTI','SEVK_EDILDI','TAMAMLANDI')
                   ORDER BY id ASC"""
            ).fetchall()
        for r in rows:
            if r['siparis_no'] in exclude:
                continue
            if not _silinebilir_mi(con, r['id'], r['siparis_no']):
                continue
            if prefer_batch:
                n = con.execute(
                    """SELECT COUNT(*) n FROM nexgen_uretim_batch b
                       JOIN nexgen_uretim_plan p ON p.id=b.plan_id
                       WHERE p.planlama_siparis_id=?""",
                    (r['id'],),
                ).fetchone()['n']
                if n <= 0:
                    continue
            return r['siparis_no']
        return None
    finally:
        con.close()


def set_durum_temp(no, yeni):
    con = db()
    try:
        old = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE siparis_no=?', (no,)
        ).fetchone()
        if not old:
            return False
        _restore_sql.append(
            ('UPDATE nexgen_planlama_siparis SET durum=? WHERE siparis_no=?',
             (old['durum'], no))
        )
        con.execute(
            'UPDATE nexgen_planlama_siparis SET durum=? WHERE siparis_no=?',
            (yeni, no),
        )
        con.commit()
        return True
    finally:
        con.close()


def insert_finans_blok(siparis_no, with_sevkiyat=False):
    con = db()
    try:
        sip = con.execute(
            'SELECT cari_id, cari_unvan FROM nexgen_planlama_siparis WHERE siparis_no=?',
            (siparis_no,),
        ).fetchone()
        cari_id = (sip['cari_id'] if sip and sip['cari_id'] else 1)
        cari_unvan = (sip['cari_unvan'] if sip and sip['cari_unvan'] else 'TEST CARI')
        kod = f'TEST-SIL1B-{TS}-{"SV" if with_sevkiyat else "FN"}'
        con.execute(
            """INSERT INTO finans_belgesi
               (belge_kodu, belge_tipi, durum, siparis_no, cari_id, cari_unvan,
                islem_tarihi, para_birimi, toplam_tutar, idempotency_key, aktif, sevkiyat_id)
               VALUES (?, 'FATURA', 'BEKLIYOR', ?, ?, ?, date('now'), 'TRY', 0, ?, 1, ?)""",
            (
                kod, siparis_no, cari_id, cari_unvan, kod,
                999002 if with_sevkiyat else None,
            ),
        )
        fid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
        con.commit()
        _restore_sql.append(('DELETE FROM finans_belgesi WHERE id=?', (fid,)))
        return fid
    finally:
        con.close()


def insert_stok_hareket_blok(siparis_no):
    """Plan referanslı geçici stok hareketi — silme engeli."""
    con = db()
    try:
        plan = con.execute(
            """SELECT p.id FROM nexgen_uretim_plan p
               JOIN nexgen_planlama_siparis s ON s.id=p.planlama_siparis_id
               WHERE s.siparis_no=? LIMIT 1""",
            (siparis_no,),
        ).fetchone()
        if not plan:
            # plan yoksa oluşturulamayan engel — durum SET + sahte plan id kullanma
            return None
        sk = con.execute('SELECT id FROM nexgen_stok_kart LIMIT 1').fetchone()
        if not sk:
            return None
        con.execute(
            """INSERT INTO nexgen_stok_hareket
               (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
                aciklama, referans_tip, referans_id)
               VALUES (?, 'CIKIS', 0.01, 0, 0, 'TEST-SIL1B', 'URETIM_PLAN', ?)""",
            (sk['id'], plan['id']),
        )
        hid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
        con.commit()
        _restore_sql.append(('DELETE FROM nexgen_stok_hareket WHERE id=?', (hid,)))
        return hid
    finally:
        con.close()


def restore_all():
    if not _restore_sql:
        return
    con = db()
    try:
        for sql, args in reversed(_restore_sql):
            try:
                con.execute(sql, args)
            except Exception as e:
                print('  [restore warn]', e)
        con.commit()
    finally:
        con.close()
    _restore_sql.clear()


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
        page.wait_for_timeout(700)
    page.wait_for_timeout(300)


def open_detay(page, siparis_no):
    row = siparis_row(siparis_no)
    if not row:
        return None
    page.wait_for_selector(f'#pzm-tbody tr:has-text("{siparis_no}")', timeout=20000)
    page.locator('#pzm-tbody tr').filter(has_text=siparis_no).first.click()
    page.wait_for_function(
        '() => document.getElementById("ekran-detay")?.style.display !== "none"',
        timeout=20000,
    )
    page.wait_for_timeout(350)
    return row['id']


def sil_btn_ust(page):
    return page.evaluate(
        """() => {
          const btn = document.getElementById('pzm-detay-btn-sil');
          if (!btn) return {exists: false};
          const r = btn.getBoundingClientRect();
          return {
            exists: true,
            visible: r.width > 0 && r.height > 0 && getComputedStyle(btn).display !== 'none',
            disabled: !!btn.disabled,
            text: (btn.textContent || '').trim(),
          };
        }"""
    )


def do_delete(page, siparis_no):
    page.click('#pzm-detay-btn-sil')
    page.wait_for_function(
        '() => document.getElementById("pzm-sil-panel")?.style.display === "flex"',
        timeout=8000,
    )
    page.fill('#pzm-sil-confirm-inp', siparis_no)
    page.wait_for_timeout(100)
    row = siparis_row(siparis_no)
    tid = row['id']
    with page.expect_response(
        lambda r: f'/nexgen/api/pazarlama/talep/{tid}/sil' in r.url and r.request.method == 'POST',
        timeout=30000,
    ) as resp_info:
        page.click('#pzm-sil-onay-btn')
    resp = resp_info.value
    data = resp.json()
    page.wait_for_timeout(350)
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


def goto_pazarlama(page):
    with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
        page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
    page.wait_for_timeout(300)


# --- aday seçimi ---
SIL_ONAY = os.environ.get('PZM_SIL_ONAY') or pick_any()
SIL_PLANHAZIR = os.environ.get('PZM_SIL_PLANHAZIR') or pick_any(exclude=[SIL_ONAY])
SIL_URETIM = os.environ.get('PZM_SIL_URETIM') or pick_any(
    prefer_batch=True, durum='URETIMDE', exclude=[SIL_ONAY, SIL_PLANHAZIR]
)
if not SIL_URETIM:
    SIL_URETIM = pick_any(prefer_batch=True, exclude=[SIL_ONAY, SIL_PLANHAZIR])

BLOK_FINANS = os.environ.get('PZM_BLOK_FINANS') or pick_any(
    exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM]
)
BLOK_SEVK = os.environ.get('PZM_BLOK_SEVK') or pick_any(
    exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS]
)
BLOK_STOK = os.environ.get('PZM_BLOK_STOK') or pick_any(
    prefer_batch=False, durum='URETIMDE',
    exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK],
)
if not BLOK_STOK:
    BLOK_STOK = pick_any(
        exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK]
    )
# sonuç durum UI — geçici
TMP_BITTI = pick_any(exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK, BLOK_STOK])
TMP_SEVK = pick_any(exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK, BLOK_STOK, TMP_BITTI])
TMP_TAMAM = pick_any(exclude=[SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK, BLOK_STOK, TMP_BITTI, TMP_SEVK])

print('=== FAZ-PZM-ADMIN-SIPARIS-SILME-1B ===')
print('SHOT', SHOT_DIR)
print('sil', SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM)
print('blok', BLOK_FINANS, BLOK_SEVK, BLOK_STOK)

EXTRA = [x for x in (
    SIL_ONAY, SIL_PLANHAZIR, SIL_URETIM, BLOK_FINANS, BLOK_SEVK, BLOK_STOK,
    TMP_BITTI, TMP_SEVK, TMP_TAMAM,
) if x]

try:
    # ara durumlar — gerçek allowlist kaldırma testi
    if SIL_ONAY:
        set_durum_temp(SIL_ONAY, 'ONAYLANDI')
    if SIL_PLANHAZIR:
        set_durum_temp(SIL_PLANHAZIR, 'PLANLAMAYA_HAZIR')
    if BLOK_FINANS:
        insert_finans_blok(BLOK_FINANS, with_sevkiyat=False)
    if BLOK_SEVK:
        insert_finans_blok(BLOK_SEVK, with_sevkiyat=True)
    stok_hid = insert_stok_hareket_blok(BLOK_STOK) if BLOK_STOK else None
    if TMP_BITTI:
        set_durum_temp(TMP_BITTI, 'BITTI')
    if TMP_SEVK:
        set_durum_temp(TMP_SEVK, 'SEVK_EDILDI')
    if TMP_TAMAM:
        set_durum_temp(TMP_TAMAM, 'TAMAMLANDI')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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
        ok('admin modal', page.locator('#pzm-sil-panel').count() == 1)

        # 1 ONAYLANDI
        ok(f'ONAYLANDI aday ({SIL_ONAY})', bool(SIL_ONAY) and siparis_row(SIL_ONAY)['durum'] == 'ONAYLANDI')
        tid = open_detay(page, SIL_ONAY)
        st = sil_btn_ust(page)
        ok('ONAYLANDI Sil aktif', st.get('visible') and not st.get('disabled'), str(st))
        status, data = do_delete(page, SIL_ONAY)
        ok('ONAYLANDI sil PASS', status == 200 and data.get('ok') is True, str(data))
        ok('ONAYLANDI DB yok', siparis_row(SIL_ONAY) is None)

        # 2 PLANLAMAYA_HAZIR
        goto_pazarlama(page)
        ok(f'PLANLAMAYA_HAZIR aday ({SIL_PLANHAZIR})',
           bool(SIL_PLANHAZIR) and siparis_row(SIL_PLANHAZIR)['durum'] == 'PLANLAMAYA_HAZIR')
        tid = open_detay(page, SIL_PLANHAZIR)
        st = sil_btn_ust(page)
        ok('PLANLAMAYA_HAZIR Sil aktif', st.get('visible') and not st.get('disabled'), str(st))
        status, data = do_delete(page, SIL_PLANHAZIR)
        ok('PLANLAMAYA_HAZIR sil PASS', status == 200 and data.get('ok') is True, str(data))
        ok('PLANLAMAYA_HAZIR DB yok', siparis_row(SIL_PLANHAZIR) is None)

        # 3 URETIMDE
        goto_pazarlama(page)
        ok(f'URETIMDE aday ({SIL_URETIM})', bool(SIL_URETIM))
        tid = open_detay(page, SIL_URETIM)
        st = sil_btn_ust(page)
        ok('URETIMDE Sil aktif', st.get('visible') and not st.get('disabled'), str(st))
        status, data = do_delete(page, SIL_URETIM)
        ok('URETIMDE sil PASS', status == 200 and data.get('ok') is True, str(data))
        ok('URETIMDE DB yok', siparis_row(SIL_URETIM) is None)

        # 4 Finans
        goto_pazarlama(page)
        tid = open_detay(page, BLOK_FINANS)
        api = api_sil(page, tid, BLOK_FINANS)
        ok(
            'Finans ENGEL',
            api.get('status') == 400 and 'Finans' in ((api.get('data') or {}).get('hata') or ''),
            str(api),
        )
        ok('Finans duruyor', siparis_row(BLOK_FINANS) is not None)

        # 5 Sevkiyat
        goto_pazarlama(page)
        tid = open_detay(page, BLOK_SEVK)
        api = api_sil(page, tid, BLOK_SEVK)
        h = ((api.get('data') or {}).get('hata') or '')
        ok(
            'Sevkiyat ENGEL',
            api.get('status') == 400 and ('sevkiyat' in h.lower() or 'Finans' in h),
            str(api),
        )
        ok('Sevkiyat duruyor', siparis_row(BLOK_SEVK) is not None)

        # 6 Stok hareket
        goto_pazarlama(page)
        if stok_hid:
            tid = open_detay(page, BLOK_STOK)
            api = api_sil(page, tid, BLOK_STOK)
            ok(
                'Stok hareket ENGEL',
                api.get('status') == 400 and 'Stok' in ((api.get('data') or {}).get('hata') or ''),
                str(api),
            )
            ok('Stok sipariş duruyor', siparis_row(BLOK_STOK) is not None)
        else:
            ok('Stok hareket ENGEL', False, 'stok hareket insert başarısız')
            ok('Stok sipariş duruyor', False)

        # 7 BITTI / SEVK_EDILDI / TAMAMLANDI
        for no, ad in ((TMP_BITTI, 'BITTI'), (TMP_SEVK, 'SEVK_EDILDI'), (TMP_TAMAM, 'TAMAMLANDI')):
            goto_pazarlama(page)
            tid = open_detay(page, no)
            st = sil_btn_ust(page)
            ok(f'{ad} Sil pasif', st.get('exists') and st.get('disabled'), str(st))
            api = api_sil(page, tid, no)
            ok(
                f'{ad} API ENGEL',
                api.get('status') == 400 and not (api.get('data') or {}).get('ok'),
                str(api),
            )

        ctx.close()

        # Mehmet / Ali
        ctx2 = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx2.new_page()
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))
        login(page, 'mehmet', [BLOK_FINANS])
        ok('mehmet Sil yok', page.locator('#pzm-detay-btn-sil').count() == 0)
        open_detay(page, BLOK_FINANS)
        ok('mehmet detayda Sil yok', page.locator('#pzm-detay-btn-sil').count() == 0)
        ctx2.close()

        ctx3 = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx3.new_page()
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.on('pageerror', lambda err: console_errors.append(str(err)))
        login(page, 'ali', EXTRA, require_pazarlama=False)
        ok('ali Sil yok', page.locator('#pzm-detay-btn-sil').count() == 0, f'url={page.url}')
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
ok('Console 0', len(real_console) == 0, '; '.join(real_console[:5]))
ok('Network 0', len(network_errors) == 0, '; '.join(network_errors[:5]))

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== ÖZET {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(0 if failed == 0 else 1)
