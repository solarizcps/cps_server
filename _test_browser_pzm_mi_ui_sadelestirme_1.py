# -*- coding: utf-8 -*-
"""FAZ-MALZEME-İHTİYAÇ-UI-SADELEŞTİRME-1 — Boyut Detayları kaldırıldı."""
import io
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / 'app'))

import sqlite3
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from config import Config
import app as flask_app
from modules.nexgen.routes import _pzm_talep_satir_dict

BASE = os.environ.get('CPS_BASE_URL', 'http://127.0.0.1:8084')
USE_EMBEDDED = not os.environ.get('CPS_BASE_URL')
if USE_EMBEDDED:
    _server = make_server('127.0.0.1', 8084, flask_app.app, threaded=True)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    time.sleep(1.2)

TS = datetime.now().strftime('%Y%m%d_%H%M%S')
SHOT = _ROOT / 'backup' / 'screenshots' / f'pzm_mi_ui_sade_{TS}'
SHOT.mkdir(parents=True, exist_ok=True)

SINGLE_NO = os.environ.get('PZM_SINGLE_NO', 'PZM-2026-0033')
MULTI_NO = os.environ.get('PZM_MULTI_NO', 'PZM-2026-0034')

results = []
console_errors = []
network_errors = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def db_id(no):
    con = sqlite3.connect(Config.MOCK_DB_PATH)
    r = con.execute('SELECT id FROM nexgen_planlama_siparis WHERE siparis_no=?', (no,)).fetchone()
    con.close()
    return r[0] if r else None


def fetch_talep_dict(no):
    con = sqlite3.connect(Config.MOCK_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            '''SELECT id, siparis_no, cari_id, cari_unvan, termin_tarihi,
                      durum, notlar, talep_referansi, olusturma_tarihi,
                      olusturan_id, kaynak_modul, anlasma_para_birimi,
                      vade_gun, anlasma_birim_fiyat, musteri_termin,
                      onerilen_termin, teslim_sekli, revizyon_gerekce
               FROM nexgen_planlama_siparis WHERE siparis_no=?''', (no,)
        ).fetchone()
        return _pzm_talep_satir_dict(row, con) if row else None
    finally:
        con.close()


def inject_talepler(route, extra_nos):
    resp = route.fetch()
    data = resp.json()
    liste = data.get('liste') or []
    seen = {x.get('siparis_no') for x in liste}
    for no in extra_nos:
        if no in seen:
            continue
        t = fetch_talep_dict(no)
        if t:
            liste.insert(0, t)
    data['liste'] = liste
    route.fulfill(status=resp.status, content_type='application/json',
                  body=json.dumps(data, ensure_ascii=False))


def open_detay(page, no):
    tid = db_id(no)
    page.wait_for_selector(f'#pzm-tbody tr:has-text("{no}")', timeout=20000)
    page.locator('#pzm-tbody tr').filter(has_text=no).first.click()
    page.wait_for_function(
        '() => document.getElementById("ekran-detay")?.style.display !== "none"',
        timeout=20000,
    )
    page.wait_for_timeout(600)
    # Aşama 3 MI
    page.evaluate(
        '''() => {
          const el = document.getElementById("pzm-det-" + (window._pzmDetayAktifId||"") + "-asama-3")
            || Array.from(document.querySelectorAll(".pzm-det-akk")).find(x =>
                 (x.textContent||"").indexOf("Malzeme") >= 0);
          if (el && !el.classList.contains("pzm-akk-acik")) {
            const hdr = el.querySelector(".pzm-akk-hdr");
            if (hdr) hdr.click();
          }
        }'''
    )
    page.wait_for_timeout(800)
    return tid


def probe_mi(page):
    return page.evaluate(
        '''() => {
          const asama = document.getElementById("pzm-detay-asamalar");
          const txt = asama ? (asama.innerText || "") : "";
          const html = asama ? (asama.innerHTML || "") : "";
          const excel = document.querySelector(".pzm-mi-rapor-excel");
          const uretim = Array.from(document.querySelectorAll("#pzm-detay-alt-butonlar button"))
            .find(b => (b.textContent || "").indexOf("retime") >= 0)
            || document.querySelector("[id$='-btn-uretim']");
          const boyuts = Array.from(document.querySelectorAll(".pzm-mi-bolum-baslik"))
            .filter(el => (el.textContent || "").trim() === "Boyut Detayları");
          return {
            hasBoyutBaslik: boyuts.length > 0,
            hasBoyutInText: txt.indexOf("Boyut Detayları") >= 0,
            hasPlanKart: !!document.querySelector(".pzm-plan-kart"),
            hasOperasyonOzet: txt.indexOf("Operasyon Özeti") >= 0
              || !!document.querySelector(".pzm-mpr-metrik-grid")
              || html.indexOf("pzmMiMetrik") >= 0
              || txt.indexOf("Analiz tamamlandı") >= 0,
            hasToplu: html.indexOf("pzm-mi-rapor") >= 0 || txt.indexOf("Toplu") >= 0
              || !!document.querySelector(".pzm-mi-rapor-kart, .pzm-mi-rapor-tablo, #pzm-mi-rapor"),
            excelExists: !!excel,
            excelDisabled: excel ? !!excel.disabled : true,
            uretimExists: !!uretim,
            uretimDisabled: uretim ? !!uretim.disabled : true,
            raporText: (txt.match(/Analiz tamamlandı|Malzeme|Stok/i) || [""])[0],
          };
        }'''
    )


def wait_mi(page, timeout_ms=90000):
    try:
        page.wait_for_function(
            '''() => {
              const t = document.getElementById("pzm-detay-asamalar");
              if (!t) return false;
              const s = t.innerText || "";
              return s.indexOf("Analiz tamamlandı") >= 0
                  || s.indexOf("Operasyon Özeti") >= 0
                  || !!document.querySelector(".pzm-mi-rapor-excel");
            }''',
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


print('=== FAZ-MI-UI-SADELEŞTİRME-1 ===')
print('SHOT', SHOT)

admin_pw = sqlite3.connect(Config.MOCK_DB_PATH).execute(
    "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
).fetchone()[0]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.route('**/nexgen/api/pazarlama/talepler',
               lambda route: inject_talepler(route, [SINGLE_NO, MULTI_NO]))
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
    page.on('pageerror', lambda err: console_errors.append(str(err)))
    page.on(
        'response',
        lambda r: network_errors.append(f'{r.status} {r.url}')
        if r.status >= 400 and '/nexgen/' in r.url else None,
    )

    page.goto(f'{BASE}/giris', wait_until='networkidle')
    page.fill('input[name="kullanici"]', 'admin')
    page.fill('input[name="sifre"]', admin_pw)
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle')
    with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
        page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')

    for label, no in (('tek', SINGLE_NO), ('cok', MULTI_NO)):
        with page.expect_response(lambda r: '/nexgen/api/pazarlama/talepler' in r.url and r.status == 200):
            page.goto(f'{BASE}/nexgen/pazarlama', wait_until='networkidle')
        tid = open_detay(page, no)
        ok(f'{label} sipariş açık ({no})', tid is not None)
        ready = wait_mi(page)
        ok(f'{label} MI hazır', ready)
        snap = probe_mi(page)
        ok(f'{label} Boyut Detayları DOM yok', not snap['hasBoyutBaslik'] and not snap['hasBoyutInText'], str(snap))
        ok(f'{label} plan-kart yok', not snap['hasPlanKart'], str(snap))
        ok(f'{label} Operasyon Özeti duruyor', snap['hasOperasyonOzet'], str(snap))
        ok(f'{label} MI rapor alanı', snap['hasToplu'] or snap['excelExists'], str(snap))
        ok(f'{label} Excel butonu var', snap['excelExists'], str(snap))
        # Excel tıkla — download
        if snap['excelExists'] and not snap['excelDisabled']:
            with page.expect_download(timeout=30000) as dl_info:
                page.locator('.pzm-mi-rapor-excel').first.click()
            dl = dl_info.value
            path = SHOT / f'{label}_{no}_mi.xlsx'
            dl.save_as(str(path))
            ok(f'{label} Excel Export PASS', path.exists() and path.stat().st_size > 200, f'size={path.stat().st_size}')
        else:
            # stok yüklenene kadar bekle
            try:
                page.wait_for_function(
                    '() => { const b=document.querySelector(".pzm-mi-rapor-excel"); return b && !b.disabled; }',
                    timeout=60000,
                )
                with page.expect_download(timeout=30000) as dl_info:
                    page.locator('.pzm-mi-rapor-excel').first.click()
                dl = dl_info.value
                path = SHOT / f'{label}_{no}_mi.xlsx'
                dl.save_as(str(path))
                ok(f'{label} Excel Export PASS', path.exists() and path.stat().st_size > 200,
                   f'size={path.stat().st_size}')
            except Exception as e:
                ok(f'{label} Excel Export PASS', False, str(e))
        snap2 = probe_mi(page)
        ok(f'{label} Gönder butonu DOM', snap2['uretimExists'], str(snap2))
        page.screenshot(path=str(SHOT / f'{label}_{no}_mi.png'), full_page=True)

    browser.close()

real_c = [c for c in console_errors if c and 'favicon' not in c.lower()
          and not ('failed to load resource' in c.lower() and ('400' in c or '403' in c))]
ok('Console 0', len(real_c) == 0, '; '.join(real_c[:4]))
ok('Network 0', len(network_errors) == 0, '; '.join(network_errors[:4]))

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== ÖZET {passed}/{len(results)} PASS, {failed} FAIL ===')
print('SHOT', SHOT)
sys.exit(0 if failed == 0 else 1)
