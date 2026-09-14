# -*- coding: utf-8 -*-
"""Driver map DTO — R04 single-map contract (read-only canonical)."""
from __future__ import annotations

from typing import Any

from modules.planlama.arac_location_resolver import resolve_base_location
from modules.planlama.arac_route_constraints import INACTIVE_PLAN_STATUSES, active_tasks_sorted
from modules.planlama.arac_takip_repo import (
    get_active_plan_row,
    list_plan_tasks,
    tables_ready,
)
from modules.planlama.arac_whatsapp_message_service import sort_stops_for_whatsapp
from modules.planlama.road_routing.route_planner_service import build_plan_route_dto
from modules.planlama.road_routing.env_loader import ors_key_present


def safe_maps_open_url(lat: Any, lng: Any) -> str | None:
    """External open link — never embed raw passthrough URLs."""
    try:
        if lat is None or lng is None:
            return None
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= la <= 90 and -180 <= ln <= 180):
        return None
    from modules.planlama.arac_whatsapp_message_service import format_coordinate
    return (
        f'https://www.google.com/maps?q='
        f'{format_coordinate(la)},{format_coordinate(ln)}'
    )


def _stop_dto(task: dict, *, sira: int) -> dict[str, Any]:
    pri = (task.get('priority') or task.get('oncelik') or 'NORMAL').strip().upper()
    status = (task.get('status') or 'PLANLANDI').strip().upper()
    has_coords = bool(task.get('has_coordinates'))
    return {
        'plan_item_id': task.get('plan_item_id'),
        'id': task.get('id'),
        'sira': sira,
        'order_no': task.get('order_no'),
        'display_order_no': task.get('display_order_no'),
        'firma': task.get('company_name') or '—',
        'adres': task.get('address_text') or task.get('adres') or '—',
        'yapilacak_is': task.get('job_title') or task.get('yapilacak_is') or '—',
        'oncelik': pri,
        'priority_label': task.get('priority_label') or pri,
        'durum': status,
        'status_label': task.get('status_label') or status,
        'latitude': task.get('latitude'),
        'longitude': task.get('longitude'),
        'location_valid': has_coords,
        'location_warning': None if has_coords else 'Konum eksik',
        'planned_time': task.get('planned_time'),
        'is_acil': pri == 'ACIL',
        'safe_maps_url': safe_maps_open_url(task.get('latitude'), task.get('longitude')),
        'visit_state': task.get('visit_state'),
    }


def _resolve_stop_order(active_tasks: list[dict], route_dto: dict | None) -> list[dict]:
    """WhatsApp / günlük plan ile aynı sıra kaynağı."""
    ordered = sort_stops_for_whatsapp(active_tasks)
    by_id = {str(t.get('id')): t for t in active_tasks}
    route_ids = []
    if route_dto:
        cur = route_dto.get('current') or {}
        route_ids = list(cur.get('full_task_ids') or cur.get('task_ids') or [])
    if route_ids:
        seen = set()
        merged: list[dict] = []
        for tid in route_ids:
            t = by_id.get(str(tid))
            if t and str(tid) not in seen:
                merged.append(t)
                seen.add(str(tid))
        for t in ordered:
            tid = str(t.get('id'))
            if tid not in seen:
                merged.append(t)
        ordered = merged
    out: list[dict] = []
    for i, task in enumerate(ordered, start=1):
        out.append(_stop_dto(task, sira=i))
    return out


def build_driver_map_dto(plan_date: str, vehicle_id: str) -> dict[str, Any] | None:
    if not tables_ready() or not plan_date or not vehicle_id:
        return None

    plan_row = get_active_plan_row(plan_date, str(vehicle_id))
    if not plan_row:
        return None

    plan_id = int(plan_row.get('id') or 0)
    tasks = list_plan_tasks(plan_date, str(vehicle_id))
    active = active_tasks_sorted(tasks)

    base_row = None
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    if operasyon_ayar_ready():
        base_row = get_active_base()
    base = resolve_base_location(base_row)

    route_dto = build_plan_route_dto(base, tasks)
    provider_status = route_dto.get('status') or 'UNKNOWN'
    route_line_available = bool((route_dto.get('current') or {}).get('geometry'))
    route_fallback = provider_status in ('UNCONFIGURED', 'UNAVAILABLE') or not route_line_available

    stops = _resolve_stop_order(active, route_dto)
    missing = [s for s in stops if not s['location_valid']]
    valid = [s for s in stops if s['location_valid']]

    return {
        'plan_id': plan_id,
        'plan_date': plan_date,
        'vehicle_id': str(vehicle_id),
        'vehicle_external_id': str(vehicle_id),
        'plate': plan_row.get('arac_plaka_snapshot') or '—',
        'driver_name': plan_row.get('sofor_adi_snapshot') or '—',
        'departure_time': plan_row.get('cikis_saati'),
        'base_start': {
            'name': base.get('base_name') or 'Fabrika',
            'address': base.get('base_address') or '',
            'latitude': base.get('latitude'),
            'longitude': base.get('longitude'),
            'location_valid': bool(base.get('has_coordinates')),
            'safe_maps_url': safe_maps_open_url(base.get('latitude'), base.get('longitude')),
        },
        'base_end': {
            'name': base.get('base_name') or 'Fabrika',
            'label': 'Dönüş',
            'latitude': base.get('latitude'),
            'longitude': base.get('longitude'),
            'location_valid': bool(base.get('has_coordinates')),
            'safe_maps_url': safe_maps_open_url(base.get('latitude'), base.get('longitude')),
        },
        'stops': stops,
        'valid_location_stops': valid,
        'missing_location_stops': missing,
        'completeness': {
            'total_active': len(stops),
            'valid': len(valid),
            'missing': len(missing),
        },
        'provider_status': provider_status,
        'provider_message': route_dto.get('message') or '',
        'route_fallback': route_fallback,
        'route_fallback_message': (
            'Güzergâh çizgisi oluşturulamadı; duraklar plan sırasıyla gösteriliy.'
            if route_fallback else ''
        ),
        'route_geometry': (route_dto.get('current') or {}).get('geometry') or [],
        'item_id_order': [int(s['plan_item_id']) for s in stops if s.get('plan_item_id')],
        'ors_configured': ors_key_present(),
    }


def build_driver_map_page_url(plan_date: str, vehicle_id: str, plan_id: int, *, external: bool = True) -> str:
    from modules.planlama.arac_driver_map_token import sign_driver_map_token

    token = sign_driver_map_token(plan_date, vehicle_id, plan_id)
    rel = (
        f'/planlama/arac-takip/sofor-haritasi'
        f'?date={plan_date[:10]}&vehicle_id={vehicle_id}&plan_id={int(plan_id)}&t={token}'
    )
    if not external:
        return rel
    try:
        from flask import has_request_context, request, url_for
        if has_request_context():
            return url_for(
                'arac_takip_bp.arac_takip_sofor_haritasi',
                date=plan_date[:10],
                vehicle_id=str(vehicle_id),
                plan_id=int(plan_id),
                t=token,
                _external=True,
            )
        from flask import current_app
        with current_app.app_context():
            with current_app.test_request_context(base_url='http://127.0.0.1:8080'):
                return url_for(
                    'arac_takip_bp.arac_takip_sofor_haritasi',
                    date=plan_date[:10],
                    vehicle_id=str(vehicle_id),
                    plan_id=int(plan_id),
                    t=token,
                    _external=True,
                )
    except Exception:
        return f'http://127.0.0.1:8080{rel}'
