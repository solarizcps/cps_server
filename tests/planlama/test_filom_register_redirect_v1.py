# -*- coding: utf-8 -*-
"""Filom register redirect / base URL normalization — worker vs web shared adapter."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'app')


def _resolve_canonical_db() -> str | None:
    """Read-only canonical path — env first, then repo app/mock_data.db; never copy."""
    env_path = os.environ.get('CPS_CANONICAL_DB_SOURCE', '').strip()
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)
    repo_path = os.path.join(APP, 'mock_data.db')
    if os.path.isfile(repo_path):
        return os.path.abspath(repo_path)
    return None


CANONICAL_DB = _resolve_canonical_db()
sys.path.insert(0, APP)
os.chdir(APP)

ADP = 'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter'


def _import_adapter():
    mod = importlib.import_module(ADP)
    importlib.reload(mod)
    mod._cache.clear()
    return mod


def _ok_register_response(token: str = 'mock-token'):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'token': token}
    return resp


def _redirect_response(location: str, code: int = 301):
    resp = MagicMock()
    resp.status_code = code
    resp.headers = {'Location': location}
    return resp


@contextmanager
def _filom_env(base_url: str):
    with patch.dict(os.environ, {
        'TURKCELL_FILOM_BASE_URL': base_url,
        'TURKCELL_FILOM_USERNAME': 'svc-user',
        'TURKCELL_FILOM_PASSWORD': 'svc-secret',
    }, clear=False):
        yield


class TestNormalizeFilomBaseUrl(unittest.TestCase):
    def test_http_upgraded_to_https(self):
        adp = _import_adapter()
        self.assertEqual(
            adp._normalize_filom_base_url('http://filom.test/mobilws/services'),
            'https://filom.test/mobilws/services',
        )

    def test_strip_register_suffix(self):
        adp = _import_adapter()
        self.assertEqual(
            adp._normalize_filom_base_url(
                'https://filom.test/mobilws/services/register',
            ),
            'https://filom.test/mobilws/services',
        )

    def test_strip_trailing_slash(self):
        adp = _import_adapter()
        self.assertEqual(
            adp._normalize_filom_base_url(
                'https://filom.test/mobilws/services/',
            ),
            'https://filom.test/mobilws/services',
        )


class TestRegisterRedirectBehavior(unittest.TestCase):
    def tearDown(self):
        adp = importlib.import_module(ADP)
        adp._cache.clear()

    @patch(f'{ADP}.requests.post')
    def test_register_uses_https_without_redirect_chain(self, mock_post):
        adp = _import_adapter()
        mock_post.return_value = _ok_register_response()
        with _filom_env('http://filom.test/mobilws/services/register'):
            token = adp.authenticate(force=True)
        self.assertEqual(token, 'mock-token')
        self.assertEqual(mock_post.call_count, 1)
        url = mock_post.call_args[0][0]
        self.assertEqual(url, 'https://filom.test/mobilws/services/register')
        self.assertIs(mock_post.call_args[1].get('allow_redirects'), False)

    @patch(f'{ADP}.requests.post')
    def test_redirect_chain_repro_without_normalization(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.TooManyRedirects(
            response=MagicMock(status_code=302),
        )
        with self.assertRaises(requests.exceptions.TooManyRedirects):
            requests.post(
                'http://filom.test/mobilws/services/register',
                params={'language': 'tr'},
                headers={'username': 'u', 'password': 'p'},
                allow_redirects=True,
            )

    @patch(f'{ADP}.requests.post')
    def test_same_host_redirect_followed_once(self, mock_post):
        adp = _import_adapter()
        mock_post.side_effect = [
            _redirect_response('https://filom.test/mobilws/services/register'),
            _ok_register_response('tok2'),
        ]
        with _filom_env('https://filom.test/mobilws/services'):
            token = adp.authenticate(force=True)
        self.assertEqual(token, 'tok2')
        self.assertEqual(mock_post.call_count, 2)

    @patch(f'{ADP}.requests.post')
    def test_cross_host_redirect_blocked_no_credential_forward(self, mock_post):
        adp = _import_adapter()
        mock_post.return_value = _redirect_response('https://evil.example/register')
        with _filom_env('https://filom.test/mobilws/services'):
            with self.assertRaises(adp.FilomApiError) as ctx:
                adp.authenticate(force=True)
        self.assertIn('cross-host', str(ctx.exception).lower())
        self.assertEqual(mock_post.call_count, 1)


class TestPollOnceWithMockFilom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical_db = CANONICAL_DB
        if not cls.canonical_db:
            raise RuntimeError(
                'Canonical DB not found for read-only fixture check. '
                'Set CPS_CANONICAL_DB_SOURCE to a readable mock_data.db path, '
                f'or place mock_data.db at {os.path.join(APP, "mock_data.db")}.',
            )
        cls.canonical_sha = hashlib.sha256(open(cls.canonical_db, 'rb').read()).hexdigest()

    def _run_migration(self, db_path: str, filename: str) -> None:
        spec = importlib.util.spec_from_file_location(
            filename, os.path.join(APP, 'migrations', filename),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(db_path)

    @contextmanager
    def _temp_gps_db(self):
        import shutil
        td = tempfile.mkdtemp(prefix='filom_redirect_fix_')
        db = os.path.join(td, 'test.db')
        for mig in (
            '176_arac_takip_v13.py',
            '177_arac_operasyon_ayar.py',
            '178_arac_is_talebi_ux_v2_fields.py',
            '179_arac_gps_snapshot_p1.py',
        ):
            self._run_migration(db, mig)
        import config
        with patch.object(config.Config, 'MOCK_DB_PATH', db):
            yield db

    def test_poll_once_insert_and_dedup(self):
        with self._temp_gps_db():
            from modules.planlama import arac_gps_poll_service as poll_mod
            importlib.reload(poll_mod)

            ts = '2026-09-07 10:00:00'
            vehicle = {
                'id': '45077045',
                'plate': '34MOR049',
                'plate_display': '34 MOR 049',
                'latitude': 41.0,
                'longitude': 29.0,
                'has_valid_location': True,
                'last_seen_at': ts,
                'is_stale_data': False,
                'speed_kmh': 40,
                'activity_status': 'HAREKETLI',
                'ignition': 'Açık',
                'total_distance_km': 100.0,
            }
            fetcher = lambda: {'ok': True, 'vehicles': [vehicle]}
            now = datetime(2026, 9, 7, 10, 1, 0)
            r1 = poll_mod.poll_once(fetcher, now=now)
            r2 = poll_mod.poll_once(fetcher, now=now)
            self.assertTrue(r1['ok'], r1)
            self.assertGreater(r1['inserted'], 0)
            self.assertEqual(r2['skipped_dedup'], 1)
            self.assertEqual(r2['inserted'], 0)

    def test_canonical_db_unchanged(self):
        after = hashlib.sha256(open(self.canonical_db, 'rb').read()).hexdigest()
        self.assertEqual(after, self.canonical_sha)


class TestCredentialNotLogged(unittest.TestCase):
    @patch(f'{ADP}.requests.post')
    def test_log_call_does_not_include_secrets(self, mock_post):
        adp = _import_adapter()
        mock_post.return_value = _ok_register_response()
        with _filom_env('https://filom.test/mobilws/services'):
            with self.assertLogs('cps.filom', level='INFO') as logs:
                adp.authenticate(force=True)
            joined = '\n'.join(logs.output)
            self.assertNotIn('svc-secret', joined)
            self.assertNotIn('svc-user', joined)


if __name__ == '__main__':
    unittest.main()
