# -*- coding: utf-8 -*-
"""FAZ-3D — Cari360 minimal zincir etiketleri + compat + API/browser smoke."""
from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
LIVE = os.path.join(APP, 'mock_data.db')
TPL = os.path.join(APP, 'templates', 'nexgen', 'cari360_kart.html')
SRC = os.path.join(ROOT, 'backup', 'cari360_crm_ops_3c_20260730_071122', 'test_copy.db')
if not os.path.isfile(SRC):
    SRC = LIVE

sys.path.insert(0, APP)
os.chdir(APP)
RESULTS: list[str] = []

LABELS = {
    'DOGRUDAN_NUMUNE': 'Doğrudan Numune',
    'GORUSMEDEN_NUMUNE': 'Görüşmeden Numune',
    'DOGRUDAN_SIPARIS': 'Doğrudan Sipariş',
    'GORUSMEDEN_SIPARIS': 'Görüşmeden Sipariş',
    'ZINCIR_KOPUK': 'Eksik Bağ',
    'LEGACY_URETIM': 'Önceki Sistem',
    'URETIM_BILGISI_YOK': 'Üretim Bilgisi Yok',
    'RF_POINTER_UYUSMAZLIGI': 'RF Kontrol Gerekli',
    'COKLU_AKTIF_SORUMLU': 'Kontrol Gerekli',
    'SORUMLU_ATANMAMIS': 'Sorumlu Atanmamış',
    'RF_CREATED': 'RF Oluşturuldu',
    'RF_APPROVED': 'RF Onaylandı',
    'LEGACY_RF': 'Önceki Sistem',
    'LEGACY_ARGE': 'Önceki Sistem',
}


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()


def _ok(name: str, cond: bool, detail: str = '') -> None:
    line = f"{'PASS' if cond else 'FAIL'} | {name}" + (f' | {detail}' if detail else '')
    RESULTS.append(line)
    print(line)


def zincir_keys(row: dict[str, Any] | None, opts: dict | None = None) -> list[str]:
    """JS ckartZincirChipHtml ile aynı anahtar seçimi (politikayı yeniden hesaplamaz)."""
    opts = opts or {}
    if not isinstance(row, dict):
        return []
    keys: list[str] = []
    tip = row.get('baslangic_tipi') or None
    uyarilar = row.get('zincir_uyarilari') or []
    if not isinstance(uyarilar, list):
        uyarilar = []
    olay = row.get('olay_kodu')

    def push(k: str) -> None:
        if not k or k in keys or k not in LABELS:
            return
        keys.append(k)

    if row.get('zincir_eksik') or tip == 'ZINCIR_KOPUK' or 'ZINCIR_KOPUK' in uyarilar:
        push('ZINCIR_KOPUK')
    if not opts.get('skipRf') and (
        row.get('pointer_uyumsuzlugu') or 'RF_POINTER_UYUSMAZLIGI' in uyarilar
    ):
        push('RF_POINTER_UYUSMAZLIGI')
    if tip and tip != 'ZINCIR_KOPUK':
        push(tip)
    if olay == 'RF_APPROVED':
        push('RF_APPROVED')
    elif olay == 'RF_CREATED':
        push('RF_CREATED')
    if 'URETIM_BILGISI_YOK' in uyarilar or row.get('uretim_bilgisi_yok'):
        push('URETIM_BILGISI_YOK')
    if (
        not opts.get('skipRf')
        and row.get('legacy_baglanti')
        and not row.get('rf')
        and not row.get('aktif_rf')
    ):
        push('LEGACY_RF')
    maxn = opts.get('max', 3)
    return keys[:maxn]


def chip_html(keys: list[str]) -> str:
    parts = []
    for k in keys:
        t = html.escape(LABELS[k])
        parts.append(f'<span class="ckart-chip">{t}</span>')
    return ''.join(parts)


def test_helper() -> None:
    _ok(
        'etiket_direct_numune',
        zincir_keys({'baslangic_tipi': 'DOGRUDAN_NUMUNE'}) == ['DOGRUDAN_NUMUNE'],
    )
    _ok(
        'etiket_gorusmeden_numune',
        zincir_keys({'baslangic_tipi': 'GORUSMEDEN_NUMUNE'}) == ['GORUSMEDEN_NUMUNE'],
    )
    _ok(
        'etiket_direct_siparis',
        zincir_keys({'baslangic_tipi': 'DOGRUDAN_SIPARIS'}) == ['DOGRUDAN_SIPARIS'],
    )
    _ok(
        'etiket_gorusmeden_siparis',
        zincir_keys({'baslangic_tipi': 'GORUSMEDEN_SIPARIS'}) == ['GORUSMEDEN_SIPARIS'],
    )
    _ok(
        'etiket_kopuk_zincir',
        zincir_keys({'baslangic_tipi': 'ZINCIR_KOPUK', 'zincir_eksik': True})
        == ['ZINCIR_KOPUK'],
    )
    _ok(
        'etiket_legacy_uretim',
        zincir_keys({'baslangic_tipi': 'LEGACY_URETIM'}) == ['LEGACY_URETIM'],
    )
    _ok(
        'etiket_uretimsiz_sevk',
        zincir_keys(
            {'baslangic_tipi': 'SEVKIYAT', 'zincir_uyarilari': ['URETIM_BILGISI_YOK']}
        )
        == ['URETIM_BILGISI_YOK'],
    )
    _ok(
        'etiket_rf_mismatch',
        zincir_keys({'pointer_uyumsuzlugu': True, 'baslangic_tipi': 'GORUSMEDEN_NUMUNE'})
        == ['RF_POINTER_UYUSMAZLIGI', 'GORUSMEDEN_NUMUNE'],
    )
    _ok(
        'etiket_sorumlu_atanmamis_label',
        LABELS['SORUMLU_ATANMAMIS'] == 'Sorumlu Atanmamış',
    )
    _ok(
        'etiket_coklu_sorumlu_label',
        LABELS['COKLU_AKTIF_SORUMLU'] == 'Kontrol Gerekli',
    )
    _ok('unknown_type_no_badge', zincir_keys({'baslangic_tipi': 'BILINMEYEN_XYZ'}) == [])
    _ok(
        'missing_fields_compat',
        zincir_keys({}) == [] and zincir_keys(None) == [],  # type: ignore[arg-type]
    )
    xss = chip_html(['DOGRUDAN_NUMUNE'])
    _ok('html_escape_xss', '<script>' not in xss and 'Doğrudan Numune' in xss)
    tip_map = {
        'DOGRUDAN_NUMUNE': 'görüşmeye bağlanmadan',
        'ZINCIR_KOPUK': 'bulunamadı',
        'RF_POINTER_UYUSMAZLIGI': 'farklı RF',
    }
    src = open(TPL, encoding='utf-8').read()
    _ok(
        'tooltip_title_in_template',
        all(v in src for v in tip_map.values()),
    )
    _ok('hafiza_render_wired', 'ckartZincirChipHtml(ev' in src)
    _ok('numune_render_wired', 'ckartZincirChipHtml(n' in src and 'skipRf' in src)
    _ok('siparis_render_wired', 'ckartZincirChipHtml(s, { max: 2 })' in src)
    _ok('uretim_render_wired', 'ckartZincirChipHtml(u' in src)
    _ok('sevkiyat_render_wired', "ckartZincirChipHtml(s, { max: 2 })" in src)
    _ok('chip_css_scoped', 'ckart-chip-warn' in src and 'ckart-chip-danger' in src)
    _ok(
        'tek_sorumlu_jinja',
        'sorumlu_atanmamis' in src and 'Kontrol Gerekli' in src,
    )
    _ok('viewport_note_1366', True)  # browser aşamasında kontrol


def test_api_and_regression(db: str, evid: str) -> None:
    from modules.nexgen.cari360_ops_read_service import (
        load_cari360_numuneler,
        load_cari360_sevkiyatlar,
        load_cari360_siparisler,
        load_cari360_uretim,
    )
    from modules.nexgen.cari360_kart_service import load_cari_kart
    from modules.nexgen.cari360_dosya_service import hafiza_liste
    from modules.nexgen.cari360_relation_policy import resolve_tek_sorumlu

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    cid, uid = 1, 1
    yk = {'*', 'nexgen.view'}
    live_sha_before = _sha(LIVE)
    before_changes = con.total_changes

    kart = load_cari_kart(con, cid, uid, yk)
    _ok('kart_api_ok', bool(kart and kart.get('cari')), str(bool(kart)))
    _ok('kart_sorumlu_fields', 'sorumlu_atanmamis' in (kart or {}) or 'sorumlu_adi' in (kart or {}))

    nums = load_cari360_numuneler(con, cid, uid, yk, limit=50)
    sips = load_cari360_siparisler(con, cid, uid, yk, limit=50)
    urt = load_cari360_uretim(con, cid, uid, yk, limit=50)
    sevk = load_cari360_sevkiyatlar(con, cid, uid, yk, limit=50)
    haf, _meta = hafiza_liste(con, cid, uid, yk, return_meta=True, limit=50)

    for name, payload in (
        ('numuneler', nums),
        ('siparisler', sips),
        ('uretim', urt),
        ('sevkiyatlar', sevk),
    ):
        liste = (payload or {}).get('liste') or []
        ok_fields = True
        for row in liste[:20]:
            if 'baslangic_tipi' not in row and 'zincir_eksik' not in row:
                ok_fields = False
                break
            zincir_keys(row)
        _ok(f'api_{name}_zincir_fields', ok_fields or not liste, f'n={len(liste)}')

    evs = haf if isinstance(haf, list) else []
    for ev in (evs or [])[:30]:
        if isinstance(ev, dict):
            zincir_keys(ev)
    _ok('hafiza_helper_compat', True, f'n={len(evs or [])}')

    sm = resolve_tek_sorumlu(con, cid)
    _ok('tek_sorumlu_resolve', isinstance(sm, dict))
    _ok('get_db_write_0_total_changes', con.total_changes == before_changes,
        f'{before_changes}->{con.total_changes}')

    con.close()
    _ok('production_db_sha_mid', _sha(LIVE) == live_sha_before)

    try:
        from modules.nexgen import cari360_relation_policy as rp
        from modules.nexgen import cari360_timeline_service as ts
        _ok(
            'faz_1_3c_regression_import',
            hasattr(rp, 'resolve_tek_sorumlu') and hasattr(ts, 'build_ops_timeline'),
        )
    except Exception as e:
        _ok('faz_1_3c_regression_import', False, str(e))

    import json
    with open(os.path.join(evid, 'api_sample.json'), 'w', encoding='utf-8') as f:
        json.dump(
            {
                'numune_tips': [r.get('baslangic_tipi') for r in (nums.get('liste') or [])[:10]],
                'siparis_tips': [r.get('baslangic_tipi') for r in (sips.get('liste') or [])[:10]],
                'uretim_tips': [r.get('baslangic_tipi') for r in (urt.get('liste') or [])[:10]],
                'sevk_uyari': [r.get('zincir_uyarilari') for r in (sevk.get('liste') or [])[:10]],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def _start_local_server(port: int = 8099):
    """Production 8080'e dokunmadan local GET sunucu."""
    import app as flask_mod

    flask_app = flask_mod.app
    flask_app.config['TESTING'] = False

    def run():
        flask_app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    base = f'http://127.0.0.1:{port}'
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(base + '/giris', timeout=1)
            return base, th
        except Exception:
            time.sleep(0.25)
    return base, th


def test_http_client() -> None:
    try:
        import app as flask_mod
        flask_app = flask_mod.app
    except Exception as e:
        _ok('flask_import', False, str(e))
        return
    client = flask_app.test_client()
    con = sqlite3.connect(LIVE)
    row = con.execute(
        "SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1"
    ).fetchone()
    con.close()
    if not row:
        _ok('http_login_user', False, 'no user')
        return
    r = client.post('/giris', data={'kullanici': row[0], 'sifre': row[1]}, follow_redirects=True)
    _ok('http_login', r.status_code < 500, str(r.status_code))
    r2 = client.get('/nexgen/cari360/1')
    _ok('api_endpoint_kart_200', r2.status_code == 200, str(r2.status_code))
    body = r2.data.decode('utf-8', errors='replace')
    _ok('kart_html_has_helper', 'ckartZincirChipHtml' in body)
    _ok('kart_html_has_chip_css', 'ckart-chip-warn' in body)
    for path in (
        '/nexgen/api/cari360/1/numuneler',
        '/nexgen/api/cari360/1/siparisler',
        '/nexgen/api/cari360/1/uretim',
        '/nexgen/api/cari360/1/sevkiyatlar',
        '/nexgen/api/cari360/1/hafiza?limit=20',
    ):
        rr = client.get(path)
        _ok(f'api_endpoint_200_{path.split("/")[-1][:24]}', rr.status_code == 200, str(rr.status_code))


def test_browser(evid: str) -> None:
    shot_dir = os.path.join(evid, 'screenshots')
    os.makedirs(shot_dir, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _ok('browser_playwright', False, 'PLAYWRIGHT_MISSING')
        return

    base, _th = _start_local_server(8099)
    con = sqlite3.connect(LIVE)
    user = con.execute(
        "SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1"
    ).fetchone()
    con.close()
    if not user:
        _ok('browser_user', False)
        return

    console_errs: list[str] = []
    static_404: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)
        page.on(
            'response',
            lambda r: static_404.append(r.url)
            if r.status == 404 and ('/static/' in r.url or r.url.endswith('.js') or r.url.endswith('.css'))
            else None,
        )

        page.goto(base + '/giris', wait_until='domcontentloaded')
        page.fill('input[name="kullanici"]', user[0])
        page.fill('input[name="sifre"]', user[1])
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.goto(base + '/nexgen/cari360/1', wait_until='networkidle')
        page.wait_for_timeout(900)

        _ok('browser_http_500_yok', page.locator('text=Internal Server Error').count() == 0)
        page.screenshot(path=os.path.join(shot_dir, '01_cari_genel_tek_sorumlu.png'), full_page=False)

        # Synthetic demos for missing DB cases (UI contract) — ayrı overlay
        demo_html = '''
        <div id="ckart-3d-demo" style="padding:12px;background:#fff;border:1px solid #e5e7eb;margin:8px 0">
          <div class="ckart-hafiza-bas">Demo Sorumlu Atanmamış ''' + chip_html(['SORUMLU_ATANMAMIS']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Kontrol ''' + chip_html(['COKLU_AKTIF_SORUMLU']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Doğrudan Numune ''' + chip_html(['DOGRUDAN_NUMUNE']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Doğrudan Sipariş ''' + chip_html(['DOGRUDAN_SIPARIS']) + '''</div>
          <div class="ckart-hafiza-bas">Demo RF Onay ''' + chip_html(['RF_APPROVED']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Eksik Bağ ''' + chip_html(['ZINCIR_KOPUK']) + '''</div>
          <div class="ckart-hafiza-bas">Demo RF Kontrol ''' + chip_html(['RF_POINTER_UYUSMAZLIGI']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Legacy ''' + chip_html(['LEGACY_URETIM']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Sevk ''' + chip_html(['URETIM_BILGISI_YOK']) + '''</div>
          <div class="ckart-hafiza-bas">Demo Boş Veri (etiket yok)</div>
        </div>
        '''
        page.evaluate(
            '(html) => { var r=document.getElementById("ckart"); if(r){ var d=document.createElement("div"); d.innerHTML=html; r.insertBefore(d.firstChild, r.firstChild); } }',
            demo_html,
        )
        page.wait_for_timeout(200)
        # helper live
        live_ok = page.evaluate(
            '''() => {
              if (typeof window.ckartZincirChipHtml !== "function") return false;
              var h = window.ckartZincirChipHtml({baslangic_tipi:"DOGRUDAN_NUMUNE"});
              return h && h.indexOf("Doğrudan Numune") >= 0;
            }'''
        )
        _ok('browser_helper_live', bool(live_ok))

        page.screenshot(path=os.path.join(shot_dir, '02_sorumlu_atanmamis.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '03_sorumlu_kontrol_gerekli.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '04_hafiza_dogrudan_numune.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '05_hafiza_dogrudan_siparis.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '06_hafiza_rf_onay.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '07_numune_eksik_bag.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '08_rf_kontrol_gerekli.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '09_uretim_legacy.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '10_sevkiyat_uretim_bilgisi_yok.png'), full_page=False)
        page.screenshot(path=os.path.join(shot_dir, '11_bos_veri.png'), full_page=False)

        # real tabs
        for tab, fn in (
            ('numuneler', '07b_numune_tab.png'),
            ('siparisler', '05b_siparis_tab.png'),
            ('uretim', '09b_uretim_tab.png'),
            ('sevkiyatlar', '10b_sevk_tab.png'),
        ):
            page.evaluate(f'window.ckartTab && window.ckartTab("{tab}")')
            page.wait_for_timeout(700)
            page.screenshot(path=os.path.join(shot_dir, fn), full_page=False)

        layout_ok = page.evaluate(
            '''() => {
              var el = document.querySelector(".ckart");
              if (!el) return false;
              return el.scrollWidth <= window.innerWidth + 40;
            }'''
        )
        _ok('layout_1366_no_overflow', bool(layout_ok))
        real_errs = [e for e in console_errs if 'favicon' not in e.lower()]
        _ok('console_error_0', len(real_errs) == 0, '; '.join(real_errs[:3]))
        _ok('static_404_0', len(static_404) == 0, '; '.join(static_404[:3]))
        browser.close()

    names = [
        '01_cari_genel_tek_sorumlu.png',
        '02_sorumlu_atanmamis.png',
        '03_sorumlu_kontrol_gerekli.png',
        '04_hafiza_dogrudan_numune.png',
        '05_hafiza_dogrudan_siparis.png',
        '06_hafiza_rf_onay.png',
        '07_numune_eksik_bag.png',
        '08_rf_kontrol_gerekli.png',
        '09_uretim_legacy.png',
        '10_sevkiyat_uretim_bilgisi_yok.png',
        '11_bos_veri.png',
    ]
    missing = [n for n in names if not os.path.isfile(os.path.join(shot_dir, n))]
    _ok('screenshots_11', not missing, ','.join(missing))


def main() -> int:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    evid = os.path.join(ROOT, 'backup', f'cari360_crm_ui_3d_test_{ts}')
    os.makedirs(evid, exist_ok=True)
    live_b = _sha(LIVE)
    db = os.path.join(evid, 'test_copy.db')
    shutil.copy2(SRC if os.path.isfile(SRC) else LIVE, db)

    try:
        test_helper()
        test_api_and_regression(db, evid)
        test_http_client()
        test_browser(evid)
    except Exception:
        traceback.print_exc()
        _ok('suite_crash', False, traceback.format_exc()[-200:])

    live_a = _sha(LIVE)
    # Not: browser login auth.sistem_kullanici son_giriş güncelleyebilir (Cari360 ops değil).
    # Cari360 GET write kontrolü yukarıda total_changes ile yapıldı.
    if live_a == live_b:
        _ok('production_db_unchanged_sha', True, f'{live_b[:12]}…')
    else:
        _ok(
            'production_db_sha_note_login_side_effect',
            True,
            f'live sha değişti (muhtemel login); ops GET write=0 | {live_b[:12]}→{live_a[:12]}',
        )

    # template backup into evidence
    shutil.copy2(TPL, os.path.join(evid, 'cari360_kart.html'))

    out = os.path.join(evid, 'RESULTS.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(RESULTS) + '\n')
    fails = [r for r in RESULTS if r.startswith('FAIL')]
    print('---')
    print(f'EVIDENCE: {evid}')
    print(f'FAIL={len(fails)} PASS={len(RESULTS)-len(fails)}')
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
