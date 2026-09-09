# -*- coding: utf-8 -*-
"""Deploy server process start — detached / non-blocking regression tests."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

WT = Path(__file__).resolve().parents[2]
if str(WT) not in sys.path:
    sys.path.insert(0, str(WT))

from tools import deploy_and_rollback as dar


class TestDetachedServerStart:
    def test_start_returns_without_waiting(self, tmp_path):
        repo = str(tmp_path / 'repo')
        app_dir = Path(repo) / 'app'
        app_dir.mkdir(parents=True)
        (app_dir / 'app.py').write_text('import time; time.sleep(30)\n', encoding='utf-8')

        fake_proc = mock.Mock()
        fake_proc.pid = 4242
        fake_proc.poll.return_value = None

        t0 = time.monotonic()
        with mock.patch.object(dar, '_popen_detached_server', return_value=fake_proc):
            result = dar.start_process(
                repo=repo, db=str(tmp_path / 'test.db'), port=8080,
                _startup_grace_sec=0.0,
            )
        elapsed = time.monotonic() - t0

        assert result['ok'] is True
        assert result['pid'] == '4242'
        assert elapsed < 0.5

    def test_child_stdout_not_inherited(self, tmp_path):
        repo = str(tmp_path / 'repo')
        stdout_log = str(tmp_path / 'out.log')
        stderr_log = str(tmp_path / 'err.log')
        with mock.patch('tools.deploy_and_rollback.subprocess.Popen') as popen_mock:
            popen_mock.return_value = mock.Mock(pid=111)
            dar._popen_detached_server(
                [sys.executable, 'app.py'],
                cwd=str(tmp_path),
                env={'FLASK_DEBUG': '0'},
                stdout_log=stdout_log,
                stderr_log=stderr_log,
            )
            kwargs = popen_mock.call_args.kwargs
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['stdout'] is not None
        assert kwargs['stdout'] != subprocess.PIPE
        assert kwargs['stderr'] is not None
        assert kwargs['stderr'] != subprocess.PIPE

    def test_child_stderr_not_inherited(self, tmp_path):
        repo = str(tmp_path / 'repo')
        stdout_log = str(tmp_path / 'out.log')
        stderr_log = str(tmp_path / 'err.log')
        with mock.patch('tools.deploy_and_rollback.subprocess.Popen') as popen_mock:
            popen_mock.return_value = mock.Mock(pid=222)
            dar._popen_detached_server(
                [sys.executable, 'app.py'],
                cwd=str(tmp_path),
                env={'FLASK_DEBUG': '0'},
                stdout_log=stdout_log,
                stderr_log=stderr_log,
            )
            kwargs = popen_mock.call_args.kwargs
        assert kwargs['stderr'] is not subprocess.STDOUT
        assert kwargs['stderr'] is not None
        assert kwargs['stdin'] == subprocess.DEVNULL

    def test_child_pid_returned(self, tmp_path):
        repo = str(tmp_path / 'repo')
        Path(repo, 'app').mkdir(parents=True)
        fake_proc = mock.Mock()
        fake_proc.pid = 9876
        fake_proc.poll.return_value = None

        with mock.patch.object(dar, '_popen_detached_server', return_value=fake_proc):
            result = dar.start_process(repo=repo, _startup_grace_sec=0.0)

        assert result['ok'] is True
        assert result['pid'] == '9876'

    def test_early_exit_blocks(self, tmp_path):
        repo = str(tmp_path / 'repo')
        app_dir = Path(repo) / 'app'
        app_dir.mkdir(parents=True)
        (app_dir / 'app.py').write_text('raise SystemExit(1)\n', encoding='utf-8')

        stdout_log, stderr_log = dar._server_log_paths(repo)
        Path(stdout_log).write_text('startup banner\n', encoding='utf-8')
        Path(stderr_log).write_text('fatal error\n', encoding='utf-8')

        fake_proc = mock.Mock()
        fake_proc.pid = 333
        fake_proc.poll.return_value = 1
        fake_proc.returncode = 1

        with mock.patch.object(dar, '_popen_detached_server', return_value=fake_proc):
            result = dar.start_process(repo=repo, _startup_grace_sec=0.05)

        assert result['ok'] is False
        assert 'exited early' in result['error']
        assert 'startup banner' in result['error'] or 'fatal error' in result['error']

    def test_build_server_env_sets_flask_debug_and_db(self):
        env = dar._build_server_env(db_path=r'C:\data\mock_data.db', port=8080)
        assert env['FLASK_DEBUG'] == '0'
        assert env['CPS_PORT'] == '8080'
        assert env['CPS_MOCK_DB_PATH'] == r'C:\data\mock_data.db'


class TestDeployProcessIntegration:
    def test_health_poll_after_start(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_health_ok, _fake_stop, COMMIT, COMPUTER, WT,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest

        td, db = _make_temp_db()
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        call_order: list[str] = []

        def _start(**kwargs):
            call_order.append('start')
            return _fake_start_ok(**kwargs)

        def _health(url):
            call_order.append('health')
            return _fake_health_ok(url)

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
            ):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_start,
                    _fake_health=_health,
                    _fake_stop=_fake_stop,
                )
            assert r['DEPLOY_RESULT'] == 'PASS'
            assert call_order == ['start', 'health']
        finally:
            import shutil
            shutil.rmtree(td)

    def test_single_8080_process_stop_before_start(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_health_ok, COMMIT, COMPUTER, WT,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest

        td, db = _make_temp_db()
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        stopped: list[str] = []
        started: list[str] = []

        def _stop(pid):
            stopped.append(pid)
            return True

        def _start(**kwargs):
            started.append('yes')
            return _fake_start_ok(**kwargs)

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
            ):
                run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=['6820'],
                    _fake_start=_start,
                    _fake_health=_fake_health_ok,
                    _fake_stop=_stop,
                )
            assert stopped == ['6820']
            assert started == ['yes']
        finally:
            import shutil
            shutil.rmtree(td)

    def test_rollback_restart_detached(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_stop, COMMIT, COMPUTER, WT,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest

        td, db = _make_temp_db()
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        start_calls: list[dict] = []

        def _start(**kwargs):
            start_calls.append(kwargs)
            return _fake_start_ok(**kwargs)

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
            ):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_start,
                    _fake_health=lambda url: {'ok': False, 'status': 0},
                    _fake_stop=_fake_stop,
                )
            assert r.get('ROLLBACK_APPLIED') == 'YES'
            assert len(start_calls) == 2
            assert start_calls[0]['db'] == db
            assert start_calls[1]['db'] == db
        finally:
            import shutil
            shutil.rmtree(td)

    def test_old_head_and_db_restored_on_health_fail(self, tmp_path):
        from tests.tools.test_deploy_rollback_v1 import (
            _good_manifest, _make_temp_db, _planlama_apply_ok, _planlama_mig_ok,
            _fake_start_ok, _fake_stop, COMMIT, COMPUTER, WT,
        )
        from tools.deploy_and_rollback import run_deploy
        from tools.release_manifest import save_manifest

        td, db = _make_temp_db()
        mp = str(tmp_path / 'manifest.json')
        save_manifest(_good_manifest(), Path(mp))
        reset_called: list[str] = []
        restore_called: list[tuple[str, str]] = []

        def _reset(repo, commit):
            reset_called.append(commit)
            return True

        def _restore(backup, target):
            restore_called.append((backup, target))
            return True

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
            ), mock.patch.object(dar, 'git_reset_hard', side_effect=_reset), mock.patch.object(
                dar, 'restore_db', side_effect=_restore,
            ):
                r = run_deploy(
                    manifest_path=mp, repo=str(WT), db=db,
                    target_commit=COMMIT, execute=True,
                    confirm_release='r-test-001',
                    expected_computer=COMPUTER,
                    expected_head=COMMIT,
                    skip_process_check=True, _fake_pids=[],
                    _fake_start=_fake_start_ok,
                    _fake_health=lambda url: {'ok': False, 'status': 0},
                    _fake_stop=_fake_stop,
                )
            assert r.get('ROLLBACK_APPLIED') == 'YES'
            assert restore_called
            assert reset_called
        finally:
            import shutil
            shutil.rmtree(td)
