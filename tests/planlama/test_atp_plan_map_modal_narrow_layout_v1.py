# -*- coding: utf-8 -*-
"""Fullscreen plan map modal — stop list layout CSS (portaled outside #atpV2Root)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8')


def _block(selector: str) -> str:
    idx = CSS.find(selector)
    assert idx != -1, f'missing selector: {selector}'
    brace = CSS.find('{', idx)
    depth = 0
    for i in range(brace, len(CSS)):
        if CSS[i] == '{':
            depth += 1
        elif CSS[i] == '}':
            depth -= 1
            if depth == 0:
                return CSS[idx : i + 1]
    raise AssertionError(f'unclosed block: {selector}')


def test_modal_dialog_scoped_palette_and_typography():
    block = _block('#atpPlanMapModalDialog.atp-plan-map-modal-dialog {')
    for token in ('--gold:', '--green:', '--border:', 'font-family:', 'font-size:13px'):
        assert token in block


def test_modal_stops_grid_column_and_min_width():
    stops = _block('#atpPlanMapModalDialog .atp-plan-map-modal-stops {')
    assert 'grid-column:1' in stops.replace(' ', '')
    assert 'min-width:220px' in stops.replace(' ', '')


def test_modal_map_col_grid_column_two():
    col = _block('#atpPlanMapModalDialog .atp-plan-map-modal-map-col {')
    assert 'grid-column:2' in col.replace(' ', '')


def test_modal_stop_list_flex_parity_outside_v2_root():
    lst = _block('#atpPlanMapModalDialog .atp-plan-map-modal-stops-list .stop-list {')
    compact = lst.replace(' ', '').replace('\n', '')
    assert 'display:flex' in compact
    assert 'flex-direction:column' in compact
    item = _block('#atpPlanMapModalDialog .atp-plan-map-modal-stops-list .stop-item {')
    assert 'display:flex' in item.replace(' ', '')
    assert 'var(--gray-50)' in item


def test_modal_leaflet_contained_in_map_col():
    leaf = _block('#atpPlanMapModalDialog #atpPlanLeafletMap,')
    assert 'max-width:100%' in leaf.replace(' ', '')
    assert 'z-index:1' in leaf.replace(' ', '')


def test_modal_narrow_viewport_stacked_grid():
    body = _block('#atpPlanMapModalDialog .atp-plan-map-modal-body {')
    assert '@media (max-width:768px)' in CSS
    idx = CSS.find('@media (max-width:768px)')
    tail = CSS[idx:]
    assert '#atpPlanMapModalDialog .atp-plan-map-modal-body' in tail
    narrow_body = tail.split('#atpPlanMapModalDialog .atp-plan-map-modal-body {', 1)[1]
    narrow_body = narrow_body.split('}', 1)[0]
    compact = narrow_body.replace(' ', '')
    assert 'grid-template-columns:1fr' in compact
    assert 'grid-template-rows:minmax(120px,34%)' in compact
    assert 'grid-template-columns:minmax(220px,34%)' in body.replace(' ', '')
