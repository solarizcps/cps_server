# -*- coding: utf-8 -*-
"""OET V2 non-blocking Yenile + poll/refresh dedup + runtime guard regression."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import unittest
from unittest.mock import patch

APP = os.path.join(os.path.dirname(__file__), '..', 'app')
ROOT = os.path.abspath(os.path.join(APP, '..'))
sys.path.insert(0, os.path.abspath(APP))
os.chdir(os.path.abspath(APP))
os.environ.setdefault('API_MODE', 'mock')
os.environ.setdefault('API_WRITE_ENABLED', 'false')

INDEX_HTML = os.path.join(APP, 'templates', 'online_eticaret', 'index.html')
ROUTES_PY = os.path.join(APP, 'modules', 'online_eticaret', 'routes.py')
ORDER_POLL_PY = os.path.join(APP, 'modules', 'online_eticaret', 'order_poll.py')
START_PS1 = os.path.join(ROOT, '_start_8080_clean.ps1')


class TestNonblockingRefreshTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = open(INDEX_HTML, encoding='utf-8').read()

    def test_yenile_is_button_not_nav_link(self):
        self.assertIn('id="oet-btn-yenile"', self.html)
        self.assertNotRegex(
            self.html,
            r'<a[^>]+class="btn-yenile"[^>]+href="\?days=[^"]*&refresh=1',
        )

    def test_manual_refresh_dedup_flag(self):
        self.assertIn('manualRefreshInFlight', self.html)
        self.assertIn('Güncelleniyor', self.html)

    def test_fetch_refresh_get_only(self):
        self.assertIn("method: 'GET'", self.html)
        self.assertIn("refresh', '1'", self.html)
        self.assertNotIn('method: \'POST\'', self.html.split('runManualRefresh')[1][:1200])

    def test_poll_skips_during_manual_refresh(self):
        block = self.html.split('function runOrderPoll')[1][:600]
        self.assertIn('manualRefreshInFlight', block)

    def test_data_preserved_on_error_toast(self):
        self.assertIn('mevcut veri korundu', self.html)

    def test_oet_refresh_export(self):
        self.assertIn('__OET_REFRESH__', self.html)
        self.assertIn('nonblocking: true', self.html)


class TestScopeLiveFetchDedup(unittest.TestCase):
    def setUp(self):
        import modules.online_eticaret.order_poll as poll

        with poll._POLL_LOCK:
            poll._POLL_IN_FLIGHT = False
            poll._SCOPE_LIVE_FETCH = None
        self.poll = poll

    def test_double_begin_blocked(self):
        self.assertTrue(self.poll.try_begin_scope_live_fetch('open'))
        self.assertFalse(self.poll.try_begin_scope_live_fetch('open'))
        self.poll.end_scope_live_fetch('open')

    def test_poll_busy_while_scope_held(self):
        self.assertTrue(self.poll.try_begin_scope_live_fetch('today'))
        result = self.poll.check_order_updates(
            'today',
            None,
            lambda o, s, m: [],
            lambda r, i, p=None: [],
            lambda df: (0, 1),
        )
        self.assertTrue(result.get('busy'))
        self.poll.end_scope_live_fetch('today')

    def test_open_today_scope_not_shared(self):
        self.assertTrue(self.poll.try_begin_scope_live_fetch('open'))
        self.assertFalse(self.poll.try_begin_scope_live_fetch('today'))
        self.poll.end_scope_live_fetch('open')


class TestRuntimeGuard(unittest.TestCase):
    def test_startup_script_strips_mock_db_path(self):
        text = open(START_PS1, encoding='utf-8').read()
        self.assertIn('CPS_MOCK_DB_PATH', text)
        self.assertIn('Remove-Item', text)
        self.assertIn('cps_startup_env', text)

    def test_child_env_still_allows_tests_with_mock_db(self):
        from tools.cps_startup_env import child_env_from_parent

        parent = dict(os.environ)
        parent['CPS_MOCK_DB_PATH'] = r'C:\Temp\isolated_test.db'
        child = child_env_from_parent(parent)
        self.assertNotIn('CPS_MOCK_DB_PATH', child)


class TestRoutesStillGetOnly(unittest.TestCase):
    def test_no_write_methods(self):
        src = open(ROUTES_PY, encoding='utf-8').read()
        self.assertEqual(len(re.findall(r"methods=\[.*?(POST|PUT|PATCH|DELETE)", src, re.I)), 0)

    def test_scope_live_fetch_import(self):
        src = open(ROUTES_PY, encoding='utf-8').read()
        self.assertIn('try_begin_scope_live_fetch', src)
        self.assertIn('end_scope_live_fetch', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
