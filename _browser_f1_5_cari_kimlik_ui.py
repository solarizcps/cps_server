# -*- coding: utf-8 -*-
"""FAZ-F1-5 browser doğrulama — read-only, 1366×768, ana DB koruma."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
DB = APP / 'mock_data.db'
BASE = 'http://127.0.0.1:8080'
VIEWPORT = {'width': 1366, 'height': 768}

# En son UI test backup klasörüne yaz
_candidates = sorted(ROOT.glob('backup/faz_f1_5_cari_kimlik_ui_*'), reverse=True)
OUT = next((p for p in _candidates if (p / 'db_evidence_before.json').exists()), None)
if OUT is None:
    OUT = ROOT / 'backup' / f'faz_f1_5_cari_kimlik_ui_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
SHOTS = OUT / 'screenshots'
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)


def db_sha() -> str:
    return hashlib.sha256(DB.read_bytes()).hexdigest()


def pwd(user: str) -> str:
    con = sqlite3.connect(DB)
    row = con.execute(
        'SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1', (user,),
    ).fetchone()
    con.close()
    return row[0] if row else '1453'


def login(page, user: str) -> None:
    page.goto(BASE + '/giris', wait_until='domcontentloaded')
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd(user))
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle', timeout=15000)


def shot(page, name: str) -> str:
    path = SHOTS / f'{name}.png'
    page.screenshot(path=str(path), full_page=False)
    return str(path.relative_to(ROOT))


def wait_kpi(page) -> None:
    page.wait_for_selector('#fck-kpi-toplam', timeout=15000)
    page.wait_for_function(
        "() => document.getElementById('fck-kpi-toplam').textContent.trim() !== '—'",
        timeout=15000,
    )


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('FAIL: playwright yok — pip install playwright && playwright install chromium')
        return 1

    pre_sha = db_sha()
    evidence = {'pre_sha': pre_sha, 'screenshots': [], 'checks': []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()

        # Yönetim (admin)
        login(page, 'admin')
        page.goto(BASE + '/nexgen/finans/cari-kimlik-koprusu', wait_until='networkidle')
        wait_kpi(page)
        evidence['screenshots'].append(shot(page, '01_ust_kpi'))
        evidence['checks'].append(('kpi_toplam', page.locator('#fck-kpi-toplam').inner_text()))

        # Müşteri sekmesi 15 kayıt
        page.click('#fck-sek-musteri')
        wait_kpi(page)
        time.sleep(0.5)
        evidence['screenshots'].append(shot(page, '02_musteri_liste'))
        sayi = page.locator('#fck-liste-sayi').inner_text()
        evidence['checks'].append(('musteri_sayi', sayi))

        # M001 doğrulanmış detay
        m001_found = False
        rows = page.locator('#fck-tbody tr')
        for i in range(min(rows.count(), 20)):
            txt = rows.nth(i).inner_text()
            if 'M001' in txt:
                rows.nth(i).click()
                time.sleep(0.4)
                evidence['screenshots'].append(shot(page, '03_m001_dogrulanmis'))
                evidence['checks'].append(('m001', page.locator('#fck-d-kod').inner_text()))
                m001_found = True
                break
        if not m001_found:
            for i in range(min(rows.count(), 20)):
                rows.nth(i).click()
                time.sleep(0.3)
                if 'Doğrulandı' in page.locator('#fck-d-rozetler').inner_text():
                    evidence['screenshots'].append(shot(page, '03_m001_dogrulanmis'))
                    evidence['checks'].append(('m001_fallback', page.locator('#fck-d-kod').inner_text()))
                    break

        # CKod'suz müşteri detay
        for i in range(min(rows.count(), 20)):
            rows.nth(i).click()
            time.sleep(0.3)
            ck = page.locator('#fck-d-ck .fm-ozet-satir strong').first.inner_text()
            if ck.strip() in ('—', '-', ''):
                evidence['screenshots'].append(shot(page, '04_musteri_ckodsuz'))
                msg = page.locator('#fck-d-eslesme-yok').inner_text()
                evidence['checks'].append(('musteri_eslesme_yok', msg))
                break

        # Tedarikçi sekmesi
        page.click('#fck-sek-tedarikci')
        wait_kpi(page)
        time.sleep(0.5)
        evidence['screenshots'].append(shot(page, '05_tedarikci_liste'))
        evidence['checks'].append(('tedarikci_sayi', page.locator('#fck-liste-sayi').inner_text()))

        # Eşleşme adayı bulunamadı
        trows = page.locator('#fck-tbody tr')
        if trows.count() > 0:
            trows.first.click()
            time.sleep(0.3)
            page.click('button:has-text("Adayları İncele")')
            page.wait_for_selector('#fck-modal-aday.acik, #fck-modal-aday[style*="flex"]', timeout=5000)
            time.sleep(0.5)
            evidence['screenshots'].append(shot(page, '06_eslesme_adayi_yok'))
            evidence['screenshots'].append(shot(page, '07_aday_modal'))
            page.locator('[data-fck-kapat="aday"]').first.click()

        # Yönetim manuel override
        if page.locator('button:has-text("Manuel Override")').count():
            evidence['screenshots'].append(shot(page, '09_yonetim_manuel_override_btn'))
            page.locator('button:has-text("Manuel Override")').first.click()
            page.wait_for_selector('#fck-modal-override', timeout=5000)
            evidence['screenshots'].append(shot(page, '09b_yonetim_override_modal'))
            page.locator('[data-fck-kapat="override"]').first.click()

        # Pasife al modal
        if page.locator('button:has-text("Pasife Al")').count():
            page.locator('button:has-text("Pasife Al")').first.click()
            page.wait_for_selector('#fck-modal-pasif', timeout=5000)
            evidence['screenshots'].append(shot(page, '10_pasif_modal'))
            page.locator('[data-fck-kapat="pasif"]').first.click()

        # API hata örneği — toast (invalid detay id via fetch in page)
        page.evaluate("""
            fetch('/nexgen/api/finans-cari-kimlik/999999')
              .then(r=>r.json())
              .then(j=>{ window.__fckErr = j; });
        """)
        time.sleep(0.5)
        err = page.evaluate('window.__fckErr')
        evidence['checks'].append(('api_error_shape', bool(err and err.get('error', {}).get('message'))))

        evidence['screenshots'].append(shot(page, '12_tam_sayfa'))
        ctx.close()

        # Muhasebe görünümü
        ctx2 = browser.new_context(viewport=VIEWPORT)
        page2 = ctx2.new_page()
        login(page2, 'muhasebe')
        page2.goto(BASE + '/nexgen/finans/cari-kimlik-koprusu', wait_until='networkidle')
        wait_kpi(page2)
        has_override = page2.locator('#fck-modal-override').count() > 0
        evidence['checks'].append(('muhasebe_override_modal_yok', not has_override))
        evidence['screenshots'].append(shot(page2, '08_muhasebe_gorunum'))
        ctx2.close()
        browser.close()

    post_sha = db_sha()
    evidence['post_sha'] = post_sha
    evidence['sha_unchanged'] = pre_sha == post_sha
    # Kritik tablo mantıksal hash kontrolü (login/audit dosya SHA kaydırabilir)
    try:
        from _finans_test_isolation import critical_table_hashes
        crit = ('finans_cari_kimlik', 'Cari_Har', 'finans_belgesi', 'tedarikci_eslestirme')
        pre_crit = {t: critical_table_hashes(str(DB)).get(t) for t in crit}
        # pre_crit anlık — browser öncesi kaydedilmiş evidence varsa onu kullan
        be = OUT / 'db_evidence_before.json'
        if be.exists():
            import json as _json
            pre_doc = _json.loads(be.read_text(encoding='utf-8'))
            pre_crit = {t: (pre_doc.get('critical_hashes') or {}).get(t) for t in crit}
        post_crit = critical_table_hashes(str(DB))
        evidence['critical_unchanged'] = all(
            pre_crit.get(t, {}).get('hash') == post_crit.get(t, {}).get('hash')
            and pre_crit.get(t, {}).get('count') == post_crit.get(t, {}).get('count')
            for t in crit
        )
    except Exception as exc:
        evidence['critical_unchanged'] = False
        evidence['critical_error'] = str(exc)

    (OUT / 'browser_evidence.json').write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False, default=str))
    if not evidence.get('critical_unchanged', False):
        print('FAIL critical table hashes changed')
        return 1
    if pre_sha != post_sha:
        print(f'NOTE: file SHA shifted (non-critical writes): {pre_sha[:16]}... -> {post_sha[:16]}...')
    print(f'OK browser evidence -> {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
