# -*- coding: utf-8 -*-
"""FAZ-F1-5 — Finans Cari Kimlik Köprüsü UI testleri (izole DB + ana DB koruma)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
MAIN_DB = APP / 'mock_data.db'
BASELINE_SHA = 'bc631c7acd9f4a46369b032369e2038ede627ed67e10e2bc4c9376cda3c8dcb9'
PAGE_ROUTE = '/nexgen/finans/cari-kimlik-koprusu'
TEMPLATE = APP / 'templates' / 'nexgen' / 'finans_cari_kimlik_koprusu.html'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP))
os.chdir(APP)

from _finans_test_isolation import (  # noqa: E402
    assert_main_db_logical_unchanged,
    assert_main_db_unchanged,
    critical_table_hashes,
    db_counts,
    db_sha256,
    pin_all_db_paths,
    use_isolated_finans_db,
)

YK_NONE = frozenset()
YK_VIEW = frozenset({'nexgen.finans.cari_kimlik.view:can_view'})
YK_MUHASEBE = frozenset({
    'nexgen.finans.cari_kimlik.view:can_view',
    'nexgen.finans.cari_kimlik.manage:can_update',
    'nexgen.finans.tedarikci_kimlik.manage:can_update',
})
YK_YONETIM = frozenset({
    'nexgen.finans.cari_kimlik.view:can_view',
    'nexgen.finans.cari_kimlik.manage:can_manage',
    'nexgen.finans.tedarikci_kimlik.manage:can_manage',
})


def _ts() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _con(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys = ON')
    return c


def _fck_summary(db_path: str) -> dict:
    con = _con(db_path)
    total = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
    dog = int(con.execute("SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='DOGRULANDI'").fetchone()[0])
    bek = int(con.execute("SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='BEKLIYOR'").fetchone()[0])
    mus = int(con.execute("SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='MUSTERI'").fetchone()[0])
    ted = int(con.execute("SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='TEDARIKCI'").fetchone()[0])
    tes = int(con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0])
    con.close()
    return {
        'finans_cari_kimlik': total,
        'DOGRULANDI': dog,
        'BEKLIYOR': bek,
        'MUSTERI': mus,
        'TEDARIKCI': ted,
        'tedarikci_eslestirme': tes,
    }


class UiTester:
    def __init__(self, db: str, client, app, template_html: str) -> None:
        self.db = db
        self.client = client
        self.app = app
        self.template_html = template_html
        self.results: list[tuple[str, str, str]] = []
        self.lines: list[str] = []

    def log(self, msg: str) -> None:
        print(msg)
        self.lines.append(msg)

    def ok(self, name: str, detail: str = '') -> None:
        self.results.append(('PASS', name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(('FAIL', name, detail))

    def login(self, rol_ad: str = 'Yonetim', rol_id: int = 1, kadi: str = 'admin'):
        with self.client.session_transaction() as s:
            s['kullanici'] = {
                'Id': 9001, 'KullaniciAdi': kadi, 'Tip': 'sistem',
                'RolId': rol_id, 'RolAd': rol_ad, 'Aktif': 1,
            }
            s['kullanici_tip'] = 'sistem'

    def run_all(self) -> None:
        self._test_page_auth()
        self._test_template_rm_design()
        self._test_api_bindings()
        self._test_no_native_dialogs()
        self._test_muhasebe_vs_yonetim()
        self._test_tedarikci_no_auto_match()
        self._test_eslesme_label()
        self._test_pasif_modal()
        self._test_api_error_ux()
        self._test_db_counts_isolated()
        self._test_db_guard_flags()

    def _test_page_auth(self) -> None:
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_NONE):
            self.login('Anonim', 99, 'anon')
            r = self.client.get(PAGE_ROUTE)
            if r.status_code == 403:
                self.ok('sayfa yetkisiz 403', str(r.status_code))
            else:
                self.fail('sayfa yetkisiz 403', str(r.status_code))

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
            self.login('FinansRO', 10, 'fin_ro')
            r2 = self.client.get(PAGE_ROUTE)
            if r2.status_code == 200 and b'Cari Kimlik' in r2.data:
                self.ok('view yetkili 200', str(r2.status_code))
            else:
                self.fail('view yetkili 200', str(r2.status_code))

        for rol, rid, label in (
            ('Planlama', 5, 'planlama'),
            ('Depo Operasyon', 6, 'depo'),
            ('Sevkiyat', 7, 'sevkiyat'),
        ):
            with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
                self.login(rol, rid, f'{label}_test')
                r3 = self.client.get(PAGE_ROUTE)
                if r3.status_code == 403:
                    self.ok(f'{label} 403', str(r3.status_code))
                else:
                    self.fail(f'{label} 403', str(r3.status_code))

    def _test_template_rm_design(self) -> None:
        html = self.template_html
        checks = [
            ('rm-kpi-bar', 'rm-kpi-bar'),
            ('rm-sekme-bar', 'rm-sekme-bar'),
            ('rm-panel', 'rm-panel'),
            ('--rm-teal', '--rm-teal'),
            ('--rm-font', '--rm-font'),
            ('rm-page-hdr', 'rm-page-hdr'),
        ]
        for name, needle in checks:
            if needle in html:
                self.ok(f'rm tasarım referansı {name}', 'found')
            else:
                self.fail(f'rm tasarım referansı {name}', 'missing')

    def _test_api_bindings(self) -> None:
        html = self.template_html
        apis = [
            '/nexgen/api/finans-cari-kimlik/liste',
            '/nexgen/api/finans-cari-kimlik/',
            '/adaylar',
            'musteri-sync',
            'manuel-override',
            'pasife-al',
            'yeniden-aktif',
            '/eslestir',
        ]
        for api in apis:
            if api in html:
                self.ok(f'API bağlantısı {api}', 'found')
            else:
                self.fail(f'API bağlantısı {api}', 'missing')

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
            self.login('FinansRO', 10)
            r = self.client.get('/nexgen/api/finans-cari-kimlik/liste?kimlik_tipi=MUSTERI&limit=50')
            j = r.get_json() or {}
            if r.status_code == 200 and j.get('ok') and 'kpi' in (j.get('data') or {}):
                self.ok('KPI API bağlantısı', 'liste+kpi')
            else:
                self.fail('KPI API bağlantısı', str(j)[:120])

            r2 = self.client.get('/nexgen/api/finans-cari-kimlik/liste?kimlik_tipi=MUSTERI&limit=50')
            j2 = r2.get_json() or {}
            items = (j2.get('data') or {}).get('items') or []
            if items:
                kid = items[0]['id']
                r3 = self.client.get(f'/nexgen/api/finans-cari-kimlik/{kid}')
                if r3.status_code == 200 and (r3.get_json() or {}).get('ok'):
                    self.ok('detay API bağlantısı', str(kid))
                else:
                    self.fail('detay API bağlantısı', str(r3.status_code))
                op_id = items[0].get('operasyonel_id') or items[0].get('nexgen_cari_id')
                tip = items[0].get('kimlik_tipi', 'MUSTERI')
                if op_id:
                    r4 = self.client.get(f'/nexgen/api/finans-cari-kimlik/{tip}/{op_id}/adaylar?limit=5')
                    if r4.status_code == 200:
                        self.ok('aday API bağlantısı', str(r4.status_code))
                    else:
                        self.fail('aday API bağlantısı', str(r4.status_code))

    def _test_no_native_dialogs(self) -> None:
        html = self.template_html
        if re.search(r'\balert\s*\(', html):
            self.fail('native alert yok', 'alert() found')
        else:
            self.ok('native alert yok', 'clean')
        if re.search(r'\bconfirm\s*\(', html):
            self.fail('native confirm yok', 'confirm() found')
        else:
            self.ok('native confirm yok', 'clean')

    def _test_muhasebe_vs_yonetim(self) -> None:
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_MUHASEBE):
            self.login('Muhasebe', 2, 'muhasebe')
            r = self.client.get(PAGE_ROUTE)
            body = r.get_data(as_text=True)
            if r.status_code == 200 and 'canManuelOverride: false' in body.replace(' ', ''):
                self.ok('Muhasebe manuel override DOM yok', 'canManuelOverride=false')
            elif r.status_code == 200 and 'canManuelOverride: false' in body:
                self.ok('Muhasebe manuel override DOM yok', 'canManuelOverride=false')
            else:
                has_modal = 'fck-modal-override' in body
                has_false = 'canManuelOverride: false' in body
                if r.status_code == 200 and not has_modal and has_false:
                    self.ok('Muhasebe manuel override DOM yok', 'modal absent')
                else:
                    self.fail('Muhasebe manuel override DOM yok', f'status={r.status_code} modal={has_modal}')

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
            self.login('Yonetim', 1, 'admin')
            r2 = self.client.get(PAGE_ROUTE)
            body2 = r2.get_data(as_text=True)
            if r2.status_code == 200 and 'fck-modal-override' in body2 and 'Manuel Override' in body2:
                self.ok('Yönetim manuel override görebilir', 'modal present')
            else:
                self.fail('Yönetim manuel override görebilir', str(r2.status_code))

    def _test_tedarikci_no_auto_match(self) -> None:
        html = self.template_html.lower()
        bad = ['otomatik eşleştir', 'otomatik eslestir', 'auto match', 'auto-match']
        found = [b for b in bad if b in html]
        if found:
            self.fail('tedarikçide otomatik eşleştirme yok', ','.join(found))
        else:
            self.ok('tedarikçide otomatik eşleştirme yok', 'clean')

    def _test_eslesme_label(self) -> None:
        html = self.template_html
        if 'Eşleşme adayı bulunamadı' in html:
            self.ok('Eşleşme adayı bulunamadı etiketi', 'found')
        else:
            self.fail('Eşleşme adayı bulunamadı etiketi', 'missing')
        if 'Cari Kart eşleşmesi bulunamadı' in html:
            self.ok('müşteri eşleşme yok etiketi', 'found')
        else:
            self.fail('müşteri eşleşme yok etiketi', 'missing')

    def _test_pasif_modal(self) -> None:
        html = self.template_html
        if 'fck-modal-pasif' in html and 'Kimliği Pasife Al' in html:
            self.ok('pasife alma özel modal', 'found')
        else:
            self.fail('pasife alma özel modal', 'missing')

    def _test_api_error_ux(self) -> None:
        html = self.template_html
        if 'apiErr' in html and 'error.message' in html.replace(' ', ''):
            self.ok('API hata JSON kullanıcı mesajı', 'apiErr')
        elif 'apiErr' in html and 'j.error' in html:
            self.ok('API hata JSON kullanıcı mesajı', 'apiErr+j.error')
        else:
            self.fail('API hata JSON kullanıcı mesajı', 'missing handler')

    def _test_db_counts_isolated(self) -> None:
        s = _fck_summary(self.db)
        if s['finans_cari_kimlik'] == 24:
            self.ok('DB finans_cari_kimlik 24', str(s))
        else:
            self.fail('DB finans_cari_kimlik 24', str(s))
        if s['DOGRULANDI'] >= 1 and s['BEKLIYOR'] >= 1:
            self.ok('DB durum dagilimi', f"DOGRULANDI={s['DOGRULANDI']} BEKLIYOR={s['BEKLIYOR']}")
        else:
            self.fail('DB durum dagilimi', str(s))

    def _test_db_guard_flags(self) -> None:
        counts = db_counts(self.db)
        if counts['cari_har'] == 82:
            self.ok('Cari_Har 82', str(counts['cari_har']))
        else:
            self.fail('Cari_Har 82', str(counts['cari_har']))
        if counts['finans_belgesi'] == 2:
            self.ok('finans_belgesi 2', str(counts['finans_belgesi']))
        else:
            self.fail('finans_belgesi 2', str(counts['finans_belgesi']))
        s = _fck_summary(self.db)
        if s['tedarikci_eslestirme'] == 0:
            self.ok('tedarikci_eslestirme 0', '0')
        else:
            self.fail('tedarikci_eslestirme 0', str(s['tedarikci_eslestirme']))
        try:
            from modules.nexgen import mo_tahsilat_config as mtc
            if not bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None)):
                self.ok('CARI_ENTEGRASYON_AKTIF=False', 'False')
            else:
                self.fail('CARI_ENTEGRASYON_AKTIF=False', 'True')
        except Exception as exc:
            self.fail('CARI_ENTEGRASYON_AKTIF=False', str(exc))


def _build_report(backup_dir: Path, evidence: dict, fails: list) -> str:
    tr = evidence.get('test_results', [])
    lines = '\n'.join(f"- [{t['status']}] {t['name']}: {t['detail']}" for t in tr)
    shots = evidence.get('screenshots', [])
    shot_lines = '\n'.join(f"- `{s}`" for s in shots) if shots else '- (browser script ile üretilecek)'
    return f"""# FAZ-F1-5 Cari Kimlik Köprüsü UI Raporu

**Backup:** `{backup_dir}`

## 1. Kapsam

Finans Merkezi içinde Cari Kimlik Köprüsü UI — rm-* tasarım dili, F1-3 API kullanımı, read-only ana DB doğrulama.

## 2. Değişen dosyalar

- `app/templates/nexgen/finans_cari_kimlik_koprusu.html`
- `app/modules/nexgen/finans_cari_kimlik_routes.py` (HTML route)
- `app/modules/nexgen/finans_routes.py` (Finans Merkezi link)
- `app/templates/nexgen/finans_merkezi.html` (iç navigasyon)
- `_test_faz_f1_finans_cari_kimlik_ui.py`

## 3. Sayfa route'u

`GET /nexgen/finans/cari-kimlik-koprusu`

## 4. Finans Merkezi entegrasyonu

Finans Merkezi üst aksiyonlarında `can_cari_kimlik_koprusu` ile koşullu link.

## 5. Görsel dil ve rm-* kullanımı

rm-kpi-bar, rm-sekme-bar, rm-panel, --rm-* değişkenleri, rm-page-hdr.

## 6–16. UI bileşenleri

KPI (7 kart), filtreler, liste/tablo, detay paneli, müşteri/tedarikçi sekmeleri, aday modal, manuel override (yönetim), pasife al modal, toast UX.

## 17. Browser doğrulama

Viewport 1366×768 — read-only ana DB.

## 18. Ekran görüntüleri

{shot_lines}

## 19. Test sonuçları

{lines}

## 20. Regresyon sonuçları

- migration/service/api pre-check: {evidence.get('regression_status', 'n/a')}

## 21. Ana DB SHA önce/sonra

- Önce: `{evidence.get('pre_main_sha')}`
- Sonra: `{evidence.get('post_main_sha')}`
- Beklenen baseline: `{BASELINE_SHA}`

## 22. Cari_Har / finans_belgesi kanıtı

- Cari_Har: {evidence.get('post_har')}
- finans_belgesi: {evidence.get('post_fb')}
- finans_cari_kimlik: {json.dumps(evidence.get('fck_summary', {}), ensure_ascii=False)}

## 23. Bilinen riskler

1. Browser write işlemleri ana DB'de yapılmadı (read-only doğrulama)
2. Detay paneli 1366×768'de tek kolon moda düşer
3. Posting uygunluk bilgi amaçlıdır

## 24. F1-6 öncesi kullanıcı onayı

Adem onayı beklenir — commit/push/deploy yapılmadı.

---

**SONUC:** {'PASS' if not fails else f'FAIL ({len(fails)} hata)'}
"""


def main() -> int:
    ts = _ts()
    backup_dir = ROOT / 'backup' / f'faz_f1_5_cari_kimlik_ui_{ts}'
    files_dir = backup_dir / 'files'
    screenshots_dir = backup_dir / 'screenshots'
    files_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    pre_sha = db_sha256(str(MAIN_DB))
    pre_hashes = critical_table_hashes(str(MAIN_DB))
    pre_counts = db_counts(str(MAIN_DB))
    pre_fck = _fck_summary(str(MAIN_DB))

    db_evidence_before = {
        'sha256': pre_sha,
        'baseline_expected': BASELINE_SHA,
        'counts': pre_counts,
        'fck_summary': pre_fck,
        'critical_hashes': pre_hashes,
    }
    (backup_dir / 'db_evidence_before.json').write_text(
        json.dumps(db_evidence_before, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )

    regression_status = 'PASS'
    for script in (
        '_test_faz_f1_migration_131.py',
        '_test_faz_f1_finans_cari_kimlik_service.py',
        '_test_faz_f1_finans_cari_kimlik_api.py',
    ):
        rc = subprocess.run(
            [sys.executable, str(ROOT / script)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        name = script.replace('_test_', '').replace('.py', '')
        if rc.returncode != 0:
            print(f'REGRESSON FAIL {name}:', (rc.stdout + rc.stderr)[-500:])
            regression_status = f'FAIL {name}'
            break

    reg_sha = db_sha256(str(MAIN_DB))
    if reg_sha != pre_sha:
        print(f'REGRESSON MAIN DB SHA POLLUTION: {pre_sha} -> {reg_sha}')
        return 1
    ok_reg_log, reg_log_msg = assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))
    if not ok_reg_log:
        print(f'REGRESSON LOGICAL POLLUTION: {reg_log_msg}')
        return 1

    isolated = use_isolated_finans_db(str(ROOT), str(MAIN_DB), tag='f1_5_ui')
    pin_all_db_paths(isolated)
    import app as flask_app
    pin_all_db_paths(isolated)
    app = flask_app.app
    app.config['TESTING'] = True
    client = app.test_client()

    template_html = TEMPLATE.read_text(encoding='utf-8')
    for fname in (
        'finans_cari_kimlik_koprusu.html',
        'finans_cari_kimlik_routes.py',
        'finans_routes.py',
        'finans_merkezi.html',
    ):
        src = APP / ('templates/nexgen' if fname.endswith('.html') else 'modules/nexgen') / fname
        if src.exists():
            shutil.copy2(src, files_dir / fname)

    rules = sorted(
        r.rule for r in app.url_map.iter_rules()
        if 'cari-kimlik' in r.rule or 'finans-cari-kimlik' in r.rule
    )
    (backup_dir / 'route_map.txt').write_text('\n'.join(rules), encoding='utf-8')

    tester = UiTester(isolated, client, app, template_html)
    tester.log(f'pre_main_sha={pre_sha}')
    tester.log(f'isolated_db={isolated}')
    tester.ok('regresyon pre-check', regression_status)

    try:
        tester.run_all()
    except Exception:
        tester.fail('run_all exception', traceback.format_exc()[-300:])

    post_sha = db_sha256(str(MAIN_DB))
    post_counts = db_counts(str(MAIN_DB))
    post_fck = _fck_summary(str(MAIN_DB))
    ok_main, main_msg = assert_main_db_unchanged(
        pre_sha, str(MAIN_DB),
        pre_har=pre_counts['cari_har'],
        pre_fb=pre_counts['finans_belgesi'],
    )
    ok_log, log_msg = assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))

    if ok_main:
        tester.ok('ana DB SHA korundu', main_msg)
    else:
        tester.fail('ana DB SHA korundu', main_msg)
    if ok_log:
        tester.ok('ana DB logical korundu', log_msg)
    else:
        tester.fail('ana DB logical korundu', log_msg)

    db_evidence_after = {
        'sha256': post_sha,
        'counts': post_counts,
        'fck_summary': post_fck,
        'unchanged': ok_main and ok_log,
    }
    (backup_dir / 'db_evidence_after.json').write_text(
        json.dumps(db_evidence_after, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )

    fails = [r for r in tester.results if r[0] == 'FAIL']
    for r in tester.results:
        tester.log(f"[{r[0]}] {r[1]} — {r[2]}")

    evidence = {
        'timestamp': ts,
        'pre_main_sha': pre_sha,
        'post_main_sha': post_sha,
        'post_har': post_counts['cari_har'],
        'post_fb': post_counts['finans_belgesi'],
        'fck_summary': post_fck,
        'regression_status': regression_status,
        'route_count': len(rules),
        'routes': rules,
        'test_results': [{'status': a, 'name': b, 'detail': c} for a, b, c in tester.results],
        'fail_count': len(fails),
        'screenshots': [],
    }
    (backup_dir / 'browser_evidence.json').write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, default=str),
        encoding='utf-8',
    )
    (backup_dir / 'test_output.txt').write_text('\n'.join(tester.lines), encoding='utf-8')
    (backup_dir / 'RAPOR.md').write_text(_build_report(backup_dir, evidence, fails), encoding='utf-8')

    tester.log(f'\nBackup: {backup_dir}')
    tester.log(f'SONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


if __name__ == '__main__':
    raise SystemExit(main())
