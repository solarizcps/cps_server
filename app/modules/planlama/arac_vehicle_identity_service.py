# -*- coding: utf-8 -*-
"""Canonical araç kimliği — outage-safe tiered resolver."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

from modules.planlama.arac_takip_repo import PLAN_PROVIDER_FILOM, get_conn

_RESOLVE_CACHE: ContextVar[dict[tuple[str, str], dict[str, str]] | None] = ContextVar(
    'atp_vehicle_identity_resolve_cache',
    default=None,
)

# Server-side trusted catalog — last successful Filom fetch (dropdown ile aynı kaynak).
_CATALOG_TTL_SEC = int(__import__('os').environ.get('TURKCELL_FILOM_TOKEN_TTL_SEC', '3600'))
_filom_catalog: dict[str, Any] = {'at': 0.0, 'by_id': {}}


class VehicleNotResolvedError(ValueError):
    code = 'VEHICLE_NOT_RESOLVED'

    def __init__(self, provider: str, external_id: str, detail: str = '') -> None:
        self.provider = provider
        self.external_id = external_id
        msg = f'VEHICLE_NOT_RESOLVED: Seçilen araç doğrulanamadı ({provider}/{external_id})'
        if detail:
            msg += f' — {detail}'
        super().__init__(msg)


def begin_vehicle_identity_request_scope() -> Token:
    """HTTP request / batch submit başında yeni boş cache scope aç."""
    return _RESOLVE_CACHE.set({})


def end_vehicle_identity_request_scope(token: Token) -> None:
    """Başarı, validation error ve exception yollarında scope kapat."""
    _RESOLVE_CACHE.reset(token)


@contextmanager
def vehicle_identity_request_scope() -> Iterator[None]:
    token = begin_vehicle_identity_request_scope()
    try:
        yield
    finally:
        end_vehicle_identity_request_scope(token)


def clear_vehicle_identity_resolve_cache() -> None:
    """Test helper — explicit empty scope (production: prefer request scope)."""
    _RESOLVE_CACHE.set({})


def _resolve_cache() -> dict[tuple[str, str], dict[str, str]]:
    cache = _RESOLVE_CACHE.get()
    if cache is None:
        cache = {}
        _RESOLVE_CACHE.set(cache)
    return cache


def _normalize_provider(provider: str | None) -> str:
    prov = (provider or PLAN_PROVIDER_FILOM).strip()
    if prov not in (PLAN_PROVIDER_FILOM, 'TURKCELL_FILOM'):
        raise VehicleNotResolvedError(prov, '', f'Desteklenmeyen provider: {prov}')
    return PLAN_PROVIDER_FILOM


def _plate_from_filom_dto(vehicle: dict) -> str:
    from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import normalize_plate_display

    plate_raw = (vehicle.get('plate') or '').strip()
    return (
        (vehicle.get('plate_display') or normalize_plate_display(plate_raw)).strip()
    )


def _identity_result(provider: str, external_id: str, plate: str, source: str) -> dict[str, str]:
    plate = (plate or '').strip()
    if not plate or plate == 'Plaka bilgisi yok':
        raise VehicleNotResolvedError(provider, external_id, f'Plaka boş ({source})')
    return {
        'arac_provider': provider,
        'arac_external_id': external_id,
        'arac_plaka_snapshot': plate,
        '_resolve_source': source,
    }


def update_filom_vehicle_catalog(vehicles: list[dict] | None) -> None:
    """Trusted catalog — başarılı Filom yanıtından beslenir."""
    if not vehicles:
        return
    by_id: dict[str, dict] = {}
    for vehicle in vehicles:
        vid = str(vehicle.get('id') or '').strip()
        if vid:
            by_id[vid] = vehicle
    _filom_catalog['by_id'] = by_id
    _filom_catalog['at'] = time.time()


def _catalog_entry(external_id: str) -> dict | None:
    by_id = _filom_catalog.get('by_id') or {}
    if not by_id:
        return None
    age = time.time() - float(_filom_catalog.get('at') or 0)
    if age > _CATALOG_TTL_SEC:
        return None
    return by_id.get(external_id)


def _lookup_gps_plate(provider: str, external_id: str) -> str | None:
    try:
        from modules.planlama.arac_gps_snapshot_repo import get_latest_gps_snapshot, gps_tables_ready
    except ImportError:
        return None
    if not gps_tables_ready():
        return None
    row = get_latest_gps_snapshot(external_id, provider=provider)
    if not row:
        return None
    plate = (row.get('plate_snapshot') or '').strip()
    return plate or None


def _lookup_plan_plate(provider: str, external_id: str) -> str | None:
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            """
            SELECT arac_plaka_snapshot
            FROM arac_gunluk_plan
            WHERE arac_provider=? AND arac_external_id=?
              AND TRIM(COALESCE(arac_plaka_snapshot, '')) != ''
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (provider, external_id),
        ).fetchone()
        if not row:
            return None
        plate = (row['arac_plaka_snapshot'] or '').strip()
        return plate or None
    finally:
        con.close()


def _try_live_filom_refresh(provider: str, external_id: str) -> dict[str, str] | None:
    """Canlı Filom — yalnız refresh; başarısızlık submit'i durdurmaz."""
    from modules.planlama.arac_operasyonu.services.turkcell_filom_adapter import get_live_vehicles

    live = get_live_vehicles()
    if not live.get('ok'):
        return None
    vehicles = live.get('vehicles') or []
    update_filom_vehicle_catalog(vehicles)
    for vehicle in vehicles:
        vid = str(vehicle.get('id') or '').strip()
        if vid != external_id:
            continue
        plate = _plate_from_filom_dto(vehicle)
        if plate:
            return _identity_result(provider, external_id, plate, 'filom_live')
    return None


def _resolve_vehicle_identity_impl(provider: str, external_id: str) -> dict[str, str]:
    # 1) Trusted in-memory Filom catalog (dropdown'un server-side karşılığı)
    cached = _catalog_entry(external_id)
    if cached:
        plate = _plate_from_filom_dto(cached)
        if plate:
            return _identity_result(provider, external_id, plate, 'filom_catalog')

    # 2) Son güvenilir GPS snapshot
    gps_plate = _lookup_gps_plate(provider, external_id)
    if gps_plate:
        return _identity_result(provider, external_id, gps_plate, 'gps_snapshot')

    # 3) Geçmiş doğrulanmış günlük plan snapshot
    plan_plate = _lookup_plan_plate(provider, external_id)
    if plan_plate:
        return _identity_result(provider, external_id, plan_plate, 'plan_history')

    # 4) Canlı Filom refresh (best-effort)
    live_hit = _try_live_filom_refresh(provider, external_id)
    if live_hit:
        return live_hit

    raise VehicleNotResolvedError(provider, external_id, 'Trusted catalog veya geçmiş kayıtta bulunamadı')


def resolve_vehicle_identity(provider: str | None, external_id: str | None) -> dict:
    """
    provider + external_id → doğrulanmış plaka snapshot.
    Submit başına aynı kimlik için tek çözüm (ContextVar cache).
    """
    prov = _normalize_provider(provider)
    ext_id = str(external_id or '').strip()
    if not ext_id:
        raise VehicleNotResolvedError(prov, ext_id, 'external_id boş')

    cache = _resolve_cache()
    key = (prov, ext_id)
    if key in cache:
        return dict(cache[key])

    result = _resolve_vehicle_identity_impl(prov, ext_id)
    cache[key] = result
    out = {
        'arac_provider': result['arac_provider'],
        'arac_external_id': result['arac_external_id'],
        'arac_plaka_snapshot': result['arac_plaka_snapshot'],
    }
    return out
