# -*- coding: utf-8 -*-
"""Tahsilat TCMB → TRY hedef UI browser doğrulama."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
USER = 'erhan'
PASS = '147258'
SHOT = os.path.join(os.path.dirname(__file__), '_shot_tahsilat_tcmb_try_ui')
os.makedirs(SHOT, exist_ok=True)

sys.path.insert(0, os.path.dirname(__file__))
from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_adaylari
from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, install_live_db_write_guard

REPORT: dict = {'tests': {}}
LIVE_DB = os.path.join(os.path.dirname(__file__), 'mock_data.db')


def resolve_test_db_path() -> str:
    db = os.environ.get('CPS_MOCK_DB_PATH')
    if not db:
        raise RuntimeError(
            'CPS_MOCK_DB_PATH zorunlu — browser testleri izole DB olmadan çalışamaz'
        )
    db = os.path.abspath(db)
    live = os.path.abspath(LIVE_DB)
    if os.path.normcase(db) == os.path.normcase(live):
        raise RuntimeError(f'CPS_MOCK_DB_PATH live DB ile aynı: {db}')
    install_live_db_write_guard(live)
    assert_resolved_db_is_tmp(db, live)
    return db


def ok(name: str, passed: bool, note: str = '') -> None:
    REPORT['tests'][name] = {'pass': bool(passed), 'note': note}
    safe_name = str(name or '').encode('ascii', 'replace').decode('ascii')
    safe_note = str(note or '').encode('ascii', 'replace').decode('ascii')
    print(('PASS' if passed else 'FAIL'), safe_name, safe_note)


def setup_test_data(con: sqlite3.Connection) -> dict:
    tag = uuid.uuid4().hex[:8]
    cari = con.execute(
        "SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1"
    ).fetchone()
    if not cari:
        raise RuntimeError('cari yok')
    cari_id = int(cari['id'])

    kur_tarih = '2026-08-09'
    con.execute(
        """
        INSERT INTO sistem_kur (ParaBirimi, Tarih, Satis, MerkezKur, Alis)
        VALUES ('USD', ?, 47.25, 47.20, 47.10)
        """,
        (kur_tarih,),
    )
    kur_row = con.execute(
        "SELECT rowid FROM sistem_kur WHERE ParaBirimi='USD' AND Tarih=?",
        (kur_tarih,),
    ).fetchone()
    kur_rowid = int(kur_row[0]) if kur_row else None

    cur = con.execute(
        """
        INSERT INTO nexgen_planlama_siparis (
            siparis_no, cari_id, durum, anlasma_birim_fiyat,
            anlasma_para_birimi, olusturma_tarihi
        ) VALUES (?, ?, 'ONAYLANDI', 2, 'USD', datetime('now'))
        """,
        (f'TCMB-{tag}', cari_id),
    )
    siparis_id = int(cur.lastrowid)

    cur2 = con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat (
            sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi,
            idempotency_key, olusturan_id, olusturma_tarihi
        ) VALUES (?, ?, ?, 'SEVK_EDILDI', 1, ?, ?, 1, datetime('now'))
        """,
        (f'MSV-TCMB-{tag}', cari_id, siparis_id, kur_tarih, f'sevk-tcmb-{tag}'),
    )
    sevk_id = int(cur2.lastrowid)
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem (
            sevkiyat_id, urun_adi, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot, olusturma_tarihi
        ) VALUES (?, 'Test Ürün', 200, 2, 'USD', datetime('now'))
        """,
        (sevk_id,),
    )
    aday = tahsilat_sevk_adaylari(con, siparis_id)
    sevk = next((a for a in aday if int(a['sevkiyat_id']) == sevk_id), None)
    return {
        'tag': tag,
        'cari_id': cari_id,
        'siparis_id': siparis_id,
        'sevk_id': sevk_id,
        'kur_tarih': kur_tarih,
        'kur_rowid': kur_rowid,
        'kalan_fx': float(sevk['kalan']) if sevk else 400.0,
        'try_hedef': round(float(sevk['kalan']) * 47.25, 2) if sevk else 18900.0,
    }


def login(page) -> None:
    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', USER)
    page.fill('input[name="sifre"]', PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r'.*/(nexgen|musteri).*'), timeout=15000)


def dismiss_karar_popup_if_visible(page) -> None:
    """MO Talep Sonucu popup görünürse gerçek Tamam click ile kapat."""
    pop = page.locator('#mp-karar-popup')
    try:
        pop.wait_for(state='visible', timeout=2500)
    except PlaywrightTimeoutError:
        return
    page.locator('#mp-karar-popup-tamam').click()
    pop.wait_for(state='hidden', timeout=5000)


def money_has(val: str, amount: int) -> bool:
    s = (val or '').replace(' ', '').replace('.', '')
    return str(amount) in s or str(amount).replace('.', ',') in (val or '')


def wait_try_preview(page, timeout_ms: int = 8000) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        txt = page.locator('#mp-t-sevk-tcmb-try').inner_text()
        if money_has(txt, 18900):
            return
        page.wait_for_timeout(300)
    page.wait_for_timeout(500)


def cleanup_test_kur(con: sqlite3.Connection, ctx: dict) -> None:
    """Yalnız testin INSERT ettiği USD kur satırını sil."""
    rowid = ctx.get('kur_rowid')
    kur_tarih = ctx.get('kur_tarih')
    if rowid is not None:
        con.execute('DELETE FROM sistem_kur WHERE rowid=?', (rowid,))
    elif kur_tarih:
        con.execute(
            "DELETE FROM sistem_kur WHERE ParaBirimi='USD' AND Tarih=?",
            (kur_tarih,),
        )


def cleanup_test_data(con: sqlite3.Connection, ctx: dict) -> None:
    con.execute('DELETE FROM mo_tahsilat_kayit WHERE siparis_id=?', (ctx['siparis_id'],))
    rows = con.execute(
        'SELECT id FROM mo_musteri_sevkiyat WHERE siparis_id=?', (ctx['siparis_id'],)
    ).fetchall()
    for r in rows:
        con.execute('DELETE FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?', (r['id'],))
    con.execute('DELETE FROM mo_musteri_sevkiyat WHERE siparis_id=?', (ctx['siparis_id'],))
    con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (ctx['siparis_id'],))
    cleanup_test_kur(con, ctx)


def main() -> int:
    db = resolve_test_db_path()
    con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    ctx = None
    try:
        con.execute('BEGIN IMMEDIATE')
        ctx = setup_test_data(con)
        con.commit()
        print('SETUP', json.dumps(ctx, ensure_ascii=False))

        draft_id = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            login(page)
            page.goto(f'{BASE}/nexgen/musteri-pazarlama', wait_until='networkidle')
            time.sleep(0.5)
            dismiss_karar_popup_if_visible(page)
            page.locator('.mp-v2-hizli-btn[data-modal="tahsilat"], .mp-hizli-btn[data-modal="tahsilat"]').first.click()
            time.sleep(0.5)
            page.select_option('#mp-t-cari', str(ctx['cari_id']))
            time.sleep(0.8)
            page.select_option('#mp-t-siparis', str(ctx['siparis_id']))
            time.sleep(1.0)
            page.select_option('#mp-t-sevkiyat', str(ctx['sevk_id']))
            time.sleep(1.5)
            page.screenshot(path=os.path.join(SHOT, '01_sevk_tcmb_panel.png'), full_page=True)

            fx_txt = page.locator('#mp-t-sevk-tcmb-fx').inner_text()
            kur_txt = page.locator('#mp-t-sevk-tcmb-kur').inner_text()
            tarih_txt = page.locator('#mp-t-sevk-tcmb-tarih').inner_text()
            try_txt = page.locator('#mp-t-sevk-tcmb-try').inner_text()

            wait_try_preview(page)
            fx_txt = page.locator('#mp-t-sevk-tcmb-fx').inner_text()
            kur_txt = page.locator('#mp-t-sevk-tcmb-kur').inner_text()
            tarih_txt = page.locator('#mp-t-sevk-tcmb-tarih').inner_text()
            try_txt = page.locator('#mp-t-sevk-tcmb-try').inner_text()

            ok('FX kalan görünür', '400' in fx_txt and 'USD' in fx_txt, fx_txt)
            ok('TCMB Satis görünür', '47,2500' in kur_txt or '47.2500' in kur_txt, kur_txt)
            ok('Kur tarihi', '09.08.2026' in tarih_txt, tarih_txt)
            ok('TRY hedef', money_has(try_txt, 18900), try_txt)

            hedef_ro = page.locator('#mp-t-beklenen').get_attribute('readonly')
            ok('TRY hedef readonly', hedef_ro is not None, str(hedef_ro))
            ok('NAKIT', money_has(try_txt, 18900), try_txt)

            page.fill('#mp-t-alinan', '10000')
            page.locator('#mp-t-alinan').blur()
            page.wait_for_timeout(400)
            kalan_txt = page.locator('#mp-t-kalan').input_value()
            ok('NAKIT kalan', money_has(kalan_txt, 8900), kalan_txt)
            page.screenshot(path=os.path.join(SHOT, '02_nakit_partial.png'), full_page=True)

            page.select_option('#mp-t-odeme-tipi', 'CEK')
            page.wait_for_timeout(600)
            page.click('#mp-cek-ekle-btn')
            page.wait_for_timeout(200)
            rows = page.locator('#mp-cek-tbody tr')
            rows.nth(0).locator('.mp-cek-tutar').fill('10000')
            rows.nth(0).locator('.mp-cek-alim').fill(ctx['kur_tarih'])
            rows.nth(0).locator('.mp-cek-vade').fill('2026-09-09')
            page.click('#mp-cek-ekle-btn')
            page.wait_for_timeout(200)
            rows = page.locator('#mp-cek-tbody tr')
            rows.nth(1).locator('.mp-cek-tutar').fill('8900')
            rows.nth(1).locator('.mp-cek-alim').fill(ctx['kur_tarih'])
            rows.nth(1).locator('.mp-cek-vade').fill('2026-10-09')
            page.wait_for_timeout(3500)
            kars = page.locator('#mp-cek-oz-karsilama').inner_text()
            ok('CEK', '100' in kars, kars)
            page.screenshot(path=os.path.join(SHOT, '03_cek_100.png'), full_page=True)

            # Taslak + hydrate (NAKIT modunda — snapshot doğrulama)
            page.select_option('#mp-t-odeme-tipi', 'NAKIT')
            page.wait_for_timeout(500)
            page.click('#mp-tahsilat-taslak-btn')
            page.wait_for_timeout(3000)
            draft_id = page.evaluate("""() => {
              var el = document.getElementById('mp-t-kayit-id');
              return el && el.value ? parseInt(el.value, 10) : null;
            }""")
            frozen_kur = page.locator('#mp-t-sevk-tcmb-kur').inner_text()
            frozen_try = page.locator('#mp-t-sevk-tcmb-try').inner_text()
            page.evaluate("""() => { if (typeof closeModal === 'function') closeModal('tahsilat'); }""")
            page.wait_for_timeout(500)
            page.evaluate(
                """(id) => { if (typeof hydrateTahsilatDraft === 'function') hydrateTahsilatDraft(id); if (typeof openModal === 'function') openModal('tahsilat'); }""",
                draft_id,
            )
            page.wait_for_timeout(3500)
            hydrate_kur = page.locator('#mp-t-sevk-tcmb-kur').inner_text()
            hydrate_try = page.locator('#mp-t-sevk-tcmb-try').inner_text()
            hydrate_tarih = page.locator('#mp-t-sevk-tcmb-tarih').inner_text()
            ok('Hydrate snapshot', frozen_kur == hydrate_kur and money_has(hydrate_try, 18900) and '09.08.2026' in hydrate_tarih,
               f'kur={hydrate_kur} try={hydrate_try}')

            page.evaluate(
                """(cid) => { sessionStorage.removeItem('mo_tahsilat_draft_' + cid); }""",
                ctx['cari_id'],
            )
            page.screenshot(path=os.path.join(SHOT, '04_hydrate.png'), full_page=True)

            page.select_option('#mp-t-odeme-tipi', 'NAKIT')
            con.execute('DELETE FROM mo_tahsilat_kayit WHERE siparis_id=?', (ctx['siparis_id'],))
            cleanup_test_kur(con, ctx)
            con.commit()
            api_res = page.request.post(
                f'{BASE}/nexgen/api/musteri-pazarlama/tahsilat-kayit',
                data=json.dumps({
                    'cari_id': ctx['cari_id'],
                    'siparis_id': ctx['siparis_id'],
                    'sevkiyat_id': ctx['sevk_id'],
                    'odeme_tipi': 'NAKIT',
                    'alinan_tarih': ctx['kur_tarih'],
                    'idempotency_key': f"kur-yok-{ctx['tag']}",
                }),
                headers={'Content-Type': 'application/json'},
            )
            api_j = api_res.json()
            ok('Kur yok API', not api_j.get('ok') and 'bulunamadı' in (api_j.get('mesaj') or ''), api_j.get('mesaj'))
            page.evaluate(
                """(args) => {
                  sessionStorage.removeItem('mo_tahsilat_draft_' + args.cari_id);
                  if (typeof resetTahsilatModal === 'function') resetTahsilatModal(args.cari_id, { siparis_id: args.siparis_id });
                }""",
                {'cari_id': ctx['cari_id'], 'siparis_id': ctx['siparis_id']},
            )
            page.wait_for_timeout(2500)
            page.fill('#mp-t-alinan', '')
            page.select_option('#mp-t-sevkiyat', str(ctx['sevk_id']))
            page.wait_for_timeout(500)
            page.evaluate("""() => {
              if (typeof window.mpRefreshTahsilatTryPreview === 'function') return window.mpRefreshTahsilatTryPreview();
            }""")
            page.wait_for_timeout(4000)
            err_txt = page.locator('#mp-t-sevk-tcmb-err').evaluate('el => el ? (el.textContent || "").trim() : ""')
            ok('Kur yok mesajı', 'TCMB' in err_txt and 'bulunamadı' in err_txt, err_txt)
            page.screenshot(path=os.path.join(SHOT, '05_kur_yok.png'), full_page=True)

            browser.close()

    except Exception as exc:
        print('ERROR', exc)
        raise
    finally:
        if ctx:
            try:
                cleanup_test_data(con, ctx)
                con.commit()
            except Exception:
                pass
        con.close()

    out = os.path.join(SHOT, 'report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'ctx': ctx, 'draft_id': draft_id, **REPORT}, f, ensure_ascii=False, indent=2)
    print('REPORT', out)
    fails = [k for k, v in REPORT['tests'].items() if not v['pass']]
    return 0 if not fails else 1


if __name__ == '__main__':
    raise SystemExit(main())
