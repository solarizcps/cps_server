# -*- coding: utf-8 -*-
"""ATP GPS History Trail API — read-only regression (temp DB only)."""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
_WORKTREE_CANONICAL_DB = _APP_DIR / 'mock_data.db'
_PLANLAMA_TESTS = Path(__file__).resolve().parent
for _p in (str(_APP_DIR), str(_PLANLAMA_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
)
os.environ['CPS_TEST_DB_GUARD'] = '1'

from tools.atp_test_db_guard import (  # noqa: E402
    bind_temp_db_path,
    guard_stats,
    install_atp_test_db_guard,
    is_canonical_path,
)
from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
    cleanup_tmp,
    connect_sqlite,
    sha256_file,
)

PHASE = 'ATP_GPS_HISTORY_TRAIL_API_UI_IMPLEMENT_V1'
MOR_PLAN_ID = 7
MOR_VEHICLE = '45077045'
MOR_PLATE = '34 MOR 049'


def _assert_worktree_canonical_absent(phase: str) -> None:
    if _WORKTREE_CANONICAL_DB.exists():
        raise AssertionError(
            f'worktree app/mock_data.db must not exist ({phase}); '
            f'path={_WORKTREE_CANONICAL_DB!s}',
        )


def db_counts(db: str) -> dict[str, int]:
    con = connect_sqlite(db, readonly=True)
    try:
        def cnt(t: str) -> int:
            try:
                return int(con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
            except sqlite3.OperationalError:
                return -1
        return {
            'arac_gps_snapshot': cnt('arac_gps_snapshot'),
            'arac_plan_rota_snapshot': cnt('arac_plan_rota_snapshot'),
            'arac_plan_olay': cnt('arac_plan_olay'),
            'arac_gunluk_plan': cnt('arac_gunluk_plan'),
        }
    finally:
        con.close()


def _copy_source_path() -> str:
    """Read-only seed source; never the runtime test DB."""
    source = canonical_db_path()
    if not os.path.isfile(source):
        raise FileNotFoundError(f'GPS test copy source missing: {source}')
    return source


def setup_temp_db() -> tuple[str, str, str]:
    _assert_worktree_canonical_absent('before setup_temp_db')
    source = _copy_source_path()
    install_atp_test_db_guard(source)
    tmp_dir = tempfile.mkdtemp(prefix='atp_gps_trail_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(source, db)
    assert_resolved_db_is_tmp(db, source)
    bind_temp_db_path(db)
    assert not is_canonical_path(db)
    _assert_worktree_canonical_absent('after setup_temp_db')
    return db, source, tmp_dir


def make_client(db: str):
    import config as cfg
    from tools.atp_test_db_guard import resolve_path
    assert resolve_path(cfg.Config.MOCK_DB_PATH) == resolve_path(db)
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    return flask_app.app.test_client()


def mehmet_user(con: sqlite3.Connection) -> dict:
    row = con.execute(
        "SELECT Id,KullaniciAdi,AdSoyad,RolId,Aktif,ZorunluSifreDegistir,AuthVersion FROM sistem_kullanici WHERE Id=31"
    ).fetchone()
    return {
        'Id': row[0], 'KullaniciAdi': row[1], 'AdSoyad': row[2], 'Tip': 'sistem',
        'RolId': row[3], 'Aktif': row[4], 'ZorunluSifreDegistir': int(row[5] or 0),
        'AuthVersion': int(row[6] or 1),
    }


def erhan_user(con: sqlite3.Connection) -> dict:
    row = con.execute(
        "SELECT Id,KullaniciAdi,AdSoyad,RolId,Aktif,ZorunluSifreDegistir,AuthVersion FROM sistem_kullanici WHERE Id=49"
    ).fetchone()
    return {
        'Id': row[0], 'KullaniciAdi': row[1], 'AdSoyad': row[2], 'Tip': 'sistem',
        'RolId': row[3], 'Aktif': row[4], 'ZorunluSifreDegistir': int(row[5] or 0),
        'AuthVersion': int(row[6] or 1),
    }


class AtpPlanGpsTrailTests(unittest.TestCase):
    db: str
    copy_source: str
    tmp_dir: str
    client: object
    db_sha_before: str
    db_counts_before: dict

    @classmethod
    def setUpClass(cls):
        _assert_worktree_canonical_absent('before setUpClass')
        cls.db, cls.copy_source, cls.tmp_dir = setup_temp_db()
        cls.db_sha_before = sha256_file(cls.db)
        cls.db_counts_before = db_counts(cls.db)
        cls.client = make_client(cls.db)
        con = sqlite3.connect(cls.db)
        cls.mehmet = mehmet_user(con)
        cls.erhan = erhan_user(con)
        con.close()

    @classmethod
    def tearDownClass(cls):
        cleanup_tmp({'tmp_dir': cls.tmp_dir})
        _assert_worktree_canonical_absent('after tearDownClass')

    def setUp(self):
        _assert_worktree_canonical_absent('before test')

    def tearDown(self):
        _assert_worktree_canonical_absent('after test')

    def _login(self, user: dict):
        with self.client.session_transaction() as sess:
            sess['kullanici'] = user
            sess['kullanici_tip'] = 'sistem'

    def test_T1_mor_plan_trail_200(self):
        self._login(self.mehmet)
        r = self.client.get(f'/planlama/arac-takip/api/plan-gps-trail?plan_id={MOR_PLAN_ID}')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d['ok'])
        self.assertEqual(d['plate'], MOR_PLATE)
        pts = d['gps_points']
        self.assertGreater(len(pts), 0)
        ts = [p['timestamp'] for p in pts]
        self.assertEqual(ts, sorted(ts))

    def test_T2_route_and_gps_together(self):
        self._login(self.mehmet)
        d = self.client.get(f'/planlama/arac-takip/api/plan-gps-trail?plan_id={MOR_PLAN_ID}').get_json()
        self.assertIn(d['route_geometry'].get('type'), ('LineString', 'MultiLineString'))
        self.assertGreater(len(d['gps_points']), 0)

    def test_T3_gap_segments(self):
        from modules.planlama.arac_plan_gps_trail_service import get_plan_gps_trail
        d = get_plan_gps_trail(MOR_PLAN_ID)
        for g in d.get('gap_segments') or []:
            self.assertGreater(g.get('gap_seconds', 0), 180)

    def test_T4_stale_invalid_handling(self):
        from modules.planlama.arac_plan_gps_trail_service import get_plan_gps_trail
        d = get_plan_gps_trail(MOR_PLAN_ID)
        for p in d['gps_points']:
            self.assertIsInstance(p['latitude'], (int, float))
            self.assertIsInstance(p['longitude'], (int, float))
            self.assertIn('is_stale', p)

    def test_T5_empty_gps_plan_200(self):
        self._login(self.mehmet)
        con = sqlite3.connect(self.db)
        row = con.execute(
            "SELECT id FROM arac_gunluk_plan WHERE arac_external_id='991001' LIMIT 1"
        ).fetchone()
        con.close()
        if not row:
            self.skipTest('no fixture plan without gps')
        r = self.client.get(f'/planlama/arac-takip/api/plan-gps-trail?plan_id={row[0]}')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertFalse(d.get('has_gps_history'))
        self.assertEqual(d.get('empty_code'), 'NO_GPS_HISTORY')

    def test_T6_missing_plan_404(self):
        self._login(self.mehmet)
        r = self.client.get('/planlama/arac-takip/api/plan-gps-trail?plan_id=999999991')
        self.assertEqual(r.status_code, 404)

    def test_T7_unauthorized_403(self):
        self._login(self.erhan)
        r = self.client.get(f'/planlama/arac-takip/api/plan-gps-trail?plan_id={MOR_PLAN_ID}')
        self.assertEqual(r.status_code, 403)

    def test_T8_db_unchanged_after_api(self):
        """Read-only API calls must not mutate the bound temp DB."""
        sha_mid = sha256_file(self.db)
        counts_mid = db_counts(self.db)
        self._login(self.mehmet)
        self.client.get(f'/planlama/arac-takip/api/plan-gps-trail?plan_id={MOR_PLAN_ID}')
        self.client.get('/planlama/arac-takip/api/history-plans?limit=5')
        self.assertEqual(sha_mid, sha256_file(self.db))
        self.assertEqual(counts_mid, db_counts(self.db))
        self.assertEqual(self.db_sha_before, sha256_file(self.db))
        self.assertEqual(self.db_counts_before, db_counts(self.db))
        stats = guard_stats()
        self.assertEqual(stats.get('blocked_connects', 0), 0)

    def test_T9_history_plans_api(self):
        self._login(self.mehmet)
        r = self.client.get('/planlama/arac-takip/api/history-plans?limit=20')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d['ok'])
        self.assertGreaterEqual(d['count'], 1)
        mor = [x for x in d['rows'] if x.get('vehicle_external_id') == MOR_VEHICLE]
        if mor:
            self.assertIn('has_gps_history', mor[0])

    def test_T15_route_realization_regression(self):
        from modules.planlama.arac_route_realization_service import compute_route_realization_from_db
        dto = compute_route_realization_from_db(
            MOR_PLAN_ID, MOR_VEHICLE, '2026-08-24', db_path=self.db,
        )
        self.assertEqual(dto.plan_id, MOR_PLAN_ID)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AtpPlanGpsTrailTests)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        'phase': PHASE,
        'tests_run': res.testsRun,
        'failures': len(res.failures),
        'errors': len(res.errors),
        'pass': res.wasSuccessful(),
    }
    out = os.path.join(os.path.dirname(__file__), '..', '..', '_audit_out', 'atp_plan_gps_trail_v1_results.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)
    raise SystemExit(0 if res.wasSuccessful() else 1)
