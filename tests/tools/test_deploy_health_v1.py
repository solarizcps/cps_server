# -*- coding: utf-8 -*-
"""Deploy health readiness probe regression tests."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

WT = Path(__file__).resolve().parents[2]
if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))

from tools import deploy_and_rollback as dar


class TestHttpProbeSemantics:
    def test_health_login_200(self):
        with mock.patch.object(dar, '_http_probe_no_redirect', return_value={'ok': True, 'status': 200, 'error': ''}):
            r = dar.health_check(
                url='http://127.0.0.1:8080/giris',
                _total_timeout_sec=1,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is True
        assert r['status'] == 200

    def test_health_root_302(self):
        with mock.patch.object(
            dar, '_http_probe_no_redirect',
            return_value={'ok': False, 'status': 302, 'error': 'HTTP 302'},
        ):
            r = dar.health_check(
                url='http://127.0.0.1:8080/',
                _total_timeout_sec=1,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is False
        assert r['status'] == 302

    def test_health_404(self):
        with mock.patch.object(
            dar, '_http_probe_no_redirect',
            return_value={'ok': False, 'status': 404, 'error': 'HTTP 404'},
        ):
            r = dar.health_check(_total_timeout_sec=1, _poll_interval_sec=0.01)
        assert r['ok'] is False
        assert r['status'] == 404

    def test_health_500(self):
        with mock.patch.object(
            dar, '_http_probe_no_redirect',
            return_value={'ok': False, 'status': 500, 'error': 'HTTP 500'},
        ):
            r = dar.health_check(_total_timeout_sec=1, _poll_interval_sec=0.01)
        assert r['ok'] is False
        assert r['status'] == 500

    def test_default_health_url_is_giris(self):
        assert dar.health_url(8080).endswith('/giris')


class TestHealthRetryAndGuards:
    def test_delayed_start_eventually_pass(self):
        responses = [
            {'ok': False, 'status': 0, 'error': 'connection refused'},
            {'ok': False, 'status': 0, 'error': 'connection refused'},
            {'ok': True, 'status': 200, 'error': ''},
        ]

        def _probe(url, timeout):
            return responses.pop(0)

        with mock.patch.object(dar, '_http_probe_no_redirect', side_effect=_probe), mock.patch.object(
            dar, '_process_alive', return_value=True,
        ), mock.patch.object(dar, '_port_listening_pids', return_value=['1234']):
            r = dar.health_check(
                expected_pid='1234',
                _total_timeout_sec=5,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is True
        assert r['attempts'] == 3

    def test_timeout_bounded_60s(self):
        with mock.patch.object(
            dar, '_http_probe_no_redirect',
            return_value={'ok': False, 'status': 0, 'error': 'connection refused'},
        ), mock.patch.object(dar, '_process_alive', return_value=True), mock.patch(
            'time.sleep', side_effect=lambda _s: None,
        ) as sleep_mock:
            r = dar.health_check(
                _total_timeout_sec=0.05,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is False
        assert 'timeout' in r['error'].lower()
        assert sleep_mock.call_count >= 1

    def test_early_process_exit(self):
        with mock.patch.object(dar, '_process_alive', return_value=False):
            r = dar.health_check(
                expected_pid='9999',
                stderr_log='',
                stdout_log='',
                _total_timeout_sec=1,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is False
        assert 'exited' in r['error']

    def test_wrong_port_owner(self):
        with mock.patch.object(dar, '_process_alive', return_value=True), mock.patch.object(
            dar, '_port_listening_pids', return_value=['7777'],
        ):
            r = dar.health_check(
                expected_pid='1234',
                port=8080,
                _total_timeout_sec=1,
                _poll_interval_sec=0.01,
            )
        assert r['ok'] is False
        assert 'owned by' in r['error']


class TestDeployHealthIntegration:
    def test_deploy_health_pass(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_stop, COMMIT, COMPUTER, WT as REPO,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest
        import shutil

        td, db = _make_temp_db(apply_190=False)
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        try:
            with mock.patch(
                'tools.deploy_preflight.run_migration_runner',
                side_effect=_planlama_mig_ok,
            ), mock.patch(
                'tools.deploy_and_rollback.run_migration_runner',
                side_effect=_planlama_apply_ok,
            ), mock.patch(
                'tools.deploy_and_rollback.check_parity',
                return_value={'PARITY_RESULT': 'PASS'},
            ), mock.patch(
                'tools.deploy_and_rollback.health_check',
                return_value={'ok': True, 'status': 200, 'url': dar.health_url(8080), 'attempts': 1},
            ):
                r = run_deploy(
                    manifest_path=mp, repo=str(REPO), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_fake_start_ok,
                    _fake_stop=_fake_stop,
                )
            assert r['DEPLOY_RESULT'] == 'PASS'
            assert r['HEALTH_AFTER'] == 'PASS'
            assert '/giris' in r.get('HEALTH_URL', '')
        finally:
            shutil.rmtree(td)

    def test_health_failure_rollback_pass(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_stop, COMMIT, COMPUTER, WT as REPO,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest
        import shutil

        td, db = _make_temp_db(apply_190=False)
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        calls = {'n': 0}

        def _health(**kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                return {'ok': False, 'status': 0, 'error': 'timeout', 'attempts': 3, 'url': dar.health_url(8080)}
            return {'ok': True, 'status': 200, 'attempts': 2, 'url': dar.health_url(8080)}

        try:
            with mock.patch(
                'tools.deploy_preflight.run_migration_runner',
                side_effect=_planlama_mig_ok,
            ), mock.patch(
                'tools.deploy_and_rollback.run_migration_runner',
                side_effect=_planlama_apply_ok,
            ), mock.patch(
                'tools.deploy_and_rollback.check_parity',
                return_value={'PARITY_RESULT': 'PASS'},
            ), mock.patch(
                'tools.deploy_and_rollback.health_check',
                side_effect=lambda **kw: _health(),
            ):
                r = run_deploy(
                    manifest_path=mp, repo=str(REPO), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_fake_start_ok,
                    _fake_stop=_fake_stop,
                )
            assert r['HEALTH_AFTER'] == 'FAIL'
            assert r['HEALTH_ROLLBACK'] == 'PASS'
            assert r.get('ROLLBACK_APPLIED') == 'YES'
        finally:
            shutil.rmtree(td)
