# -*- coding: utf-8 -*-
"""APS P2 — resource calendar / scheduling domain contracts (no DB migration)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

# Calendar types
CALENDAR_ENJ_SLOT = 'ENJ_SLOT'
CALENDAR_FIXED_DAILY = 'FIXED_DAILY'

# Weekend work modes
WEEKEND_HAYIR = 'HAYIR'
WEEKEND_EVET_ONAYLI = 'EVET_ONAYLI'

# Reservation statuses (blocking)
RESERVATION_STATUS_ACTIVE = 'ACTIVE'
RESERVATION_STATUS_PLANNED = 'PLANNED'
RESERVATION_STATUS_CANCELLED = 'CANCELLED'
RESERVATION_STATUS_PASSIVE = 'PASSIVE'

BLOCKING_RESERVATION_STATUSES = frozenset({
    RESERVATION_STATUS_ACTIVE,
    RESERVATION_STATUS_PLANNED,
})

# Downtime reasons (P2 contract — DB tablo yok)
DOWNTIME_REASONS = frozenset({
    'ELEKTRIK',
    'MAKINE_ARIZA',
    'KALIP_ARIZA',
    'BAKIM',
    'PERSONEL_YETERSIZ',
    'YONETICI_KAPATMA',
    'DIGER',
})

# Enj calisma modlari — enj_kapasite_motor parity
ENJ_CALISMA_GUNDUZ = 'GUNDUZ'
ENJ_CALISMA_GECE = 'GECE'
ENJ_CALISMA_GUNDUZ_GECE = 'GUNDUZ_GECE'


@dataclass
class ResourceCalendarSpec:
    """Domain contract — resource master DB migration P2'de yok."""
    resource_key: str
    location: str = 'SOLARIZ'
    calendar_type: str = CALENDAR_FIXED_DAILY
    normal_start: time = time(7, 0)
    normal_end: time = time(17, 0)
    normal_hours: float = 10.0
    max_overtime_hours: float = 14.0
    weekend_default: str = WEEKEND_HAYIR
    active: bool = True
    # Mesai — approved_hours NULL → normal_hours; overtime_approved=False → max normal_end
    approved_hours: float | None = None
    overtime_approved: bool = False
    # Hafta sonu
    weekend_work: str = WEEKEND_HAYIR
    weekend_shift_start: time | None = None
    weekend_shift_end: time | None = None
    # Enj slot-specific
    calisma_modu: str = ENJ_CALISMA_GUNDUZ_GECE
    hafta_sonu_kural: str = 'A'
    hs_vardiya: str | None = None

    def __post_init__(self) -> None:
        if self.weekend_work == WEEKEND_EVET_ONAYLI:
            if self.weekend_shift_start is None or self.weekend_shift_end is None:
                raise ValueError(
                    'STOP: weekend_work=EVET_ONAYLI icin weekend_shift_start/end zorunlu — '
                    'sahte hafta sonu saati uydurulamaz'
                )

    def effective_daily_hours(self) -> float:
        if self.approved_hours is not None:
            return min(float(self.approved_hours), float(self.max_overtime_hours))
        return float(self.normal_hours)

    def effective_end_time(self) -> time:
        """Fixed-daily: normal_end veya onaylı mesai uzatması."""
        if not self.overtime_approved or self.approved_hours is None:
            return self.normal_end
        from datetime import timedelta
        base = datetime(2000, 1, 1, self.normal_start.hour, self.normal_start.minute)
        end = base + timedelta(hours=self.approved_hours)
        return end.time()


@dataclass
class WorkingWindow:
    start: datetime
    end: datetime
    source: str = 'calendar'  # calendar | overtime | weekend_approved

    @property
    def duration_minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))


@dataclass
class DowntimeInterval:
    resource_key: str
    start: datetime
    end: datetime
    reason: str
    approved_by: str | None = None
    source: str | None = None


@dataclass
class ReservationInterval:
    resource_key: str
    start: datetime
    end: datetime
    status: str = RESERVATION_STATUS_ACTIVE
    reservation_id: int | None = None
    operation_id: int | None = None


@dataclass
class OperationScheduleTimes:
    """5 zaman ayrımı — P2 persist yok, contract only."""
    planned_start: datetime | None = None
    original_planned_end: datetime | None = None
    current_estimated_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None

    def resource_free_from(self) -> datetime | None:
        """Erken/geç bitiş — kapasite serbestlik noktası."""
        if self.actual_end:
            return self.actual_end
        return self.current_estimated_end or self.original_planned_end


@dataclass
class FirstAvailableResult:
    ok: bool
    first_available_start: datetime | None = None
    estimated_end: datetime | None = None
    working_windows_used: list[WorkingWindow] = field(default_factory=list)
    conflicts_skipped: list[ReservationInterval] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'ok': self.ok,
            'first_available_start': _fmt(self.first_available_start),
            'estimated_end': _fmt(self.estimated_end),
            'working_windows_used': [
                {'start': _fmt(w.start), 'end': _fmt(w.end), 'source': w.source}
                for w in self.working_windows_used
            ],
            'conflicts_skipped': [
                {
                    'resource_key': r.resource_key,
                    'start': _fmt(r.start),
                    'end': _fmt(r.end),
                    'status': r.status,
                }
                for r in self.conflicts_skipped
            ],
            'warnings': list(self.warnings),
        }


@dataclass
class ImpactAnalysisItem:
    operation_id: int | str
    old_end: datetime | None
    new_estimated_end: datetime | None
    delta_minutes: int
    affected_operations: list[int | str] = field(default_factory=list)
    requires_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            'operation_id': self.operation_id,
            'old_end': _fmt(self.old_end),
            'new_estimated_end': _fmt(self.new_estimated_end),
            'delta_minutes': self.delta_minutes,
            'affected_operations': list(self.affected_operations),
            'requires_approval': self.requires_approval,
        }


@dataclass
class AvailabilitySummary:
    resource_key: str
    working_windows: list[WorkingWindow]
    downtime: list[DowntimeInterval]
    reservations: list[ReservationInterval]
    availability_status: str  # AVAILABLE | PARTIAL | BLOCKED

    def to_dhtmlx_contract(self) -> dict[str, Any]:
        return {
            'resource_key': self.resource_key,
            'working_windows': [
                {'start': _fmt(w.start), 'end': _fmt(w.end), 'source': w.source}
                for w in self.working_windows
            ],
            'downtime': [
                {
                    'start': _fmt(d.start),
                    'end': _fmt(d.end),
                    'reason': d.reason,
                }
                for d in self.downtime
            ],
            'availability_status': self.availability_status,
        }


def _fmt(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def monta_calendar(org: str, band_no: int, **kwargs) -> ResourceCalendarSpec:
    from modules.planlama.aps_resource_keys import monta_resource_key
    defaults = {
        'resource_key': monta_resource_key(org, band_no),
        'location': org.upper(),
        'calendar_type': CALENDAR_FIXED_DAILY,
        'normal_start': time(7, 0),
        'normal_end': time(17, 0),
        'normal_hours': 10.0,
        'max_overtime_hours': 14.0,
        'weekend_default': WEEKEND_HAYIR,
    }
    defaults.update(kwargs)
    return ResourceCalendarSpec(**defaults)


def enj_slot_calendar(makine_kod: str, slot: str, **kwargs) -> ResourceCalendarSpec:
    """ENJ:M1:A — istasyonlar üst slot takvimi."""
    mk = str(makine_kod).strip().upper()
    sl = str(slot).strip().upper()
    return ResourceCalendarSpec(
        resource_key=f'ENJ:{mk}:{sl}',
        location='SOLARIZ',
        calendar_type=CALENDAR_ENJ_SLOT,
        calisma_modu=kwargs.pop('calisma_modu', ENJ_CALISMA_GUNDUZ_GECE),
        hafta_sonu_kural=kwargs.pop('hafta_sonu_kural', 'A'),
        **kwargs,
    )
