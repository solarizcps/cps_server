# -*- coding: utf-8 -*-
"""Planlama > Araç Takip & Plan — V1.1 UI (mock DTO)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, render_template, request, session

from modules.auth import yetki_gerekli, yetki_var
from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
from modules.planlama.arac_lokasyon_service import (
    get_location_suggestions,
    search_locations,
)
from modules.planlama.arac_request_user_service import get_cps_user_by_id, search_cps_users
from modules.planlama.arac_plan_service import (
    add_job_request,
    build_whatsapp_plan_message,
    get_tasks_for_session,
    move_task,
    reorder_tasks,
    whatsapp_web_url,
)

arac_takip_bp = Blueprint(
    'arac_takip_bp',
    __name__,
    url_prefix='/planlama/arac-takip',
)

_VALID_TABS = frozenset({'canli', 'gunluk', 'haftalik', 'gecmis'})


def _uid() -> int:
    u = session.get('kullanici') or {}
    return int(u.get('Id') or u.get('id') or 0)


def _session_user_label() -> str:
    return _session_user_dict()['display_name']


def _session_user_dict() -> dict:
    u = session.get('kullanici') or {}
    uid = int(u.get('Id') or u.get('id') or 0)
    label = (u.get('AdSoyad') or u.get('KullaniciAdi') or '—').strip()
    return {'id': uid, 'display_name': label}


def _parse_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    return date.today()


def _planlama_duzenle() -> bool:
    return bool(
        yetki_var('planlama', 'can_update')
        or yetki_var('planlama', 'can_create')
        or yetki_var('planlama', 'can_manage')
    )


def _build_dto(tab: str | None = None, plan_date: date | None = None) -> dict:
    tab = tab if tab in _VALID_TABS else 'gunluk'
    d = plan_date or date.today()
    uid = _uid()
    vehicle_id = request.args.get('vehicle_id') or None
    driver_id = request.args.get('driver_id') or None
    tasks = get_tasks_for_session(uid, d.isoformat(), vehicle_id)
    return get_arac_dashboard_dto(
        plan_date=d,
        active_tab=tab,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        daily_tasks=tasks,
    )


@arac_takip_bp.route('/', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_sayfa():
    tab = request.args.get('tab') or 'gunluk'
    if tab not in _VALID_TABS:
        tab = 'gunluk'
    dto = _build_dto(tab=tab, plan_date=_parse_date(request.args.get('date')))
    return render_template(
        'planlama/arac_takip_plan.html',
        dashboard=dto,
        active_tab=tab,
        current_user_label=_session_user_label(),
        current_user=_session_user_dict(),
    )


@arac_takip_bp.route('/api/dashboard', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_dashboard():
    tab = request.args.get('tab') or 'gunluk'
    dto = _build_dto(tab=tab, plan_date=_parse_date(request.args.get('date')))
    return jsonify({'ok': True, 'dashboard': dto})


@arac_takip_bp.route('/api/reorder', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_reorder():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    body = request.get_json(silent=True) or {}
    plan_date = _parse_date(body.get('date') or request.args.get('date'))
    uid = _uid()
    vehicle_id = body.get('vehicle_id') or request.args.get('vehicle_id')
    if body.get('task_id') and body.get('direction') in ('up', 'down'):
        tasks = move_task(uid, plan_date.isoformat(), body['task_id'], body['direction'], vehicle_id)
    else:
        task_ids = body.get('task_ids') or []
        tasks = reorder_tasks(uid, plan_date.isoformat(), task_ids, vehicle_id)
    dto = get_arac_dashboard_dto(
        plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks,
    )
    return jsonify({'ok': True, 'daily_tasks': tasks, 'dashboard': dto})


@arac_takip_bp.route('/api/talepler/bekleyen', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_talepler_bekleyen():
    from modules.planlama.arac_takip_repo import list_bekleyen_talepler, tables_ready
    if not tables_ready():
        return jsonify({'ok': True, 'talepler': [], 'count': 0})
    rows = list_bekleyen_talepler()
    return jsonify({'ok': True, 'talepler': rows, 'count': len(rows)})


@arac_takip_bp.route('/api/talepler/plana-al', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plana_al():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_takip_repo import assign_to_plan, tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    try:
        result = assign_to_plan(
            session_user_id=_uid(),
            talep_id=int(body['talep_id']),
            plan_date=str(body.get('plan_tarihi') or body.get('tarih'))[:10],
            arac_external_id=str(body['arac_external_id']),
            arac_plaka=str(body.get('arac_plaka') or body.get('plaka') or ''),
            sofor_id=int(body['sofor_id']) if body.get('sofor_id') not in (None, '') else None,
            sofor_adi=(body.get('sofor_adi') or '').strip() or None,
            planlanan_saat=(body.get('planlanan_saat') or body.get('saat') or '').strip() or None,
            sira=int(body['sira']) if body.get('sira') not in (None, '') else None,
        )
        return jsonify(result)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@arac_takip_bp.route('/api/whatsapp', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_whatsapp():
    dto = _build_dto(tab='gunluk', plan_date=_parse_date(request.args.get('date')))
    msg = build_whatsapp_plan_message(dto)
    url = whatsapp_web_url(msg, request.args.get('phone', ''))
    return jsonify({'ok': True, 'message': msg, 'whatsapp_url': url})


@arac_takip_bp.route('/api/locations/search', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_locations_search():
    q = request.args.get('q', '')
    limit = min(int(request.args.get('limit', 12) or 12), 30)
    return jsonify({'ok': True, 'results': search_locations(q, limit=limit)})


@arac_takip_bp.route('/api/locations/suggestions', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_locations_suggestions():
    return jsonify({'ok': True, **get_location_suggestions(_uid())})


@arac_takip_bp.route('/api/users/search', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_users_search():
    q = request.args.get('q', '')
    limit = min(int(request.args.get('limit', 20) or 20), 50)
    return jsonify({'ok': True, 'results': search_cps_users(q, limit=limit)})


@arac_takip_bp.route('/api/request', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_request():
    body = request.get_json(silent=True) or {}
    talep_uid = body.get('talep_eden_user_id')
    try:
        talep_uid = int(talep_uid) if talep_uid not in (None, '') else _uid()
    except (TypeError, ValueError):
        talep_uid = _uid()
    if not (body.get('talep_eden_adi') or body.get('talep_eden')):
        picked = get_cps_user_by_id(talep_uid)
        if picked:
            body['talep_eden_adi'] = picked['display_name']
    body['talep_eden_user_id'] = talep_uid
    req = add_job_request(body, session_user_id=_uid())
    return jsonify({'ok': True, 'request': req})


@arac_takip_bp.route('/api/araclar', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_araclar():
    from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import get_live_vehicles
    result = get_live_vehicles()
    status = 200 if result.get('ok') else 503
    return jsonify(result), status
