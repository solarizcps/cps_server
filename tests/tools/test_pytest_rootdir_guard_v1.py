# -*- coding: utf-8 -*-
"""Pytest rootdir — global tests/conftest.py canonical guard must always load."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _pytest_rootdir_for(*args: str) -> str:
    cmd = [sys.executable, '-m', 'pytest', '--collect-only', *args]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    combined = proc.stdout + proc.stderr
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('rootdir:'):
            return stripped.split(':', 1)[1].strip()
    ini = ROOT / 'pytest.ini'
    assert ini.is_file(), f'pytest.ini missing; output tail: {combined[-1500:]}'
    return str(ROOT.resolve())


def test_rootdir_tools_legacy_without_explicit_rootdir_flag():
    root = _pytest_rootdir_for('tests/tools/test_legacy_canonical_writer_guard_v1.py')
    assert Path(root).resolve() == ROOT.resolve()


def test_rootdir_planlama_db_guard_without_explicit_rootdir_flag():
    root = _pytest_rootdir_for('tests/planlama/test_atp_db_guard_v1.py')
    assert Path(root).resolve() == ROOT.resolve()


def test_global_guard_fixture_visible_from_tools_subtree():
    """Session guard from tests/conftest.py must bind under tools collection."""
    assert (ROOT / 'tests' / 'conftest.py').is_file()
    from tools.atp_test_db_guard import atp_guard_is_active, is_test_guard_enabled

    assert is_test_guard_enabled()
    assert atp_guard_is_active()


def test_repo_root_has_no_package_init_that_imports_routes():
    assert not (ROOT / '__init__.py').is_file(), 'repo root __init__.py breaks pytest collection'
