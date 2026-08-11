# -*- coding: utf-8 -*-
"""TEST-DB-ISOLATION-GUARD-01/02 — canonical DB + HTTP write protection lock tests."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from tools.nexgen_tmp_db import (
    CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST,
    LiveDbWriteError,
    bootstrap_canonical_write_guard,
    canonical_db_path,
    connect_sqlite,
    db_fingerprint,
    guard_is_active,
    install_live_db_write_guard,
    tmp_db_context,
    uninstall_live_db_write_guard,
)
from tools.test_db_guard import (
    browser_adhoc_context,
    bootstrap_adhoc_script_guards,
    run_adhoc_with_tmp_db,
    uninstall_all_test_guards,
)
from tools.test_db_http_guard import (
    LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST,
    LiveHttpWriteError,
    install_live_http_write_guard,
    uninstall_live_http_write_guard,
)

CANONICAL_DB = Path(__file__).resolve().parents[2] / 'app' / 'mock_data.db'


class TestDbIsolationGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CANONICAL_DB.exists():
            raise unittest.SkipTest(f'canonical DB missing: {CANONICAL_DB}')
        cls.sha_before = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        cls.live = canonical_db_path(str(CANONICAL_DB))

    @classmethod
    def tearDownClass(cls) -> None:
        uninstall_all_test_guards()
        if CANONICAL_DB.exists():
            sha_after = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
            cls.sha_after = sha_after
            if sha_after != cls.sha_before:
                raise AssertionError(
                    f'canonical DB SHA changed: before={cls.sha_before} after={sha_after}'
                )

    def tearDown(self) -> None:
        uninstall_all_test_guards()

    def test_a_canonical_sqlite_write_blocked(self) -> None:
        install_live_db_write_guard(self.live)
        with self.assertRaises(LiveDbWriteError) as ctx:
            sqlite3.connect(self.live)
        self.assertIn(CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST, str(ctx.exception))
        self.assertIn('attempted_path', str(ctx.exception))

    def test_b_temp_sqlite_write_allowed(self) -> None:
        install_live_db_write_guard(self.live)
        td = tempfile.mkdtemp(prefix='guard_b_')
        try:
            tmp_db = os.path.join(td, 'tmp.db')
            shutil.copy2(str(CANONICAL_DB), tmp_db)
            con = sqlite3.connect(tmp_db)
            con.execute(
                "CREATE TABLE IF NOT EXISTS _guard_probe (id INTEGER PRIMARY KEY, note TEXT)"
            )
            con.execute("INSERT INTO _guard_probe (note) VALUES ('ok')")
            con.commit()
            n = con.execute('SELECT COUNT(*) FROM _guard_probe').fetchone()[0]
            con.close()
            self.assertEqual(int(n), 1)
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_c_canonical_readonly_select_allowed(self) -> None:
        install_live_db_write_guard(self.live)
        con = connect_sqlite(self.live, readonly=True)
        try:
            n = con.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0]
            self.assertGreater(int(n), 0)
        finally:
            con.close()

    def test_d_live_http_write_blocked(self) -> None:
        install_live_http_write_guard(live_port=8080)
        import requests

        with self.assertRaises(LiveHttpWriteError) as ctx:
            requests.post('http://127.0.0.1:8080/nexgen/api/test-guard-probe', json={'x': 1}, timeout=2)
        self.assertIn(LIVE_HTTP_WRITE_FORBIDDEN_IN_TEST, str(ctx.exception))
        self.assertIn('127.0.0.1:8080', str(ctx.exception.url or ctx.exception))

    def test_e_isolated_http_write_allowed_on_temp_db(self) -> None:
        bootstrap_adhoc_script_guards(self.live)
        sha_before = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        with browser_adhoc_context(self.live, prefix='guard_http_e_') as srv:
            import requests

            s = requests.Session()
            r = s.post(
                srv['base_url'] + '/giris',
                data={'kullanici': 'admin', 'sifre': '1453'},
                timeout=15,
            )
            self.assertIn(r.status_code, (200, 302))
            self.assertNotEqual(srv['port'], 8080)
            self.assertTrue(os.path.isfile(srv['tmp_db']))
        sha_after = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        self.assertEqual(sha_after, sha_before)

    def test_f_browser_isolated_server_temp_db(self) -> None:
        fp_before = db_fingerprint(str(CANONICAL_DB))
        with browser_adhoc_context(self.live, prefix='guard_browser_f_') as srv:
            self.assertTrue(srv['tmp_db'].endswith('.db'))
            self.assertNotEqual(
                os.path.normcase(os.path.abspath(srv['tmp_db'])),
                os.path.normcase(os.path.abspath(self.live)),
            )
            self.assertTrue(str(srv['port']) != '8080')
        fp_after = db_fingerprint(str(CANONICAL_DB))
        self.assertEqual(fp_after['sha256'], fp_before['sha256'])

    def test_g_static_zero_risk_audit(self) -> None:
        from tools.test_db_audit import audit_repo

        report = audit_repo()
        self.assertEqual(len(report['sqlite_unguarded_write']), 0)
        self.assertEqual(len(report['http_live8080_write_unguarded']), 0)
        self.assertEqual(len(report['active_write_risk']), 0)

    def test_h_sha_lock(self) -> None:
        sha_now = hashlib.sha256(CANONICAL_DB.read_bytes()).hexdigest()
        self.assertEqual(sha_now, self.sha_before)

    def test_production_context_unaffected(self) -> None:
        self.assertFalse(guard_is_active())
        td = tempfile.mkdtemp(prefix='guard_d_')
        try:
            fake_live = os.path.join(td, 'mock_data.db')
            shutil.copy2(str(CANONICAL_DB), fake_live)
            con = sqlite3.connect(fake_live)
            con.execute(
                "CREATE TABLE IF NOT EXISTS _prod_sim (id INTEGER PRIMARY KEY)"
            )
            con.execute('INSERT INTO _prod_sim DEFAULT VALUES')
            con.commit()
            con.close()
        finally:
            shutil.rmtree(td, ignore_errors=True)
        self.assertFalse(guard_is_active())

    def test_relative_path_bypass_blocked(self) -> None:
        install_live_db_write_guard(self.live)
        app_dir = str(CANONICAL_DB.parent)
        rel = os.path.relpath(str(CANONICAL_DB), app_dir)
        old = os.getcwd()
        try:
            os.chdir(app_dir)
            with self.assertRaises(LiveDbWriteError):
                sqlite3.connect(rel)
        finally:
            os.chdir(old)

    def test_run_adhoc_with_tmp_db_writes(self) -> None:
        with run_adhoc_with_tmp_db(str(CANONICAL_DB), prefix='guard_unit_') as info:
            tmp_db = info['tmp_db']
            self.assertNotEqual(
                os.path.normcase(os.path.abspath(tmp_db)),
                os.path.normcase(os.path.abspath(self.live)),
            )
            con = sqlite3.connect(tmp_db)
            con.execute(
                "CREATE TABLE IF NOT EXISTS _adhoc_probe (id INTEGER PRIMARY KEY)"
            )
            con.execute('INSERT INTO _adhoc_probe DEFAULT VALUES')
            con.commit()
            con.close()
        fp = db_fingerprint(str(CANONICAL_DB))
        self.assertEqual(fp['sha256'], self.sha_before)


if __name__ == '__main__':
    unittest.main()
