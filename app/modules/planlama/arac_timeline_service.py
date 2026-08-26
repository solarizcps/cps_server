# -*- coding: utf-8 -*-
"""
arac_timeline_service.py
Araç Takip — Çıkış Saati + rota ayakları + işlem süresi → timeline DTO.

HESAP KURALI:
  Çıkış Saati
  → Fabrika–1. durak yol süresi
  → 1. durak Varış
  → DEFAULT_STOP_SERVICE_MINUTES İşlem
  → 1. durak Çıkış
  → 2. durak yol süresi
  ...
  → Son durak Çıkış
  → Dönüş ayağı süresi
  → Tahmini Fabrika Dönüşü

MATEMATİK KURALI:
  Tüm ara hesaplar HAM FLOAT SANİYE olarak tutulur.
  Ara yuvarlama YAPILMAZ.
  Yuvarlama yalnız ekranda gösterim için en son adımda uygulanır.
  Gecikmeyi düşük göstermemek için gösterimde ceil kullanılır.
  Formül tutarlılığı:
    estimated_return_offset == total_travel_s + total_service_s + return_s
    estimated_total_s == total_travel_s + total_service_s + return_s

SABITLER:
  DEFAULT_STOP_SERVICE_MINUTES = 10
  Bu sabit tek kaynakta tanımlıdır. Frontend kendi başına bu hesabı yapmaz.

SINIRLAR:
  - planlanan_saat DOKUNULMAZ.
  - tahmini_varis_saati: migration 188 sonrası yazılabilir (caller kararı).
  - Migration 188 yoksa DB write yapılmaz; preview response üretilir.
  - Inactive işlere ETA yazılmaz.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Istanbul')

# ── Tek canonical sabit ─────────────────────────────────────────────────────
DEFAULT_STOP_SERVICE_MINUTES: int = 10

# ETA durum kodları (bu faz)
TIMELINE_STATUS_OK = 'HESAPLANDI'
TIMELINE_STATUS_MISSING_LEG = 'AYAK_EKSIK'
TIMELINE_STATUS_NO_DEPARTURE = 'CIKIS_SAATI_EKSIK'


def _fmt_ceil(dt: datetime) -> str:
    """HH:mm — saniye varsa bir sonraki dakikaya CEIL eder.
    09:02:42 → 09:03  |  09:12:00 → 09:12  (tam dakika değişmez)
    Ara hesaplar exact datetime üzerinden devam eder; bu fonksiyon yalnız gösterim için.
    """
    local = dt.astimezone(TZ)
    if local.second > 0 or local.microsecond > 0:
        local = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return local.strftime('%H:%M')


def _ceil_minutes(seconds: float) -> int:
    """Saniyeyi dakikaya ceil ile çevirir — gecikmeyi düşük göstermez."""
    return math.ceil(seconds / 60)


def build_duration_label_summary(
    *,
    outbound_travel_seconds: float | None,
    return_travel_seconds: float | None,
    total_travel_seconds: float | None,
    total_service_seconds: float | None,
) -> dict[str, Any]:
    """Yalnız gösterim — ham saniyelerden ceil; alt kalemler toplanmaz."""
    outbound_min = (
        _ceil_minutes(outbound_travel_seconds)
        if outbound_travel_seconds is not None else None
    )
    return_min = (
        _ceil_minutes(return_travel_seconds)
        if return_travel_seconds is not None else None
    )
    total_drive_min = (
        _ceil_minutes(total_travel_seconds)
        if total_travel_seconds is not None else None
    )
    service_min = (
        int(total_service_seconds // 60)
        if total_service_seconds is not None else None
    )
    total_plan_min = None
    if total_travel_seconds is not None and total_service_seconds is not None:
        total_plan_min = _ceil_minutes(total_travel_seconds + total_service_seconds)

    lines: list[str] = []
    if outbound_min is not None:
        lines.append(f'Duraklara kadar sürüş: yaklaşık {outbound_min} dk')
    if return_min is not None:
        lines.append(f'Fabrikaya dönüş: yaklaşık {return_min} dk')
    if total_drive_min is not None:
        lines.append(f'Toplam sürüş: {total_drive_min} dk')
    if service_min is not None:
        lines.append(f'İşlem: {service_min} dk')
    if total_plan_min is not None:
        lines.append(f'Toplam plan: {total_plan_min} dk')

    return {
        'outbound_travel_minutes': outbound_min,
        'return_travel_minutes': return_min,
        'total_drive_minutes': total_drive_min,
        'service_minutes': service_min,
        'total_plan_minutes': total_plan_min,
        'lines': lines,
    }


def _parse_hhmm(plan_date: str, hhmm: str | None) -> datetime | None:
    if not hhmm or hhmm == '—':
        return None
    s = (hhmm or '').strip()[:5]
    try:
        h, m = int(s[:2]), int(s[3:5])
        if h > 23 or m > 59:
            return None
        naive = datetime.strptime(f'{plan_date[:10]} {h:02d}:{m:02d}', '%Y-%m-%d %H:%M')
        return naive.replace(tzinfo=TZ)
    except (ValueError, IndexError):
        return None


def build_timeline(
    plan_date: str,
    departure_hhmm: str | None,
    active_tasks: list[dict],
    leg_details: list[dict],
    return_duration_s: float | None,
    *,
    service_minutes: int = DEFAULT_STOP_SERVICE_MINUTES,
) -> dict[str, Any]:
    """
    Pure hesap — DB write yok.

    Tüm iç hesaplar ham float saniye üzerinden yapılır.
    Yuvarlama yalnız gösterim alanlarında (travel_minutes, total_*_minutes) en son adımda.

    Parameters:
        plan_date         — 'YYYY-MM-DD'
        departure_hhmm    — 'HH:mm' çıkış saati
        active_tasks      — sıralı aktif görevler [{id, order_no, display_order_no, ...}]
        leg_details       — [{task_id, duration_s, distance_m, ...}]
        return_duration_s — son durak→fabrika dönüş süresi (ham saniye float, None=bilinmiyor)
        service_minutes   — işlem süresi dk (default=DEFAULT_STOP_SERVICE_MINUTES)
    """
    service_s: float = service_minutes * 60.0

    if not departure_hhmm:
        return {
            'status': TIMELINE_STATUS_NO_DEPARTURE,
            'reason': 'Çıkış Saati girilmemiş — ETA hesaplanamaz.',
            'stops': [],
            'plan_departure_time': None,
            'estimated_return_time': None,
            'total_travel_seconds': None,
            'total_service_seconds': None,
            'estimated_total_seconds': None,
            'total_travel_minutes': None,
            'total_service_minutes': None,
            'estimated_total_minutes': None,
            'timeline_complete': False,
        }

    departure_dt = _parse_hhmm(plan_date, departure_hhmm)
    if not departure_dt:
        return {
            'status': TIMELINE_STATUS_NO_DEPARTURE,
            'reason': f'Çıkış Saati parse edilemedi: {departure_hhmm!r}',
            'stops': [],
            'plan_departure_time': departure_hhmm,
            'estimated_return_time': None,
            'total_travel_seconds': None,
            'total_service_seconds': None,
            'estimated_total_seconds': None,
            'total_travel_minutes': None,
            'total_service_minutes': None,
            'estimated_total_minutes': None,
            'timeline_complete': False,
        }

    leg_by_task: dict[str, dict] = {}
    for leg in leg_details or []:
        tid = str(leg.get('task_id') or '')
        if tid:
            leg_by_task[tid] = leg

    cursor = departure_dt
    stops: list[dict] = []
    total_travel_s: float = 0.0
    any_missing = False

    for task in active_tasks:
        tid = str(task.get('id') or '')
        display_no = task.get('display_order_no') or task.get('order_no')
        plan_item_id = task.get('plan_item_id')
        company = task.get('company_name') or '—'

        if not tid or tid not in leg_by_task:
            any_missing = True
            stops.append({
                'display_order_no': display_no,
                'plan_item_id': plan_item_id,
                'company_name': company,
                'travel_seconds': None,
                'travel_minutes': None,
                'arrival_time': None,
                'service_minutes': service_minutes,
                'departure_time': None,
                'eta_status': TIMELINE_STATUS_MISSING_LEG,
                'actual_arrival_time': None,
                'actual_departure_time': None,
                'actual_service_minutes': None,
                'tracking_state': None,
            })
            continue

        leg = leg_by_task[tid]
        dur_raw = leg.get('duration_s')
        try:
            # Ham float — ara yuvarlama yok
            travel_s: float = max(0.0, float(dur_raw))
        except (TypeError, ValueError):
            any_missing = True
            stops.append({
                'display_order_no': display_no,
                'plan_item_id': plan_item_id,
                'company_name': company,
                'travel_seconds': None,
                'travel_minutes': None,
                'arrival_time': None,
                'service_minutes': service_minutes,
                'departure_time': None,
                'eta_status': TIMELINE_STATUS_MISSING_LEG,
                'actual_arrival_time': None,
                'actual_departure_time': None,
                'actual_service_minutes': None,
                'tracking_state': None,
            })
            continue

        # Kesin datetime hesabı — timedelta float-safe
        arrival = cursor + timedelta(seconds=travel_s)
        departure_from_stop = arrival + timedelta(seconds=service_s)
        total_travel_s += travel_s

        stops.append({
            'display_order_no': display_no,
            'plan_item_id': plan_item_id,
            'company_name': company,
            'leg_distance_m': leg.get('distance_m'),
            'travel_seconds': travel_s,
            'travel_minutes': _ceil_minutes(travel_s),
            'arrival_time': _fmt_ceil(arrival),
            'arrival_exact': arrival.isoformat(),
            'service_minutes': service_minutes,
            'service_seconds': int(service_s),
            'departure_time': _fmt_ceil(departure_from_stop),
            'departure_exact': departure_from_stop.isoformat(),
            'eta_status': TIMELINE_STATUS_OK,
            'actual_arrival_time': None,
            'actual_departure_time': None,
            'actual_service_minutes': None,
            'tracking_state': None,
        })
        cursor = departure_from_stop

    # Aktif stop sayısı (sadece hesaplananlar)
    ok_stop_count = sum(1 for s in stops if s['eta_status'] == TIMELINE_STATUS_OK)
    total_service_s: float = ok_stop_count * service_s

    # Dönüş ayağı — ham float saniye, exact datetime
    estimated_return_hhmm: str | None = None
    return_s: float = 0.0
    if return_duration_s is not None:
        try:
            return_s = max(0.0, float(return_duration_s))
            return_dt = cursor + timedelta(seconds=return_s)
            estimated_return_hhmm = _fmt_ceil(return_dt)
        except (TypeError, ValueError):
            return_s = 0.0

    # total_travel_seconds = outbound + return (her ikisi de travel)
    outbound_travel_s: float = total_travel_s
    total_travel_s_with_return: float = outbound_travel_s + return_s

    # estimated_total_s = travel(outbound+return) + service
    estimated_total_s: float = total_travel_s_with_return + total_service_s

    timeline_complete = (not any_missing) and (return_duration_s is not None)

    duration_labels = build_duration_label_summary(
        outbound_travel_seconds=outbound_travel_s,
        return_travel_seconds=return_s if return_duration_s is not None else None,
        total_travel_seconds=total_travel_s_with_return,
        total_service_seconds=total_service_s,
    )

    return {
        'status': TIMELINE_STATUS_MISSING_LEG if any_missing else TIMELINE_STATUS_OK,
        'reason': 'Bir veya daha fazla durak için rota ayağı eksik.' if any_missing else None,
        'stops': stops,
        'plan_departure_time': departure_hhmm,
        'estimated_return_time': estimated_return_hhmm,
        # Ham saniyeler — tutarlılık kontrolü için
        'outbound_travel_seconds': outbound_travel_s,
        'return_travel_seconds': return_s if return_duration_s is not None else None,
        'total_travel_seconds': total_travel_s_with_return,
        'total_service_seconds': total_service_s,
        'return_seconds': return_s if return_duration_s is not None else None,
        'estimated_total_seconds': estimated_total_s if estimated_total_s else None,
        # Gösterim dakikaları — ceil, tek kaynaktan
        'total_travel_minutes': _ceil_minutes(total_travel_s_with_return) if total_travel_s_with_return else 0,
        'outbound_travel_minutes': duration_labels.get('outbound_travel_minutes'),
        'total_service_minutes': int(total_service_s // 60),
        'total_return_minutes': _ceil_minutes(return_s) if return_s else None,
        'estimated_total_minutes': _ceil_minutes(estimated_total_s) if estimated_total_s else None,
        'duration_labels': duration_labels,
        'timeline_complete': timeline_complete,
        'service_minutes_used': service_minutes,
    }


def build_timeline_for_plan(
    plan_date: str,
    arac_external_id: str,
    *,
    service_minutes: int = DEFAULT_STOP_SERVICE_MINUTES,
) -> dict[str, Any]:
    """
    Convenience wrapper: yükle + hesapla.

    Migration 188 uygulanmamışsa DB write YAPILMAZ.
    Preview response üretilir (timeline_complete=True/False).
    """
    from modules.planlama.arac_takip_repo import (
        INACTIVE_PLAN_STATUSES, get_active_plan_row, list_plan_tasks, tables_ready,
    )
    from modules.planlama.arac_departure_service import _compute_route_legs_for_plan

    if not tables_ready():
        return {'status': 'TABLES_NOT_READY', 'stops': [], 'timeline_complete': False}

    plan_row = get_active_plan_row(plan_date, arac_external_id)
    if not plan_row:
        return {'status': 'PLAN_NOT_FOUND', 'stops': [], 'timeline_complete': False}

    tasks = list_plan_tasks(plan_date, arac_external_id)
    active_tasks = [t for t in tasks if (t.get('status') or '').upper() not in INACTIVE_PLAN_STATUSES]

    departure_hhmm = plan_row.get('cikis_saati') or None

    leg_details, return_duration_s = _compute_route_legs_for_plan(
        plan_date, arac_external_id, active_tasks
    )

    return build_timeline(
        plan_date=plan_date,
        departure_hhmm=departure_hhmm,
        active_tasks=active_tasks,
        leg_details=leg_details,
        return_duration_s=return_duration_s,
        service_minutes=service_minutes,
    )
