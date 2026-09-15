# -*- coding: utf-8 -*-
"""R07 — traffic-aware constrained route proposal (single backend source)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from modules.planlama.arac_route_constraints import (
    active_tasks_sorted,
    build_r07_constrained_full_order,
    classify_route_tasks,
    load_visit_states_for_tasks,
    normalize_priority,
)
from modules.planlama.road_routing.env_loader import google_routes_key_present, ors_key_present
from modules.planlama.road_routing.google_route_matrix import compute_google_traffic_matrix
from modules.planlama.road_routing.google_routes_provider import (
    PROFILE_TRAFFIC_FAST,
    departure_utc_from_local,
    make_google_provider,
)
from modules.planlama.road_routing.route_planner_service import (
    _build_routable_points,
    _format_duration,
    _format_km,
    _route_points_with_return,
    _route_with_cache,
    get_routing_provider,
)
from modules.planlama.road_routing.suggest import suggest_segment_order
from modules.planlama.road_routing.traffic_proposal_cache import single_flight
from modules.planlama.road_routing.types import RoutingError

_TZ = ZoneInfo('Europe/Istanbul')
_TRAFFIC_CACHE_TTL_SEC = 300
_MAX_MATRIX_ELEMENTS = 625
_TRAFFIC_MODEL = 'TRAFFIC_AWARE_OPTIMAL'


def _now() -> datetime:
    return datetime.now(_TZ)


def _item_ids(tasks: list[dict], order: list[str]) -> list[int]:
    by_id = {str(t['id']): t for t in tasks}
    out: list[int] = []
    for tid in order:
        t = by_id.get(str(tid))
        if t and t.get('plan_item_id') is not None:
            out.append(int(t['plan_item_id']))
    return out


def _acil_violation_in_order(
    task_ids: list[str],
    tasks: list[dict],
    constraints: dict[str, Any],
) -> bool:
    """True when an unstarted ACIL appears after a normal eligible stop."""
    by_id = {str(t['id']): t for t in tasks}
    locked = set(constraints.get('locked_task_ids') or [])
    critical = set(constraints.get('critical_task_ids') or [])
    eligible = set(constraints.get('eligible_task_ids') or [])
    seen_eligible_normal = False
    for tid in task_ids:
        if tid in locked:
            continue
        task = by_id.get(str(tid))
        if not task:
            continue
        pri = normalize_priority(task.get('priority'))
        if str(tid) in critical and pri == 'ACIL':
            if seen_eligible_normal:
                return True
        elif str(tid) in eligible and pri != 'ACIL':
            seen_eligible_normal = True
    return False


def _duration_delta_seconds(cur_tot: dict, sug_tot: dict) -> float | None:
    cur_d = cur_tot.get('total_duration_seconds')
    sug_d = sug_tot.get('total_duration_seconds')
    if cur_d is None or sug_d is None:
        return None
    return round(float(cur_d) - float(sug_d), 1)


def _distance_delta_meters(cur_tot: dict, sug_tot: dict) -> float | None:
    cur_m = cur_tot.get('total_distance_meters')
    sug_m = sug_tot.get('total_distance_meters')
    if cur_m is None or sug_m is None:
        return None
    return round(float(cur_m) - float(sug_m), 1)


def _km_display(km: float) -> str:
    return str(round(float(km), 1)).replace('.', ',')


def _format_time_delta_label(seconds_saved: float | None) -> str:
    """Signed duration delta; positive = savings, negative = increase."""
    if seconds_saved is None:
        return '—'
    s = float(seconds_saved)
    if abs(s) < 0.05:
        return '0 sn'
    abs_s = abs(s)
    if abs_s < 60:
        n = int(round(abs_s))
        return f'{n} sn kazanç' if s > 0 else f'{n} sn artış'
    mins = int(abs_s // 60)
    secs = int(round(abs_s % 60))
    if secs == 60:
        mins += 1
        secs = 0
    core = f'{mins} dk' if secs == 0 else f'{mins} dk {secs} sn'
    return f'{core} kazanç' if s > 0 else f'{core} artış'


def _format_time_faster_label(seconds_saved: float | None) -> str:
    if seconds_saved is None:
        return '—'
    s = float(seconds_saved)
    if abs(s) < 0.05:
        return '0 sn'
    if s < 0:
        return _format_time_delta_label(s)
    if s < 60:
        return f'{int(round(s))} sn daha hızlı'
    mins = int(s // 60)
    secs = int(round(s % 60))
    if secs == 60:
        mins += 1
        secs = 0
    if secs == 0:
        return f'{mins} dk daha hızlı'
    return f'{mins} dk {secs} sn daha hızlı'


def _format_distance_delta_label(delta_m: float | None) -> str:
    """Positive = current route shorter."""
    if delta_m is None:
        return '—'
    d = float(delta_m)
    if abs(d) < 0.5:
        return '0 km'
    km_str = _km_display(abs(d) / 1000.0)
    if d > 0:
        return f'{km_str} km daha kısa'
    return f'{km_str} km daha uzun'


def _format_comparison_label(delta_m: float | None, seconds_saved: float | None) -> str:
    parts: list[str] = []
    dist = _format_distance_delta_label(delta_m)
    if dist not in ('—', '0 km'):
        parts.append(dist)
    if seconds_saved is not None and abs(float(seconds_saved)) >= 0.05:
        if float(seconds_saved) > 0:
            parts.append(_format_time_faster_label(seconds_saved))
        else:
            parts.append(_format_time_delta_label(seconds_saved))
    return ' · '.join(parts) if parts else '—'


def _format_traffic_compare_label(
    cur_dur_label: str,
    sug_dur_label: str,
    time_delta_label: str,
) -> str:
    return f'Mevcut: {cur_dur_label} · Önerilen: {sug_dur_label} · {time_delta_label}'


def _attach_proposal_metric_labels(
    proposal: dict[str, Any],
    cur_tot: dict[str, float | None],
    sug_tot: dict[str, float | None],
) -> dict[str, Any]:
    cur_d = cur_tot.get('total_duration_seconds')
    sug_d = sug_tot.get('total_duration_seconds')
    cur_m = cur_tot.get('total_distance_meters')
    sug_m = sug_tot.get('total_distance_meters')
    dist_delta = _distance_delta_meters(cur_tot, sug_tot)
    time_saved = proposal.get('time_saved_seconds')
    cur_dur_label = _format_duration(cur_d)
    sug_dur_label = _format_duration(sug_d)
    time_delta_label = _format_time_delta_label(time_saved)
    proposal['current_total_distance_meters'] = cur_m
    proposal['suggested_total_distance_meters'] = sug_m
    proposal['distance_delta_meters'] = dist_delta
    proposal['current_duration_label'] = cur_dur_label
    proposal['suggested_duration_label'] = sug_dur_label
    proposal['time_delta_label'] = time_delta_label
    proposal['distance_delta_label'] = _format_distance_delta_label(dist_delta)
    proposal['comparison_label'] = _format_comparison_label(dist_delta, time_saved)
    proposal['traffic_compare_label'] = _format_traffic_compare_label(
        cur_dur_label, sug_dur_label, time_delta_label,
    )
    return proposal


def sync_route_dto_metrics_from_traffic_proposal(
    route_dto: dict[str, Any],
    traffic_proposal: dict[str, Any],
) -> dict[str, Any]:
    """Overwrite route card metrics with traffic proposal matrix totals."""
    if not traffic_proposal:
        return route_dto
    # Google/ORS routing fallback sonuçları trafik matrisi toplamlarıyla ezilmez.
    if route_dto.get('route_fallback_provider'):
        return route_dto
    if traffic_proposal.get('provider') == 'current_order_fallback':
        return route_dto
    if traffic_proposal.get('current_total_duration_seconds') is None:
        return route_dto

    route_dto.setdefault('current', {})
    route_dto.setdefault('suggested', {})
    route_dto.setdefault('gain', {})

    cur_dist = traffic_proposal.get('current_total_distance_meters')
    sug_dist = traffic_proposal.get('suggested_total_distance_meters')
    if sug_dist is None:
        sug_dist = traffic_proposal.get('total_distance_meters')

    if cur_dist is not None:
        route_dto['current']['km'] = _format_km(cur_dist)
    if sug_dist is not None:
        route_dto['suggested']['km'] = _format_km(sug_dist)

    route_dto['current']['duration_label'] = traffic_proposal.get('current_duration_label') or _format_duration(
        traffic_proposal.get('current_total_duration_seconds'),
    )
    route_dto['suggested']['duration_label'] = traffic_proposal.get('suggested_duration_label') or _format_duration(
        traffic_proposal.get('suggested_total_duration_seconds'),
    )

    dist_delta = traffic_proposal.get('distance_delta_meters')
    if dist_delta is not None:
        route_dto['gain']['km'] = round(float(dist_delta) / 1000.0, 1)

    route_dto['gain']['duration_label'] = traffic_proposal.get('time_delta_label')
    route_dto['gain']['time_delta_label'] = traffic_proposal.get('time_delta_label')
    route_dto['gain']['distance_label'] = traffic_proposal.get('distance_delta_label')
    route_dto['gain']['comparison_label'] = traffic_proposal.get('comparison_label')
    route_dto['gain']['pct'] = None
    route_dto['gain']['duration_min'] = None
    route_dto['metrics_source'] = 'traffic_proposal'
    return route_dto


def _finalize_proposal_contract(
    *,
    active: list[dict],
    current_ids: list[str],
    suggested_ids: list[str],
    constraints: dict[str, Any],
    cur_tot: dict[str, float | None],
    sug_tot: dict[str, float | None],
    changed: bool,
) -> dict[str, Any]:
    """
    Enforce R07 safe proposal contract:
    - NO_IMPROVEMENT when normal route would not shorten duration
    - URGENT_PRIORITY when ACIL rule requires reorder (duration may increase)
    """
    acil_violation = _acil_violation_in_order(current_ids, active, constraints)
    time_saved = _duration_delta_seconds(cur_tot, sug_tot)
    cur_d = cur_tot.get('total_duration_seconds')
    sug_d = sug_tot.get('total_duration_seconds')
    eligible_count = len(constraints.get('eligible_task_ids') or [])

    out_suggested = list(suggested_ids)
    out_sug_tot = dict(sug_tot)
    out_changed = changed
    proposal_reason = 'TRAFFIC_IMPROVEMENT'
    user_message: str | None = None
    fallback_reason: str | None = None
    apply_enabled = changed and eligible_count >= 2

    if acil_violation:
        proposal_reason = 'URGENT_PRIORITY'
        if time_saved is not None and time_saved < 0:
            increase_min = max(1, int(round(abs(time_saved) / 60.0)))
            user_message = (
                f'ACİL önceliği nedeniyle rota sırası değişiyor; '
                f'toplam süre {increase_min} dakika artabilir.'
            )
        apply_enabled = out_changed and eligible_count >= 1
    elif cur_d is not None and sug_d is not None and float(sug_d) >= float(cur_d) - 0.05:
        out_suggested = list(current_ids)
        out_sug_tot = dict(cur_tot)
        out_changed = False
        time_saved = 0.0
        proposal_reason = 'NO_IMPROVEMENT'
        user_message = 'Mevcut rota trafik koşullarına göre zaten uygun.'
        fallback_reason = 'NO_IMPROVEMENT'
        apply_enabled = False

    return {
        'suggested_ids': out_suggested,
        'sug_tot': out_sug_tot,
        'changed': out_changed,
        'time_saved_seconds': time_saved,
        'proposal_reason': proposal_reason,
        'user_message': user_message,
        'fallback_reason': fallback_reason,
        'apply_enabled': apply_enabled,
    }


def _route_totals(
    order_ids: list[str],
    routable_by_id: dict[str, dict],
    matrix_d: list[list[float | None]],
    matrix_dist: list[list[float | None]] | None,
    static_matrix: list[list[float | None]] | None,
    start_index: int = 0,
) -> dict[str, float | None]:
    if len(order_ids) < 1:
        return {
            'total_duration_seconds': None,
            'total_distance_meters': None,
            'static_duration_seconds': None,
            'traffic_delay_seconds': None,
        }
    total_d = 0.0
    total_t = 0.0
    total_static = 0.0
    cur = start_index
    for tid in order_ids:
        stop = routable_by_id.get(str(tid))
        if not stop:
            continue
        nxt = int(stop['matrix_index'])
        dur = matrix_d[cur][nxt]
        if dur is None:
            return {
                'total_duration_seconds': None,
                'total_distance_meters': None,
                'static_duration_seconds': None,
                'traffic_delay_seconds': None,
            }
        total_t += float(dur)
        if static_matrix:
            st = static_matrix[cur][nxt]
            if st is not None:
                total_static += float(st)
        if matrix_dist and matrix_dist[cur][nxt] is not None:
            total_d += float(matrix_dist[cur][nxt])
        cur = nxt
    if cur != start_index:
        ret_dur = matrix_d[cur][start_index]
        if ret_dur is None:
            return {
                'total_duration_seconds': None,
                'total_distance_meters': None,
                'static_duration_seconds': None,
                'traffic_delay_seconds': None,
            }
        total_t += float(ret_dur)
        if static_matrix:
            ret_static = static_matrix[cur][start_index]
            if ret_static is not None:
                total_static += float(ret_static)
        if matrix_dist and matrix_dist[cur][start_index] is not None:
            total_d += float(matrix_dist[cur][start_index])
    delay = (total_t - total_static) if total_static > 0 else None
    return {
        'total_duration_seconds': round(total_t, 1),
        'total_distance_meters': round(total_d, 1) if total_d else None,
        'static_duration_seconds': round(total_static, 1) if total_static else None,
        'traffic_delay_seconds': round(delay, 1) if delay is not None else None,
    }


def build_proposal_state_hash(
    *,
    plan_id: int | None,
    plan_date: str,
    vehicle_id: str,
    tasks: list[dict],
    visit_states: dict[int, dict] | None = None,
) -> str:
    active = active_tasks_sorted(tasks)
    payload = {
        'plan_id': plan_id,
        'plan_date': plan_date,
        'vehicle_id': vehicle_id,
        'items': [
            {
                'id': str(t['id']),
                'plan_item_id': t.get('plan_item_id'),
                'order_no': t.get('order_no'),
                'status': (t.get('status') or 'PLANLANDI').upper(),
                'priority': (t.get('priority') or 'NORMAL').upper(),
                'lat': t.get('latitude'),
                'lon': t.get('longitude'),
                'visit_state': (visit_states or {}).get(int(t.get('plan_item_id') or 0), {}).get('state'),
            }
            for t in active
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def build_proposal_cache_key(
    *,
    plan_id: int | None,
    plan_date: str,
    vehicle_id: str,
    state_hash: str,
    departure_hhmm: str | None,
) -> str:
    bucket = int(_now().timestamp() // _TRAFFIC_CACHE_TTL_SEC)
    raw = json.dumps({
        'plan_id': plan_id,
        'plan_date': plan_date,
        'vehicle_id': vehicle_id,
        'state_hash': state_hash,
        'departure': departure_hhmm or '',
        'bucket': bucket,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _fallback_proposal(
    *,
    tasks: list[dict],
    current_ids: list[str],
    reason: str,
    warnings: list[dict] | None = None,
    plan_id: int | None = None,
    plan_date: str = '',
    vehicle_id: str = '',
    visit_states: dict | None = None,
) -> dict[str, Any]:
    now = _now()
    state_hash = build_proposal_state_hash(
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
        tasks=tasks, visit_states=visit_states,
    )
    return {
        'provider': 'current_order_fallback',
        'traffic_available': False,
        'traffic_model': None,
        'calculated_at': now.isoformat(),
        'expires_at': (now + timedelta(seconds=_TRAFFIC_CACHE_TTL_SEC)).isoformat(),
        'proposal_id': state_hash[:16],
        'proposal_hash': state_hash,
        'current_item_ids': _item_ids(tasks, current_ids),
        'suggested_item_ids': _item_ids(tasks, current_ids),
        'suggested_task_ids': list(current_ids),
        'current_task_ids': list(current_ids),
        'changed': False,
        'total_distance_meters': None,
        'total_duration_seconds': None,
        'current_total_duration_seconds': None,
        'suggested_total_duration_seconds': None,
        'static_duration_seconds': None,
        'traffic_delay_seconds': None,
        'time_saved_seconds': None,
        'fallback_reason': reason,
        'warnings': warnings or [],
        'missing_location_item_ids': [
            int(t['plan_item_id']) for t in active_tasks_sorted(tasks)
            if not t.get('latitude') or not t.get('longitude')
        ],
        'apply_enabled': False,
        'proposal_reason': 'PROVIDER_UNAVAILABLE',
        'user_message': None,
        'matrix_element_count': 0,
        'google_call_count': 0,
        'cache_hit': False,
    }


def _compute_with_matrix(
    *,
    base: dict,
    tasks: list[dict],
    constraints: dict,
    points: list[tuple[float, float]],
    routable: list[dict],
    duration_matrix: list[list[float | None]],
    distance_matrix: list[list[float | None]] | None,
    static_matrix: list[list[float | None]] | None,
    provider: str,
    traffic_available: bool,
    traffic_model: str | None,
    warnings: list[dict],
    matrix_elements: int,
    google_calls: int,
    plan_id: int | None,
    plan_date: str,
    vehicle_id: str,
    visit_states: dict,
    cache_hit: bool,
) -> dict[str, Any]:
    active = active_tasks_sorted(tasks)
    current_ids = [str(t['id']) for t in active]
    try:
        suggested_ids, opt_warnings = build_r07_constrained_full_order(
            active,
            constraints,
            routable,
            duration_matrix,
            suggest_segment_order_fn=suggest_segment_order,
        )
        warnings.extend(opt_warnings)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        suggested_ids = list(current_ids)
        warnings.append({'code': 'OPTIMIZATION_ERROR', 'message': str(exc)})
    routable_by_id = {str(s['id']): s for s in routable}
    start_idx = 0
    cur_tot = _route_totals(current_ids, routable_by_id, duration_matrix, distance_matrix, static_matrix, start_idx)
    sug_tot = _route_totals(
        [tid for tid in suggested_ids if tid in routable_by_id],
        routable_by_id,
        duration_matrix,
        distance_matrix,
        static_matrix,
        start_idx,
    )
    changed = current_ids != suggested_ids
    finalized = _finalize_proposal_contract(
        active=active,
        current_ids=current_ids,
        suggested_ids=suggested_ids,
        constraints=constraints,
        cur_tot=cur_tot,
        sug_tot=sug_tot,
        changed=changed,
    )
    suggested_ids = finalized['suggested_ids']
    sug_tot = finalized['sug_tot']
    changed = finalized['changed']
    time_saved = finalized['time_saved_seconds']
    proposal_reason = finalized['proposal_reason']
    user_message = finalized['user_message']
    fallback_reason = finalized['fallback_reason']
    apply_enabled = finalized['apply_enabled']

    now = _now()
    state_hash = build_proposal_state_hash(
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
        tasks=tasks, visit_states=visit_states,
    )

    proposal = {
        'provider': provider,
        'traffic_available': traffic_available,
        'traffic_model': traffic_model,
        'calculated_at': now.isoformat(),
        'expires_at': (now + timedelta(seconds=_TRAFFIC_CACHE_TTL_SEC)).isoformat(),
        'proposal_id': state_hash[:16],
        'proposal_hash': state_hash,
        'current_item_ids': _item_ids(tasks, current_ids),
        'suggested_item_ids': _item_ids(tasks, suggested_ids),
        'suggested_task_ids': suggested_ids,
        'current_task_ids': current_ids,
        'changed': changed,
        'total_distance_meters': sug_tot.get('total_distance_meters'),
        'total_duration_seconds': sug_tot.get('total_duration_seconds'),
        'current_total_duration_seconds': cur_tot.get('total_duration_seconds'),
        'suggested_total_duration_seconds': sug_tot.get('total_duration_seconds'),
        'static_duration_seconds': sug_tot.get('static_duration_seconds'),
        'traffic_delay_seconds': sug_tot.get('traffic_delay_seconds'),
        'time_saved_seconds': time_saved,
        'fallback_reason': fallback_reason if not changed else None,
        'proposal_reason': proposal_reason,
        'user_message': user_message,
        'warnings': warnings,
        'missing_location_item_ids': [
            int(t['plan_item_id']) for t in active
            if not t.get('latitude') or not t.get('longitude')
        ],
        'apply_enabled': apply_enabled,
        'matrix_element_count': matrix_elements,
        'google_call_count': google_calls,
        'cache_hit': cache_hit,
    }
    return _attach_proposal_metric_labels(proposal, cur_tot, sug_tot)


def compute_traffic_route_proposal(
    *,
    base: dict,
    tasks: list[dict],
    plan_date: str,
    vehicle_id: str,
    plan_id: int | None = None,
    departure_hhmm: str | None = None,
    matrix_provider_fn: Callable | None = None,
    ors_provider_fn: Callable | None = None,
) -> dict[str, Any]:
    """Single traffic-aware proposal entry point."""
    visit_states = load_visit_states_for_tasks(tasks)
    constraints = classify_route_tasks(tasks, visit_states)
    active = active_tasks_sorted(tasks)
    current_ids = [str(t['id']) for t in active]
    warnings: list[dict] = []

    if not base.get('has_coordinates'):
        return _fallback_proposal(
            tasks=tasks, current_ids=current_ids, reason='NO_BASE',
            plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id, visit_states=visit_states,
        )

    points, routable, missing, meta = _build_routable_points(base, active)
    if len(routable) < 2:
        return _fallback_proposal(
            tasks=tasks, current_ids=current_ids, reason='NO_ELIGIBLE_REORDER',
            warnings=[{'code': 'MISSING_COORDINATES', 'count': meta.get('missing_count', 0)}],
            plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id, visit_states=visit_states,
        )

    n = len(points)
    if n * n > _MAX_MATRIX_ELEMENTS:
        return _fallback_proposal(
            tasks=tasks, current_ids=current_ids, reason='MATRIX_TOO_LARGE',
            warnings=[{'code': 'MATRIX_TOO_LARGE', 'elements': n * n, 'limit': _MAX_MATRIX_ELEMENTS}],
            plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id, visit_states=visit_states,
        )

    state_hash = build_proposal_state_hash(
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
        tasks=tasks, visit_states=visit_states,
    )
    cache_key = build_proposal_cache_key(
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
        state_hash=state_hash, departure_hhmm=departure_hhmm,
    )

    def _calc() -> dict[str, Any]:
        return _compute_proposal_inner(
            base=base,
            tasks=tasks,
            plan_date=plan_date,
            vehicle_id=vehicle_id,
            plan_id=plan_id,
            departure_hhmm=departure_hhmm,
            constraints=constraints,
            visit_states=visit_states,
            points=points,
            routable=routable,
            warnings=list(warnings),
            matrix_provider_fn=matrix_provider_fn,
            ors_provider_fn=ors_provider_fn,
        )

    result, cache_hit = single_flight(cache_key, _calc)
    result['cache_hit'] = cache_hit
    return result


def _compute_proposal_inner(
    *,
    base: dict,
    tasks: list[dict],
    plan_date: str,
    vehicle_id: str,
    plan_id: int | None,
    departure_hhmm: str | None,
    constraints: dict,
    visit_states: dict,
    points: list[tuple[float, float]],
    routable: list[dict],
    warnings: list[dict],
    matrix_provider_fn: Callable | None,
    ors_provider_fn: Callable | None,
) -> dict[str, Any]:
    active = active_tasks_sorted(tasks)
    current_ids = [str(t['id']) for t in active]

    dep_hhmm = (departure_hhmm or '08:00')[:5]
    dep_local = f'{plan_date}T{dep_hhmm}:00+03:00'
    try:
        dep_utc = departure_utc_from_local(dep_local)
    except Exception:
        dep_utc = departure_utc_from_local(f'{plan_date}T08:00:00+03:00')

    if google_routes_key_present():
        try:
            if matrix_provider_fn:
                try:
                    matrix, static_matrix, elements, gcalls = matrix_provider_fn(points, dep_utc)
                except TypeError:
                    matrix, static_matrix, elements, gcalls = matrix_provider_fn()
            else:
                from modules.planlama.road_routing.env_loader import load_routing_env
                import os
                load_routing_env()
                key = (os.environ.get('GOOGLE_ROUTES_API_KEY') or '').strip()
                matrix, static_matrix, elements = compute_google_traffic_matrix(
                    points, departure_utc=dep_utc, api_key=key,
                )
                gcalls = 1
            return _compute_with_matrix(
                base=base, tasks=tasks, constraints=constraints,
                points=points, routable=routable,
                duration_matrix=matrix.duration_s,
                distance_matrix=matrix.distance_m,
                static_matrix=static_matrix,
                provider='google_traffic',
                traffic_available=True,
                traffic_model=_TRAFFIC_MODEL,
                warnings=warnings,
                matrix_elements=elements,
                google_calls=gcalls,
                plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
                visit_states=visit_states,
                cache_hit=False,
            )
        except RoutingError as exc:
            warnings.append({'code': exc.code, 'message': str(exc)})

    prov = ors_provider_fn() if ors_provider_fn else get_routing_provider()
    if prov is not None and ors_key_present():
        try:
            matrix = prov.matrix(points)
            return _compute_with_matrix(
                base=base, tasks=tasks, constraints=constraints,
                points=points, routable=routable,
                duration_matrix=matrix.duration_s,
                distance_matrix=matrix.distance_m,
                static_matrix=None,
                provider='ors_no_traffic',
                traffic_available=False,
                traffic_model=None,
                warnings=warnings + [{'code': 'ORS_NO_TRAFFIC', 'message': 'Canlı trafik dahil değildir.'}],
                matrix_elements=len(points) * len(points),
                google_calls=0,
                plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
                visit_states=visit_states,
                cache_hit=False,
            )
        except RoutingError as exc:
            warnings.append({'code': exc.code, 'message': str(exc)})

    reason = warnings[-1]['code'] if warnings else 'PROVIDER_UNAVAILABLE'
    return _fallback_proposal(
        tasks=tasks, current_ids=current_ids, reason=reason,
        warnings=warnings,
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id, visit_states=visit_states,
    )


def validate_proposal_for_apply(
    *,
    tasks: list[dict],
    proposed_task_ids: list[str],
    proposal_hash: str | None,
    proposal_expires_at: str | None,
    plan_id: int | None,
    plan_date: str,
    vehicle_id: str,
) -> None:
    """Raise RouteApplyConflictError on stale/expired proposal."""
    from modules.planlama.arac_route_constraints import RouteApplyConflictError

    visit_states = load_visit_states_for_tasks(tasks)
    current_hash = build_proposal_state_hash(
        plan_id=plan_id, plan_date=plan_date, vehicle_id=vehicle_id,
        tasks=tasks, visit_states=visit_states,
    )
    if proposal_hash and proposal_hash != current_hash:
        raise RouteApplyConflictError(
            'STALE_PROPOSAL',
            'Plan durumu değişti; öneri güncel değil. Sayfayı yenileyin.',
            proposal_hash=proposal_hash,
            current_hash=current_hash,
        )
    if proposal_expires_at:
        try:
            exp = datetime.fromisoformat(proposal_expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_TZ)
            if _now() > exp:
                raise RouteApplyConflictError(
                    'STALE_PROPOSAL',
                    'Öneri süresi doldu; yeniden hesaplayın.',
                )
        except RouteApplyConflictError:
            raise
        except Exception:
            pass

    active_ordered = [str(t['id']) for t in active_tasks_sorted(tasks)]
    if [str(t) for t in proposed_task_ids] == active_ordered:
        return
    if not proposal_hash:
        return

    from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
    from modules.planlama.arac_location_resolver import resolve_base_location

    base_row = get_active_base() if operasyon_ayar_ready() else None
    base = resolve_base_location(base_row)
    fresh = compute_traffic_route_proposal(
        base=base,
        tasks=tasks,
        plan_date=plan_date,
        vehicle_id=vehicle_id,
        plan_id=plan_id,
    )
    fresh_ids = [str(t) for t in fresh.get('suggested_task_ids') or []]
    prop_ids = [str(t) for t in proposed_task_ids]
    if fresh_ids != prop_ids:
        if not fresh.get('apply_enabled') and fresh.get('proposal_reason') == 'NO_IMPROVEMENT':
            raise RouteApplyConflictError(
                'NO_IMPROVEMENT',
                fresh.get('user_message') or 'Mevcut rota trafik koşullarına göre zaten uygun.',
            )
        raise RouteApplyConflictError(
            'STALE_PROPOSAL',
            'Plan durumu değişti; öneri güncel değil. Sayfayı yenileyin.',
            proposal_hash=proposal_hash,
            current_hash=current_hash,
        )
    if not fresh.get('apply_enabled'):
        code = str(fresh.get('proposal_reason') or 'NO_IMPROVEMENT')
        message = fresh.get('user_message') or 'Mevcut rota trafik koşullarına göre zaten uygun.'
        raise RouteApplyConflictError(code, message)
