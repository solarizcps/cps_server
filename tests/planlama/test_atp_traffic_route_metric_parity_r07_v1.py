# -*- coding: utf-8 -*-
"""R07 — traffic proposal metric parity (single UI source)."""
from __future__ import annotations

from modules.planlama.arac_traffic_route_proposal_service import (
    _attach_proposal_metric_labels,
    _format_time_delta_label,
    sync_route_dto_metrics_from_traffic_proposal,
)


def _proposal_from_totals(cur_tot: dict, sug_tot: dict, **extra) -> dict:
    time_saved = None
    if cur_tot.get('total_duration_seconds') is not None and sug_tot.get('total_duration_seconds') is not None:
        time_saved = round(
            float(cur_tot['total_duration_seconds']) - float(sug_tot['total_duration_seconds']), 1,
        )
    base = {
        'provider': 'google_traffic',
        'time_saved_seconds': time_saved,
        'current_total_duration_seconds': cur_tot.get('total_duration_seconds'),
        'suggested_total_duration_seconds': sug_tot.get('total_duration_seconds'),
        **extra,
    }
    return _attach_proposal_metric_labels(base, cur_tot, sug_tot)


def test_longer_km_shorter_time_labels():
    cur = {'total_duration_seconds': 300.0, 'total_distance_meters': 90000.0}
    sug = {'total_duration_seconds': 240.0, 'total_distance_meters': 105200.0}
    p = _proposal_from_totals(cur, sug, proposal_reason='TRAFFIC_IMPROVEMENT', apply_enabled=True)
    assert p['distance_delta_label'] == '15,2 km daha uzun'
    assert p['time_delta_label'] == '1 dk kazanç'
    assert 'daha uzun' in p['comparison_label']
    assert 'daha hızlı' in p['comparison_label']
    assert 'daha kısa' not in p['comparison_label']


def test_both_distance_and_time_improve():
    cur = {'total_duration_seconds': 3600.0, 'total_distance_meters': 100000.0}
    sug = {'total_duration_seconds': 3420.0, 'total_distance_meters': 97500.0}
    p = _proposal_from_totals(cur, sug)
    assert p['distance_delta_label'] == '2,5 km daha kısa'
    assert p['time_delta_label'] == '3 dk kazanç'
    assert 'daha kısa' in p['comparison_label']
    assert 'daha hızlı' in p['comparison_label']


def test_no_improvement_zero_labels():
    cur = {'total_duration_seconds': 600.0, 'total_distance_meters': 50000.0}
    sug = {'total_duration_seconds': 600.0, 'total_distance_meters': 50000.0}
    p = _proposal_from_totals(
        cur, sug, proposal_reason='NO_IMPROVEMENT', apply_enabled=False, time_saved_seconds=0.0,
    )
    assert p['time_delta_label'] == '0 sn'
    assert p['distance_delta_label'] == '0 km'
    assert p['comparison_label'] == '—'


def test_sub_minute_time_saved_shows_seconds():
    cur = {'total_duration_seconds': 200.0, 'total_distance_meters': 90000.0}
    sug = {'total_duration_seconds': 158.0, 'total_distance_meters': 91000.0}
    p = _proposal_from_totals(cur, sug)
    assert _format_time_delta_label(42.0) == '42 sn kazanç'
    assert p['time_delta_label'] == '42 sn kazanç'
    assert p['traffic_compare_label'].endswith('42 sn kazanç')


def test_sync_overwrites_stale_ors_route_dto():
    stale = {
        'current': {'km': 90.1, 'duration_label': '2 sa 5 dk'},
        'suggested': {'km': 88.0, 'duration_label': '1 sa 50 dk'},
        'gain': {'km': 2.1, 'duration_label': '15 dk', 'pct': 2.3},
    }
    cur = {'total_duration_seconds': 10860.0, 'total_distance_meters': 90100.0}
    sug = {'total_duration_seconds': 10818.0, 'total_distance_meters': 105200.0}
    tp = _proposal_from_totals(cur, sug, changed=True, apply_enabled=True)
    synced = sync_route_dto_metrics_from_traffic_proposal(dict(stale), tp)
    assert synced['metrics_source'] == 'traffic_proposal'
    assert synced['current']['km'] == 90.1
    assert synced['suggested']['km'] == 105.2
    assert synced['current']['duration_label'] == tp['current_duration_label']
    assert synced['suggested']['duration_label'] == tp['suggested_duration_label']
    assert synced['gain']['comparison_label'] == tp['comparison_label']
    assert synced['gain']['pct'] is None
    assert synced['gain']['time_delta_label'] == tp['time_delta_label']
    assert synced['current']['duration_label'] == tp['current_duration_label']


def test_top_card_and_panel_share_same_proposal_labels():
    cur = {'total_duration_seconds': 10860.0, 'total_distance_meters': 90100.0}
    sug = {'total_duration_seconds': 10818.0, 'total_distance_meters': 105200.0}
    tp = _proposal_from_totals(cur, sug)
    route = sync_route_dto_metrics_from_traffic_proposal({'current': {}, 'suggested': {}, 'gain': {}}, tp)
    route['traffic_proposal'] = tp
    assert route['current']['duration_label'] == tp['current_duration_label']
    assert route['suggested']['duration_label'] == tp['suggested_duration_label']
    assert route['gain']['comparison_label'] == tp['comparison_label']
    assert tp['traffic_compare_label'].count('Mevcut:') == 1
    assert tp['current_duration_label'] in tp['traffic_compare_label']
    assert tp['suggested_duration_label'] in tp['traffic_compare_label']
    assert tp['time_delta_label'] in tp['traffic_compare_label']
