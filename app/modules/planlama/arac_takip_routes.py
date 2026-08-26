# -*- coding: utf-8 -*-
"""Planlama > Araç Takip & Plan — V1.1 UI (mock DTO)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, g, jsonify, render_template, request, session

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
    get_daily_plan_aggregate,
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

_VEHICLE_IDENTITY_SCOPE_ENDPOINTS = frozenset({
    'arac_takip_bp.arac_takip_api_plana_is_ekle',
    'arac_takip_bp.arac_takip_api_plana_is_ekle_batch',
})


@arac_takip_bp.before_request
def _vehicle_identity_scope_begin():
    if request.endpoint not in _VEHICLE_IDENTITY_SCOPE_ENDPOINTS:
        return None
    from modules.planlama.arac_vehicle_identity_service import begin_vehicle_identity_request_scope
    g._atp_vehicle_identity_scope_token = begin_vehicle_identity_request_scope()
    return None


@arac_takip_bp.teardown_request
def _vehicle_identity_scope_end(exc):
    token = getattr(g, '_atp_vehicle_identity_scope_token', None)
    if token is None:
        return None
    from modules.planlama.arac_vehicle_identity_service import end_vehicle_identity_request_scope
    end_vehicle_identity_request_scope(token)
    return None


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
    from modules.planlama.arac_takip_repo import tables_ready
    if tables_ready():
        dto['day_plan_summary'] = get_daily_plan_aggregate(dto['date'])
    else:
        dto['day_plan_summary'] = None
    return jsonify({'ok': True, 'dashboard': dto})


@arac_takip_bp.route('/api/day-plan-summary', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_day_plan_summary():
    plan_date = _parse_date(request.args.get('date'))
    summary = get_daily_plan_aggregate(plan_date.isoformat())
    return jsonify({
        'ok': True,
        'plan_date': plan_date.isoformat(),
        'day_plan_summary': summary,
    })


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


@arac_takip_bp.route('/api/locations/for-company', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_locations_for_company():
    from modules.planlama.arac_takip_repo import list_company_locations, tables_ready
    if not tables_ready():
        return jsonify({'ok': True, 'locations': [], 'company': None})
    anchor = request.args.get('anchor_id') or request.args.get('location_master_id')
    cari_id = request.args.get('cari_id', type=int)
    try:
        anchor_id = int(anchor) if anchor not in (None, '') else None
    except (TypeError, ValueError):
        anchor_id = None
    data = list_company_locations(anchor_location_id=anchor_id, cari_id=cari_id)
    return jsonify({'ok': True, **data})


@arac_takip_bp.route('/api/maps/resolve', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_maps_resolve():
    """Validate-only maps coordinate resolve — no DB write."""
    from modules.planlama.arac_lokasyon_service import MAPS_COORD_USER_ERROR, resolve_maps_input
    body = request.get_json(silent=True) or {}
    try:
        result = resolve_maps_input(body)
        return jsonify({'ok': True, **result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@arac_takip_bp.route('/api/locations/from-maps', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_location_from_maps():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_takip_repo import create_or_resolve_kayitli_yer, tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    try:
        result = create_or_resolve_kayitli_yer(_uid(), body)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


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


@arac_takip_bp.route('/api/operasyon/base', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_base_get():
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location
    if not operasyon_ayar_ready():
        return jsonify({'ok': True, 'base': resolve_base_location(None)})
    return jsonify({'ok': True, 'base': resolve_base_location(get_active_base())})


@arac_takip_bp.route('/api/operasyon/base', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_base_save():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_operasyon_ayar_repo import save_base_location, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location
    if not operasyon_ayar_ready():
        return jsonify({'ok': False, 'error': 'Migration 177 gerekli'}), 503
    body = request.get_json(silent=True) or {}
    try:
        result = save_base_location(_uid(), body)
        result['base'] = resolve_base_location(result.get('base'))
        return jsonify(result)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@arac_takip_bp.route('/api/plan-items/konum', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_item_konum():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_lokasyon_service import MAPS_COORD_USER_ERROR, parse_maps_coords
    from modules.planlama.arac_takip_repo import (
        save_talep_konum_with_master,
        tables_ready,
    )
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    try:
        talep_id = int(body['is_talebi_id'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'is_talebi_id gerekli'}), 400
    maps_url = (body.get('maps_url') or body.get('konum_linki') or '').strip()
    if not maps_url:
        return jsonify({'ok': False, 'error': MAPS_COORD_USER_ERROR}), 400
    lat, lng = parse_maps_coords(maps_url)
    if lat is None or lng is None:
        return jsonify({'ok': False, 'error': MAPS_COORD_USER_ERROR}), 400
    try:
        result = save_talep_konum_with_master(_uid(), talep_id, lat, lng, maps_url or None)
        plan_date = _parse_date(body.get('date') or request.args.get('date'))
        vehicle_id = body.get('vehicle_id') or request.args.get('vehicle_id')
        tasks = get_tasks_for_session(_uid(), plan_date.isoformat(), vehicle_id)
        dto = get_arac_dashboard_dto(
            plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks,
        )
        return jsonify({'ok': True, **result, 'daily_tasks': tasks, 'dashboard': dto})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@arac_takip_bp.route('/api/route/plan', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_route_plan():
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.arac_plan_service import get_tasks_for_session
    from modules.planlama.arac_route_constraints import active_tasks_sorted
    from modules.planlama.arac_route_explainer_dto import enrich_route_explainer_dto
    from modules.planlama.arac_takip_repo import get_active_plan_row
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto
    import os

    plan_date = _parse_date(request.args.get('date'))
    vehicle_id = request.args.get('vehicle_id') or None
    uid = _uid()
    plan_date_str = plan_date.isoformat()
    tasks = get_tasks_for_session(uid, plan_date_str, vehicle_id)
    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)
    route_dto = build_plan_route_dto(base, tasks)

    active = active_tasks_sorted(tasks)
    id_to_task = {str(t['id']): t for t in active}
    routable_current = [
        t for t in active
        if t.get('has_coordinates') and t.get('latitude') is not None and t.get('longitude') is not None
    ]
    sug_full = (route_dto.get('suggested') or {}).get('full_task_ids') or []
    routable_suggested = [
        id_to_task[i] for i in sug_full
        if i in id_to_task
        and id_to_task[i].get('has_coordinates')
        and id_to_task[i].get('latitude') is not None
    ]
    plan_row = get_active_plan_row(plan_date_str, vehicle_id) if vehicle_id else None
    departure = (plan_row or {}).get('cikis_saati') or None
    profile = os.environ.get('ORS_PROFILE') or 'driving-car'
    if route_dto.get('status') in ('OK', 'PARTIAL') and routable_current:
        route_dto = enrich_route_explainer_dto(
            route_dto,
            plan_date=plan_date_str,
            departure_hhmm=departure,
            base=base,
            routable_tasks=routable_current,
            suggested_tasks=routable_suggested or routable_current,
            profile=profile,
        )

    dto = get_arac_dashboard_dto(
        plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks,
    )
    dto['route_plan'] = route_dto
    dto['route_analysis'] = {
        'current': {'km': route_dto['current']['km'], 'duration_label': route_dto['current']['duration_label']},
        'recommended': {'km': route_dto['suggested']['km'], 'duration_label': route_dto['suggested']['duration_label']},
        'gain': {
            'km': route_dto['gain']['km'],
            'duration_label': route_dto['gain']['duration_label'],
            'pct': route_dto['gain']['pct'],
        },
        'fuel_saving': {'liters': '—', 'try_amount': '—'},
        'current_order': route_dto['current'].get('order_labels', ''),
        'suggested_order': route_dto['suggested'].get('order_labels', ''),
        'status': route_dto.get('status'),
        'message': route_dto.get('message'),
    }
    if route_dto.get('status') in ('OK', 'PARTIAL'):
        dto['daily_totals'] = {
            'distance_km': route_dto['current']['km'],
            'duration_label': route_dto['current']['duration_label'],
        }
    return jsonify({'ok': True, 'route': route_dto, 'dashboard': dto})


@arac_takip_bp.route('/api/route/apply', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_route_apply():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    body = request.get_json(silent=True) or {}
    plan_date = _parse_date(body.get('date') or request.args.get('date'))
    vehicle_id = body.get('vehicle_id') or request.args.get('vehicle_id')
    task_ids = body.get('task_ids') or []
    if not task_ids:
        return jsonify({'ok': False, 'error': 'task_ids gerekli'}), 400
    uid = _uid()
    plan_date_str = plan_date.isoformat()

    from modules.planlama.arac_route_apply_service import (
        RouteApplyPersistenceError,
        RouteApplyRouteError,
        RouteApplySchemaError,
        RouteApplyValidationError,
        apply_route_order_and_snapshot,
        resolve_route_apply_mode,
    )
    from modules.planlama.arac_route_constraints import RouteApplyConflictError
    from modules.planlama.arac_plan_service import reorder_tasks

    mode = resolve_route_apply_mode()
    if mode == 'schema_error':
        return jsonify({
            'ok': False,
            'error': 'Plan rota snapshot şeması eksik',
            'code': 'ROUTE_SNAPSHOT_SCHEMA_MISSING',
        }), 503

    if mode == 'atomic':
        try:
            departure_time = (body.get('departure_time') or body.get('cikis_saati') or '').strip() or None
            apply_source = (body.get('apply_source') or body.get('routing_source') or '').strip().lower()
            google_profile = (body.get('google_profile') or '').strip().lower() or None
            keep_current = bool(body.get('keep_current_order'))
            profile_only = bool(body.get('profile_only') or body.get('apply_mode') == 'profile_only')

            if apply_source == 'google':
                if not google_profile:
                    return jsonify({'ok': False, 'error': 'google_profile gerekli', 'code': 'INVALID_REQUEST'}), 400
                if not departure_time:
                    return jsonify({'ok': False, 'error': 'departure_time gerekli', 'code': 'INVALID_REQUEST'}), 400
                from modules.planlama.arac_google_route_apply_service import apply_google_route_order_and_snapshot
                result = apply_google_route_order_and_snapshot(
                    uid,
                    plan_date_str,
                    str(vehicle_id or ''),
                    [str(t) for t in task_ids],
                    google_profile=google_profile,
                    departure_time=departure_time,
                    user_id=uid,
                    keep_current_order=keep_current or profile_only,
                    profile_only=profile_only,
                )
            else:
                result = apply_route_order_and_snapshot(
                    uid, plan_date_str, str(vehicle_id or ''), task_ids, user_id=uid,
                    departure_time=departure_time,
                )
        except RouteApplyConflictError as exc:
            return jsonify(exc.to_dict()), 409
        except RouteApplyValidationError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        except RouteApplyRouteError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        except RouteApplySchemaError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 503
        except RouteApplyPersistenceError as exc:
            return jsonify({'ok': False, 'error': str(exc), 'code': 'ROUTE_APPLY_FAILED'}), 409
        dto = get_arac_dashboard_dto(
            plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=result.tasks,
        )
        return jsonify({
            'ok': True,
            'applied': True,
            'daily_tasks': result.tasks,
            'dashboard': dto,
            'route_snapshot': result.route_snapshot,
            'route_version': result.route_version,
            'deduplicated': result.deduplicated,
            'eta_applied': result.eta_applied,
            'departure_source': result.departure_source,
            'reorder_applied': result.reorder_applied,
            'google_profile': google_profile if apply_source == 'google' else None,
            'departure_time': result.eta_by_task and next(iter(result.eta_by_task.values()), {}).get('departure_source_at', '')[:5] if result.eta_by_task else None,
            'eta_reason': (
                'Rota profili uygulandı ve durak saatleri güncellendi.'
                if result.eta_applied and apply_source == 'google' and profile_only
                else 'Rota sırası uygulandı ve durak saatleri güncellendi.'
                if result.eta_applied
                else 'Rota uygulandı. Saatler için Çıkış Saati girin.'
            ),
        })

    # Legacy (pre-migration-179 / canonical): reorder only — mevcut 8080 davranışı korunur
    try:
        tasks = reorder_tasks(uid, plan_date_str, task_ids, vehicle_id)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    dto = get_arac_dashboard_dto(plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks)
    return jsonify({'ok': True, 'daily_tasks': tasks, 'dashboard': dto})


@arac_takip_bp.route('/api/today-operations', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_today_operations():
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    plan_date = _parse_date(request.args.get('date'))
    dto = get_today_vehicle_operations(plan_date.isoformat())
    return jsonify(dto)


@arac_takip_bp.route('/api/plan-changes', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_changes():
    from modules.planlama.arac_plan_changes_service import list_plan_changes_for_date
    plan_date = _parse_date(request.args.get('date'))
    return jsonify(list_plan_changes_for_date(plan_date.isoformat()))


@arac_takip_bp.route('/api/plan-timeline', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_timeline():
    from modules.planlama.arac_plan_timeline_service import list_plan_timeline
    plan_id = request.args.get('plan_id', type=int)
    plan_is_id = request.args.get('plan_item_id', type=int) or request.args.get('plan_is_id', type=int)
    plan_date = request.args.get('date')
    vehicle_id = request.args.get('vehicle_id')
    if not any([plan_id, plan_is_id, plan_date, vehicle_id]):
        return jsonify({'ok': False, 'error': 'plan_id, plan_item_id, date veya vehicle_id gerekli'}), 400
    dto = list_plan_timeline(
        plan_id=plan_id,
        plan_is_id=plan_is_id,
        plan_date=plan_date,
        vehicle_id=vehicle_id,
    )
    return jsonify(dto)


_SENTINEL_RE = __import__('re').compile(r'^[\s\-\u2014\u2013]+$')


def _batch_validate_row(idx: int, row: dict) -> str | None:
    """
    Backend guard for a single batch row.
    Returns an error string if invalid, None if ok.
    Never lets placeholder sentinels ('—') reach the service.
    """
    import re
    sentinel = _SENTINEL_RE

    firma = (row.get('firma') or row.get('firma_adi') or '').strip()
    if not firma or sentinel.match(firma) or len(firma) < 2:
        return f'Satır {idx + 1}: firma adı eksik veya çok kısa (min 2 karakter)'

    yapilacak = (row.get('is') or row.get('yapilacak_is') or '').strip()
    if not yapilacak or sentinel.match(yapilacak) or len(yapilacak) < 2:
        return f'Satır {idx + 1}: yapılacak iş eksik veya çok kısa (min 2 karakter)'

    arac = (row.get('arac_external_id') or '').strip()
    if not arac:
        return f'Satır {idx + 1}: araç seçilmemiş'

    lat_raw = row.get('latitude') or row.get('lat')
    lng_raw = row.get('longitude') or row.get('lng')
    try:
        lat = float(lat_raw) if lat_raw not in (None, '') else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng_raw) if lng_raw not in (None, '') else None
    except (TypeError, ValueError):
        lng = None
    loc_id = row.get('location_master_id') or row.get('kayitli_yer_id')
    if (lat is None or lng is None) and not loc_id:
        return f'Satır {idx + 1}: konum koordinatı doğrulanmamış'

    adres = (row.get('adres') or '').strip()
    if not adres and not loc_id:
        return f'Satır {idx + 1}: adres eksik'

    return None


@arac_takip_bp.route('/api/plana-is-ekle-batch', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plana_is_ekle_batch():
    """
    Çoklu iş ekleme — tümü-veya-hiç (all-or-nothing) güvenli mod.
    Herhangi bir satırda eksik firma/is/konum varsa hiçbir satır eklenmez.
    """
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    from modules.planlama.arac_takip_repo import tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    rows = body.get('rows', [])
    if not rows or not isinstance(rows, list):
        return jsonify({'ok': False, 'error': 'rows listesi gerekli'}), 400

    # ── Backend-side pre-validation (all-or-nothing) ──────────────────────────
    pre_errors = []
    for idx, row in enumerate(rows):
        err = _batch_validate_row(idx, row)
        if err:
            pre_errors.append({'row': idx, 'ok': False, 'error': err})

    if pre_errors:
        return jsonify({
            'ok': False,
            'ok_count': 0,
            'total': len(rows),
            'results': pre_errors,
            'error': 'Bazı satırlar geçersiz — hiçbir kayıt yapılmadı',
            'daily_tasks': [],
            'today_operations': {},
        }), 400

    uid = _uid()
    results = []
    ok_count = 0
    for idx, row in enumerate(rows):
        try:
            r = add_job_to_plan_atomic(uid, row)
            results.append({'row': idx, 'ok': True, **r})
            ok_count += 1
        except (KeyError, TypeError, ValueError) as exc:
            results.append({'row': idx, 'ok': False, 'error': str(exc)})
        except Exception as exc:
            results.append({'row': idx, 'ok': False, 'error': str(exc)})

    plan_date = _parse_date(
        body.get('plan_tarihi') or body.get('tarih')
        or (rows[0].get('plan_tarihi') if rows else None)
    )
    vehicle_id = body.get('arac_external_id') or (rows[0].get('arac_external_id') if rows else None)
    tasks = get_tasks_for_session(uid, plan_date.isoformat(), vehicle_id)
    ops = get_today_vehicle_operations(plan_date.isoformat())
    return jsonify({
        'ok': ok_count > 0,
        'ok_count': ok_count,
        'total': len(rows),
        'results': results,
        'daily_tasks': tasks,
        'today_operations': ops,
    })


@arac_takip_bp.route('/api/plana-is-ekle', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plana_is_ekle():
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    from modules.planlama.arac_takip_repo import tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    try:
        result = add_job_to_plan_atomic(_uid(), body)
        plan_date = _parse_date(body.get('plan_tarihi') or body.get('tarih'))
        vehicle_id = body.get('arac_external_id')
        tasks = get_tasks_for_session(_uid(), plan_date.isoformat(), vehicle_id)
        dto = get_arac_dashboard_dto(
            plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks,
        )
        ops = get_today_vehicle_operations(plan_date.isoformat())
        return jsonify({
            'ok': True,
            **result,
            'daily_tasks': tasks,
            'dashboard': dto,
            'today_operations': ops,
        })
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@arac_takip_bp.route('/api/plan-job/<int:plan_is_id>/detail', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_job_detail(plan_is_id: int):
    from modules.planlama.arac_plan_change_service import PlanChangeError, get_plan_job_detail
    from modules.planlama.arac_takip_repo import tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    try:
        return jsonify(get_plan_job_detail(plan_is_id))
    except PlanChangeError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@arac_takip_bp.route('/api/plan-job/<int:plan_is_id>/change', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_job_change(plan_is_id: int):
    if not _planlama_duzenle():
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    from modules.planlama.arac_plan_change_service import (
        PlanChangeError,
        PlanChangeForbidden,
        apply_plan_job_change,
    )
    from modules.planlama.arac_plan_service import get_tasks_for_session
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    from modules.planlama.arac_takip_repo import tables_ready
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil'}), 503
    body = request.get_json(silent=True) or {}
    try:
        result = apply_plan_job_change(plan_is_id, _uid(), body)
        plan_date = _parse_date(body.get('plan_tarihi') or request.args.get('date'))
        vehicle_id = (
            body.get('target_vehicle_external_id')
            or body.get('arac_external_id')
            or request.args.get('vehicle_id')
        )
        tasks = get_tasks_for_session(_uid(), plan_date.isoformat(), vehicle_id)
        ops = get_today_vehicle_operations(plan_date.isoformat())
        dto = get_arac_dashboard_dto(
            plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks,
        )
        return jsonify({
            **result,
            'daily_tasks': tasks,
            'dashboard': dto,
            'today_operations': ops,
        })
    except PlanChangeForbidden as exc:
        return jsonify({'ok': False, 'error': str(exc), 'code': 'FORBIDDEN'}), 403
    except PlanChangeError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        import sqlite3
        if isinstance(exc, sqlite3.IntegrityError):
            return jsonify({
                'ok': False,
                'error': 'Bu iş silinemez; iptal olarak kapatabilirsiniz.',
            }), 400
        return jsonify({'ok': False, 'error': str(exc)}), 500


@arac_takip_bp.route('/api/plan/departure-time', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_departure_time():
    """Araç planı çıkış saatini kaydet ve durak ETA'larını hesapla (atomic)."""
    from modules.planlama.arac_departure_service import (
        DepartureValidationError,
        save_departure_and_compute_eta,
    )

    body = request.get_json(silent=True) or {}

    # --- Input validation ---
    date_raw = (body.get('date') or '').strip()
    vehicle_id = (body.get('vehicle_id') or '').strip()
    departure_raw = (body.get('departure_time') or '').strip()
    plan_id_raw = body.get('plan_id')

    if not date_raw:
        return jsonify({'ok': False, 'error': 'date zorunludur', 'code': 'MISSING_DATE'}), 400
    if not vehicle_id:
        return jsonify({'ok': False, 'error': 'vehicle_id zorunludur', 'code': 'MISSING_VEHICLE'}), 400
    if not departure_raw:
        return jsonify({'ok': False, 'error': 'departure_time zorunludur', 'code': 'MISSING_DEPARTURE'}), 400

    try:
        plan_date = _parse_date(date_raw)
    except Exception:
        return jsonify({'ok': False, 'error': f'Geçersiz tarih: {date_raw!r}', 'code': 'INVALID_DATE'}), 400

    plan_id = None
    if plan_id_raw is not None:
        try:
            plan_id = int(plan_id_raw)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'plan_id sayısal olmalıdır', 'code': 'INVALID_PLAN_ID'}), 400

    try:
        result = save_departure_and_compute_eta(
            plan_date=plan_date.isoformat(),
            arac_external_id=str(vehicle_id),
            cikis_saati=departure_raw,
            session_user_id=_uid(),
            plan_id=plan_id,
        )
    except DepartureValidationError as exc:
        return jsonify({'ok': False, 'error': str(exc), 'code': 'INVALID_DEPARTURE_TIME'}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'code': 'UNEXPECTED_ERROR'}), 500

    if not result.get('ok'):
        code = result.get('code', 'ERROR')
        http_status = 400
        if code == 'PLAN_NOT_FOUND':
            http_status = 404
        elif code == 'TABLES_NOT_READY':
            http_status = 503
        return jsonify(result), http_status

    # Refresh dashboard DTO with updated tasks
    from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
    from modules.planlama.arac_timeline_service import build_timeline_for_plan
    tasks = result.get('tasks', [])
    dto = get_arac_dashboard_dto(plan_date=plan_date, vehicle_id=vehicle_id, daily_tasks=tasks)
    timeline = build_timeline_for_plan(plan_date.isoformat(), str(vehicle_id))

    return jsonify({
        **result,
        'dashboard': dto,
        'timeline': timeline,
    })


@arac_takip_bp.route('/api/plan-job/desired-time', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_job_desired_time():
    """İş bazlı istenen varış saatini kaydet (atomic + audit).

    Payload:
      date          — YYYY-MM-DD
      vehicle_id    — araç external_id
      plan_item_id  — arac_gunluk_plan_is.id
      desired_time  — HH:mm veya null (time_free=true ise boş olabilir)
      time_free     — boolean, true ise saat null, kaynak='SERBEST'
    """
    from modules.planlama.arac_desired_time_service import (
        DesiredTimeValidationError,
        save_desired_time,
    )
    from modules.planlama.arac_dashboard_service import get_arac_dashboard_dto
    from modules.planlama.arac_takip_repo import tables_ready

    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil', 'code': 'TABLES_NOT_READY'}), 503

    body = request.get_json(silent=True) or {}

    date_raw = body.get('date') or request.args.get('date', '')
    vehicle_id = (
        body.get('vehicle_id')
        or body.get('arac_external_id')
        or request.args.get('vehicle_id', '')
    )
    plan_item_id_raw = body.get('plan_item_id')
    desired_time_raw = body.get('desired_time') or ''
    time_free = bool(body.get('time_free', False))

    if not date_raw:
        return jsonify({'ok': False, 'error': 'date zorunludur', 'code': 'MISSING_DATE'}), 400
    if not vehicle_id:
        return jsonify({'ok': False, 'error': 'vehicle_id zorunludur', 'code': 'MISSING_VEHICLE'}), 400
    if plan_item_id_raw is None:
        return jsonify({'ok': False, 'error': 'plan_item_id zorunludur', 'code': 'MISSING_ITEM_ID'}), 400
    if not time_free and not desired_time_raw:
        return jsonify({'ok': False, 'error': 'desired_time veya time_free=true gereklidir', 'code': 'MISSING_TIME'}), 400

    try:
        plan_date = _parse_date(date_raw)
        plan_item_id = int(plan_item_id_raw)
    except (TypeError, ValueError) as exc:
        return jsonify({'ok': False, 'error': f'Geçersiz parametre: {exc}', 'code': 'INVALID_PARAM'}), 400

    try:
        result = save_desired_time(
            plan_date=plan_date.isoformat(),
            arac_external_id=str(vehicle_id),
            plan_item_id=plan_item_id,
            desired_time=desired_time_raw if not time_free else None,
            time_free=time_free,
            session_user_id=_uid(),
        )
    except DesiredTimeValidationError as exc:
        return jsonify({'ok': False, 'error': str(exc), 'code': 'INVALID_TIME'}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'code': 'UNEXPECTED_ERROR'}), 500

    if not result.get('ok'):
        code = result.get('code', 'ERROR')
        http_status = 400
        if code in ('PLAN_NOT_FOUND', 'PLAN_ITEM_NOT_FOUND'):
            http_status = 404
        elif code in ('TABLES_NOT_READY', 'MIGRATION_REQUIRED'):
            http_status = 503
        elif code == 'INACTIVE_ITEM':
            http_status = 422
        return jsonify(result), http_status

    tasks = result.get('tasks', [])
    dto = get_arac_dashboard_dto(plan_date=plan_date, vehicle_id=str(vehicle_id), daily_tasks=tasks)

    return jsonify({
        **result,
        'dashboard': dto,
    })


@arac_takip_bp.route('/api/plan/google-route-options', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_google_route_options():
    """Google Routes API ile mevcut ve önerilen sıra için rota seçeneklerini hesapla.

    Request JSON:
      date          — YYYY-MM-DD
      vehicle_id    — araç external_id
      departure_time — HH:MM
      plan_id       — optional int (araç-plan eşleşmesi için)

    Constraints:
      - Koordinatlar browser payload'ından ALINMAZ; canonical DB'den okunur.
      - Önerilen sıra mevcut build_plan_route_dto suggested zincirinden gelir.
      - ORS fallback yok; profil başarısızlığı DTO içinde raporlanır.
    """
    import dataclasses
    import re as _re

    from modules.planlama.arac_google_route_options_service import compute_google_route_options
    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_plan_service import get_tasks_for_session
    from modules.planlama.arac_route_constraints import active_tasks_sorted
    from modules.planlama.arac_takip_repo import get_active_plan_row, tables_ready
    from modules.planlama.road_routing.env_loader import google_routes_key_present
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    _HHMM_RE = _re.compile(r'^\d{2}:\d{2}$')

    body = request.get_json(silent=True) or {}

    # ── Input validation ─────────────────────────────────────────────────────
    date_raw = (body.get('date') or '').strip()
    vehicle_id = (body.get('vehicle_id') or '').strip()
    departure_raw = (body.get('departure_time') or '').strip()
    plan_id_raw = body.get('plan_id')

    if not date_raw or not vehicle_id or not departure_raw:
        return jsonify({
            'ok': False,
            'error': 'date, vehicle_id ve departure_time zorunludur',
            'code': 'INVALID_REQUEST',
        }), 400

    if not _HHMM_RE.match(departure_raw[:5]):
        return jsonify({
            'ok': False,
            'error': f'departure_time HH:MM formatında olmalıdır: {departure_raw!r}',
            'code': 'INVALID_REQUEST',
        }), 400

    try:
        plan_date = _parse_date(date_raw)
    except Exception:
        return jsonify({
            'ok': False,
            'error': f'Geçersiz tarih: {date_raw!r}',
            'code': 'INVALID_REQUEST',
        }), 400

    plan_id_req = None
    if plan_id_raw is not None:
        try:
            plan_id_req = int(plan_id_raw)
        except (TypeError, ValueError):
            return jsonify({
                'ok': False,
                'error': 'plan_id sayısal olmalıdır',
                'code': 'INVALID_REQUEST',
            }), 400

    # ── DB/table readiness ───────────────────────────────────────────────────
    if not tables_ready():
        return jsonify({'ok': False, 'error': 'Tablolar hazır değil', 'code': 'TABLES_NOT_READY'}), 503

    # ── Google key check ──────────────────────────────────────────────────────
    if not google_routes_key_present():
        return jsonify({
            'ok': False,
            'error': 'Google Routes API anahtarı yapılandırılmamış',
            'code': 'GOOGLE_ROUTES_NOT_CONFIGURED',
        }), 503

    # ── Plan doğrulama ────────────────────────────────────────────────────────
    plan_date_str = plan_date.isoformat()
    plan_row = get_active_plan_row(plan_date_str, vehicle_id)
    if not plan_row:
        return jsonify({
            'ok': False,
            'error': f'Plan bulunamadı: {plan_date_str} / {vehicle_id}',
            'code': 'PLAN_NOT_FOUND',
        }), 404

    if plan_id_req is not None and int(plan_row.get('id') or 0) != plan_id_req:
        return jsonify({
            'ok': False,
            'error': f'plan_id={plan_id_req} bu araca ait değil',
            'code': 'VEHICLE_PLAN_MISMATCH',
        }), 422

    # ── Canonical duraklar (DB kaynağı; browser payload kabul edilmez) ───────
    uid = _uid()
    tasks = get_tasks_for_session(uid, plan_date_str, vehicle_id)
    active = active_tasks_sorted(tasks)

    routable = [
        t for t in active
        if t.get('has_coordinates')
        and t.get('latitude') is not None
        and t.get('longitude') is not None
    ]

    if not active:
        return jsonify({
            'ok': False,
            'error': 'Bu planda aktif durak yok',
            'code': 'NO_ACTIVE_STOPS',
        }), 422

    if not routable:
        return jsonify({
            'ok': False,
            'error': 'Aktif durakların koordinatı eksik',
            'code': 'MISSING_COORDINATES',
        }), 422

    # ── Base / fabrika ────────────────────────────────────────────────────────
    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)

    if not base.get('has_coordinates'):
        return jsonify({
            'ok': False,
            'error': 'Başlangıç/fabrika koordinatı tanımlanmamış',
            'code': 'MISSING_COORDINATES',
        }), 422

    # ── Suggested order: mevcut Rota Kararı servisi (ORS matrix) ─────────────
    # build_plan_route_dto → suggested.full_task_ids (CPS sıralama mantığı)
    # Google waypoint optimization KULLANILMAZ.
    route_dto = build_plan_route_dto(base, tasks)
    sug_full_ids = (route_dto.get('suggested') or {}).get('full_task_ids') or []

    id_to_task = {str(t['id']): t for t in active}
    suggested_stops_for_fn = [
        id_to_task[i] for i in sug_full_ids
        if i in id_to_task
        and id_to_task[i].get('has_coordinates')
        and id_to_task[i].get('latitude') is not None
    ]

    def _suggested_order_from_route(active_tasks_arg, base_arg):
        """Inject pre-computed suggested order — no second ORS call."""
        return suggested_stops_for_fn if suggested_stops_for_fn else list(active_tasks_arg)

    # ── Orchestration call ────────────────────────────────────────────────────
    options_dto = compute_google_route_options(
        plan_date=plan_date_str,
        departure_hhmm=departure_raw[:5],
        base=base,
        tasks=tasks,
        _suggested_order_fn=_suggested_order_from_route,
    )

    result = dataclasses.asdict(options_dto)
    result['ok'] = True
    result['plan_id'] = int(plan_row.get('id') or 0)
    result['vehicle_id'] = vehicle_id

    return jsonify(result)


@arac_takip_bp.route('/api/plan/timeline', methods=['GET', 'POST'])
@yetki_gerekli('planlama', 'can_view')
def arac_takip_api_plan_departure_timeline():
    """Çıkış Saati + rota ayakları + 10 dk işlem süresi → timeline DTO.

    GET  ?date=YYYY-MM-DD&vehicle_id=...
    POST {date, vehicle_id}

    Response: timeline dict (DB write yok — sadece preview hesap)
    planlanan_saat DOKUNULMAZ. tahmini_varis_saati: migration 188 ile ayrı endpoint.
    """
    from modules.planlama.arac_timeline_service import build_timeline_for_plan
    from modules.planlama.arac_takip_repo import tables_ready

    if not tables_ready():
        return jsonify({'ok': False, 'status': 'TABLES_NOT_READY', 'stops': []}), 503

    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        date_raw = body.get('date') or request.args.get('date', '')
        vehicle_id = body.get('vehicle_id') or body.get('arac_external_id') or request.args.get('vehicle_id', '')
    else:
        date_raw = request.args.get('date', '')
        vehicle_id = request.args.get('vehicle_id', '') or request.args.get('arac_external_id', '')

    if not date_raw or not vehicle_id:
        return jsonify({'ok': False, 'error': 'date ve vehicle_id zorunludur', 'stops': []}), 400

    try:
        plan_date = _parse_date(date_raw)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': f'Geçersiz tarih: {date_raw}', 'stops': []}), 400

    timeline = build_timeline_for_plan(plan_date.isoformat(), str(vehicle_id))
    return jsonify({'ok': True, **timeline})
