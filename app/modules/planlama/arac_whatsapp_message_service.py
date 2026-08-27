# -*- coding: utf-8 -*-
"""ATP WhatsApp plan message — read-only canonical context + plain-text builder (V2)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from modules.planlama.arac_dashboard_service import _date_label
from modules.planlama.arac_location_resolver import resolve_base_location
from modules.planlama.arac_plan_service import whatsapp_web_url
from modules.planlama.arac_takip_repo import (
    INACTIVE_PLAN_STATUSES,
    get_active_plan_row,
    list_plan_tasks,
    tables_ready,
)

_MISSING_LOCATION = 'Konum tanımlanmamış'
_MISSING_BASE = 'Başlangıç noktası tanımlanmamış'
_DASH = '—'

RETURN_SOURCE_NONE = 'none'
RETURN_SOURCE_TIMELINE = 'timeline'
RETURN_SOURCE_ROUTE_SNAPSHOT = 'route_snapshot'

RETURN_SCOPE_KEY = ('plan_date', 'vehicle_external_id', 'plan_id')


def _valid_coord(lat: Any, lng: Any) -> bool:
    try:
        if lat is None or lng is None:
            return False
        float(lat)
        float(lng)
        return True
    except (TypeError, ValueError):
        return False


def format_coordinate(value: float) -> str:
    """Google Maps q= — trimmed decimal, no excessive precision."""
    text = f'{float(value):.6f}'.rstrip('0').rstrip('.')
    if text == '-0':
        return '0'
    return text


def maps_link_from_coordinates(lat: Any, lng: Any) -> str | None:
    if not _valid_coord(lat, lng):
        return None
    return (
        f'https://www.google.com/maps?q='
        f'{format_coordinate(float(lat))},{format_coordinate(float(lng))}'
    )


def resolve_stop_location_link(task: dict) -> str:
    link = maps_link_from_coordinates(task.get('latitude'), task.get('longitude'))
    if link:
        return link
    url = (task.get('location_url') or task.get('konum_linki') or '').strip()
    if url:
        return url
    return _MISSING_LOCATION


def resolve_stop_eta(task: dict) -> str:
    for key in ('tahmini_varis_saati', 'eta_time', 'istenen_varis_saati', 'planned_time'):
        val = task.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text and text != _DASH:
            return text
    return _DASH


def _stop_sort_key(task: dict) -> tuple:
    display_no = task.get('display_order_no')
    if display_no is not None:
        try:
            return (0, int(display_no), int(task.get('plan_item_id') or 0))
        except (TypeError, ValueError):
            pass
    order_no = task.get('order_no')
    try:
        if order_no is not None and int(order_no) > 0:
            return (1, int(order_no), int(task.get('plan_item_id') or 0))
    except (TypeError, ValueError):
        pass
    pt = (task.get('planned_time') or '').strip()
    pt_sort = pt if pt and pt != _DASH else '99:99'
    return (2, pt_sort, int(task.get('plan_item_id') or 0))


def filter_active_stops(tasks: list[dict]) -> list[dict]:
    return [
        t for t in tasks
        if (t.get('status') or 'PLANLANDI').upper() not in INACTIVE_PLAN_STATUSES
    ]


def sort_stops_for_whatsapp(tasks: list[dict]) -> list[dict]:
    active = filter_active_stops(tasks)
    return sorted(active, key=_stop_sort_key)


def resolve_base_maps_link(base: dict) -> str:
    link = maps_link_from_coordinates(base.get('latitude'), base.get('longitude'))
    if link:
        return link
    url = (base.get('base_maps_url') or '').strip()
    if url:
        return url
    return _MISSING_LOCATION


def _normalize_hhmm(value: str | None) -> str | None:
    if not value or value == _DASH:
        return None
    text = str(value).strip()[:5]
    return text if len(text) == 5 and text[2] == ':' else None


def format_return_time_display(
    plan_date: str,
    departure_hhmm: str | None,
    return_hhmm: str | None,
    *,
    return_dt=None,
) -> str | None:
    """WhatsApp dönüş satırı — gece yarısı geçişinde (ertesi gün) etiketi."""
    if not return_hhmm:
        return None
    dep_norm = _normalize_hhmm(departure_hhmm)
    ret_norm = _normalize_hhmm(return_hhmm)
    if not dep_norm or not ret_norm:
        return ret_norm or return_hhmm

    from modules.planlama.arac_timeline_service import _parse_hhmm

    dep_dt = _parse_hhmm(plan_date, dep_norm)
    if dep_dt is None:
        return ret_norm

    if return_dt is None:
        ret_dt = _parse_hhmm(plan_date, ret_norm)
        if ret_dt is None:
            return ret_norm
        dep_min = dep_dt.hour * 60 + dep_dt.minute
        ret_min = ret_dt.hour * 60 + ret_dt.minute
        if ret_min <= dep_min:
            ret_dt = ret_dt + timedelta(days=1)
    else:
        ret_dt = return_dt

    if ret_dt.date() > dep_dt.date():
        return f'{ret_norm} (ertesi gün)'
    return ret_norm


def resolve_scoped_estimated_return(
    plan_date: str,
    vehicle_external_id: str,
    plan_id: int,
    departure_time: str | None,
    *,
    active_stop_count: int = 0,
    service_minutes: int | None = None,
) -> dict[str, Any]:
    """
    Tahmini dönüş — yalnız seçili plan/date/vehicle kapsamından (read-only).

    Başka plan/araç/tarih fallback yok; güvenilir değer yoksa None.
    """
    invalid = {
        'estimated_return_time': None,
        'return_source': RETURN_SOURCE_NONE,
        'return_scope_valid': False,
    }
    if not plan_date or not vehicle_external_id or not plan_id:
        return invalid

    plan_row = get_active_plan_row(plan_date, str(vehicle_external_id))
    if not plan_row or int(plan_row.get('id') or 0) != int(plan_id):
        return invalid

    plan_dep = _normalize_hhmm(plan_row.get('cikis_saati'))
    req_dep = _normalize_hhmm(departure_time) or plan_dep
    if plan_dep and req_dep and plan_dep != req_dep:
        return invalid

    departure_hhmm = plan_dep or req_dep

    from modules.planlama.arac_timeline_service import (
        DEFAULT_STOP_SERVICE_MINUTES,
        TIMELINE_STATUS_OK,
        build_timeline_for_plan,
    )
    svc_min = (
        int(service_minutes)
        if service_minutes is not None
        else DEFAULT_STOP_SERVICE_MINUTES
    )
    try:
        timeline = build_timeline_for_plan(
            plan_date,
            str(vehicle_external_id),
            service_minutes=svc_min,
        )
    except Exception:
        timeline = {}

    tl_dep = _normalize_hhmm(timeline.get('plan_departure_time'))
    if tl_dep and plan_dep and tl_dep != plan_dep:
        return invalid

    if (
        timeline.get('timeline_complete')
        and timeline.get('status') == TIMELINE_STATUS_OK
        and timeline.get('estimated_return_time')
    ):
        from modules.planlama.arac_timeline_service import _parse_hhmm

        ret_hhmm = str(timeline['estimated_return_time']).strip()
        ret_dt = None
        dep_dt = _parse_hhmm(plan_date, departure_hhmm) if departure_hhmm else None
        total_s = timeline.get('estimated_total_seconds')
        if dep_dt is not None and total_s is not None:
            try:
                ret_dt = dep_dt + timedelta(seconds=float(total_s))
            except (TypeError, ValueError):
                ret_dt = None
        display = format_return_time_display(
            plan_date,
            departure_hhmm,
            ret_hhmm,
            return_dt=ret_dt,
        )
        return {
            'estimated_return_time': display,
            'return_source': RETURN_SOURCE_TIMELINE,
            'return_scope_valid': True,
        }

    snap_return = _return_from_scoped_route_snapshot(
        plan_date,
        int(plan_id),
        departure_hhmm,
        active_stop_count,
        service_minutes=svc_min,
    )
    if snap_return:
        return {
            'estimated_return_time': snap_return,
            'return_source': RETURN_SOURCE_ROUTE_SNAPSHOT,
            'return_scope_valid': True,
        }

    return invalid


def _return_from_scoped_route_snapshot(
    plan_date: str,
    plan_id: int,
    departure_hhmm: str | None,
    active_stop_count: int,
    *,
    service_minutes: int,
) -> str | None:
    """Applied route snapshot — yalnız verilen plan_id için."""
    if not departure_hhmm or active_stop_count <= 0:
        return None
    try:
        from modules.planlama.arac_gps_snapshot_repo import plan_rota_tables_ready
        from modules.planlama.arac_timeline_service import _fmt_ceil, _parse_hhmm
    except Exception:
        return None

    if not plan_rota_tables_ready():
        return None

    try:
        from modules.planlama.arac_takip_repo import get_conn

        con = get_conn()
        try:
            row = con.execute(
                """
                SELECT total_duration_s FROM arac_plan_rota_snapshot
                WHERE plan_id=? AND is_active=1
                ORDER BY route_version DESC LIMIT 1
                """,
                (int(plan_id),),
            ).fetchone()
        finally:
            con.close()
        if not row or row[0] is None:
            return None
        total_duration_s = float(row[0])
    except Exception:
        return None

    dep_dt = _parse_hhmm(plan_date, departure_hhmm)
    if dep_dt is None:
        return None

    try:
        drive_s = max(0.0, total_duration_s)
        service_s = max(0, int(active_stop_count)) * max(0, int(service_minutes)) * 60
        ret_dt = dep_dt + timedelta(seconds=drive_s + service_s)
    except (TypeError, ValueError):
        return None

    ret_hhmm = _fmt_ceil(ret_dt)
    return format_return_time_display(
        plan_date,
        departure_hhmm,
        ret_hhmm,
        return_dt=ret_dt,
    )


def build_base_section(base: dict, *, heading: str) -> list[str]:
    if not base.get('configured'):
        return [f'🏭 *{heading}*', _MISSING_BASE, '']
    name = (base.get('base_name') or 'Fabrika').strip()
    return [
        f'🏭 *{heading}: {name}*',
        f'📍 {resolve_base_maps_link(base)}',
        '',
    ]


def build_whatsapp_plan_message_v2(context: dict[str, Any]) -> str:
    """Plain-text WhatsApp message — safe *bold* only, no HTML."""
    lines: list[str] = [
        '🚚 *GÜNLÜK ARAÇ PROGRAMI*',
        f"📅 Tarih: {context.get('date_label') or context.get('plan_date') or _DASH}",
        f"🚘 Plaka: {context.get('plate') or _DASH}",
        f"👤 Sürücü: {context.get('driver_name') or _DASH}",
        f"🕐 Çıkış: {context.get('departure_time') or _DASH}",
        '',
    ]
    lines.extend(build_base_section(context.get('base') or {}, heading='Başlangıç'))

    for stop in context.get('stops') or []:
        label_no = stop.get('display_order_no') or stop.get('order_no') or '?'
        company = (stop.get('company_name') or '—').strip()
        job = (stop.get('job_title') or stop.get('yapilacak_is') or '—').strip()
        eta = resolve_stop_eta(stop)
        loc = resolve_stop_location_link(stop)
        lines.append(f'*{label_no}. {company}*')
        lines.append(f'İş: {job}')
        lines.append(f'ETA: {eta}')
        if stop.get('phone'):
            lines.append(f'Telefon: {stop["phone"]}')
        addr = (stop.get('address_text') or stop.get('adres') or '').strip()
        if addr and addr not in (loc, _MISSING_LOCATION):
            lines.append(f'Adres: {addr}')
        lines.append(f'📍 {loc}')
        lines.append('')

    base = context.get('base') or {}
    if base.get('configured'):
        name = (base.get('base_name') or 'Fabrika').strip()
        lines.append(f'🏭 *Dönüş: {name}*')
    else:
        lines.append('🏭 *Dönüş*')
        lines.append(_MISSING_BASE)
    ret = context.get('estimated_return_time')
    lines.append(f'Tahmini dönüş: {ret if ret else _DASH}')
    if base.get('configured'):
        lines.append(f'📍 {resolve_base_maps_link(base)}')
    return '\n'.join(lines).strip()


def load_whatsapp_plan_context(plan_date: str, vehicle_id: str) -> dict[str, Any] | None:
    """Read-only canonical context — no DOM, no DB writes."""
    if not tables_ready() or not plan_date or not vehicle_id:
        return None

    plan_row = get_active_plan_row(plan_date, str(vehicle_id))
    if not plan_row:
        return None

    tasks = list_plan_tasks(plan_date, str(vehicle_id))
    stops = sort_stops_for_whatsapp(tasks)

    base_row = None
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    if operasyon_ayar_ready():
        base_row = get_active_base()
    base = resolve_base_location(base_row)

    plan_id = int(plan_row.get('id') or 0)
    return_info = resolve_scoped_estimated_return(
        plan_date,
        str(vehicle_id),
        plan_id,
        plan_row.get('cikis_saati'),
        active_stop_count=len(stops),
    )

    try:
        d = date.fromisoformat(plan_date[:10])
        date_label = _date_label(d)
    except ValueError:
        date_label = plan_date

    return {
        'plan_id': plan_id,
        'plan_date': plan_date,
        'vehicle_external_id': str(vehicle_id),
        'date_label': date_label,
        'vehicle_id': str(vehicle_id),
        'plate': plan_row.get('arac_plaka_snapshot') or _DASH,
        'driver_name': plan_row.get('sofor_adi_snapshot') or _DASH,
        'departure_time': plan_row.get('cikis_saati') or None,
        'base': base,
        'stops': stops,
        'estimated_return_time': return_info.get('estimated_return_time'),
        'return_source': return_info.get('return_source', RETURN_SOURCE_NONE),
        'return_scope_valid': bool(return_info.get('return_scope_valid')),
    }


def _whatsapp_order_ids(stops: list[dict]) -> list[str]:
    ids: list[str] = []
    for stop in stops:
        raw = stop.get('plan_item_id') or stop.get('id')
        if raw is None:
            continue
        ids.append(str(raw))
    return ids


def build_whatsapp_payload(
    plan_date: str,
    vehicle_id: str,
    *,
    phone: str = '',
) -> dict[str, Any] | None:
    context = load_whatsapp_plan_context(plan_date, vehicle_id)
    if context is None:
        return None
    message = build_whatsapp_plan_message_v2(context)
    return {
        'ok': True,
        'message': message,
        'whatsapp_url': whatsapp_web_url(message, phone),
        'context': context,
    }


def build_whatsapp_api_response(
    plan_date: str,
    vehicle_id: str,
    *,
    phone: str = '',
) -> dict[str, Any]:
    """Public /api/whatsapp body — no plain-text message field."""
    payload = build_whatsapp_payload(plan_date, vehicle_id, phone=phone)
    if payload is None:
        return {
            'ok': False,
            'code': 'PLAN_NOT_FOUND',
            'error': 'Plan bulunamadı',
        }

    context = payload.get('context') or {}
    stops = context.get('stops') or []
    whatsapp_url = (payload.get('whatsapp_url') or '').strip()
    if not whatsapp_url.startswith('https://'):
        return {
            'ok': False,
            'code': 'WHATSAPP_URL_INVALID',
            'error': 'WhatsApp planı hazırlanamadı.',
        }

    return {
        'ok': True,
        'whatsapp_url': whatsapp_url,
        'vehicle_external_id': str(context.get('vehicle_external_id') or vehicle_id),
        'plan_id': context.get('plan_id'),
        'stop_count': len(stops),
        'order_ids': _whatsapp_order_ids(stops),
    }
