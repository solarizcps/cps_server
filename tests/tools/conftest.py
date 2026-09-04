# -*- coding: utf-8 -*-
"""tests/tools — sys.path + release-history route DB isolation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = str(Path(__file__).resolve().parents[2] / "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from release_history_test_db import isolated_route_db, session_canonical_guard  # noqa: E402

pytest_plugins = ("release_history_test_guard",)


def _session_has_route_db_tests(session) -> bool:
    return any(
        "route_db_isolation" in getattr(item, "fixturenames", ())
        for item in session.items
    )


@pytest.fixture(scope="session", autouse=True)
def _release_history_route_session_guard(request):
    if not _session_has_route_db_tests(request.session):
        yield
        return
    with session_canonical_guard():
        yield


@pytest.fixture()
def route_db_isolation():
    """Flask route tests: temp DB copy under CPS_TEST_DB_GUARD (canonical untouched)."""
    with isolated_route_db() as info:
        yield info
