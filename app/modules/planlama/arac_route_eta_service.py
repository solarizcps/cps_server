# -*- coding: utf-8 -*-
"""Route ETA — departure anchor + leg-based stop arrival times (Europe/Istanbul).

SEMANTİK NOT:
  Bu servis yalnız rota ayaklarından ETA hesaplar.
  Sonuçlar tahmini_varis_saati kolonuna yazılır (planlanan_saat DOKUNULMAZ).
  leg_details: `build_plan_route_dto` veya `_compute_route_legs_for_plan` tarafından üretilen dicts.
    Her dict: {task_id, duration_s, ...}
  Dönüş ayağı: route.legs[n_stops] olarak mevcut — return_duration_s olarak alınır.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from modules.planlama.arac_takip_repo import INACTIVE_PLAN_STATUSES

TZ_ISTANBUL = ZoneInfo('Europe/Istanbul')
_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')


def parse_plan_hhmm(plan_date: str, raw: str) -> datetime | None:
    """Parse HH:mm (or HH:mm:ss) on plan_date in Europe/Istanbul."""
    text = (raw or '').strip()
    if not text or text == '—':
        return None
    hhmm = text[:5] if len(text) >= 5 and text[2] == ':' else text
    m = _HHMM_RE.match(hhmm)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    try:
        naive = datetime.strptime(f'{plan_date[:10]} {hour:02d}:{minute:02d}', '%Y-%m-%d %H:%M')
    except ValueError:
        return None
    return naive.replace(tzinfo=TZ_ISTANBUL)


def format_display_hhmm(dt: datetime) -> str:
    """HH:mm — saniye varsa bir sonraki dakikaya ceil (timeline ile aynı kural)."""
    local = dt.astimezone(TZ_ISTANBUL)
    if local.second > 0 or local.microsecond > 0:
        local = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return local.strftime('%H:%M')


def resolve_departure_anchor(
    plan_date: str,
    plan_row: dict | None,
    *,
    explicit_departure_time: str | None = None,
) -> tuple[datetime | None, str | None]:
    """
    Resolve factory departure anchor. Never fabricates a default time.

    Priority:
    1. Explicit apply/API departure_time (HH:mm)
    2. Future plan-row fields: cikis_saati, departure_time, plan_cikis_saati

    planlanan_saat on first stop is customer visit time (istenen_saat lineage), not
    factory departure — intentionally excluded.
    """
    if explicit_departure_time:
        dt = parse_plan_hhmm(plan_date, explicit_departure_time)
        if dt:
            return dt, 'explicit_departure_time'

    if plan_row:
        for key in ('cikis_saati', 'departure_time', 'plan_cikis_saati'):
            raw = plan_row.get(key)
            if raw:
                dt = parse_plan_hhmm(plan_date, str(raw))
                if dt:
                    return dt, key

    return None, None


def _is_active_task(task: dict) -> bool:
    st = (task.get('status') or 'PLANLANDI').upper()
    return st not in INACTIVE_PLAN_STATUSES


def compute_stop_etas(
    departure: datetime,
    ordered_tasks: list[dict],
    leg_details: list[dict],
    *,
    service_seconds: int = 0,
    return_duration_s: float | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Forward ETA from factory departure using route leg_details (base→stop1, stop1→stop2, …).

    Returns task_id -> {
        eta_at (ISO local),
        display_hhmm,
        arrival_time,        HH:mm varış
        departure_time,      HH:mm çıkış (arrival + service_seconds)
        leg_duration_s,
        service_seconds,
        cumulative_travel_s,
        departure_source_at,
    }
    Plan seviyesi tahmini dönüş: result['__return__']['display_hhmm'] (return_duration_s verilmişse)
    """
    leg_by_task: dict[str, dict] = {}
    for leg in leg_details or []:
        tid = leg.get('task_id')
        if tid:
            leg_by_task[str(tid)] = leg

    active_ordered = [
        t for t in sorted(ordered_tasks, key=lambda x: x.get('order_no') or 0)
        if _is_active_task(t)
    ]

    out: dict[str, dict[str, Any]] = {}
    cursor = departure
    cumulative_travel = 0

    for task in active_ordered:
        tid = str(task.get('id') or '')
        if not tid or tid not in leg_by_task:
            continue
        leg = leg_by_task[tid]
        dur = leg.get('duration_s')
        if dur is None:
            continue
        try:
            travel_s = max(0.0, float(dur))
        except (TypeError, ValueError):
            continue

        cumulative_travel += travel_s
        arrival = cursor + timedelta(seconds=travel_s)
        departure_from_stop = arrival + timedelta(seconds=service_seconds)

        out[tid] = {
            'eta_at': arrival.isoformat(),
            'display_hhmm': format_display_hhmm(arrival),
            'arrival_time': format_display_hhmm(arrival),
            'departure_time': format_display_hhmm(departure_from_stop),
            'leg_duration_s': travel_s,
            'cumulative_travel_s': cumulative_travel,
            'service_seconds': service_seconds,
            'departure_source_at': departure.isoformat(),
        }
        cursor = departure_from_stop
        if service_seconds > 0:
            cumulative_travel += service_seconds

    # Tahmini fabrika dönüşü
    if return_duration_s is not None:
        try:
            ret_s = max(0.0, float(return_duration_s))
            return_at = cursor + timedelta(seconds=ret_s)
            out['__return__'] = {
                'display_hhmm': format_display_hhmm(return_at),
                'return_duration_s': ret_s,
                'estimated_return_at': return_at.isoformat(),
            }
        except (TypeError, ValueError):
            pass

    return out


def eta_hhmm_map(eta_result: dict[str, dict[str, Any]]) -> dict[str, str]:
    """task_id -> arrival HH:mm for DB persist (tahmini_varis_saati). Skips __return__ key."""
    return {
        tid: (info.get('arrival_time') or info.get('display_hhmm') or '')
        for tid, info in eta_result.items()
        if tid != '__return__' and (info.get('arrival_time') or info.get('display_hhmm'))
    }
