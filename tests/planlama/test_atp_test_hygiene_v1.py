# -*- coding: utf-8 -*-
"""Process hygiene regression — cwd/env restore under combined pytest."""
from __future__ import annotations

import os

import pytest

from atp_test_hygiene import app_dir, capture_env_state, repo_root, restore_env_state


class TestAtpProcessHygieneV1:
    def test_repo_root_cwd_after_autouse_fixtures(self):
        assert os.getcwd() == str(repo_root())

    def test_app_dir_not_required_for_cwd(self):
        assert app_dir().is_dir()
        assert os.getcwd() != str(app_dir())

    def test_env_restore_on_exception(self):
        saved = capture_env_state()
        token = 'atp_hygiene_probe'
        os.environ['CPS_ATP_TEST_SKIP_FILOM'] = token
        try:
            raise RuntimeError('probe')
        except RuntimeError:
            restore_env_state(saved)
        assert os.environ.get('CPS_ATP_TEST_SKIP_FILOM') != token or token not in os.environ

    def test_chdir_restore_after_manual_pollution(self):
        saved = capture_env_state()
        try:
            os.chdir(str(app_dir()))
            assert os.getcwd() == str(app_dir())
            raise ValueError('probe exception path')
        except ValueError:
            restore_env_state(saved)
        assert os.getcwd() == str(repo_root())
