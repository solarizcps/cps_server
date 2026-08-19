# -*- coding: utf-8 -*-
"""Planlama > Enjeksiyon Planı V1 — READ-ONLY kapasite/doluluk ekranı."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from db import get_conn
from modules.auth import yetki_gerekli

enjeksiyon_plan_bp = Blueprint(
    'enjeksiyon_plan_bp',
    __name__,
    url_prefix='/planlama/enjeksiyon-plan',
)


@enjeksiyon_plan_bp.route('/')
@yetki_gerekli('planlama', 'can_view')
def enjeksiyon_plan_sayfa():
    return render_template('planlama/enjeksiyon_plan.html')


@enjeksiyon_plan_bp.route('/api/kapasite-hesap', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_kapasite_hesap():
    """Faz 2A — tahmini bitiş / doluluk motoru (READ-ONLY ENJ verisi)."""
    body = request.get_json(silent=True) or {}
    ref_days = int(body.get('ref_days') or body.get('days') or 90)
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_motor import hesapla_kapasite
        result = hesapla_kapasite(con, body, ref_days=ref_days)
        status = 200 if result.get('ok') else 400
        return jsonify(result), status
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:300]}), 500
    finally:
        con.close()


@enjeksiyon_plan_bp.route('/api/calendar')
@yetki_gerekli('planlama', 'can_view')
def api_calendar():
    """Faz 2B — takvim / ajanda plan görünümü (READ-ONLY)."""
    makine_kod = (request.args.get('makine_kod') or 'M1').strip()
    view = (request.args.get('view') or 'bu_hafta').strip()
    anchor = request.args.get('anchor')
    include_live = request.args.get('live') == '1'
    con = get_conn()
    try:
        from modules.planlama.enjeksiyon_plan_calendar_service import build_calendar
        result = build_calendar(con, makine_kod, view=view, anchor=anchor, include_live=include_live)
        status = 200 if result.get('ok') else 400
        return jsonify(result), status
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:300]}), 500
    finally:
        con.close()


@enjeksiyon_plan_bp.route('/api/canli-tahmin', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_canli_tahmin():
    """Faz 2A.2 — canli tahmini bitis (READ-ONLY ENJ verisi)."""
    body = request.get_json(silent=True) or {}
    ref_days = int(body.get('ref_days') or body.get('days') or 90)
    con = get_conn()
    try:
        from modules.planlama.enj_canli_tahmin_motor import hesapla_canli_tahmin
        result = hesapla_canli_tahmin(con, body, ref_days=ref_days)
        status = 200 if result.get('ok') else 400
        return jsonify(result), status
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:300]}), 500
    finally:
        con.close()
