# -*- coding: utf-8 -*-
"""ATP canonical DB write guard regression tests (T1–T5B)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tools.atp_test_db_guard import (  # noqa: E402
    atp_guard_is_active,
    bind_temp_db_path,
    install_atp_test_db_guard,
    is_canonical_path,
    is_test_guard_enabled,
    resolve_path,
    uninstall_atp_test_db_guard,
)
from tools.nexgen_tmp_db import (  # noqa: E402
    CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST,
    LiveDbWriteError,
    canonical_db_path,
)


def _windows_case_variant(canonical: str) -> str:
    """Return a mixed-case path string that still resolves to canonical on Windows."""
    dirname, basename = os.path.split(canonical)
    if not any(c.isalpha() for c in basename):
        raise ValueError(f'No swappable letters in canonical basename: {basename!r}')
    swapped_base = ''.join(
        c.upper() if c.islower() else c.lower() if c.isupper() else c for c in basename
    )
    variant = os.path.join(dirname, swapped_base)
    if variant == canonical:
        raise ValueError(f'Case variant identical to canonical: {canonical!r}')
    return variant


@pytest.fixture(autouse=True)
def _restore_session_guard_after_test():
    """Session conftest installs guard — restore if an individual test disables it."""
    yield
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    install_atp_test_db_guard()


@pytest.fixture
def canonical_path():
    return canonical_db_path()


@pytest.fixture
def temp_db_file():
    temp_dir = tempfile.mkdtemp(prefix='atp_guard_case_')
    temp_db = os.path.join(temp_dir, 'temp.db')
    sqlite3.connect(temp_db).close()
    try:
        yield temp_db
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestAtpDbGuardRegression:
    def test_t1_test_mode_canonical_rw_block(self, canonical_path):
        assert is_test_guard_enabled()
        assert atp_guard_is_active()
        with pytest.raises(LiveDbWriteError) as exc:
            sqlite3.connect(canonical_path)
        assert CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST in str(exc.value)

    def test_t2_test_mode_temp_rw_pass(self, temp_db_file):
        con = sqlite3.connect(temp_db_file)
        con.execute('CREATE TABLE IF NOT EXISTS _probe (id INTEGER PRIMARY KEY)')
        con.execute('INSERT INTO _probe DEFAULT VALUES')
        con.commit()
        n = con.execute('SELECT COUNT(*) FROM _probe').fetchone()[0]
        con.close()
        assert n == 1

    def test_t3_normal_mode_not_blocked(self, canonical_path):
        uninstall_atp_test_db_guard()
        os.environ.pop('CPS_TEST_DB_GUARD', None)
        try:
            import config
            import db

            orig = config.Config.MOCK_DB_PATH
            try:
                config.Config.MOCK_DB_PATH = canonical_path
                assert is_test_guard_enabled() is False
                assert not atp_guard_is_active()
                mem = sqlite3.connect(':memory:')
                with patch('db.sqlite3.connect', return_value=mem) as mock_connect:
                    conn = db.get_conn()
                    conn.close()
                mock_connect.assert_called_once_with(canonical_path, timeout=15)
            finally:
                config.Config.MOCK_DB_PATH = orig
        finally:
            os.environ['CPS_TEST_DB_GUARD'] = '1'
            install_atp_test_db_guard()

    def test_t4_canonical_copy2_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            shutil.copy2(temp_db_file, canonical_path)

    def test_t4_canonical_copy_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            shutil.copy(temp_db_file, canonical_path)

    def test_t4_canonical_copyfile_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            shutil.copyfile(temp_db_file, canonical_path)

    def test_t5_canonical_os_replace_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            os.replace(temp_db_file, canonical_path)

    def test_t5_canonical_os_rename_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            os.rename(temp_db_file, canonical_path)

    def test_t5_canonical_path_rename_block(self, canonical_path, temp_db_file):
        with pytest.raises(LiveDbWriteError):
            Path(temp_db_file).rename(canonical_path)

    def test_t5_canonical_path_replace_block(self, canonical_path, temp_db_file):
        if not hasattr(Path, 'replace'):
            pytest.skip('Path.replace not available on this platform')
        with pytest.raises(LiveDbWriteError):
            Path(temp_db_file).replace(canonical_path)

    def test_t5b_canonical_source_to_temp_copy_pass(self, canonical_path, temp_db_file):
        shutil.copy2(canonical_path, temp_db_file)
        assert os.path.getsize(temp_db_file) > 0
        con = sqlite3.connect(temp_db_file)
        ic = con.execute('PRAGMA integrity_check').fetchone()[0]
        con.close()
        assert ic == 'ok'

    @pytest.mark.parametrize(
        'candidate',
        [
            'app/mock_data.db',
            'app\\mock_data.db',
            './app/mock_data.db',
        ],
    )
    def test_path_bypass_variants_block_rw(self, candidate, canonical_path):
        rel = str(ROOT / candidate)
        assert is_canonical_path(rel)
        with pytest.raises(LiveDbWriteError):
            sqlite3.connect(rel)

    def test_db_get_conn_blocks_canonical_in_test_mode(self, canonical_path):
        import config
        import db

        orig = config.Config.MOCK_DB_PATH
        try:
            config.Config.MOCK_DB_PATH = canonical_path
            with pytest.raises(RuntimeError) as exc:
                db.get_conn()
            assert CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST in str(exc.value)
        finally:
            config.Config.MOCK_DB_PATH = orig

    def test_bind_temp_db_rejects_canonical(self, canonical_path):
        with pytest.raises(LiveDbWriteError):
            bind_temp_db_path(canonical_path)

    def test_resolve_path_normcase(self, canonical_path):
        assert resolve_path(canonical_path) == resolve_path(str(APP / 'mock_data.db'))

    def test_case_normalization_bypass_block_rw(self, canonical_path):
        if os.name != 'nt':
            pytest.skip('Windows case-insensitive filesystem required for case bypass test')
        case_variant = _windows_case_variant(canonical_path)
        assert case_variant != canonical_path
        assert resolve_path(case_variant) == resolve_path(canonical_path)
        assert is_canonical_path(case_variant)
        with pytest.raises(LiveDbWriteError) as exc:
            sqlite3.connect(case_variant)
        assert CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST in str(exc.value)
