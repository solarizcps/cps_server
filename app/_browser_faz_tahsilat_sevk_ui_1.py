# -*- coding: utf-8 -*-
"""Tahsilat ↔ Sevkiyat V1 UI browser doğrulama."""
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
SHOT = os.path.join(os.path.dirname(__file__), '_shot_tahsilat_sevk_ui')
os.makedirs(SHOT, exist_ok=True)

sys.path.insert(0, os.path.dirname(__file__))
from modules.nexgen.mo_tahsilat_config import (
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
    KAYNAK_MUSTERI_OPERASYONU,
)
from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_adaylari

REPORT: dict = {'tests': {}}


def ok(name: str, passed: bool, note: str = '') -> None:
    REPORT['tests'][name] = {'pass': bool(passed), 'note': note}
    print(('PASS' if passed else 'FAIL'), name, note)


def setup_test_data(con: sqlite3.Connection) -> dict:
    tag = uuid.uuid4().hex[:8]
    cari = con.execute(
        "SELECT id FROM nexgen_cari WHERE aktif=1 AND unvan LIKE '%' LIMIT 1"
    ).fetchone()
    if not cari:
        raise RuntimeError('cari yok')
    cari_id = int(cari['id'])

    cur = con.execute(
        """
        INSERT INTO nexgen_planlama_siparis (
            siparis_no, cari_id, durum, anlasma_birim_fiyat,
            anlasma_para_birimi, olusturma_tarihi
        ) VALUES (?, ?, 'ONAYLANDI', 2, 'USD', datetime('now'))
        """,
        (f'TSVK-{tag}', cari_id),
    )
    siparis_id = int(cur.lastrowid)

    def _sevk(kg: float, tarih: str) -> int:
        cur2 = con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat (
                sevkiyat_no, cari_id, siparis_id, durum, aktif, sevk_tarihi,
                idempotency_key, olusturan_id, olusturma_tarihi
            ) VALUES (?, ?, ?, 'SEVK_EDILDI', 1, ?, ?, 1, datetime('now'))
            """,
            (f'MSV-TSVK-{tag}-{kg:g}', cari_id, siparis_id, tarih, f'sevk-{tag}-{kg:g}'),
        )
        sevk_id = int(cur2.lastrowid)
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat_kalem (
                sevkiyat_id, urun_adi, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot, olusturma_tarihi
            ) VALUES (?, 'Test Ürün', ?, 2, 'USD', datetime('now'))
            """,
            (sevk_id, kg),
        )
        return sevk_id

    sevk1 = _sevk(300, '2026-08-01')
    sevk2 = _sevk(200, '2026-08-15')

    con.execute(
        """
        INSERT INTO sistem_kur (ParaBirimi, Tarih, Satis, MerkezKur, Alis)
        VALUES ('USD', '2026-08-01', 47.25, 47.20, 47.10),
               ('USD', '2026-08-15', 47.25, 47.20, 47.10)
        """
    )

    con.execute(
        """
        INSERT INTO mo_tahsilat_kayit (
            kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul,
            beklenen_tutar, alinan_tutar, kalan_tutar, para_birimi,
            sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot,
            durum, aktif, odeme_tipi, idempotency_key, olusturan_id, olusturma_tarihi
        ) VALUES (?, ?, ?, ?, ?, 400, 200, 200, 'USD', 600, 'USD', ?, 1, 'NAKIT', ?, 1, datetime('now'))
        """,
        (
            f'MO-T-TSVK-{tag}', cari_id, siparis_id, sevk1,
            KAYNAK_MUSTERI_OPERASYONU, KAYIT_DURUM_MUHASEBE_BEKLIYOR,
            f'rezerv-{tag}',
        ),
    )

    aday = tahsilat_sevk_adaylari(con, siparis_id)
    return {
        'tag': tag,
        'cari_id': cari_id,
        'siparis_id': siparis_id,
        'sevk1': sevk1,
        'sevk2': sevk2,
        'aday': aday,
    }


def cleanup(con: sqlite3.Connection, ctx: dict) -> None:
    sid = ctx['siparis_id']
    con.execute('DELETE FROM mo_tahsilat_kayit WHERE siparis_id=?', (sid,))
    rows = con.execute('SELECT id FROM mo_musteri_sevkiyat WHERE siparis_id=?', (sid,)).fetchall()
    for r in rows:
        con.execute('DELETE FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?', (r['id'],))
    con.execute('DELETE FROM mo_musteri_sevkiyat WHERE siparis_id=?', (sid,))
    con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (sid,))
    con.execute("DELETE FROM sistem_kur WHERE ParaBirimi='USD' AND Tarih IN ('2026-08-01','2026-08-15')")


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


def money_raw(page, sel: str) -> float:
    return page.evaluate(
        """(s) => {
          const el = document.querySelector(s);
          if (!el) return 0;
          const raw = el.dataset.rawValue || el.value || '';
          const t = String(raw).replace(/\\./g,'').replace(',','.');
          const n = parseFloat(t);
          return isNaN(n) ? 0 : n;
        }""",
        sel,
    )


def wait_try_hedef(page, amount: float = 18900.0, timeout_ms: int = 8000) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        v = money_raw(page, '#mp-t-beklenen')
        if abs(v - amount) < 1.0:
            return
        time.sleep(0.3)
    time.sleep(0.3)


def main() -> int:
    db = os.path.join(os.path.dirname(__file__), 'mock_data.db')
    con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    ctx = None
    try:
        con.execute('BEGIN IMMEDIATE')
        ctx = setup_test_data(con)
        con.commit()
        print('SETUP', json.dumps({k: v for k, v in ctx.items() if k != 'aday'}, ensure_ascii=False))
        sevk1_aday = next(a for a in ctx['aday'] if a['sevkiyat_id'] == ctx['sevk1'])
        ok('setup_sevk1_hedef', sevk1_aday.get('sevk_hedef_tutar') == 600, str(sevk1_aday))
        ok('setup_sevk1_kalan', sevk1_aday.get('kalan') == 400, str(sevk1_aday.get('kalan')))

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
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

            wrap_vis = page.locator('#mp-t-sevk-wrap').is_visible()
            ok('sevkiyat_dropdown', wrap_vis, 'wrap visible')
            opt_count = page.locator('#mp-t-sevkiyat option').count()
            ok('coklu_sevk', opt_count >= 3, f'options={opt_count}')

            auto_val = page.input_value('#mp-t-sevkiyat')
            ok('coklu_sevk_auto_yok', auto_val == '', 'coklu sevk — auto yok')

            page.select_option('#mp-t-sevkiyat', str(ctx['sevk1']))
            wait_try_hedef(page)
            hedef1 = money_raw(page, '#mp-t-beklenen')
            ro1 = page.locator('#mp-t-beklenen').evaluate('el => el.readOnly')
            fx_txt = page.locator('#mp-t-sevk-tcmb-fx').inner_text()
            ok('kalan_hedef_readonly', ro1 and abs(hedef1 - 18900) < 1, f'hedef={hedef1} ro={ro1}')
            ok('fx_kalan_panel', '400' in fx_txt and 'USD' in fx_txt, fx_txt)
            page.screenshot(path=os.path.join(SHOT, '01_sevk1_hedef.png'), full_page=True)

            page.select_option('#mp-t-sevkiyat', str(ctx['sevk2']))
            wait_try_hedef(page)
            hedef2 = money_raw(page, '#mp-t-beklenen')
            ok('sevk2_hedef', abs(hedef2 - 18900) < 1, str(hedef2))

            page.select_option('#mp-t-odeme-tipi', 'NAKIT')
            time.sleep(0.3)
            ok('nakit_hedef_ro', page.locator('#mp-t-beklenen').evaluate('el => el.readOnly'), '')

            page.select_option('#mp-t-odeme-tipi', 'CEK')
            time.sleep(0.4)
            hedef_cek = money_raw(page, '#mp-t-beklenen')
            ok('cek_paket_hedef', page.locator('#mp-t-beklenen').evaluate('el => el.readOnly') and abs(hedef_cek - 18900) < 1, str(hedef_cek))

            # Yanlış cari sızıntısı — farklı cari ile API
            other = con.execute(
                'SELECT id FROM nexgen_cari WHERE aktif=1 AND id != ? LIMIT 1',
                (ctx['cari_id'],),
            ).fetchone()
            leak = False
            if other:
                r = page.request.get(
                    f"{BASE}/nexgen/api/musteri-pazarlama/tahsilat-sevkiyatlar"
                    f"?siparis_id={ctx['siparis_id']}&cari_id={other['id']}"
                )
                leak = r.status == 200 and r.json().get('ok')
            ok('yanlis_cari_sizintisi', not leak, 'VAR' if leak else 'YOK')

            # Taslak hydrate
            payload = {
                'cari_id': ctx['cari_id'],
                'siparis_id': ctx['siparis_id'],
                'sevkiyat_id': ctx['sevk1'],
                'alinan_tutar': 100,
                'alinan_tarih': '2026-08-09',
                'odeme_tipi': 'NAKIT',
                'idempotency_key': f'tsvk-{ctx["tag"]}',
            }
            taslak = page.request.post(
                f'{BASE}/nexgen/api/musteri-pazarlama/tahsilat-kayit',
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'},
            )
            tj = taslak.json()
            kid = (tj.get('kayit') or {}).get('id')
            ok('taslak_api', tj.get('ok') and kid, str(tj.get('mesaj', kid)))
            if kid:
                det = page.request.get(f'{BASE}/nexgen/api/musteri-pazarlama/tahsilat-kayit/{kid}').json()
                sevk_saved = (det.get('kayit') or {}).get('sevkiyat_id')
                ok('taslak_sevkiyat_id', int(sevk_saved or 0) == ctx['sevk1'], str(sevk_saved))

            page.reload(wait_until='networkidle')
            time.sleep(0.5)
            page.locator('.mp-v2-hizli-btn[data-modal="tahsilat"], .mp-hizli-btn[data-modal="tahsilat"]').first.click()
            time.sleep(0.5)
            page.evaluate(
                '(args) => { sessionStorage.setItem("mo_tahsilat_draft_" + args.cid, String(args.kid)); }',
                {'cid': str(ctx['cari_id']), 'kid': kid},
            )
            page.select_option('#mp-t-cari', str(ctx['cari_id']))
            page.dispatch_event('#mp-t-cari', 'change')
            page.wait_for_function(
                '(sid) => document.getElementById("mp-t-sevkiyat") && document.getElementById("mp-t-sevkiyat").value === String(sid)',
                arg=ctx['sevk1'],
                timeout=12000,
            )
            sevk_h = page.input_value('#mp-t-sevkiyat')
            hedef_h = money_raw(page, '#mp-t-beklenen')
            ok('taslak_hydrate', sevk_h == str(ctx['sevk1']) and abs(hedef_h - 18900) < 1, f'sevk={sevk_h} hedef={hedef_h}')
            page.screenshot(path=os.path.join(SHOT, '02_hydrate.png'), full_page=True)

            browser.close()
    finally:
        if ctx:
            con.execute('BEGIN IMMEDIATE')
            cleanup(con, ctx)
            con.commit()
        con.close()

    fails = [k for k, v in REPORT['tests'].items() if not v['pass']]
    out = os.path.join(SHOT, 'report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print('REPORT', out)
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
