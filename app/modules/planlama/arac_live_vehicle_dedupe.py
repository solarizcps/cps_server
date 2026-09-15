# -*- coding: utf-8 -*-
"""Canlı Takip read-model — normalize plaka bazlı fiziksel araç deduplication."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any

_PLATE_KEY_RE = re.compile(r'[^A-Z0-9]')


def normalize_plate_key(plate: str | None) -> str:
    """Identity key: uppercase alfanumerik (boşluk/noktalama yok)."""
    return _PLATE_KEY_RE.sub('', (plate or '').upper())


def _parse_last_seen_ts(vehicle: dict) -> float:
    raw = (vehicle.get('last_seen_at') or '').strip()
    if not raw:
        return 0.0
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def _rank_vehicle(vehicle: dict, preferred_external_ids: set[str] | None) -> tuple:
    """
    Deterministic winner ranking (max wins):
    1) newest GPS timestamp
    2) fresh (not stale)
    3) in_use
    4) valid coordinates
    5) CPS preferred external id
    6) higher numeric external id (stable tie-break, not random)
    """
    preferred = preferred_external_ids or set()
    ext_id = str(vehicle.get('id') or '').strip()
    try:
        ext_num = int(ext_id)
    except ValueError:
        ext_num = 0
    return (
        _parse_last_seen_ts(vehicle),
        0 if vehicle.get('is_stale_data') else 1,
        1 if vehicle.get('in_use', True) else 0,
        1 if vehicle.get('has_valid_location') else 0,
        1 if ext_id in preferred else 0,
        ext_num,
    )


def _plate_key_for_vehicle(vehicle: dict) -> str:
    for field in ('plate', 'plate_display'):
        key = normalize_plate_key(vehicle.get(field))
        if key:
            return key
    return ''


def load_preferred_external_ids(con: sqlite3.Connection | None = None) -> set[str]:
    """
    CPS plan geçmişinden tercih edilen external id'ler.
    Aynı normalize plaka için en son güncellenen plan kaydı kazanır.
    """
    owned = con is None
    if owned:
        from modules.planlama.arac_takip_repo import get_conn

        con = get_conn()
    preferred: dict[str, tuple[float, str]] = {}
    try:
        rows = con.execute(
            """
            SELECT arac_external_id, arac_plaka_snapshot,
                   COALESCE(updated_at, created_at, '') AS ts
            FROM arac_gunluk_plan
            WHERE TRIM(COALESCE(arac_external_id, '')) != ''
              AND TRIM(COALESCE(arac_plaka_snapshot, '')) != ''
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        for ext_id, plate, ts in rows:
            key = normalize_plate_key(plate)
            if not key or not ext_id:
                continue
            ts_val = 0.0
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    ts_val = datetime.strptime(str(ts).strip(), fmt).timestamp()
                    break
                except ValueError:
                    continue
            prev = preferred.get(key)
            if prev is None or ts_val >= prev[0]:
                preferred[key] = (ts_val, str(ext_id).strip())
    finally:
        if owned and con is not None:
            con.close()
    return {ext_id for _, ext_id in preferred.values()}


def dedupe_live_vehicles(
    vehicles: list[dict],
    preferred_external_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Aynı fiziksel plaka için tek Canlı Takip satırı döndür.
    Eski teknik kayıtlar silinmez; yalnız read-model'de bastırılır.
    """
    preferred = preferred_external_ids or set()
    groups: dict[str, list[dict]] = {}
    passthrough: list[dict] = []

    for vehicle in vehicles:
        key = _plate_key_for_vehicle(vehicle)
        if not key:
            passthrough.append(vehicle)
            continue
        groups.setdefault(key, []).append(vehicle)

    winners: list[dict] = []
    suppressed: list[dict] = []
    ambiguous: list[dict] = []

    for key, items in groups.items():
        if len(items) == 1:
            winners.append(items[0])
            continue

        ranked = sorted(items, key=lambda v: _rank_vehicle(v, preferred), reverse=True)
        winner = ranked[0]
        top_rank = _rank_vehicle(winner, preferred)
        tied = [v for v in ranked[1:] if _rank_vehicle(v, preferred) == top_rank]
        if tied:
            ambiguous.append({
                'plate_key': key,
                'candidate_ids': [str(v.get('id')) for v in ranked],
                'selected_id': str(winner.get('id')),
                'reason': 'equal_rank_deterministic_external_id',
            })

        hidden_ids = [str(v.get('id')) for v in ranked[1:]]
        enriched = dict(winner)
        if hidden_ids:
            enriched['suppressed_device_ids'] = hidden_ids
            enriched['duplicate_resolution'] = 'newest_gps_timestamp'
        winners.extend([enriched])
        for loser in ranked[1:]:
            suppressed.append({
                'id': str(loser.get('id')),
                'plate_key': key,
                'last_seen_at': loser.get('last_seen_at'),
                'winner_id': str(winner.get('id')),
            })

    winners.extend(passthrough)
    winners.sort(key=lambda v: (_plate_key_for_vehicle(v), str(v.get('id') or '')))

    return {
        'vehicles': winners,
        'deduplicated': len(suppressed) > 0,
        'suppressed_count': len(suppressed),
        'suppressed': suppressed,
        'ambiguous': ambiguous,
        'unique_plate_count': len(groups) + len(passthrough),
    }
