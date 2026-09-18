# -*- coding: utf-8 -*-
"""Header MOCK badge visibility vs runtime env (UI only; db.py unchanged)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from runtime_mock_badge import compute_show_mock_badge  # noqa: E402


def _canonical_env() -> dict[str, str]:
    return {'CPS_MOCK_DB_PATH': '', 'CPS_TEST_DB_GUARD': ''}


def test_production_canonical_env_hides_mock_badge():
    assert compute_show_mock_badge(_canonical_env()) is False


def test_cps_mock_db_path_shows_mock_badge():
    env = {'CPS_MOCK_DB_PATH': r'C:\Temp\pytest_mock.db', 'CPS_TEST_DB_GUARD': ''}
    assert compute_show_mock_badge(env) is True


def test_cps_test_db_guard_shows_mock_badge():
    env = {'CPS_MOCK_DB_PATH': '', 'CPS_TEST_DB_GUARD': '1'}
    assert compute_show_mock_badge(env) is True


@pytest.mark.parametrize(
    'guard_val',
    ['', '0', 'false', 'False', 'off', 'no'],
)
def test_guard_passive_values_hide_mock_badge(guard_val: str):
    env = {'CPS_MOCK_DB_PATH': '', 'CPS_TEST_DB_GUARD': guard_val}
    assert compute_show_mock_badge(env) is False


def test_base_template_only_mock_pill_when_show_mock_badge():
    html = (ROOT / 'app' / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'SHOW_MOCK_BADGE' in html
    assert "{% if SHOW_MOCK_BADGE %}" in html
    assert 'db-pill prod' not in html
    mock_block_start = html.index('{% if SHOW_MOCK_BADGE %}')
    mock_block_end = html.index('{% endif %}', mock_block_start)
    block = html[mock_block_start:mock_block_end]
    assert 'DB_MODE' not in block
    assert 'db-pill mock' in block


def _header_shell_html(monkeypatch: pytest.MonkeyPatch) -> str:
    """Render base.html shell (login page does not extend base)."""
    monkeypatch.delenv('CPS_MOCK_DB_PATH', raising=False)
    import app as cps_app  # noqa: WPS433 — app/app.py
    from flask import render_template_string

    tpl = (
        '{% extends "base.html" %}'
        '{% block title %}Mock badge probe{% endblock %}'
        '{% block content %}{% endblock %}'
    )
    with cps_app.app.test_request_context('/'):
        return render_template_string(tpl)


def test_canonical_html_has_no_environment_pills(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '')
    html = _header_shell_html(monkeypatch)
    assert 'db-pill mock' not in html
    assert 'db-pill prod' not in html
    assert '<span class="db-pill mock">MOCK</span>' not in html


def test_temp_html_shows_mock_pill(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('CPS_MOCK_DB_PATH', str(ROOT / '_preview_temp_mock.db'))
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')
    html = _header_shell_html(monkeypatch)
    assert 'db-pill mock' in html
    assert '<span class="db-pill mock">MOCK</span>' in html
    assert 'db-pill prod' not in html
