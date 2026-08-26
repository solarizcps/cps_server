# -*- coding: utf-8 -*-
"""
Araç Takip — Çıkış Saati kaydet + ETA hesapla (atomic).

POST /planlama/arac-takip/api/plan/departure-time

İş kuralları:
- cikis_saati plan bazında tutulur (arac_gunluk_plan.cikis_saati)
- Kayıt + ETA güncelleme tek transaction'da
- Departure yoksa ETA yazılmaz (0 satır update, rollback değil)
- Inactive işlere dokunulmaz
- Başka araç/tarihe dokunulmaz

SEMANTİK TANIMLAR:
- ETA hesabı → tahmini_varis_saati alanına yazar (migration 188 sonrası)
- planlanan_saat → DOKUNULMAZ (legacy istenen saat, kullanıcı/talep kaynaklı)
- istenen_varis_saati → DOKUNULMAZ (canonical kullanıcı istenen saati)
- Migration 188 uygulanmamışsa ETA yazımı sessizce atlanır (planlanan_saat korunur)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from db import get_conn
from modules.planlama.arac_route_eta_service import (
    compute_stop_etas,
    eta_hhmm_map,
    parse_plan_hhmm,
)
from modules.planlama.arac_takip_repo import (
    INACTIVE_PLAN_STATUSES,
    PLAN_PROVIDER_FILOM,
    _update_plan_item_times_bulk_conn,
    get_active_plan_row,
    list_plan_tasks,
    tables_ready,
    update_plan_cikis_saati,
)

_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')


class DepartureValidationError(ValueError):
    pass


def _validate_hhmm(raw: str) -> str:
    """Return canonical HH:mm or raise DepartureValidationError."""
    text = (raw or '').strip()
    m = _HHMM_RE.match(text)
    if not m:
        raise DepartureValidationError(f'Geçersiz saat formatı: {raw!r} — HH:mm bekleniyor')
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        raise DepartureValidationError(f'Geçersiz saat değeri: {raw!r}')
    return f'{hour:02d}:{minute:02d}'


def _compute_route_legs_for_plan(
    plan_date: str,
    arac_external_id: str,
    active_tasks: list[dict],
) -> tuple[list[dict], float | None]:
    """
    Runtime ORS çağrısıyla leg_details hesapla.

    Returns (leg_details_list, return_duration_s)
    Leg_details_list: [{task_id, order_no, company_name, duration_s, distance_m, ...}, ...]
    return_duration_s: son durak → fabrika dönüş süresi (saniye), yoksa None.

    NOT: arac_plan_rota_snapshot tablosunda leg_details_json kolonu YOK.
    Snapshot yalnız stop_order_json ve total_duration_s taşır.
    Leg detayları her seferinde runtime ORS/mock provider'dan hesaplanır.
    """
    from modules.planlama.arac_location_resolver import resolve_base_location
    from modules.planlama.arac_operasyon_ayar_repo import get_active_base
    from modules.planlama.road_routing.route_planner_service import (
        _build_routable_points, _legs_for_stops, _route_points_with_return,
        _route_with_cache, get_routing_provider,
    )

    base_row = get_active_base()
    base = resolve_base_location(base_row)

    if not active_tasks or not base.get('has_coordinates'):
        return [], None

    prov = get_routing_provider()
    if prov is None:
        return [], None

    points, routable, _missing, meta = _build_routable_points(base, active_tasks)
    if len(points) < 2 or not routable:
        return [], None

    route_points = _route_points_with_return(points)
    try:
        result = _route_with_cache(prov, route_points)
    except Exception:
        return [], None

    leg_details: list[dict] = []
    n_stops = len(routable)
    stop_legs = _legs_for_stops(result, n_stops)
    for i, stop in enumerate(routable):
        leg = stop_legs[i]
        leg_details.append({
            'task_id': stop.get('id'),
            'order_no': stop.get('order_no'),
            'company_name': stop.get('company_name'),
            'duration_s': leg.get('duration_s'),
            'distance_m': leg.get('distance_m'),
        })

    # Dönüş ayağı: legs[n_stops] mevcutsa al
    return_duration_s: float | None = None
    if len(result.legs) > n_stops:
        ret_leg = result.legs[n_stops]
        return_duration_s = ret_leg.duration_s

    return leg_details, return_duration_s


def save_departure_and_compute_eta(
    plan_date: str,
    arac_external_id: str,
    cikis_saati: str,
    session_user_id: int,
    plan_id: int | None = None,
) -> dict[str, Any]:
    """
    Atomic:
    1. Validate HH:mm
    2. Load plan row (vehicle+date match guard)
    3. Load current tasks (canonical sira order)
    4. Load route leg_details from latest snapshot
    5. Compute ETAs for active tasks
    6. BEGIN IMMEDIATE
    7. UPDATE arac_gunluk_plan.cikis_saati
    8. UPDATE active arac_gunluk_plan_is.tahmini_varis_saati per ETA
       (planlanan_saat DOKUNULMAZ — legacy istenen saat)
    9. COMMIT
    10. Return result dict

    On any error: rollback (context manager), raise.
    """
    if not tables_ready():
        return {'ok': False, 'error': 'Araç takip tabloları hazır değil', 'code': 'TABLES_NOT_READY'}

    try:
        canonical_hhmm = _validate_hhmm(cikis_saati)
    except DepartureValidationError as exc:
        return {'ok': False, 'error': str(exc), 'code': 'INVALID_DEPARTURE_TIME'}

    plan_row = get_active_plan_row(plan_date, arac_external_id)
    if not plan_row:
        return {'ok': False, 'error': 'Aktif plan bulunamadı', 'code': 'PLAN_NOT_FOUND'}

    resolved_plan_id = int(plan_row['id'])
    if plan_id is not None and int(plan_id) != resolved_plan_id:
        return {
            'ok': False,
            'error': 'Plan ID uyuşmazlığı — araç ve tarih bazlı plan kullanıldı',
            'code': 'PLAN_ID_MISMATCH',
        }

    tasks = list_plan_tasks(plan_date, arac_external_id)
    active_tasks = [t for t in tasks if (t.get('status') or '').upper() not in INACTIVE_PLAN_STATUSES]

    # Runtime leg hesabı (snapshot'ta leg_details_json kolonu yok)
    leg_details, return_duration_s = _compute_route_legs_for_plan(
        plan_date, arac_external_id, active_tasks
    )

    departure_dt = parse_plan_hhmm(plan_date, canonical_hhmm)
    if not departure_dt:
        return {'ok': False, 'error': 'Çıkış saati parse edilemedi', 'code': 'DEPARTURE_PARSE_ERROR'}

    # Compute ETAs (pure, no DB writes yet)
    eta_by_task: dict[str, dict] = {}
    missing_legs: list[str] = []
    from modules.planlama.arac_timeline_service import DEFAULT_STOP_SERVICE_MINUTES
    service_s = DEFAULT_STOP_SERVICE_MINUTES * 60
    if leg_details:
        eta_by_task = compute_stop_etas(
            departure_dt, active_tasks, leg_details,
            service_seconds=service_s,
            return_duration_s=return_duration_s,
        )
        for t in active_tasks:
            tid = str(t.get('id') or '')
            if tid and tid not in eta_by_task:
                missing_legs.append(t.get('company_name') or tid)

    time_map = eta_hhmm_map(eta_by_task) if eta_by_task else {}

    # Atomic write
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        update_plan_cikis_saati(resolved_plan_id, canonical_hhmm, session_user_id, con)
        if time_map:
            _update_plan_item_times_bulk_conn(con, resolved_plan_id, time_map)
        con.execute(
            'UPDATE arac_gunluk_plan SET updated_at=datetime("now","localtime") WHERE id=?',
            (resolved_plan_id,),
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        return {'ok': False, 'error': f'Kayıt hatası: {exc}', 'code': 'DB_ERROR'}
    finally:
        con.close()

    # Reload tasks with updated planlanan_saat
    updated_tasks = list_plan_tasks(plan_date, arac_external_id)

    return {
        'ok': True,
        'plan_id': resolved_plan_id,
        'departure_time': canonical_hhmm,
        'eta_applied': bool(time_map),
        'eta_count': len(time_map),
        'missing_leg_count': len(missing_legs),
        'missing_legs': missing_legs,
        'eta_reason': (
            'Çıkış Saati kaydedildi ve durak saatleri hesaplandı.'
            if time_map
            else 'Çıkış Saati kaydedildi. Rota snapshot bulunamadı — saatler hesaplanmadı.'
        ),
        'tasks': updated_tasks,
    }
