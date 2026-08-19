# -*- coding: utf-8 -*-
"""APS V1 — deterministic resource key naming."""
from __future__ import annotations

RESOURCE_TYPE_ENJ = 'ENJ_ISTASYON'
RESOURCE_TYPE_TEM = 'TEMIZLEME_HAT'
RESOURCE_TYPE_MONTA = 'MONTAJ_BAND'

RESERVATION_ACTIVE = 'ACTIVE'
RESERVATION_PLANNED = 'PLANNED'
RESERVATION_CANCELLED = 'CANCELLED'
RESERVATION_PASSIVE = 'PASSIVE'

BLOCKING_RESERVATION_STATUSES = frozenset({
    RESERVATION_ACTIVE,
    RESERVATION_PLANNED,
})

OPERATION_UNSCHEDULED = 'UNSCHEDULED'
OPERATION_SCHEDULED = 'SCHEDULED'
OPERATION_IN_PROGRESS = 'IN_PROGRESS'
OPERATION_DONE = 'DONE'


def enj_resource_key(makine_kod: str, slot: str, istasyon_no: int) -> str:
    """ENJ:M1:A:IST1"""
    mk = str(makine_kod or '').strip().upper()
    sl = str(slot or '').strip().upper()
    return f'ENJ:{mk}:{sl}:IST{int(istasyon_no)}'


def temizleme_resource_key(hat_no: int = 1) -> str:
    return f'TEMIZLEME:T{int(hat_no)}'


def monta_resource_key(org: str, band_no: int) -> str:
    """MONTA:SOLARIZ:B1 | MONTA:PERA:B2"""
    org_key = str(org or '').strip().upper()
    return f'MONTA:{org_key}:B{int(band_no)}'


def parse_enj_resource_key(resource_key: str) -> dict | None:
    parts = str(resource_key or '').split(':')
    if len(parts) != 4 or parts[0] != 'ENJ' or not parts[3].startswith('IST'):
        return None
    try:
        return {
            'makine_kod': parts[1],
            'slot': parts[2],
            'istasyon_no': int(parts[3][3:]),
        }
    except ValueError:
        return None


def operation_type_for_proses(proses_kod: str) -> str:
    pk = str(proses_kod or '').strip()
    mapping = {
        '26': 'enjeksiyon',
        '02': 'kesim',
        '15': 'saya',
        '08': 'baski',
        '28': 'montaj_bas',
        '30': 'montaj',
        '35': 'temizleme',
        '40': 'paketleme',
        '50': 'eva_hazir',
    }
    return mapping.get(pk, 'generic')
