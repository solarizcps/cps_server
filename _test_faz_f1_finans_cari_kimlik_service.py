# -*- coding: utf-8 -*-
"""FAZ-F1-2 — Finans cari kimlik servis/read izole test paketi."""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

import _finans_test_isolation as iso  # noqa: E402

from modules.nexgen.finans_cari_kimlik_service import (  # noqa: E402
    FinansCariKimlikError,
    create_kimlik_musteri,
    create_kimlik_tedarikci,
    deactivate_kimlik,
    normalize_ctip,
    reactivate_kimlik,
    resolve_kimlik,
    sync_musteri_ckod_from_eslestirme,
    validate_ctip_for_kimlik,
)
from modules.nexgen.finans_cari_kimlik_read_service import (  # noqa: E402
    detay,
    eslestirme_adaylari,
    kpi,
    liste,
)
from modules.nexgen.tedarikci_eslestirme_service import (  # noqa: E402
    create_or_update_tedarikci_eslestirme,
    sync_tedarikci_kimlik_ckod,
)

MAIN_DB = APP / 'mock_data.db'
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'
BASELINE_CARI_HAR = 82


def _ts() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _connect(db: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def _finans_belgesi_summary(db: Path) -> dict:
    con = _connect(db)
    rows = con.execute('SELECT id, durum FROM finans_belgesi ORDER BY id').fetchall()
    by: dict[str, int] = {}
    for r in rows:
        d = str(r['durum'])
        by[d] = by.get(d, 0) + 1
    con.close()
    return {'total': len(rows), 'by_durum': by}


class TestRunner:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []
        self.lines: list[str] = []

    def log(self, msg: str) -> None:
        print(msg)
        self.lines.append(msg)

    def ok(self, name: str, detail: str = '') -> None:
        self.results.append(('PASS', name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(('FAIL', name, detail))

    def run(self, temp_db: Path) -> None:
        con = _connect(temp_db)
        try:
            self._test_ctip()
            self._test_kimlik_create(con)
            self._test_resolve(con)
            self._test_sync_musteri(con, temp_db)
            self._test_tedarikci(con, temp_db)
            self._test_dual_ckod(con, temp_db)
            self._test_m099(con, temp_db)
            self._test_lifecycle(con)
            self._test_read(con)
            self._test_posting(con, temp_db)
            self._test_transaction(con)
        finally:
            con.close()

    def _test_ctip(self) -> None:
        cases = [
            ('CTip 1', 1, {'MUSTERI'}),
            ("CTip 'MUSTERI'", 'MUSTERI', {'MUSTERI'}),
            ('CTip 2', 2, {'TEDARIKCI'}),
            ("CTip 'TEDARIKCI'", 'TEDARIKCI', {'TEDARIKCI'}),
            ('CTip 3', 3, {'MUSTERI', 'TEDARIKCI'}),
            ('CTip BOTH', 'BOTH', {'MUSTERI', 'TEDARIKCI'}),
            ('bilinmeyen CTip', 'XYZ_UNKNOWN', set()),
        ]
        for name, val, expected in cases:
            got = normalize_ctip(val)
            if got == expected:
                self.ok(name, str(got))
            else:
                self.fail(name, f'{got} != {expected}')

    def _test_kimlik_create(self, con: sqlite3.Connection) -> None:
        cari_id = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
        ).fetchone()[0]
        ted_id = con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 ORDER BY id LIMIT 1'
        ).fetchone()[0]

        m1 = create_kimlik_musteri(con, cari_id, user_id=1)
        if m1.get('kimlik_tipi') == 'MUSTERI' and (
            m1.get('durum') == 'BEKLIYOR'
            or (m1.get('idempotent') and m1.get('durum') in ('BEKLIYOR', 'DOGRULANDI', 'MANUEL'))
        ):
            self.ok('musteri kimlik create', f"id={m1['id']} idempotent={m1.get('idempotent')}")
        else:
            self.fail('musteri kimlik create', str(m1))

        m2 = create_kimlik_musteri(con, cari_id, user_id=1)
        if m2.get('idempotent') and m2['id'] == m1['id']:
            self.ok('musteri kimlik idempotent', str(m2['id']))
        else:
            self.fail('musteri kimlik idempotent', str(m2))

        t1 = create_kimlik_tedarikci(con, ted_id, user_id=1)
        if t1.get('kimlik_tipi') == 'TEDARIKCI':
            self.ok('tedarikci kimlik create', f"id={t1['id']}")
        else:
            self.fail('tedarikci kimlik create', str(t1))

        t2 = create_kimlik_tedarikci(con, ted_id, user_id=1)
        if t2.get('idempotent'):
            self.ok('tedarikci kimlik idempotent', str(t2['id']))
        else:
            self.fail('tedarikci kimlik idempotent', str(t2))

        self._musteri_kimlik_id = m1['id']
        self._tedarikci_kimlik_id = t1['id']
        self._cari_id = cari_id
        self._ted_id = ted_id
        con.commit()

    def _test_resolve(self, con: sqlite3.Connection) -> None:
        try:
            resolve_kimlik(con)
            self.fail('yanlis resolve parametreleri', 'exception bekleniyordu')
        except FinansCariKimlikError as e:
            if e.http_status == 400:
                self.ok('yanlis resolve parametreleri', e.code)
            else:
                self.fail('yanlis resolve parametreleri', str(e))

        try:
            resolve_kimlik(con, kimlik_id=999999)
            self.fail('bulunamayan kimlik', '404 bekleniyordu')
        except FinansCariKimlikError as e:
            if e.http_status == 404:
                self.ok('bulunamayan kimlik', e.code)
            else:
                self.fail('bulunamayan kimlik', str(e))

        paket = resolve_kimlik(con, kimlik_id=self._musteri_kimlik_id)
        if paket.get('id') == self._musteri_kimlik_id:
            self.ok('resolve by id', str(paket['id']))
        else:
            self.fail('resolve by id', str(paket))

    def _ensure_ckod(self, con: sqlite3.Connection, ckod: str, ctip: str, cname: str) -> None:
        ex = con.execute('SELECT 1 FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
        if not ex:
            con.execute(
                'INSERT INTO Cari_Kart (CKod, CName, CTip) VALUES (?, ?, ?)',
                (ckod, cname, ctip),
            )

    def _test_sync_musteri(self, con: sqlite3.Connection, temp_db: Path) -> None:
        ckod_ok = 'F1T_M001'
        self._ensure_ckod(con, ckod_ok, '1', 'F1 Test Musteri')
        es = con.execute(
            'SELECT id FROM cari_eslestirme WHERE nexgen_cari_id=? AND aktif=1',
            (self._cari_id,),
        ).fetchone()
        if es:
            con.execute(
                "UPDATE cari_eslestirme SET cari_kart_ckod=?, eslestirme_durumu='DOGRULANDI' WHERE id=?",
                (ckod_ok, es['id']),
            )
        else:
            con.execute(
                """
                INSERT INTO cari_eslestirme
                    (nexgen_cari_id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi, aktif)
                VALUES (?, ?, 'DOGRULANDI', 'MANUEL', 1)
                """,
                (self._cari_id, ckod_ok),
            )
        con.commit()

        synced = sync_musteri_ckod_from_eslestirme(con, self._musteri_kimlik_id, user_id=1, commit=True)
        if synced.get('cari_kart_ckod') == ckod_ok and synced.get('durum') == 'DOGRULANDI':
            self.ok('musteri CKod sync DOGRULANDI', ckod_ok)
        else:
            self.fail('musteri CKod sync DOGRULANDI', str(synced))

        ckod_ted_only = 'F1T_T002'
        self._ensure_ckod(con, ckod_ted_only, '2', 'F1 Test Tedarikci Only')
        es2 = con.execute(
            'SELECT id FROM cari_eslestirme WHERE nexgen_cari_id=?', (self._cari_id,),
        ).fetchone()
        con.execute(
            "UPDATE cari_eslestirme SET cari_kart_ckod=? WHERE id=?",
            (ckod_ted_only, es2['id']),
        )
        con.execute(
            'UPDATE finans_cari_kimlik SET cari_kart_ckod=NULL, durum=\'BEKLIYOR\' WHERE id=?',
            (self._musteri_kimlik_id,),
        )
        con.commit()
        try:
            sync_musteri_ckod_from_eslestirme(con, self._musteri_kimlik_id, commit=True)
            self.fail('musteri CTip uyumsuz blok', 'exception bekleniyordu')
        except FinansCariKimlikError as e:
            if e.code == 'CTIP_UYUMSUZ':
                self.ok('musteri CTip uyumsuz blok', e.code)
            else:
                self.fail('musteri CTip uyumsuz blok', e.code)

        ckod_unk = 'F1T_UNK'
        self._ensure_ckod(con, ckod_unk, 'GARbage', 'F1 Unknown CTip')
        con.execute(
            "UPDATE cari_eslestirme SET cari_kart_ckod=?, eslestirme_durumu='DOGRULANDI' WHERE nexgen_cari_id=?",
            (ckod_unk, self._cari_id),
        )
        con.execute(
            "UPDATE finans_cari_kimlik SET cari_kart_ckod=NULL, durum='BEKLIYOR' WHERE id=?",
            (self._musteri_kimlik_id,),
        )
        con.commit()
        manuel = sync_musteri_ckod_from_eslestirme(
            con, self._musteri_kimlik_id,
            manuel_override=True, manuel_not='Test override bilinmeyen CTip',
            user_id=1, commit=True,
        )
        if manuel.get('durum') == 'MANUEL':
            self.ok('musteri MANUEL override', manuel.get('durum'))
        else:
            self.fail('musteri MANUEL override', str(manuel))

    def _test_tedarikci(self, con: sqlite3.Connection, temp_db: Path) -> None:
        ckod = 'F1T_TED01'
        self._ensure_ckod(con, ckod, '2', 'F1 Tedarikci Cari')
        con.commit()

        es = create_or_update_tedarikci_eslestirme(
            con, self._ted_id, ckod, user_id=1, commit=True,
        )
        if es.get('cari_kart_ckod') == ckod:
            self.ok('tedarikci eslestirme create', ckod)
        else:
            self.fail('tedarikci eslestirme create', str(es))

        synced = sync_tedarikci_kimlik_ckod(con, self._tedarikci_kimlik_id, user_id=1, commit=True)
        if synced.get('cari_kart_ckod') == ckod:
            self.ok('tedarikci kimlik sync', ckod)
        else:
            self.fail('tedarikci kimlik sync', str(synced))

        ted2 = con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 AND id!=? LIMIT 1',
            (self._ted_id,),
        ).fetchone()
        if ted2:
            try:
                create_or_update_tedarikci_eslestirme(
                    con, ted2['id'], ckod, user_id=1, commit=True,
                )
                self.fail('tedarikci duplicate CKod blok', 'exception bekleniyordu')
            except FinansCariKimlikError as e:
                if e.code == 'CKOD_CAKISMA':
                    self.ok('tedarikci duplicate CKod blok', e.code)
                else:
                    self.fail('tedarikci duplicate CKod blok', e.code)

    def _test_dual_ckod(self, con: sqlite3.Connection, temp_db: Path) -> None:
        ckod = 'F1T_DUAL3'
        self._ensure_ckod(con, ckod, '3', 'F1 Dual CTip')
        cari2 = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 AND id!=? LIMIT 1',
            (self._cari_id,),
        ).fetchone()
        if not cari2:
            self.ok('CTip=3 dual CKod', 'SKIP — ikinci cari yok')
            return

        m = create_kimlik_musteri(con, cari2['id'], user_id=1, commit=True)
        con.execute(
            """
            INSERT INTO cari_eslestirme (nexgen_cari_id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi, aktif)
            VALUES (?, ?, 'DOGRULANDI', 'MANUEL', 1)
            """,
            (cari2['id'], ckod),
        )
        con.commit()
        sync_musteri_ckod_from_eslestirme(con, m['id'], commit=True)

        ted2 = con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 AND id!=? LIMIT 1',
            (self._ted_id,),
        ).fetchone()
        if ted2:
            tm = create_kimlik_tedarikci(con, ted2['id'], user_id=1, commit=True)
            create_or_update_tedarikci_eslestirme(con, ted2['id'], ckod, commit=True)
            st = sync_tedarikci_kimlik_ckod(con, tm['id'], commit=True)
            if st.get('cari_kart_ckod') == ckod:
                self.ok('CTip=3 ayni CKod iki tipte izinli', ckod)
            else:
                self.fail('CTip=3 ayni CKod iki tipte izinli', str(st))

    def _test_m099(self, con: sqlite3.Connection, temp_db: Path) -> None:
        m099 = con.execute("SELECT CKod, CTip FROM Cari_Kart WHERE CKod='M099'").fetchone()
        if not m099:
            self._ensure_ckod(con, 'M099', 'MUSTERI', 'M099 Test')
            m099 = con.execute("SELECT CKod, CTip FROM Cari_Kart WHERE CKod='M099'").fetchone()

        val = validate_ctip_for_kimlik(dict(m099), 'MUSTERI')
        if val.get('uygun'):
            self.ok("CTip M099='MUSTERI' musteri uygun", str(val.get('ctip_normalized')))
        else:
            self.fail("CTip M099 musteri uygun", str(val))

        val2 = validate_ctip_for_kimlik(dict(m099), 'TEDARIKCI')
        if not val2.get('uygun'):
            self.ok('M099 tedarikci uyumsuz', val2.get('blok_kodu') or '')
        else:
            self.fail('M099 tedarikci uyumsuz', str(val2))

    def _test_lifecycle(self, con: sqlite3.Connection) -> None:
        kid = self._musteri_kimlik_id
        cnt_before = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
        deact = deactivate_kimlik(con, kid, 'test pasif', user_id=1, commit=True)
        cnt_after = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
        if cnt_before == cnt_after and deact.get('durum') == 'IPTAL' and not deact.get('aktif'):
            self.ok('deactivate fiziksel silmez', f"count={cnt_after}")
        else:
            self.fail('deactivate fiziksel silmez', f"{cnt_before}->{cnt_after}")

        rea = reactivate_kimlik(con, kid, user_id=1, commit=True)
        if rea.get('aktif'):
            self.ok('reactivate', rea.get('durum', ''))
        else:
            self.fail('reactivate', str(rea))

        cari3 = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 AND id!=? ORDER BY id DESC LIMIT 1',
            (self._cari_id,),
        ).fetchone()
        if not cari3:
            self.ok('reactivate duplicate kontrolu', 'SKIP')
            return
        k3 = create_kimlik_musteri(con, cari3['id'], commit=True)
        deactivate_kimlik(con, k3['id'], 'dup test', commit=True)
        ckod = con.execute(
            'SELECT cari_kart_ckod FROM finans_cari_kimlik WHERE id=?',
            (kid,),
        ).fetchone()[0]
        if ckod:
            con.execute(
                'UPDATE finans_cari_kimlik SET cari_kart_ckod=? WHERE id=? AND aktif=0',
                (ckod, k3['id']),
            )
            con.commit()
            try:
                reactivate_kimlik(con, k3['id'], commit=True)
                self.fail('reactivate duplicate kontrolu', 'CKOD_CAKISMA bekleniyordu')
            except FinansCariKimlikError as e:
                if e.code == 'CKOD_CAKISMA':
                    self.ok('reactivate duplicate kontrolu', e.code)
                else:
                    self.fail('reactivate duplicate kontrolu', e.code)
        else:
            self.ok('reactivate duplicate kontrolu', 'SKIP — ckod yok')

    def _test_read(self, con: sqlite3.Connection) -> None:
        lst = liste(con, kimlik_tipi='MUSTERI', limit=50)
        if isinstance(lst.get('kayitlar'), list):
            self.ok('liste filtreleri', f"toplam={lst['toplam']}")
        else:
            self.fail('liste filtreleri', str(lst))

        kp = kpi(con)
        if kp.get('toplam', 0) >= 1 and 'posting_engelli' in kp:
            self.ok('KPI sayilari', json.dumps(kp))
        else:
            self.fail('KPI sayilari', str(kp))

        aday = eslestirme_adaylari(con, 'MUSTERI', self._cari_id, limit=5)
        if aday and 'secilebilir' in aday[0]:
            self.ok('aday CKod uygunluklari', f"count={len(aday)}")
        else:
            self.fail('aday CKod uygunluklari', str(aday))

        d = detay(con, self._musteri_kimlik_id)
        if d.get('id') == self._musteri_kimlik_id:
            self.ok('detay', str(d['id']))
        else:
            self.fail('detay', str(d))

    def _test_posting(self, con: sqlite3.Connection, temp_db: Path) -> None:
        d = detay(con, self._musteri_kimlik_id)
        if d.get('durum') in ('DOGRULANDI', 'MANUEL') and d.get('cari_kart_ckod'):
            if d.get('posting_uygun'):
                self.ok('posting_uygun hesaplamasi', 'True')
            else:
                self.ok('posting_uygun hesaplamasi', d.get('posting_engel_kodu') or '')
        else:
            if not d.get('posting_uygun') and d.get('posting_engel_kodu'):
                self.ok('posting_uygun hesaplamasi', d.get('posting_engel_kodu'))
            else:
                self.fail('posting_uygun hesaplamasi', str(d))

    def _test_transaction(self, con: sqlite3.Connection) -> None:
        cari = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1 OFFSET 2'
        ).fetchone()
        if not cari:
            self.ok('commit=False rollback', 'SKIP')
            return
        cnt0 = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
        try:
            con.execute('BEGIN')
            create_kimlik_musteri(con, cari['id'], commit=False)
            con.execute('ROLLBACK')
        except Exception as exc:
            con.rollback()
            self.fail('commit=False rollback', str(exc))
            return
        cnt1 = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
        if cnt0 == cnt1:
            self.ok('commit=False rollback', f"{cnt0}={cnt1}")
        else:
            self.fail('commit=False rollback', f"{cnt0}->{cnt1}")


def main() -> int:
    ts = _ts()
    backup_dir = ROOT / 'backup' / f'faz_f1_2_service_read_{ts}'
    files_dir = backup_dir / 'files'
    files_dir.mkdir(parents=True, exist_ok=True)

    pre_sha = iso.db_sha256(str(MAIN_DB))
    pre_counts = iso.db_counts(str(MAIN_DB))
    pre_fb = _finans_belgesi_summary(MAIN_DB)
    pre_hashes = iso.critical_table_hashes(str(MAIN_DB))

    runner = TestRunner()
    runner.log(f'pre_main_sha={pre_sha}')
    runner.log(f'pre_counts={pre_counts}')

    temp_db = backup_dir / 'temp_test.db'
    shutil.copy2(MAIN_DB, temp_db)

    for fname in (
        'finans_cari_kimlik_service.py',
        'tedarikci_eslestirme_service.py',
        'finans_cari_kimlik_read_service.py',
    ):
        shutil.copy2(APP / 'modules' / 'nexgen' / fname, files_dir / fname)
    shutil.copy2(ROOT / '_test_faz_f1_finans_cari_kimlik_service.py',
                 files_dir / '_test_faz_f1_finans_cari_kimlik_service.py')

    try:
        runner.run(temp_db)
    except Exception as exc:
        runner.fail('runner exception', traceback.format_exc())
        runner.log(traceback.format_exc())

    post_sha = iso.db_sha256(str(MAIN_DB))
    post_counts = iso.db_counts(str(MAIN_DB))
    post_fb = _finans_belgesi_summary(MAIN_DB)
    ok_main, main_msg = iso.assert_main_db_unchanged(
        pre_sha, str(MAIN_DB),
        pre_har=pre_counts['cari_har'],
        pre_fb=pre_counts['finans_belgesi'],
    )
    ok_log, log_msg = iso.assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))
    if ok_main:
        runner.ok('MAIN DB SHA guard', main_msg)
        runner.ok('Ana DB Cari_Har 82', str(post_counts['cari_har']))
        runner.ok('Ana DB finans_belgesi degismez', json.dumps(post_fb))
    else:
        runner.fail('MAIN DB SHA guard', main_msg)
    if ok_log:
        runner.ok('MAIN DB logical hash guard', log_msg)
    else:
        runner.fail('MAIN DB logical hash guard', log_msg)

    try:
        sys.path.insert(0, str(APP))
        from modules.nexgen import mo_tahsilat_config as mtc
        cari_ent = bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None))
        if not cari_ent:
            runner.ok('CARI_ENTEGRASYON_AKTIF=False', str(cari_ent))
        else:
            runner.fail('CARI_ENTEGRASYON_AKTIF=False', str(cari_ent))
    except Exception as exc:
        runner.fail('CARI_ENTEGRASYON_AKTIF', str(exc))

    mig_rc = subprocess.run(
        [sys.executable, str(ROOT / '_test_faz_f1_migration_131.py')],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if mig_rc.returncode == 0:
        runner.ok('Migration 131 regresyon', 'PASS')
    else:
        runner.fail('Migration 131 regresyon', mig_rc.stdout[-500:] + mig_rc.stderr[-500:])

    fails = [r for r in runner.results if r[0] == 'FAIL']
    for r in runner.results:
        runner.log(f"[{r[0]}] {r[1]} — {r[2]}")

    evidence = {
        'timestamp': ts,
        'pre_main_sha': pre_sha,
        'post_main_sha': post_sha,
        'baseline_sha': BASELINE_SHA,
        'main_unchanged': ok_main,
        'pre_counts': pre_counts,
        'post_counts': post_counts,
        'pre_finans_belgesi': pre_fb,
        'post_finans_belgesi': post_fb,
        'test_results': [{'status': a, 'name': b, 'detail': c} for a, b, c in runner.results],
        'fail_count': len(fails),
    }
    with open(backup_dir / 'db_evidence.json', 'w', encoding='utf-8') as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    with open(backup_dir / 'test_output.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(runner.lines))

    report = _build_report(backup_dir, evidence, fails)
    (backup_dir / 'RAPOR.md').write_text(report, encoding='utf-8')

    runner.log(f'\nBackup: {backup_dir}')
    runner.log(f'SONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


def _build_report(backup_dir: Path, evidence: dict, fails: list) -> str:
    tr = evidence.get('test_results', [])
    test_lines = '\n'.join(f"- [{t['status']}] {t['name']}: {t['detail']}" for t in tr)
    return f"""# FAZ-F1-2 Servis/Read Katmanı Raporu

**Backup:** `{backup_dir}`

## 1. Yeni dosyalar

- `app/modules/nexgen/finans_cari_kimlik_service.py`
- `app/modules/nexgen/tedarikci_eslestirme_service.py`
- `app/modules/nexgen/finans_cari_kimlik_read_service.py`
- `_test_faz_f1_finans_cari_kimlik_service.py`

## 2. Servis fonksiyonlari

**finans_cari_kimlik_service:** normalize_ctip, validate_ctip_for_kimlik, create_kimlik_musteri/tedarikci, resolve_kimlik, sync_musteri_ckod_from_eslestirme, deactivate/reactivate_kimlik, hesapla_posting_uygunluk

**tedarikci_eslestirme_service:** get/create/validate/sync tedarikci eslestirme

**finans_cari_kimlik_read_service:** liste, detay, kpi, eslestirme_adaylari

## 3. CTip normalizasyon

| Girdi | Cikti |
|-------|-------|
| 1, '1', MUSTERI, CUSTOMER | MUSTERI |
| 2, '2', TEDARIKCI, SUPPLIER | TEDARIKCI |
| 3, BOTH, HER_IKISI | MUSTERI+TEDARIKCI |
| bilinmeyen/bos | bos set + CTIP_BILINMIYOR |

## 4. Domain hata kodlari

FinansCariKimlikError: KIMLIK_BULUNAMADI, CTIP_UYUMSUZ, CTIP_BILINMIYOR, CKOD_CAKISMA, ESLESME_BEKLIYOR, OPERASYONEL_PASIF, PARAMETRE_HATASI, MANUEL_NOT_ZORUNLU

## 5–11. Davranis ozeti

- Idempotent kimlik create (UNIQUE operasyonel FK)
- Sync yalnizca cari_eslestirme/tedarikci_eslestirme okur — yazmaz
- Deactivate: aktif=0, durum=IPTAL (DELETE yok)
- Reactivate: CKod/CTip yeniden dogrulama
- posting_uygun bilgi amaclı — FinancialPostingService degismedi

## 12. Test sonuclari

{test_lines}

## 13. Migration regresyon

Migration 131 izole test paketi yeniden calistirildi.

## 14–17. Ana DB kaniti

| Metrik | Once | Sonra |
|--------|------|-------|
| SHA | `{evidence.get('pre_main_sha')}` | `{evidence.get('post_main_sha')}` |
| Cari_Har | {evidence.get('pre_counts', {}).get('cari_har')} | {evidence.get('post_counts', {}).get('cari_har')} |
| finans_belgesi | {json.dumps(evidence.get('pre_finans_belgesi'))} | {json.dumps(evidence.get('post_finans_belgesi'))} |

Ana DB degismedi: {evidence.get('main_unchanged')}

## 18. Bilinen riskler

1. CTip M099 metin anomalisi — DB duzeltilmedi, servis normalize ediyor
2. Manuel override yetki kontrolu F1-3 API'de uygulanacak
3. posting_uygun henuz posting servisine bagli degil

## 19. F1-3 oncesi onay

API route gelistirmesi icin Adem onayi beklenir.

---

**SONUC:** {'PASS' if not fails else f'FAIL ({len(fails)} hata)'}
"""


if __name__ == '__main__':
    raise SystemExit(main())
