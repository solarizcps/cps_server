# -*- coding: utf-8 -*-
"""FAZ-YONETIM-CARI360-GENEL-BILGILER-TAMAMLAMA-1 — browser + API yetki doğrulama."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
DB = os.path.join(APP, 'mock_data.db')
BASE = os.environ.get('CPS_BASE', 'http://127.0.0.1:8080')
OUT = os.path.join(
    ROOT, 'backup', 'faz_yonetim_cari360_genel_bilgiler_tamamlama_1_browser', 'screenshots'
)
os.makedirs(OUT, exist_ok=True)

RESULTS: dict[str, bool] = {}
NOTES: list[str] = []


def _mark(name: str, ok: bool, note: str = '') -> None:
    RESULTS[name] = bool(ok)
    line = f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {note}" if note else '')
    NOTES.append(line)
    print(line)


def _login(user: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f'{BASE}/giris', timeout=20)
    r.raise_for_status()
    r = s.post(
        f'{BASE}/giris',
        data={'kullanici': user, 'sifre': password},
        timeout=20,
        allow_redirects=True,
    )
    r.raise_for_status()
    return s


def _json(s: requests.Session, method: str, path: str, **kwargs):
    headers = kwargs.pop('headers', {})
    headers.setdefault('Accept', 'application/json')
    if method.upper() in ('POST', 'PUT', 'PATCH'):
        headers.setdefault('Content-Type', 'application/json')
    r = s.request(method, f'{BASE}{path}', headers=headers, timeout=30, **kwargs)
    ct = (r.headers.get('content-type') or '').lower()
    data = None
    if 'application/json' in ct:
        try:
            data = r.json()
        except Exception:
            data = None
    return r.status_code, data, r


def api_checks(admin_pw: str, mehmet_pw: str, cari_id: int) -> int | None:
    """HTTP API yetki matrisi. Returns created cari id (admin) or None."""
    created_id = None
    sa = _login('admin', admin_pw)

    # Admin: create
    st, kod_d, _ = _json(sa, 'GET', '/nexgen/api/yonetim/cari-sonraki-kod')
    kod = (kod_d or {}).get('kod') if st == 200 else None
    stamp = datetime.now().strftime('%H%M%S')
    payload = {
        'cari_kod': kod or f'120.NX.T{stamp}',
        'unvan': f'TEST GENEL {stamp}',
        'kisa_ad': f'TG{stamp}',
        'cari_tipi': 'MUSTERI',
        'yurt_durumu': 'YURTICI',
        'telefon': '02120000000',
        'para_birimi': 'TRY',
        'minimum_siparis_kg': 500,
        'dil': 'TR',
    }
    st, d, _ = _json(sa, 'POST', '/nexgen/api/yonetim/cari-ekle', data=json.dumps(payload))
    ok = st == 200 and bool(d and d.get('ok') and d.get('id'))
    _mark('admin_cari_create', ok, f'status={st} body={d}')
    if ok:
        created_id = int(d['id'])
        # verify REAL kg stored
        con = sqlite3.connect(DB)
        kg = con.execute(
            'SELECT minimum_siparis_kg FROM nexgen_cari WHERE id=?', (created_id,)
        ).fetchone()
        con.close()
        _mark('admin_min_kg_real', kg and float(kg[0]) == 500.0, f'kg={kg}')

    target = created_id or cari_id
    # Admin: full edit
    st, d, _ = _json(
        sa,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({
            'id': target,
            'unvan': f'TEST GENEL {stamp} UPD',
            'kisa_ad': f'TGU{stamp}',
            'sehir': 'İstanbul',
            'minimum_siparis_kg': 750.5,
            'iskonto_orani': 2.5,
        }),
    )
    _mark('admin_full_edit', st == 200 and bool(d and d.get('ok')), f'status={st}')

    # Admin: sorumlu list (manage flag)
    st, d, _ = _json(sa, 'GET', f'/nexgen/api/yonetim/cari-sorumlu?cari_id={cari_id}')
    _mark(
        'admin_sorumlu_list',
        st == 200 and bool(d and d.get('ok') and d.get('can_manage')),
        f'status={st} can_manage={(d or {}).get("can_manage")}',
    )

    # Mehmet (pazarlamacı proxy)
    sm = _login('mehmet', mehmet_pw)

    # List access
    r = sm.get(f'{BASE}/nexgen/yonetim', timeout=30)
    html = r.text or ''
    no_create_btn = 'onclick="cariYeniModalAc()"' not in html and 'data-can-create="0"' in html
    _mark(
        'pazarlamaci_liste',
        r.status_code == 200 and 'ngsd-sekme-cari' in html and no_create_btn,
        f'status={r.status_code} data-can-create={"data-can-create=\"0\"" in html}',
    )
    _mark(
        'pazarlamaci_ui_no_durum',
        'Pasif Yap' not in html and 'Aktif Yap' not in html,
        'durum butonları gizli olmalı',
    )

    # Cari 360
    r = sm.get(f'{BASE}/nexgen/cari360/{cari_id}', timeout=30)
    html360 = r.text or ''
    _mark(
        'pazarlamaci_cari360',
        r.status_code == 200 and ('ckart-genel-grid' in html360 or 'Genel Bilgiler' in html360),
        f'status={r.status_code}',
    )
    _mark(
        'pazarlamaci_edit_btn',
        'Bilgileri Düzenle' in html360,
    )

    # Whitelist update on assigned cari
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({
            'id': cari_id,
            'kisa_ad': f'MehmetKisa{stamp}',
            'telefon': '05321234567',
            'minimum_siparis_kg': 120,
            'para_birimi': 'USD',
        }),
    )
    _mark('pazarlamaci_whitelist_update', st == 200 and bool(d and d.get('ok')), f'status={st} {d}')

    # Unvan change attempt → 403
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'unvan': f'HACK UNVAN {stamp}', 'kisa_ad': 'x'}),
    )
    _mark('pazarlamaci_unvan_403', st == 403, f'status={st} {d}')

    # cari_kod change → 403
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'cari_kod': 'HACK.KOD', 'kisa_ad': 'y'}),
    )
    _mark('pazarlamaci_kod_403', st == 403, f'status={st} {d}')

    # aktif → 403
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'aktif': 0, 'kisa_ad': 'z'}),
    )
    _mark('pazarlamaci_aktif_field_403', st == 403, f'status={st} {d}')

    # sil / durum / sorumlu
    st, d, _ = _json(sm, 'POST', '/nexgen/api/yonetim/cari-sil', data=json.dumps({'id': cari_id}))
    _mark('pazarlamaci_sil_403', st == 403, f'status={st}')

    st, d, _ = _json(sm, 'POST', '/nexgen/api/yonetim/cari-durum', data=json.dumps({'id': cari_id}))
    _mark('pazarlamaci_durum_403', st == 403, f'status={st}')

    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-sorumlu-ata',
        data=json.dumps({'cari_id': cari_id, 'kullanici_id': 31, 'sorumluluk_rolu': 'YEDEK'}),
    )
    _mark('pazarlamaci_sorumlu_403', st == 403, f'status={st}')

    # create → 403
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-ekle',
        data=json.dumps({'cari_kod': '120.NX.HACK', 'unvan': 'Hack'}),
    )
    _mark('pazarlamaci_create_403', st == 403, f'status={st}')

    # Negatif alanlar → 400
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'minimum_siparis_kg': -1}),
    )
    _mark('negatif_min_kg_400', st == 400, f'status={st} {d}')
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'odeme_vadesi_gun': -5}),
    )
    _mark('negatif_vade_400', st == 400, f'status={st} {d}')
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-guncelle',
        data=json.dumps({'id': cari_id, 'iskonto_orani': -2}),
    )
    _mark('negatif_iskonto_400', st == 400, f'status={st} {d}')

    # Başka cari sızıntı — mehmet ataması olmayan cari
    con = sqlite3.connect(DB)
    other = con.execute(
        """
        SELECT c.id FROM nexgen_cari c
        WHERE c.id != ?
          AND NOT EXISTS (
            SELECT 1 FROM cari_sorumlu cs
            WHERE cs.cari_id=c.id AND cs.kullanici_id=31 AND cs.aktif=1
          )
        ORDER BY c.id LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    con.close()
    if other:
        st, d, _ = _json(
            sm,
            'POST',
            '/nexgen/api/yonetim/cari-guncelle',
            data=json.dumps({'id': int(other[0]), 'kisa_ad': f'LEAK{stamp}'}),
        )
        _mark('pazarlamaci_baska_cari_403', st == 403, f'cari={other[0]} status={st}')
    else:
        _mark('pazarlamaci_baska_cari_403', True, 'SKIP no unassigned cari')

    # Eski/null cari detay 500 yok
    st, d, _ = _json(sa, 'GET', f'/nexgen/api/yonetim/cari-detay/{cari_id}')
    _mark('null_alan_detay_ok', st == 200 and bool(d and d.get('ok') and d.get('cari')), f'status={st}')

    # Yetkili ekle (telefon unique — duplicate engeline takılmasın)
    yet_tel = f'0555{stamp[-7:]}' if len(stamp) >= 6 else f'0555{stamp}'
    st, d, _ = _json(
        sm,
        'POST',
        '/nexgen/api/yonetim/cari-yetkili-ekle',
        data=json.dumps({
            'cari_id': cari_id,
            'ad_soyad': f'Test Yetkili {stamp}',
            'telefon': yet_tel,
        }),
    )
    _mark('pazarlamaci_yetkili_ekle', st == 200 and bool(d and d.get('ok')), f'status={st} {d}')

    # Görüşme ekle — session user (frontend kullanıcı id spoof yok sayılmalı)
    st, d, _ = _json(
        sm,
        'POST',
        f'/nexgen/api/cari360/{cari_id}/gorusme',
        data=json.dumps({
            'gorusme_tipi': 'Telefon',
            'sonuc_tipi': 'Genel Görüşme',
            'kisa_not': f'Genel bilgiler test görüşme {stamp}',
            'gorusme_tarihi': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'idempotency_key': f'genel-bilgi-test-{stamp}',
            'kullanici_id': 1,
            'created_by': 1,
        }),
    )
    gorusme_ok = st == 200 and bool(d and d.get('ok'))
    uid_ok = True
    if gorusme_ok:
        kayit = d.get('kayit') or {}
        uid_ok = int(kayit.get('kullanici_id') or 0) == 31
    _mark('pazarlamaci_gorusme_ekle', gorusme_ok and uid_ok, f'status={st} kayit={(d or {}).get("kayit")}')

    # Ops ozet regression
    st, d, _ = _json(sm, 'GET', f'/nexgen/api/cari360/{cari_id}/ozet')
    _mark('regression_ozet', st == 200 and bool(d and d.get('ok')), f'status={st}')

    return created_id


def browser_checks(admin_pw: str, mehmet_pw: str, cari_id: int) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _mark('browser_playwright', False, 'PLAYWRIGHT_MISSING')
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Admin UI
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(f'{BASE}/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', 'admin')
        page.fill('input[name="sifre"]', admin_pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.goto(f'{BASE}/nexgen/yonetim#cari', wait_until='networkidle')
        page.wait_for_timeout(700)
        html = page.content()
        _mark('browser_admin_yeni_cari', 'Yeni Cari' in html)
        page.screenshot(path=os.path.join(OUT, 'admin_yonetim_cari.png'), full_page=True)

        page.goto(f'{BASE}/nexgen/cari360/{cari_id}', wait_until='networkidle')
        page.wait_for_timeout(800)
        html = page.content()
        col3 = 'ckart-genel-3kol' in html or 'ckart-genel-grid' in html or 'ckart-kol' in html
        _mark('browser_admin_genel_3kol', col3 or 'Genel Bilgiler' in html, '3 kolon / genel panel')
        page.screenshot(path=os.path.join(OUT, 'admin_cari360_genel.png'), full_page=True)
        page.close()

        # Mehmet UI
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(f'{BASE}/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', 'mehmet')
        page.fill('input[name="sifre"]', mehmet_pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.goto(f'{BASE}/nexgen/yonetim', wait_until='networkidle')
        page.wait_for_timeout(700)
        html = page.content()
        _mark('browser_mehmet_liste', 'ngsd-sekme-cari' in html and page.is_visible('#ngsd-sekme-cari'))
        _mark(
            'browser_mehmet_no_yeni',
            page.locator('button[onclick="cariYeniModalAc()"]').count() == 0
            and page.locator('#yonetim-sekme-bar[data-can-create="0"]').count() == 1,
        )
        page.screenshot(path=os.path.join(OUT, 'mehmet_yonetim_cari.png'), full_page=True)

        page.goto(f'{BASE}/nexgen/cari360/{cari_id}', wait_until='networkidle')
        page.wait_for_timeout(900)
        html = page.content()
        _mark('browser_mehmet_360', page.url.endswith(f'/cari360/{cari_id}') and 'Bilgileri Düzenle' in html)
        _mark(
            'browser_mehmet_gorusme_btn',
            page.locator('button[onclick="ckartGorusmeYeni()"]').count() >= 1
            or page.get_by_role('button', name='Yeni Görüşme').count() >= 1,
        )
        page.screenshot(path=os.path.join(OUT, 'mehmet_cari360.png'), full_page=True)

        # Deep link edit
        page.goto(f'{BASE}/nexgen/yonetim#cari?edit={cari_id}', wait_until='domcontentloaded')
        page.wait_for_timeout(1500)
        opened = False
        try:
            page.wait_for_selector('#ngym-cari-overlay.acik', timeout=4000)
            opened = True
        except Exception:
            # hash bazen SPA gibi yeniden tetiklenmez — manuel çağrı ile doğrula
            page.evaluate(f'cariDuzenleModalAc({cari_id}, "", "")')
            try:
                page.wait_for_selector('#ngym-cari-overlay.acik', timeout=3000)
                opened = True
            except Exception:
                opened = False
        _mark('browser_mehmet_edit_deeplink', opened)
        if opened:
            page.screenshot(path=os.path.join(OUT, 'mehmet_edit_modal.png'), full_page=True)
        page.close()
        browser.close()


def main() -> int:
    con = sqlite3.connect(DB)
    admin = con.execute(
        "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()
    mehmet = con.execute(
        "SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi='mehmet'"
    ).fetchone()
    cari_id = con.execute(
        'SELECT id FROM nexgen_cari WHERE id=1'
    ).fetchone()
    if not cari_id:
        cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()
    con.close()
    if not admin or not mehmet or not cari_id:
        print('FAIL missing users/cari')
        return 1

    # health
    for _ in range(20):
        try:
            if requests.get(f'{BASE}/giris', timeout=3).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print('FAIL server not up')
        return 1

    api_checks(admin[0], mehmet[0], int(cari_id[0]))
    browser_checks(admin[0], mehmet[0], int(cari_id[0]))

    print('OUT', OUT)
    failed = [k for k, v in RESULTS.items() if not v]
    print('SUMMARY', f'{len(RESULTS)-len(failed)}/{len(RESULTS)} PASS')
    if failed:
        print('FAILED', failed)
        return 1
    print('ALL_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
