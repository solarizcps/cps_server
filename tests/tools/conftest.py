# -*- coding: utf-8 -*-
"""tests/tools — sys.path + assert parent global canonical guard is active."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = str(Path(__file__).resolve().parents[2] / 'app')
if _APP not in sys.path:
    sys.path.insert(0, _APP)


@pytest.fixture(scope='session', autouse=True)
def _tools_requires_global_canonical_guard(atp_global_db_guard_session):
    """Fail fast if tests/conftest.py session guard did not load (rootdir drift)."""
    assert atp_global_db_guard_session.get('temp_db'), 'global canonical guard session missing'
    return atp_global_db_guard_session
