# -*- coding: utf-8 -*-
"""APS P2 — generic resource calendar / availability motor (planlama-only)."""
from __future__ import annotations

from datetime import datetime, timedelta, time
from typing import Any

from modules.planlama.aps_calendar_contract import (
    BLOCKING_RESERVATION_STATUSES,
    CALENDAR_ENJ_SLOT,
    CALENDAR_FIXED_DAILY,
    AvailabilitySummary,
    DowntimeInterval,
    FirstAvailableResult,
    ImpactAnalysisItem,
    OperationScheduleTimes,
    ReservationInterval,
    ResourceCalendarSpec,
    WEEKEND_EVET_ONAYLI,
    WEEKEND_HAYIR,
    WorkingWindow,
    enj_slot_calendar,
    monta_calendar,
)
from modules.planlama.enj_kapasite_motor import (
    HAFTA_SONU_KURAL,
    VARDIYA_SAAT,
    _advance_to_next_slot,
    _mode_allows_vardiya,
    _parse_dt,
    _shift_window,
    _vardiya_for_dt,
)

MAX_CALENDAR_DAYS = 366


def _parse_input_dt(val: str | datetime) -> datetime:
    if isinstance(val, datetime):
        return val.replace(second=0, microsecond=0)
    return _parse_dt(val)


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _clip_window(win: WorkingWindow, start: datetime, end: datetime) -> WorkingWindow | None:
    s = max(win.start, start)
    e = min(win.end, end)
    if e <= s:
        return None
    return WorkingWindow(s, e, win.source)


def _validate_weekend_contract(calendar: ResourceCalendarSpec) -> None:
    if calendar.weekend_work == WEEKEND_EVET_ONAYLI:
        if calendar.weekend_shift_start is None or calendar.weekend_shift_end is None:
            raise ValueError(
                'STOP: weekend_work=EVET_ONAYLI icin weekend_shift_start/end zorunlu — '
                'sahte hafta sonu saati uydurulamaz'
            )


def get_effective_end_hour(calendar: ResourceCalendarSpec) -> float:
    """Mesai: approved_hours + overtime_approved; aksi halde normal_hours."""
    if calendar.overtime_approved and calendar.approved_hours is not None:
        return min(float(calendar.approved_hours), float(calendar.max_overtime_hours))
    return float(calendar.normal_hours)


def _fixed_daily_window_for_date(
    calendar: ResourceCalendarSpec,
    day: datetime,
    *,
    weekend_work: str | None = None,
) -> WorkingWindow | None:
    _validate_weekend_contract(calendar)
    wd = day.weekday()
    ww = weekend_work or calendar.weekend_work

    if wd >= 5:
        if ww != WEEKEND_EVET_ONAYLI:
            return None
        if calendar.weekend_shift_start is None or calendar.weekend_shift_end is None:
            raise ValueError('STOP: EVET_ONAYLI weekend shift saatleri eksik')
        ws = calendar.weekend_shift_start
        we = calendar.weekend_shift_end
        start = datetime(day.year, day.month, day.day, ws.hour, ws.minute)
        end = datetime(day.year, day.month, day.day, we.hour, we.minute)
        if end <= start:
            end += timedelta(days=1)
        return WorkingWindow(start, end, 'weekend_approved')

    hours = get_effective_end_hour(calendar)
    start = datetime(day.year, day.month, day.day,
                     calendar.normal_start.hour, calendar.normal_start.minute)
    end = start + timedelta(hours=hours)
    source = 'overtime' if calendar.overtime_approved and calendar.approved_hours else 'calendar'
    return WorkingWindow(start, end, source)


def _enj_windows_for_range(
    calendar: ResourceCalendarSpec,
    range_start: datetime,
    range_end: datetime,
) -> list[WorkingWindow]:
    """Enj vardiya pencereleri — enj_kapasite_motor parity."""
    hafta_sonu = 'EVET' if calendar.weekend_work == WEEKEND_EVET_ONAYLI else 'HAYIR'
    out: list[WorkingWindow] = []
    cur = range_start.replace(second=0, microsecond=0)
    end_limit = range_end
    guard = 0
    while cur < end_limit and guard < 5000:
        guard += 1
        try:
            cur = _advance_to_next_slot(
                cur,
                calendar.calisma_modu,
                hafta_sonu,
                calendar.hs_vardiya,
            )
        except RuntimeError:
            break
        vd = _vardiya_for_dt(cur)
        win_bas, win_bit = _shift_window(cur, vd)
        if not _mode_allows_vardiya(
            calendar.calisma_modu, vd, hafta_sonu, calendar.hs_vardiya, win_bas,
        ):
            cur = win_bit + timedelta(minutes=1)
            continue
        # Kural A: Cuma gece tam pencere; HS=HAYIR ise Cmt 07:00 sonrasi yeni vardiya yok
        if (
            hafta_sonu == 'HAYIR'
            and calendar.hafta_sonu_kural == 'A'
            and vd == 'gece'
            and win_bas.weekday() == 4
        ):
            pass  # _shift_window zaten Cmt 07:00'a kadar
        seg_start = max(cur, win_bas)
        seg_end = min(win_bit, end_limit)
        if seg_end > seg_start:
            out.append(WorkingWindow(seg_start, seg_end, f'enj_{vd}'))
        cur = win_bit + timedelta(minutes=1)
    return out


def get_working_windows(
    calendar: ResourceCalendarSpec,
    range_start: str | datetime,
    range_end: str | datetime,
    *,
    weekend_work: str | None = None,
) -> list[WorkingWindow]:
    rs = _parse_input_dt(range_start)
    re = _parse_input_dt(range_end)
    if re <= rs:
        return []

    if calendar.calendar_type == CALENDAR_ENJ_SLOT:
        return _enj_windows_for_range(calendar, rs, re)

    out: list[WorkingWindow] = []
    day = datetime(rs.year, rs.month, rs.day)
    last_day = datetime(re.year, re.month, re.day)
    guard = 0
    while day <= last_day and guard < MAX_CALENDAR_DAYS:
        guard += 1
        win = _fixed_daily_window_for_date(calendar, day, weekend_work=weekend_work)
        if win:
            clipped = _clip_window(win, rs, re)
            if clipped:
                out.append(clipped)
        day += timedelta(days=1)
    return out


def subtract_downtime(
    windows: list[WorkingWindow],
    downtimes: list[DowntimeInterval],
) -> list[WorkingWindow]:
    if not downtimes:
        return list(windows)
    result = list(windows)
    for dt in downtimes:
        next_result: list[WorkingWindow] = []
        for win in result:
            if not _overlap(win.start, win.end, dt.start, dt.end):
                next_result.append(win)
                continue
            if dt.start > win.start:
                next_result.append(WorkingWindow(win.start, dt.start, win.source))
            if dt.end < win.end:
                next_result.append(WorkingWindow(dt.end, win.end, win.source))
        result = [w for w in next_result if w.duration_minutes > 0]
    return result


def subtract_reservations(
    windows: list[WorkingWindow],
    reservations: list[ReservationInterval],
    *,
    blocking_statuses: frozenset[str] | None = None,
) -> list[tuple[WorkingWindow, list[ReservationInterval]]]:
    """Her pencereden blocking reservation çıkar; boş segmentler döner."""
    blocking = blocking_statuses or BLOCKING_RESERVATION_STATUSES
    active = [r for r in reservations if r.status in blocking]
    free_segments: list[tuple[WorkingWindow, list[ReservationInterval]]] = []

    for win in windows:
        segments = [win]
        skipped: list[ReservationInterval] = []
        for res in active:
            new_segments: list[WorkingWindow] = []
            hit = False
            for seg in segments:
                if not _overlap(seg.start, seg.end, res.start, res.end):
                    new_segments.append(seg)
                    continue
                hit = True
                if res.start > seg.start:
                    new_segments.append(WorkingWindow(seg.start, res.start, seg.source))
                if res.end < seg.end:
                    new_segments.append(WorkingWindow(res.end, seg.end, seg.source))
            if hit:
                skipped.append(res)
            segments = [s for s in new_segments if s.duration_minutes > 0]
        for seg in segments:
            free_segments.append((seg, list(skipped)))
    return free_segments


def intervals_overlap_reservation(a_start: datetime, a_end: datetime,
                                  b_start: datetime, b_end: datetime) -> bool:
    return _overlap(a_start, a_end, b_start, b_end)


def find_reservation_conflicts_in_memory(
    reservations: list[ReservationInterval],
    resource_key: str,
    new_start: str | datetime,
    new_end: str | datetime,
    *,
    exclude_id: int | None = None,
) -> list[ReservationInterval]:
    ns = _parse_input_dt(new_start)
    ne = _parse_input_dt(new_end)
    out = []
    for r in reservations:
        if r.resource_key != resource_key:
            continue
        if r.status not in BLOCKING_RESERVATION_STATUSES:
            continue
        if exclude_id and r.reservation_id == exclude_id:
            continue
        if intervals_overlap_reservation(r.start, r.end, ns, ne):
            out.append(r)
    return out


def is_resource_available(
    calendar: ResourceCalendarSpec,
    check_start: str | datetime,
    check_end: str | datetime,
    *,
    reservations: list[ReservationInterval] | None = None,
    downtimes: list[DowntimeInterval] | None = None,
) -> bool:
    cs = _parse_input_dt(check_start)
    ce = _parse_input_dt(check_end)
    windows = get_working_windows(calendar, cs, ce)
    windows = subtract_downtime(windows, downtimes or [])
    free = subtract_reservations(windows, reservations or [])
    needed = int((ce - cs).total_seconds() // 60)
    avail = sum(seg.duration_minutes for seg, _ in free if seg.start <= cs and seg.end >= ce)
    if avail >= needed:
        return True
    # parça parça kontrol — tamamen working window içinde mi
    covered = 0
    cursor = cs
    for seg, _ in sorted(free, key=lambda x: x[0].start):
        if seg.end <= cursor:
            continue
        if seg.start > cursor:
            return False
        take = min(seg.end, ce) - cursor
        covered += int(take.total_seconds() // 60)
        cursor = min(seg.end, ce)
        if cursor >= ce:
            break
    return cursor >= ce and covered >= needed


def find_first_available_window(
    calendar: ResourceCalendarSpec,
    earliest_start: str | datetime,
    required_minutes: int,
    *,
    reservations: list[ReservationInterval] | None = None,
    downtimes: list[DowntimeInterval] | None = None,
    search_horizon_days: int = 60,
) -> FirstAvailableResult:
    """Generic first-available — required_minutes dışarıdan gelir."""
    req = max(1, int(required_minutes))
    es = _parse_input_dt(earliest_start)
    horizon_end = es + timedelta(days=search_horizon_days)
    warnings: list[str] = []

    if calendar.overtime_approved and calendar.approved_hours is None:
        warnings.append('MESAI_GEREKIYOR: overtime_approved=True ama approved_hours yok')

    windows = get_working_windows(calendar, es, horizon_end)
    windows = subtract_downtime(windows, downtimes or [])
    free_pairs = subtract_reservations(windows, reservations or [])

    # Segmentleri birleştir
    segments: list[WorkingWindow] = []
    all_skipped: list[ReservationInterval] = []
    seen_skip: set[int | None] = set()
    for seg, skipped in free_pairs:
        if seg.end <= es:
            continue
        start = max(seg.start, es)
        if seg.end > start:
            segments.append(WorkingWindow(start, seg.end, seg.source))
        for s in skipped:
            key = s.reservation_id
            if key not in seen_skip:
                seen_skip.add(key)
                all_skipped.append(s)

    segments.sort(key=lambda w: w.start)
    accumulated: list[WorkingWindow] = []
    total = 0
    first_start: datetime | None = None

    for seg in segments:
        if total >= req:
            break
        if first_start is None:
            first_start = seg.start
        take_end = seg.end
        seg_min = seg.duration_minutes
        need = req - total
        if seg_min >= need:
            take_end = seg.start + timedelta(minutes=need)
            accumulated.append(WorkingWindow(seg.start, take_end, seg.source))
            total += need
            break
        accumulated.append(seg)
        total += seg_min

    if total < req:
        return FirstAvailableResult(
            ok=False,
            warnings=warnings + [f'Yetersiz kapasite: {total}/{req} dk'],
            conflicts_skipped=all_skipped,
        )

    est_end = accumulated[-1].end
    return FirstAvailableResult(
        ok=True,
        first_available_start=first_start,
        estimated_end=est_end,
        working_windows_used=accumulated,
        conflicts_skipped=all_skipped,
        warnings=warnings,
    )


def compute_resource_free_from(schedule: OperationScheduleTimes) -> datetime | None:
    """Erken bitiş — NEW_AVAILABLE_FROM; geç bitiş — actual_end."""
    return schedule.resource_free_from()


def build_impact_preview(
    operation_id: int | str,
    old_end: datetime,
    new_estimated_end: datetime,
    affected_operations: list[int | str],
) -> ImpactAnalysisItem:
    delta = int((new_estimated_end - old_end).total_seconds() // 60)
    return ImpactAnalysisItem(
        operation_id=operation_id,
        old_end=old_end,
        new_estimated_end=new_estimated_end,
        delta_minutes=delta,
        affected_operations=affected_operations,
        requires_approval=True,
    )


def build_availability_summary(
    calendar: ResourceCalendarSpec,
    range_start: str | datetime,
    range_end: str | datetime,
    *,
    reservations: list[ReservationInterval] | None = None,
    downtimes: list[DowntimeInterval] | None = None,
) -> AvailabilitySummary:
    windows = get_working_windows(calendar, range_start, range_end)
    dt_list = [d for d in (downtimes or []) if d.resource_key == calendar.resource_key]
    windows = subtract_downtime(windows, dt_list)
    res_list = [r for r in (reservations or []) if r.resource_key == calendar.resource_key]
    free = subtract_reservations(windows, res_list)
    free_minutes = sum(s.duration_minutes for s, _ in free)
    total_minutes = sum(w.duration_minutes for w in windows)
    if free_minutes <= 0:
        status = 'BLOCKED'
    elif free_minutes < total_minutes:
        status = 'PARTIAL'
    else:
        status = 'AVAILABLE'
    return AvailabilitySummary(
        resource_key=calendar.resource_key,
        working_windows=windows,
        downtime=dt_list,
        reservations=res_list,
        availability_status=status,
    )


def enj_gunduz_window(day: datetime) -> WorkingWindow:
    d = day.date()
    return WorkingWindow(
        datetime(d.year, d.month, d.day, 7, 0),
        datetime(d.year, d.month, d.day, 17, 0),
        'enj_gunduz',
    )


def enj_gece_window(day: datetime) -> WorkingWindow:
    """Gece vardiyasi — 17:00 → ertesi 07:00."""
    d = day.date()
    start = datetime(d.year, d.month, d.day, 17, 0)
    end = start + timedelta(hours=VARDIYA_SAAT['gece']['sure_saat'])
    return WorkingWindow(start, end, 'enj_gece')


def default_monta_b1(**kwargs) -> ResourceCalendarSpec:
    return monta_calendar('SOLARIZ', 1, **kwargs)


def default_enj_m1_a(**kwargs) -> ResourceCalendarSpec:
    return enj_slot_calendar('M1', 'A', **kwargs)
