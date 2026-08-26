# -*- coding: utf-8 -*-
"""Araç Takip V1.4B — route planner service boundary."""
from __future__ import annotations

import os
from typing import Any

from modules.planlama.arac_route_constraints import (
    active_tasks_sorted,
    build_constrained_full_order,
    classify_route_tasks,
    load_visit_states_for_tasks,
)
from modules.planlama.road_routing.cache import cache_get, cache_set, make_cache_key
from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
from modules.planlama.road_routing.openrouteservice_provider import OpenRouteServiceProvider, provider_available
from modules.planlama.road_routing.provider_base import RoadRoutingProvider
from modules.planlama.road_routing.suggest import suggest_segment_order
from modules.planlama.road_routing.types import RouteResult, RoutingError


def _format_km(distance_m: float | None) -> str | float:
    if distance_m is None:
        return '—'
    return round(float(distance_m) / 1000.0, 1)


def _format_duration(duration_s: float | None) -> str:
    if duration_s is None:
        return '—'
    total_min = int(round(float(duration_s) / 60.0))
    if total_min < 60:
        return f'{total_min} dk'
    h, m = divmod(total_min, 60)
    if m:
        return f'{h} sa {m} dk'
    return f'{h} sa'


def get_routing_provider(force_mock: bool = False) -> RoadRoutingProvider | None:
    if force_mock:
        return MockRoadRoutingProvider()
    provider_name = (os.environ.get('ARAC_ROUTING_PROVIDER') or 'ors').strip().lower()
    if provider_name == 'mock':
        return MockRoadRoutingProvider()
    if provider_name == 'ors':
        if not provider_available():
            return None
        try:
            return OpenRouteServiceProvider()
        except RoutingError:
            return None
    return None


def routing_status_message(provider: RoadRoutingProvider | None) -> tuple[str, str | None]:
    if provider is None:
        if not provider_available() and (os.environ.get('ARAC_ROUTING_PROVIDER') or 'ors').lower() != 'mock':
            return 'UNCONFIGURED', 'Rota servisi yapılandırılmamış.'
        return 'UNAVAILABLE', 'Rota servisi kullanılamıyor.'
    return 'READY', None


def _route_points_with_return(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Round-trip route: base → stops → base. Matrix/optimization uses points without trailing base."""
    if len(points) < 2:
        return list(points)
    return list(points) + [points[0]]


def _build_routable_points(
    base: dict | None,
    tasks: list[dict],
) -> tuple[list[tuple[float, float]], list[dict], list[dict], dict[str, Any]]:
    """Returns depot+stop points [base, ...stops] for matrix; route adds return base leg separately."""
    routable: list[dict] = []
    missing: list[dict] = []
    if not base or not base.get('has_coordinates'):
        return [], [], [dict(t) for t in tasks], {
            'base_ready': False,
            'total_stops': len(tasks),
            'routable_count': 0,
            'missing_count': len(tasks),
            'return_leg_included': False,
            'route_points_start': None,
            'route_points_end': None,
        }
    points: list[tuple[float, float]] = [(float(base['latitude']), float(base['longitude']))]
    for t in sorted(tasks, key=lambda x: x.get('order_no') or 0):
        if t.get('has_coordinates') and t.get('latitude') is not None and t.get('longitude') is not None:
            points.append((float(t['latitude']), float(t['longitude'])))
            routable.append({
                **t,
                'matrix_index': len(points) - 1,
            })
        else:
            missing.append(dict(t))
    return points, routable, missing, {
        'base_ready': True,
        'total_stops': len(tasks),
        'routable_count': len(routable),
        'missing_count': len(missing),
        'return_leg_included': len(routable) > 0,
        'route_points_start': 'base',
        'route_points_end': 'base',
    }


def _route_with_cache(provider: RoadRoutingProvider, points: list[tuple[float, float]]) -> RouteResult:
    key = make_cache_key(provider.name, provider.profile, points)
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = provider.route_ordered(points)
    cache_set(key, result)
    return result


def _legs_for_stops(route: RouteResult, stop_count: int) -> list[dict]:
    """Map route legs to stop rows (leg i = point i -> point i+1). Index 0 leg is base->stop1."""
    out: list[dict] = []
    for i in range(stop_count):
        leg_idx = i
        if leg_idx < len(route.legs):
            lg = route.legs[leg_idx]
            out.append({
                'leg_index': leg_idx,
                'distance_m': lg.distance_m,
                'duration_s': lg.duration_s,
                'distance_km': _format_km(lg.distance_m),
                'duration_label': _format_duration(lg.duration_s),
            })
        else:
            out.append({
                'leg_index': leg_idx,
                'distance_m': None,
                'duration_s': None,
                'distance_km': '—',
                'duration_label': '—',
            })
    return out


def _order_labels(tasks: list[dict]) -> str:
    return ' → '.join(str(t.get('order_no') or '?') for t in tasks)


def _constraints_public(constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        'locked_task_ids': list(constraints.get('locked_task_ids') or []),
        'eligible_task_ids': list(constraints.get('eligible_task_ids') or []),
        'cancelled_task_ids': list(constraints.get('cancelled_task_ids') or []),
        'critical_task_ids': list(constraints.get('critical_task_ids') or []),
        'important_task_ids': list(constraints.get('important_task_ids') or []),
        'lock_reasons': dict(constraints.get('lock_reasons') or {}),
    }


def _routable_ids_in_full_order(full_order: list[str], routable: list[dict]) -> list[str]:
    routable_set = {str(s['id']) for s in routable}
    return [tid for tid in full_order if tid in routable_set]


def _resolve_apply_disabled(
    constraints: dict[str, Any],
    current_full_order: list[str],
    suggested_full_order: list[str],
) -> str | None:
    eligible = constraints.get('eligible_task_ids') or []
    if len(eligible) <= 1:
        return 'NO_ELIGIBLE_REORDER'
    if current_full_order == suggested_full_order:
        return 'ALREADY_OPTIMAL'
    return None


def build_plan_route_dto(
    base: dict | None,
    tasks: list[dict],
    provider: RoadRoutingProvider | None = None,
    force_mock: bool = False,
) -> dict[str, Any]:
    visit_states = load_visit_states_for_tasks(tasks)
    constraints = classify_route_tasks(tasks, visit_states)
    active_tasks = active_tasks_sorted(tasks)
    constraints_public = _constraints_public(constraints)

    prov = provider if provider is not None else get_routing_provider(force_mock=force_mock)
    status, message = routing_status_message(prov)
    points, routable, missing, meta = _build_routable_points(base, active_tasks)
    warnings: list[dict] = []

    empty_route: dict[str, Any] = {
        'status': status,
        'message': message,
        'partial': meta.get('missing_count', 0) > 0,
        'meta': meta,
        'constraints': constraints_public,
        'warnings': warnings,
        'current': {
            'km': '—', 'duration_label': '—', 'geometry': [], 'legs': [],
            'order_labels': _order_labels(active_tasks),
            'task_ids': [],
        },
        'suggested': {
            'km': '—', 'duration_label': '—', 'geometry': [], 'order_labels': '',
            'task_ids': [], 'apply_task_ids': [], 'apply_enabled': False,
            'apply_disabled_reason': 'NO_ELIGIBLE_REORDER',
        },
        'gain': {'km': '—', 'duration_label': '—', 'pct': '—'},
        'leg_details': [],
        'suggested_preview_only': True,
    }

    if prov is None:
        return empty_route

    if not meta['base_ready']:
        empty_route['message'] = 'Başlangıç noktası tanımlanmamış.'
        empty_route['status'] = 'NO_BASE'
        return empty_route

    if len(routable) == 0:
        empty_route['status'] = 'NO_STOPS'
        empty_route['message'] = 'Rota için koordinatlı durak yok.'
        return empty_route

    if len(points) < 2:
        empty_route['status'] = 'NO_ROUTE'
        return empty_route

    current_full_order = [str(t['id']) for t in active_tasks]

    try:
        current_route = _route_with_cache(prov, _route_points_with_return(points))
    except RoutingError as exc:
        empty_route['status'] = exc.code
        empty_route['message'] = str(exc) or 'Rota hesaplanamadı.'
        return empty_route

    leg_details = []
    for i, stop in enumerate(routable):
        leg = _legs_for_stops(current_route, len(routable))[i]
        leg_details.append({
            'task_id': stop.get('id'),
            'order_no': stop.get('order_no'),
            'company_name': stop.get('company_name'),
            **leg,
        })

    current_routable_ids = [str(s['id']) for s in routable]
    current_dto = {
        'km': _format_km(current_route.distance_m),
        'duration_label': _format_duration(current_route.duration_s),
        'distance_m': current_route.distance_m,
        'duration_s': current_route.duration_s,
        'geometry': current_route.geometry,
        'legs': [lg.to_dict() if hasattr(lg, 'to_dict') else {
            'from_index': lg.from_index, 'to_index': lg.to_index,
            'distance_m': lg.distance_m, 'duration_s': lg.duration_s,
        } for lg in current_route.legs],
        'order_labels': _order_labels(routable),
        'task_ids': current_routable_ids,
        'full_task_ids': current_full_order,
        'provider': current_route.provider,
    }

    suggested_full_order = list(current_full_order)
    suggested_routable_ids = list(current_routable_ids)
    suggested_route = current_route
    suggested_stops = routable

    eligible_routable = [
        s for s in routable
        if str(s['id']) in set(constraints.get('eligible_task_ids') or [])
    ]

    if len(constraints.get('eligible_task_ids') or []) >= 2 and len(eligible_routable) >= 2:
        try:
            matrix = prov.matrix(points)
            suggested_full_order, warnings = build_constrained_full_order(
                active_tasks,
                constraints,
                routable,
                matrix.duration_s,
                suggest_segment_order_fn=suggest_segment_order,
            )
            suggested_routable_ids = _routable_ids_in_full_order(suggested_full_order, routable)
            id_to_stop = {str(s['id']): s for s in routable}
            suggested_stops = [id_to_stop[i] for i in suggested_routable_ids if i in id_to_stop]
            if suggested_routable_ids != current_routable_ids:
                sug_points = [points[0]] + [
                    (float(s['latitude']), float(s['longitude'])) for s in suggested_stops
                ]
                suggested_route = _route_with_cache(prov, _route_points_with_return(sug_points))
        except RoutingError:
            suggested_full_order = list(current_full_order)
            suggested_routable_ids = list(current_routable_ids)
            suggested_stops = routable
            suggested_route = current_route

    # ── order_same (needed before gain and priority context) ──
    order_same = (current_full_order == suggested_full_order)

    # ── Gain calculation ──
    gain_km = None
    gain_min = None
    gain_pct = None
    if (
        isinstance(current_dto.get('km'), (int, float))
        and isinstance(_format_km(suggested_route.distance_m), (int, float))
        and current_route.distance_m is not None
        and current_route.distance_m > 0
    ):
        gain_km = round(
            float(current_route.distance_m - suggested_route.distance_m) / 1000.0, 1
        )
        cur_min = current_route.duration_s / 60.0
        sug_min = suggested_route.duration_s / 60.0
        gain_min = int(round(cur_min - sug_min))
        gain_pct = round(100.0 * gain_km / (float(current_route.distance_m) / 1000.0), 1)

    # ── Priority context ──
    # ACIL (critical) stops are already locked by _lock_reason → they don't get reordered.
    # YUKSEK (important) stops ARE included in optimizer scoring: lower duration wins but
    # priority weight is applied, which CAN produce a longer total route if a high-priority
    # stop is visited earlier.  We expose this to the user transparently.
    has_priority_override = bool(
        constraints.get('important_task_ids') and
        not order_same and
        isinstance(gain_km, (int, float)) and
        gain_km < 0
    )

    # ── apply_disabled: also disable when gain <= 0 and no priority driver ──
    apply_disabled_reason = _resolve_apply_disabled(
        constraints, current_full_order, suggested_full_order,
    )
    # Extend rule: if suggested is longer/equal and there's no priority override reason, disable
    if (
        apply_disabled_reason is None
        and isinstance(gain_km, (int, float))
        and gain_km <= 0
        and not has_priority_override
    ):
        apply_disabled_reason = 'NO_GAIN'

    apply_enabled = apply_disabled_reason is None and suggested_full_order != current_full_order

    suggested_dto = {
        'km': _format_km(suggested_route.distance_m),
        'duration_label': _format_duration(suggested_route.duration_s),
        'distance_m': suggested_route.distance_m,
        'duration_s': suggested_route.duration_s,
        'geometry': suggested_route.geometry,
        'legs': [lg.to_dict() if hasattr(lg, 'to_dict') else {
            'from_index': lg.from_index, 'to_index': lg.to_index,
            'distance_m': lg.distance_m, 'duration_s': lg.duration_s,
        } for lg in suggested_route.legs],
        'order_labels': _order_labels(suggested_stops),
        'task_ids': suggested_routable_ids,
        'full_task_ids': suggested_full_order,
        'apply_task_ids': suggested_full_order,
        'apply_enabled': apply_enabled,
        'apply_disabled_reason': apply_disabled_reason,
        'provider': suggested_route.provider,
    }

    partial_msg = None
    if meta['missing_count'] > 0:
        partial_msg = (
            f"{meta['routable_count']}/{meta['total_stops']} durak hesaplandı · "
            f"{meta['missing_count']} konum eksik"
        )

    if apply_disabled_reason == 'ALREADY_OPTIMAL' and not partial_msg:
        partial_msg = 'Mevcut sıra zaten uygun.'

    # ── Human-readable apply reason (read-only, no DB write) ──
    _APPLY_REASON_LABELS: dict[str, str] = {
        'ALREADY_OPTIMAL': 'Mevcut sıra rota motoruna göre zaten uygun. Daha kısa bir alternatif bulunamadı.',
        'NO_ELIGIBLE_REORDER': 'Sıralanabilir iş sayısı yetersiz (en az 2 serbest iş gerekir).',
        'NO_GAIN': 'Önerilen sıra mevcut rotadan daha uzun veya eşit; uygulama önerilmiyor.',
    }
    apply_disabled_reason_label = _APPLY_REASON_LABELS.get(
        apply_disabled_reason or '', apply_disabled_reason or ''
    )

    # ── Correct decision_reason text ──
    has_priority_reorder = bool(constraints.get('important_task_ids') and not order_same)
    if order_same:
        decision_reason = 'Mevcut sıra rota motoruna göre zaten uygun. Sıra değişmedi.'
    elif isinstance(gain_km, (int, float)) and gain_km < 0 and has_priority_override:
        decision_reason = (
            'Önerilen sıra mevcut rotadan daha uzun; ancak yüksek öncelikli iş daha erken '
            'ziyaret edildiği için bu sıra önerildi.'
        )
    elif isinstance(gain_km, (int, float)) and gain_km < 0:
        decision_reason = (
            f'Önerilen sıra mevcut rotadan daha uzun '
            f'({abs(gain_km)} km). Uygulama önerilmiyor.'
        )
    elif (
        isinstance(gain_km, (int, float)) and gain_km > 0
        and isinstance(gain_min, (int, float)) and gain_min < 0
        and has_priority_reorder
    ):
        decision_reason = (
            f'Önerilen rota {gain_km} km daha kısa; ancak tahmini sürüş süresi '
            f'{abs(gain_min)} dk daha uzun. Yüksek öncelikli iş daha erken ziyaret edildiği '
            f'için bu sıra önerildi.'
        )
    elif (
        isinstance(gain_km, (int, float)) and gain_km > 0
        and isinstance(gain_min, (int, float)) and gain_min < 0
    ):
        decision_reason = (
            f'Önerilen rota {gain_km} km daha kısa; ancak tahmini sürüş süresi '
            f'{abs(gain_min)} dk daha uzun.'
        )
    elif isinstance(gain_km, (int, float)) and gain_km == 0:
        decision_reason = 'Önerilen sıra mevcut rota ile aynı mesafede. Uygulama gerekmiyor.'
    else:
        gain_txt = f'{gain_km} km' if isinstance(gain_km, (int, float)) else '—'
        decision_reason = f'Rota motoru daha kısa bir sıra öneriyor ({gain_txt} kazanç).'

    # ── Constraint labels in human language ──
    _LOCK_LABEL_MAP: dict[str, str] = {
        'TAMAMLANDI': 'Tamamlanmış iş var; sıra değiştirilemez.',
        'BASLADI': 'Başlamış iş var; sıra değiştirilemez.',
        'ACIL': 'Acil öncelikli iş var; sırası kilitli.',
        'ARRIVED': 'Ziyaret edilmiş iş var; sırası kilitli.',
        'DEPARTED': 'Ziyaret edilmiş iş var; sırası kilitli.',
        'DEPARTED_PENDING': 'Ziyaret edilmiş iş var; sırası kilitli.',
        'VISIT_TIMESTAMP': 'Ziyaret kaydı olan iş var; sırası değiştirilemez.',
    }
    lock_reasons = constraints_public.get('lock_reasons') or {}
    constraint_labels: list[str] = []
    for reason in lock_reasons.values():
        lbl = _LOCK_LABEL_MAP.get(reason, reason)
        if lbl not in constraint_labels:
            constraint_labels.append(lbl)

    # ── Stop list for modal display (includes priority + desired/eta time skeleton) ──
    def _stop_label_list(stops: list[dict]) -> list[dict]:
        from modules.planlama.arac_route_constraints import normalize_priority
        from modules.planlama.arac_eta_status import eta_status
        _PRI_LABEL = {'ACIL': 'Acil', 'YUKSEK': 'Yüksek', 'NORMAL': 'Normal', 'DUSUK': 'Düşük'}
        out = []
        for s in stops:
            pri_code = normalize_priority(s.get('priority'))
            # Semantik ayrım:
            #   desired_time  = istenen_varis_saati (kullanıcı/kaynak istenen)
            #   eta_time      = tahmini_varis_saati (sistem ETA)
            # Migration 188 öncesi: eta_time NULL, desired_time planlanan_saat'ten legacy fallback
            desired = s.get('desired_time') or s.get('istenen_varis_saati') or None
            eta = s.get('eta_time') or s.get('tahmini_varis_saati') or None
            # planlanan_saat legacy fallback: yalnız desired boşsa VE migration 188 yoksa
            if desired is None and eta is None:
                legacy = s.get('planned_time')
                if legacy and legacy != '—':
                    desired = legacy  # legacy istenen anlamında okun
            eta_info = eta_status(eta, desired)
            out.append({
                'id': str(s.get('id') or ''),
                'order_no': s.get('order_no'),
                'display_order_no': s.get('display_order_no'),
                'company_name': s.get('company_name') or '—',
                'has_coordinates': bool(s.get('has_coordinates')),
                'priority': pri_code,
                'priority_label': _PRI_LABEL.get(pri_code, 'Normal'),
                'is_locked': str(s.get('id') or '') in set(constraints.get('locked_task_ids') or []),
                # ── Rota Kararı DTO zaman alanları (H bölümü) ──────────────
                'desired_time': desired,           # istened varış (kullanıcı/kaynak)
                'eta_time': eta,                    # tahmini varış (sistem)
                'suggested_eta': None,              # optimizer sonrası doldurulacak
                'current_time_status': eta_info['code'],
                'current_time_label': eta_info['label'],
                'suggested_time_status': None,
                'current_delay_minutes': eta_info['delay_minutes'],
                'suggested_delay_minutes': None,
            })
        return out

    # ── Priority banner text for modal (optimizer note) ──
    has_acil = bool(constraints.get('critical_task_ids'))
    has_yuksek = bool(constraints.get('important_task_ids'))
    if has_acil:
        priority_banner = (
            'Bu planda acil iş var; acil işlerin sırası değiştirilemez ve rota buna göre hesaplanır.'
        )
    elif has_yuksek:
        priority_banner = (
            'Bu planda yüksek öncelikli iş var. Optimizer yüksek öncelikli işleri önce ziyaret '
            'etmeye çalışır; bu toplam mesafeyi artırabilir.'
        )
    else:
        priority_banner = None

    return {
        'status': 'PARTIAL' if meta['missing_count'] > 0 else 'OK',
        'message': partial_msg,
        'partial': meta['missing_count'] > 0,
        'meta': meta,
        'constraints': constraints_public,
        'warnings': warnings,
        'current': current_dto,
        'suggested': suggested_dto,
        'gain': {
            'km': gain_km if gain_km is not None else '—',
            'duration_label': _format_duration(gain_min * 60) if gain_min is not None else '—',
            'duration_min': gain_min,
            'pct': gain_pct if gain_pct is not None else '—',
        },
        'leg_details': leg_details,
        'missing_stops': [
            {'id': m.get('id'), 'order_no': m.get('order_no'), 'company_name': m.get('company_name')}
            for m in missing
        ],
        'suggested_preview_only': True,
        # ── Explainer modal fields (read-only, no DB write) ──
        'decision_reason': decision_reason,
        'apply_disabled_reason_label': apply_disabled_reason_label,
        'order_same': order_same,
        'has_priority_override': has_priority_override,
        'priority_banner': priority_banner,
        'current_stop_list': _stop_label_list(routable),
        'suggested_stop_list': _stop_label_list(suggested_stops),
        'constraint_labels': constraint_labels,
        'gain_negative': isinstance(gain_km, (int, float)) and gain_km < 0,
        'gain_zero': isinstance(gain_km, (int, float)) and gain_km == 0,
    }
