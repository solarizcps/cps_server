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
    from modules.planlama.road_routing.route_planner_service import build_plan_route_dto

    plan_date = _parse_date(request.args.get('date'))
    vehicle_id = request.args.get('vehicle_id') or None
    uid = _uid()
    tasks = get_tasks_for_session(uid, plan_date.isoformat(), vehicle_id)
    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)
    route_dto = build_plan_route_dto(base, tasks)
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
            result = apply_route_order_and_snapshot(
                uid, plan_date_str, str(vehicle_id or ''), task_ids, user_id=uid,
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
