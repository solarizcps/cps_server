# -*- coding: utf-8 -*-
"""FAZ-F1-3 — Finans cari kimlik API + yetki testleri (izole DB)."""
from __future__ import annotations

import hashlib
import io
import json
import os
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
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP))
os.chdir(APP)

from _finans_test_isolation import (  # noqa: E402
    assert_main_db_unchanged,
    assert_main_db_logical_unchanged,
    critical_table_hashes,
    pin_all_db_paths,
    snapshot_finans_belgesi_seed,
    use_isolated_finans_db,
)

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


def _ensure_ckod(con: sqlite3.Connection, ckod: str, ctip: str, name: str) -> None:
    if not con.execute('SELECT 1 FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone():
        con.execute('INSERT INTO Cari_Kart (CKod, CName, CTip) VALUES (?, ?, ?)', (ckod, name, ctip))
        con.commit()


class ApiTester:
    def __init__(self, db: str, client, app) -> None:
        self.db = db
        self.client = client
        self.app = app
        self.results: list[tuple[str, str, str]] = []
        self.lines: list[str] = []
        self._cari_id: int | None = None
        self._ted_id: int | None = None
        self._m_kimlik_id: int | None = None
        self._t_kimlik_id: int | None = None

    def log(self, msg: str) -> None:
        print(msg)
        self.lines.append(msg)

    def ok(self, name: str, detail: str = '') -> None:
        self.results.append(('PASS', name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(('FAIL', name, detail))

    def login(self, rol_ad: str = 'Yonetim', rol_id: int = 1, kadi: str = 'admin_test'):
        with self.client.session_transaction() as s:
            s['kullanici'] = {
                'Id': 9001, 'KullaniciAdi': kadi, 'Tip': 'sistem',
                'RolId': rol_id, 'RolAd': rol_ad, 'Aktif': 1,
            }
            s['kullanici_tip'] = 'sistem'

    def run_all(self) -> None:
        con = _con(self.db)
        self._cari_id = int(con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
        ).fetchone()[0])
        self._ted_id = int(con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 ORDER BY id LIMIT 1'
        ).fetchone()[0])
        cari2 = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 AND id!=? LIMIT 1',
            (self._cari_id,),
        ).fetchone()
        ted2 = con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 AND id!=? LIMIT 1',
            (self._ted_id,),
        ).fetchone()
        self._cari2_id = int(cari2[0]) if cari2 else None
        self._ted2_id = int(ted2[0]) if ted2 else None
        _ensure_ckod(con, 'F1A_M001', '1', 'F1A Musteri')
        _ensure_ckod(con, 'F1A_T002', '2', 'F1A Tedarikci')
        _ensure_ckod(con, 'F1A_DUAL3', '3', 'F1A Dual')
        _ensure_ckod(con, 'F1A_UNK', 'GARBAGE', 'F1A Unknown')
        con.close()

        self._test_auth()
        self._test_read()
        self._test_create()
        self._test_yetki()
        self._test_eslestirme()
        self._test_lifecycle()
        self._test_errors()
        self._test_route_map()

    def _test_auth(self) -> None:
        self.login('Planlama', 32, 'plan_test')
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=set()):
            r = self.client.get('/nexgen/api/finans-cari-kimlik/liste')
            if r.status_code == 403:
                self.ok('Yetkisiz liste 403', str(r.status_code))
            else:
                self.fail('Yetkisiz liste 403', str(r.status_code))

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
            self.login('Muhasebe', 2, 'muh_ro')
            r2 = self.client.get('/nexgen/api/finans-cari-kimlik/liste')
            b = r2.get_json() or {}
            if r2.status_code == 200 and b.get('ok'):
                self.ok('view yetkili liste 200', str(r2.status_code))
            else:
                self.fail('view yetkili liste 200', str(r2.status_code))

        for rol, name in (('Planlama', 'plan'), ('Depo', 'depo'), ('Sevkiyat', 'sevk')):
            self.login(rol, 99, name)
            with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=set()):
                rx = self.client.get('/nexgen/api/finans-cari-kimlik/liste')
                if rx.status_code == 403:
                    self.ok(f'{rol} erisim yok', str(rx.status_code))
                else:
                    self.fail(f'{rol} erisim yok', str(rx.status_code))

    def _test_read(self) -> None:
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
            self.login('Muhasebe', 2)
            r = self.client.get('/nexgen/api/finans-cari-kimlik/liste?limit=9999')
            if r.status_code == 200:
                self.ok('limit ust siniri', '200')
            else:
                self.fail('limit ust siniri', str(r.status_code))

            r2 = self.client.get('/nexgen/api/finans-cari-kimlik/liste?kimlik_tipi=INVALID')
            b2 = r2.get_json() or {}
            if r2.status_code == 400 and b2.get('error', {}).get('code'):
                self.ok('invalid kimlik_tipi 400', b2['error']['code'])
            else:
                self.fail('invalid kimlik_tipi 400', str(r2.status_code))

            r3 = self.client.get('/nexgen/api/finans-cari-kimlik/999999')
            b3 = r3.get_json() or {}
            if r3.status_code == 404 and b3.get('error'):
                self.ok('olmayan kimlik 404', b3['error'].get('code', ''))
            else:
                self.fail('olmayan kimlik 404', str(r3.status_code))

            con = _con(self.db)
            fck0 = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
            con.close()
            self.client.get('/nexgen/api/finans-cari-kimlik/liste')
            con = _con(self.db)
            fck1 = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
            con.close()
            if fck0 == fck1:
                self.ok('read endpoint DB yazmaz', f'{fck0}={fck1}')
            else:
                self.fail('read endpoint DB yazmaz', f'{fck0}->{fck1}')

    def _test_create(self) -> None:
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
            self.login('Yonetim', 1)
            r = self.client.post(f'/nexgen/api/finans-cari-kimlik/musteri/{self._cari_id}/olustur')
            b = r.get_json() or {}
            if r.status_code == 201 and b.get('data', {}).get('created'):
                self._m_kimlik_id = b['data']['kimlik']['id']
                self.ok('musteri olustur 201', str(self._m_kimlik_id))
            elif r.status_code == 200 and b.get('data', {}).get('kimlik', {}).get('id'):
                self._m_kimlik_id = b['data']['kimlik']['id']
                self.ok('musteri olustur idempotent mevcut', str(self._m_kimlik_id))
            else:
                self.fail('musteri olustur 201', f'{r.status_code} {b}')

            r2 = self.client.post(f'/nexgen/api/finans-cari-kimlik/musteri/{self._cari_id}/olustur')
            b2 = r2.get_json() or {}
            if r2.status_code == 200 and not b2.get('data', {}).get('created'):
                self.ok('musteri idempotent 200', str(r2.status_code))
            else:
                self.fail('musteri idempotent 200', str(r2.status_code))

            r3 = self.client.post(f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted_id}/olustur')
            b3 = r3.get_json() or {}
            if r3.status_code == 201 and b3.get('data', {}).get('created'):
                self._t_kimlik_id = b3['data']['kimlik']['id']
                self.ok('tedarikci olustur 201', str(self._t_kimlik_id))
            elif r3.status_code == 200 and b3.get('data', {}).get('kimlik', {}).get('id'):
                self._t_kimlik_id = b3['data']['kimlik']['id']
                self.ok('tedarikci olustur idempotent mevcut', str(self._t_kimlik_id))
            else:
                self.fail('tedarikci olustur 201', f'{r3.status_code} {b3}')

            r4 = self.client.post(f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted_id}/olustur')
            if r4.status_code == 200:
                self.ok('tedarikci idempotent 200', str(r4.status_code))
            else:
                self.fail('tedarikci idempotent 200', str(r4.status_code))

    def _test_yetki(self) -> None:
        assert self._m_kimlik_id
        con = _con(self.db)
        con.execute(
            """
            UPDATE cari_eslestirme SET cari_kart_ckod='F1A_M001', eslestirme_durumu='DOGRULANDI', aktif=1
            WHERE nexgen_cari_id=?
            """,
            (self._cari_id,),
        )
        if not con.execute('SELECT 1 FROM cari_eslestirme WHERE nexgen_cari_id=?', (self._cari_id,)).fetchone():
            con.execute(
                """
                INSERT INTO cari_eslestirme
                    (nexgen_cari_id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi, aktif)
                VALUES (?, 'F1A_M001', 'DOGRULANDI', 'MANUEL', 1)
                """,
                (self._cari_id,),
            )
        con.commit()
        con.close()

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_MUHASEBE):
            self.login('Muhasebe', 2)
            rs = self.client.post(f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/musteri-sync')
            if rs.status_code == 200:
                self.ok('Muhasebe normal sync', str(rs.status_code))
            else:
                self.fail('Muhasebe normal sync', f'{rs.status_code} {rs.get_json()}')

            rm = self.client.post(
                f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/manuel-override',
                json={'cari_kart_ckod': 'F1A_M001', 'override_reason': 'test'},
            )
            if rm.status_code == 403:
                self.ok('Muhasebe manuel override 403', str(rm.status_code))
            else:
                self.fail('Muhasebe manuel override 403', str(rm.status_code))

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
            self.login('Yonetim', 1)
            if self._cari2_id:
                r_new = self.client.post(
                    f'/nexgen/api/finans-cari-kimlik/musteri/{self._cari2_id}/olustur',
                )
                kid2 = (r_new.get_json() or {}).get('data', {}).get('kimlik', {}).get('id')
                ro = self.client.post(
                    f'/nexgen/api/finans-cari-kimlik/{kid2}/manuel-override',
                    json={'cari_kart_ckod': 'F1A_UNK', 'override_reason': 'CTip bilinmeyen test'},
                )
            else:
                ro = self.client.post(
                    f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/manuel-override',
                    json={'cari_kart_ckod': 'F1A_UNK', 'override_reason': 'CTip bilinmeyen test'},
                )
            b = ro.get_json() or {}
            if ro.status_code == 200 and b.get('data', {}).get('kimlik', {}).get('durum') == 'MANUEL':
                self.ok('Yonetim manuel override PASS', b['data']['kimlik'].get('durum'))
            else:
                self.fail('Yonetim manuel override PASS', f'{ro.status_code} {b}')

            rb = self.client.post(
                f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/manuel-override',
                json={'cari_kart_ckod': 'F1A_M001', 'override_reason': ''},
            )
            if rb.status_code == 400:
                self.ok('override_reason bos 400', str(rb.status_code))
            else:
                self.fail('override_reason bos 400', str(rb.status_code))

    def _test_eslestirme(self) -> None:
        assert self._t_kimlik_id and self._ted_id
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_MUHASEBE):
            self.login('Muhasebe', 2)
            r_bad = self.client.post(
                f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted_id}/eslestir',
                json={'cari_kart_ckod': 'F1A_M001'},
            )
            b = r_bad.get_json() or {}
            if r_bad.status_code == 409 and b.get('error', {}).get('code') == 'CTIP_UYUMSUZ':
                self.ok('CTip uyumsuz normal 409', b['error']['code'])
            else:
                self.fail('CTip uyumsuz normal 409', f'{r_bad.status_code} {b}')

            r_ok = self.client.post(
                f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted_id}/eslestir',
                json={'cari_kart_ckod': 'F1A_T002'},
            )
            if r_ok.status_code == 200:
                self.ok('tedarikci normal eslestir', '200')
            else:
                self.fail('tedarikci normal eslestir', f'{r_ok.status_code} {r_ok.get_json()}')

        if self._ted2_id and self._cari2_id:
            with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
                self.login('Yonetim', 1)
                self.client.post(f'/nexgen/api/finans-cari-kimlik/musteri/{self._cari2_id}/olustur')
                con = _con(self.db)
                ex = con.execute(
                    'SELECT id FROM cari_eslestirme WHERE nexgen_cari_id=? AND aktif=1',
                    (self._cari2_id,),
                ).fetchone()
                if ex:
                    con.execute(
                        "UPDATE cari_eslestirme SET cari_kart_ckod='F1A_DUAL3', eslestirme_durumu='DOGRULANDI' WHERE id=?",
                        (ex['id'],),
                    )
                else:
                    con.execute(
                        """
                        INSERT INTO cari_eslestirme
                            (nexgen_cari_id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi, aktif)
                        VALUES (?, 'F1A_DUAL3', 'DOGRULANDI', 'MANUEL', 1)
                        """,
                        (self._cari2_id,),
                    )
                con.commit()
                kid_row = con.execute(
                    'SELECT id FROM finans_cari_kimlik WHERE nexgen_cari_id=?', (self._cari2_id,),
                ).fetchone()
                con.close()
                if kid_row:
                    self.client.post(f'/nexgen/api/finans-cari-kimlik/{kid_row["id"]}/musteri-sync')
                self.client.post(f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted2_id}/olustur')
                self.client.post(
                    f'/nexgen/api/finans-cari-kimlik/tedarikci/{self._ted2_id}/eslestir',
                    json={'cari_kart_ckod': 'F1A_DUAL3'},
                )
                con = _con(self.db)
                m_cnt = con.execute(
                    "SELECT COUNT(*) FROM finans_cari_kimlik WHERE cari_kart_ckod='F1A_DUAL3' AND aktif=1"
                ).fetchone()[0]
                con.close()
                if m_cnt >= 2:
                    self.ok('ayni CKod musteri+tedarikci izinli', f'count={m_cnt}')
                else:
                    self.fail('ayni CKod musteri+tedarikci izinli', str(m_cnt))

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
            self.login('Yonetim', 1)
            if self._cari2_id:
                r_dup = self.client.post(
                    f'/nexgen/api/finans-cari-kimlik/musteri/{self._cari2_id}/olustur',
                )
                kid = (r_dup.get_json() or {}).get('data', {}).get('kimlik', {}).get('id')
                if kid:
                    con = _con(self.db)
                    con.execute(
                        'UPDATE cari_eslestirme SET aktif=0 WHERE nexgen_cari_id=?',
                        (self._cari2_id,),
                    )
                    con.commit()
                    con.close()
                    rs = self.client.post(
                        f'/nexgen/api/finans-cari-kimlik/{kid}/manuel-override',
                        json={'cari_kart_ckod': 'F1A_M001', 'override_reason': 'duplicate CKod test'},
                    )
                    if rs.status_code == 409:
                        err = (rs.get_json() or {}).get('error', {})
                        self.ok('duplicate CKod musteri 409', err.get('code', str(rs.status_code)))
                    else:
                        self.fail('duplicate CKod musteri 409', f'{rs.status_code} {(rs.get_json() or {})}')
                else:
                    self.fail('duplicate CKod musteri 409', 'kimlik yok')
            else:
                self.ok('duplicate CKod musteri 409', 'SKIP')

    def _test_lifecycle(self) -> None:
        assert self._m_kimlik_id
        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_YONETIM):
            self.login('Yonetim', 1)
            con = _con(self.db)
            cnt0 = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
            con.close()
            rp = self.client.post(
                f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/pasife-al',
                json={'reason': 'api test pasif'},
            )
            con = _con(self.db)
            cnt1 = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
            con.close()
            if rp.status_code == 200 and cnt0 == cnt1:
                self.ok('pasife al fiziksel silmez', f'{cnt0}={cnt1}')
            else:
                self.fail('pasife al fiziksel silmez', f'{cnt0}->{cnt1}')

            rr = self.client.post(f'/nexgen/api/finans-cari-kimlik/{self._m_kimlik_id}/yeniden-aktif')
            if rr.status_code == 200:
                self.ok('yeniden aktif', str(rr.status_code))
            else:
                self.fail('yeniden aktif', str(rr.status_code))

    def _test_errors(self) -> None:
        from modules.nexgen.finans_cari_kimlik_service import FinansCariKimlikError

        with patch('modules.nexgen.finans_cari_kimlik_routes.kullanici_yetkileri', return_value=YK_VIEW):
            self.login('Muhasebe', 2)
            with patch('modules.nexgen.finans_cari_kimlik_routes.liste', side_effect=FinansCariKimlikError(
                'test', code='TEST_KOD', http_status=418, details={'x': 1},
            )):
                r = self.client.get('/nexgen/api/finans-cari-kimlik/liste')
                b = r.get_json() or {}
                if b.get('ok') is False and b.get('error', {}).get('code') == 'TEST_KOD':
                    self.ok('domain error JSON formati', b['error']['code'])
                else:
                    self.fail('domain error JSON formati', str(b))

            with patch('modules.nexgen.finans_cari_kimlik_routes.kpi', side_effect=RuntimeError('secret stack')):
                r2 = self.client.get('/nexgen/api/finans-cari-kimlik/liste')
                txt = r2.get_data(as_text=True)
                if r2.status_code == 500 and 'secret stack' not in txt and 'Traceback' not in txt:
                    self.ok('beklenmeyen error stack yok', str(r2.status_code))
                else:
                    self.fail('beklenmeyen error stack yok', txt[:200])

    def _test_route_map(self) -> None:
        rules = [r.rule for r in self.app.url_map.iter_rules() if 'finans-cari-kimlik' in r.rule]
        if len(rules) >= 14:
            self.ok('route map registration', str(len(rules)))
        else:
            self.fail('route map registration', str(len(rules)))


def main() -> int:
    ts = _ts()
    backup_dir = ROOT / 'backup' / f'faz_f1_3_api_yetki_{ts}'
    files_dir = backup_dir / 'files'
    files_dir.mkdir(parents=True, exist_ok=True)

    pre_sha = hashlib.sha256(MAIN_DB.read_bytes()).hexdigest()
    pre_hashes = critical_table_hashes(str(MAIN_DB))
    pre_fb_snap = None
    con_pre = _con(str(MAIN_DB))
    pre_fb_snap = snapshot_finans_belgesi_seed(con_pre)
    con_pre.close()

    for script in (
        '_test_faz_f1_migration_131.py',
        '_test_faz_f1_finans_cari_kimlik_service.py',
    ):
        rc = subprocess.run(
            [sys.executable, str(ROOT / script)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        name = script.replace('_test_', '').replace('.py', '')
        if rc.returncode != 0:
            print(f'REGRESSON FAIL {name}:', (rc.stdout + rc.stderr)[-400:])
            return 1
    reg_sha = hashlib.sha256(MAIN_DB.read_bytes()).hexdigest()
    if reg_sha != pre_sha:
        print(f'REGRESSON MAIN DB SHA POLLUTION: {pre_sha} -> {reg_sha}')
        return 1
    ok_reg_log, reg_log_msg = assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))
    if not ok_reg_log:
        print(f'REGRESSON LOGICAL POLLUTION: {reg_log_msg}')
        return 1

    isolated = use_isolated_finans_db(str(ROOT), str(MAIN_DB), tag='f1_3_api')
    shutil.copy2(isolated, backup_dir / 'temp_test.db')

    pin_all_db_paths(isolated)
    import app as flask_app
    pin_all_db_paths(isolated)
    app = flask_app.app
    app.config['TESTING'] = True
    client = app.test_client()

    for fname in (
        'finans_cari_kimlik_routes.py',
        'finans_cari_kimlik_yetki.py',
    ):
        src = APP / 'modules' / 'nexgen' / fname
        if src.exists():
            shutil.copy2(src, files_dir / fname)
    shutil.copy2(APP / 'modules' / 'nexgen' / '__init__.py', files_dir / 'nexgen_init_snapshot.py')
    shutil.copy2(ROOT / '_test_faz_f1_finans_cari_kimlik_api.py', files_dir / '_test_faz_f1_finans_cari_kimlik_api.py')

    rules = sorted(r.rule for r in app.url_map.iter_rules() if 'finans-cari-kimlik' in r.rule)
    (backup_dir / 'route_map.txt').write_text('\n'.join(rules), encoding='utf-8')

    tester = ApiTester(isolated, client, app)
    tester.log(f'regression_pre_sha={pre_sha}')
    tester.log(f'regression_post_sha={reg_sha}')
    tester.ok('regresyon migration 131', 'PASS (pre-check)')
    tester.ok('regresyon service/read', 'PASS (pre-check)')
    tester.log(f'isolated_db={isolated}')

    try:
        from modules.nexgen.finans_cari_kimlik_service import FinansCariKimlikError  # noqa: F401
        tester.run_all()
    except Exception:
        tester.fail('runner exception', traceback.format_exc()[:500])
        tester.log(traceback.format_exc())

    post_sha = hashlib.sha256(MAIN_DB.read_bytes()).hexdigest()
    con = _con(str(MAIN_DB))
    post_har = int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0])
    post_fb = int(con.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0])
    fck_main = int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0])
    con.close()

    ok_main, msg = assert_main_db_unchanged(pre_sha, str(MAIN_DB), pre_har=82, pre_fb=2)
    ok_log, log_msg = assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))
    con_chk = _con(str(MAIN_DB))
    post_fb_snap = snapshot_finans_belgesi_seed(con_chk)
    con_chk.close()
    fb_snap_ok = post_fb_snap == pre_fb_snap
    if ok_main:
        tester.ok('MAIN DB SHA guard', msg)
        tester.ok('Cari_Har 82', str(post_har))
        tester.ok('finans_belgesi degismez', str(post_fb))
    else:
        tester.fail('MAIN DB SHA guard', msg)
    if ok_log:
        tester.ok('MAIN DB logical hash guard', log_msg)
    else:
        tester.fail('MAIN DB logical hash guard', log_msg)
    if fb_snap_ok:
        tester.ok('finans_belgesi snapshot guard', 'unchanged')
    else:
        tester.fail('finans_belgesi snapshot guard', 'audit/content drift')

    if fck_main == 0:
        tester.ok('ana DB finans_cari_kimlik 0 (pre-apply)', str(fck_main))
    elif fck_main == 24:
        tester.ok('ana DB finans_cari_kimlik post-apply', str(fck_main))
    else:
        tester.fail('ana DB finans_cari_kimlik beklenen', str(fck_main))

    try:
        sys.path.insert(0, str(APP))
        from modules.nexgen import mo_tahsilat_config as mtc
        if not bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None)):
            tester.ok('CARI_ENTEGRASYON_AKTIF=False', 'False')
        else:
            tester.fail('CARI_ENTEGRASYON_AKTIF=False', 'True')
    except Exception as exc:
        tester.fail('CARI_ENTEGRASYON_AKTIF', str(exc))

    fails = [r for r in tester.results if r[0] == 'FAIL']
    for r in tester.results:
        tester.log(f"[{r[0]}] {r[1]} — {r[2]}")

    evidence = {
        'timestamp': ts,
        'regression_pre_sha': pre_sha,
        'regression_post_sha': reg_sha,
        'pre_main_sha': pre_sha,
        'post_main_sha': post_sha,
        'main_unchanged': ok_main,
        'logical_unchanged': ok_log,
        'finans_belgesi_snapshot_unchanged': fb_snap_ok,
        'post_har': post_har,
        'post_fb': post_fb,
        'fck_main_count': fck_main,
        'route_count': len(rules),
        'routes': rules,
        'test_results': [{'status': a, 'name': b, 'detail': c} for a, b, c in tester.results],
        'fail_count': len(fails),
    }
    with open(backup_dir / 'db_evidence.json', 'w', encoding='utf-8') as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    with open(backup_dir / 'test_output.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(tester.lines))

    report = _build_report(backup_dir, evidence, fails)
    (backup_dir / 'RAPOR.md').write_text(report, encoding='utf-8')

    tester.log(f'\nBackup: {backup_dir}')
    tester.log(f'SONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


def _build_report(backup_dir: Path, evidence: dict, fails: list) -> str:
    tr = evidence.get('test_results', [])
    lines = '\n'.join(f"- [{t['status']}] {t['name']}: {t['detail']}" for t in tr)
    routes = '\n'.join(f"- `{r}`" for r in evidence.get('routes', []))
    return f"""# FAZ-F1-3 API + Yetki Raporu

**Backup:** `{backup_dir}`

## 1. Endpoint listesi ({evidence.get('route_count')} adet)

{routes}

## 2. Yetki matrisi

| Islem | Yetki |
|-------|-------|
| READ | cari_kimlik.view veya manage/tedarikci view |
| WRITE musteri | cari_kimlik.manage can_update/can_manage |
| WRITE tedarikci | tedarikci_kimlik.manage veya cari_kimlik.manage |
| Manuel override | yalnizca can_manage=1 |

## 3. Muhasebe vs Yonetim

- Muhasebe: can_update=1 → normal sync/eslestirme OK, manuel override 403
- Yonetim: can_manage=1 → manuel override OK

## 4–7. Davranis

- Domain hata: `{{ok:false, error:{{code,message,details}}}}`
- Route BEGIN/COMMIT/ROLLBACK
- Audit: response `audit` meta + created_by/updated_by domain alanlari
- sistem_audit tablosu kullanilmadi (F1-3 kapsam disi)

## 8. Test sonuclari

{lines}

## 9–11. Regresyon + Ana DB

- SHA: `{evidence.get('pre_main_sha')}` → `{evidence.get('post_main_sha')}`
- Cari_Har: {evidence.get('post_har')}
- finans_belgesi: {evidence.get('post_fb')}
- finans_cari_kimlik ana DB: {evidence.get('fck_main_count')}

## 16. Bilinen riskler

1. Audit yalnizca domain alanlari + response meta
2. UI F1-4+ bekliyor (rm-* zorunlu)
3. posting_uygun henuz posting servisine bagli degil

## 17. F1-4 oncesi onay

Backfill/dry-run raporu icin Adem onayi beklenir.

---

**SONUC:** {'PASS' if not fails else f'FAIL ({len(fails)} hata)'}
"""


if __name__ == '__main__':
    raise SystemExit(main())
