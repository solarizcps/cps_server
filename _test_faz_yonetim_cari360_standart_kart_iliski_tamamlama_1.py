# -*- coding: utf-8 -*-
"""FAZ-YONETIM-CARI360-STANDART-KART-ILISKI-TAMAMLAMA-1 doğrulama."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault(
    'PLAYWRIGHT_BROWSERS_PATH',
    str(Path.home() / 'AppData' / 'Local' / 'ms-playwright'),
)

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
DB = APP / 'mock_data.db'
BASE = 'http://127.0.0.1:8080'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')
OUT = ROOT / 'backup' / f'faz_yonetim_cari360_standart_kart_iliski_tamamlama_1_{TS}' / 'screenshots'
OUT.mkdir(parents=True, exist_ok=True)

_SIPARIS_PASIF = frozenset({
    'REDDEDILDI', 'IPTAL', 'IPTAL_EDILDI', 'TAMAMLANDI', 'KAPANDI', 'IPTALEDILDI',
})


def pwd(user: str) -> str:
    con = sqlite3.connect(DB)
    row = con.execute(
        'SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1', (user,),
    ).fetchone()
    con.close()
    return row[0] if row else '1453'


def db_stats(cari_id: int) -> dict:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sip = con.execute(
        'SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=?', (cari_id,),
    ).fetchone()[0]
    aktif = 0
    for r in con.execute(
        'SELECT durum FROM nexgen_planlama_siparis WHERE cari_id=?', (cari_id,),
    ):
        d = (r['durum'] or '').strip().upper()
        if d and d not in _SIPARIS_PASIF:
            aktif += 1
    sevk = con.execute(
        'SELECT COUNT(*) FROM mo_musteri_sevkiyat WHERE cari_id=? AND COALESCE(aktif,1)=1',
        (cari_id,),
    ).fetchone()[0]
    kg = float(con.execute(
        '''SELECT COALESCE(SUM(k.miktar_kg),0)
           FROM mo_musteri_sevkiyat_kalem k
           JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
           WHERE s.cari_id=? AND COALESCE(s.aktif,1)=1''',
        (cari_id,),
    ).fetchone()[0] or 0)
    son_sevk = con.execute(
        '''SELECT COALESCE(sevk_tarihi, olusturma_tarihi) t FROM mo_musteri_sevkiyat
           WHERE cari_id=? AND COALESCE(aktif,1)=1
           ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC LIMIT 1''',
        (cari_id,),
    ).fetchone()
    gor = con.execute(
        'SELECT COUNT(*) FROM musteri_operasyon_gorusme WHERE cari_id=? AND COALESCE(aktif,1)=1',
        (cari_id,),
    ).fetchone()[0]
    son_gor = con.execute(
        '''SELECT gorusme_tarihi FROM musteri_operasyon_gorusme
           WHERE cari_id=? AND COALESCE(aktif,1)=1
           ORDER BY gorusme_tarihi DESC, id DESC LIMIT 1''',
        (cari_id,),
    ).fetchone()
    yet = con.execute(
        'SELECT COUNT(*) FROM cari_yetkili WHERE cari_id=? AND COALESCE(aktif,1)=1',
        (cari_id,),
    ).fetchone()[0]
    urun = con.execute(
        '''SELECT COUNT(*) FROM (
             SELECT 1 FROM mo_musteri_sevkiyat_kalem k
             JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
             WHERE s.cari_id=? AND COALESCE(s.aktif,1)=1
             GROUP BY COALESCE(NULLIF(TRIM(k.urun_adi),''),'—'),
                      COALESCE(NULLIF(TRIM(k.renk_ad),''),'—')
           )''',
        (cari_id,),
    ).fetchone()[0]
    con.close()
    return {
        'sip': sip, 'aktif': aktif, 'sevk': sevk, 'kg': kg,
        'son_sevk': (son_sevk['t'] if son_sevk else None),
        'gor': gor, 'son_gor': (son_gor['gorusme_tarihi'] if son_gor else None),
        'yet': yet, 'urun': urun,
    }


def login(page, user: str = 'admin') -> None:
    page.goto(BASE + '/giris', wait_until='domcontentloaded')
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd(user))
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle', timeout=25000)


def fetch_json(page, url: str):
    data = page.evaluate(
        """async (url) => {
          const r = await fetch(url, {credentials:'same-origin', headers:{'Accept':'application/json'}});
          const ct = (r.headers.get('content-type')||'').toLowerCase();
          const text = await r.text();
          let j = null;
          try { j = JSON.parse(text); } catch(e) { j = null; }
          return {status:r.status, ct, json:j, head:text.slice(0,120)};
        }""",
        url,
    )
    return data


def main() -> int:
    from playwright.sync_api import sync_playwright

    report = {'ok': True, 'cases': [], 'shots': [], 'errors': [], 'notes': []}
    # A: full ops+gorusme+yetkili | B: yetkili+gorusme focus (mock'ta saf B yok → A üzerinde)
    # C: empty
    cases = [
        (1, 'A_full'),
        (1, 'B_yetkili_gorusme'),  # same id; isolation checked vs C
        (4, 'C_empty'),
    ]
    report['notes'].append(
        'Mock DB: sip/sevk=0 ve gorusme/yetkili>0 olan ayrı cari yok; '
        'B senaryosu cari=1 yetkili+görüşme + C sızıntı kontrolü ile doğrulandı.'
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.on('pageerror', lambda exc: report['errors'].append(str(exc)))
        login(page)

        seen = set()
        for cari_id, label in cases:
            dbc = db_stats(cari_id)
            case = {'cari_id': cari_id, 'label': label, 'db': dbc, 'checks': []}
            page.goto(f'{BASE}/nexgen/cari360/{cari_id}', wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(900)
            body = page.content()
            case['checks'].append({'finans_hidden': ('Eşleşme' not in body and 'Finans eşleşme' not in body)})
            if not case['checks'][-1]['finans_hidden']:
                report['ok'] = False

            oz = fetch_json(page, f'/nexgen/api/cari360/{cari_id}/ozet')
            ok_oz = oz['status'] == 200 and oz['json'] and oz['json'].get('ok') and 'json' in oz['ct']
            case['ozet'] = oz['json'].get('kpi') if oz.get('json') else None
            case['checks'].append({'ozet_api': ok_oz})
            if not ok_oz:
                report['ok'] = False
            else:
                kpi = oz['json']['kpi']
                match = (
                    kpi['toplam_siparis'] == dbc['sip']
                    and kpi['aktif_siparis'] == dbc['aktif']
                    and kpi['toplam_sevkiyat'] == dbc['sevk']
                    and float(kpi['toplam_sevk_kg']) == dbc['kg']
                    and (oz['json'].get('gorusme_sayisi') == dbc['gor'])
                    and (oz['json'].get('yetkili_sayisi') == dbc['yet'])
                )
                case['db_match'] = match
                if not match:
                    report['ok'] = False
                    case['mismatch'] = {'api': oz['json'], 'db': dbc}

            # leak: empty cari must not show cari1 siparis count in KPI
            if cari_id == 4:
                kpi_dom = page.locator('#kpi-toplam-siparis').inner_text().strip()
                case['checks'].append({'no_leak_kpi': kpi_dom in ('0', '—')})
                if kpi_dom not in ('0', '—'):
                    report['ok'] = False

            for tab in ('yetkililer', 'siparisler', 'sevkiyatlar', 'urunler', 'gorusmeler', 'genel'):
                page.locator(f'button.ckart-sekme[data-tab="{tab}"]').click()
                page.wait_for_timeout(600)
                case['checks'].append({f'tab_{tab}': page.locator(f'#ckart-panel-{tab}').is_visible()})

            if label.startswith('B') or cari_id == 1 and 'B' not in seen:
                y = fetch_json(page, f'/nexgen/api/yonetim/cari-yetkili?cari_id={cari_id}')
                g = fetch_json(page, f'/nexgen/api/cari360/{cari_id}/gorusme')
                y_ok = y['status'] == 200 and y['json'] and y['json'].get('ok')
                g_ok = g['status'] == 200 and g['json'] and g['json'].get('ok')
                y_n = len((y['json'] or {}).get('yetkililer') or []) if y_ok else -1
                g_n = (g['json'] or {}).get('count') if g_ok else -1
                case['checks'].append({
                    'yetkili_api': y_ok,
                    'yetkili_liste_n': y_n,
                    'gorusme_api': g_ok,
                    'gorusme_n': g_n,
                })
                # Rozet = aktif yetkili; liste pasifleri de içerebilir
                if y_ok:
                    aktif_y = sum(1 for x in y['json']['yetkililer'] if int(x.get('aktif') or 0) == 1)
                    case['checks'].append({'yetkili_aktif_match': aktif_y == dbc['yet']})
                    if aktif_y != dbc['yet']:
                        report['ok'] = False
                    page.locator('button.ckart-sekme[data-tab="yetkililer"]').click()
                    page.wait_for_timeout(500)
                    ybadge = page.locator('#ckart-yetkili-badge')
                    if dbc['yet'] > 0:
                        okb = ybadge.is_visible() and ybadge.inner_text().strip() == str(dbc['yet'])
                        case['checks'].append({'yetkili_badge': okb})
                        if not okb:
                            report['ok'] = False
                if g_ok and g_n != dbc['gor']:
                    report['ok'] = False
                page.locator('button.ckart-sekme[data-tab="gorusmeler"]').click()
                page.wait_for_timeout(700)
                badge = page.locator('#ckart-gorusme-badge')
                if dbc['gor'] > 0:
                    okg = badge.is_visible() and badge.inner_text().strip() == str(dbc['gor'])
                    case['checks'].append({'gorusme_badge': okg})
                    if not okg:
                        report['ok'] = False

            if cari_id == 4:
                y4 = fetch_json(page, '/nexgen/api/yonetim/cari-yetkili?cari_id=4')
                g4 = fetch_json(page, '/nexgen/api/cari360/4/gorusme')
                y1 = fetch_json(page, '/nexgen/api/yonetim/cari-yetkili?cari_id=1')
                # when on page 4, APIs still scoped by param
                n4 = len((y4.get('json') or {}).get('yetkililer') or [])
                n1 = len((y1.get('json') or {}).get('yetkililer') or [])
                case['checks'].append({'leak_yetkili': n4 == 0 and n1 > 0})
                if not (n4 == 0 and n1 > 0):
                    report['ok'] = False
                g4n = (g4.get('json') or {}).get('count')
                leak_g_ok = g4.get('json') and g4['json'].get('ok') and int(g4n or 0) == 0
                case['checks'].append({'leak_gorusme': leak_g_ok, 'g4_count': g4n})
                if not leak_g_ok:
                    report['ok'] = False

            shot = OUT / f'{label}.png'
            page.screenshot(path=str(shot), full_page=True)
            report['shots'].append(str(shot))
            report['cases'].append(case)
            seen.add(label)

        inv = fetch_json(page, '/nexgen/api/cari360/99999/ozet')
        case_inv = {
            'status': inv['status'],
            'json': bool(inv.get('json') and inv['json'].get('ok') is False),
            'ct': inv.get('ct'),
        }
        if inv['status'] != 404 or not case_inv['json'] or 'json' not in (inv.get('ct') or ''):
            report['ok'] = False
        report['invalid'] = case_inv
        browser.close()

    outj = OUT.parent / 'report.json'
    outj.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print('SHOTS', OUT)
    print('BROWSER_PASS' if report['ok'] and not report['errors'] else 'BROWSER_FAIL')
    return 0 if report['ok'] and not report['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
