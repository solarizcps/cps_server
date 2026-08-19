# -*- coding: utf-8 -*-
"""APS P1.5 — DHTMLX Gantt technical pilot (READ-only, no persist)."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from db import get_conn
from modules.auth import yetki_gerekli
from modules.planlama.aps_enj_timeline_service import load_enj_timeline_payload
from modules.planlama.aps_pilot_data_service import (
    build_synthetic_blocks,
    load_pilot_33917_payload,
)

aps_pilot_bp = Blueprint(
    'aps_pilot_bp',
    __name__,
    url_prefix='/planlama/aps-pilot',
)


@aps_pilot_bp.route('/', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def aps_pilot_sayfa():
    return render_template(
        'planlama/aps_pilot.html',
        pilot_sip=33917,
        pilot_model='CRX-71024-KRK',
        aps_phase='P4A',
    )


@aps_pilot_bp.route('/api/enj-timeline', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_timeline():
    con = get_conn()
    demo_multi = request.args.get('demo_multi', '').lower() in ('1', 'true', 'yes')
    payload = load_enj_timeline_payload(con, demo_multi=demo_multi)
    return jsonify({'ok': True, **payload})


@aps_pilot_bp.route('/api/pilot-data', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_pilot_data():
    con = get_conn()
    payload = load_pilot_33917_payload(con)
    return jsonify({'ok': True, **payload})


@aps_pilot_bp.route('/api/synthetic', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_synthetic():
    count = request.args.get('count', 50, type=int)
    return jsonify({'ok': True, **build_synthetic_blocks(count)})
