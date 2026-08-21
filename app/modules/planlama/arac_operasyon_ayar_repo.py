# -*- coding: utf-8 -*-
"""Araç Takip V1.4A — canonical başlangıç noktası (arac_operasyon_ayar)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from db import get_conn, tablo_var_mi

from modules.planlama.arac_lokasyon_service import parse_maps_coords


def operasyon_ayar_ready() -> bool:
    return tablo_var_mi('arac_operasyon_ayar')


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _row_to_dto(row) -> dict | None:
    if not row:
        return None
    r = dict(row)
    return {
        'id': r['id'],
        'base_name': r['base_name'],
        'base_address': r.get('base_address') or '',
        'base_latitude': r.get('base_latitude'),
        'base_longitude': r.get('base_longitude'),
        'base_maps_url': r.get('base_maps_url') or '',
        'aktif': bool(r.get('aktif')),
        'updated_at': r.get('updated_at'),
    }


def get_active_base() -> dict | None:
    if not operasyon_ayar_ready():
        return None
    con = get_conn()
    try:
        row = con.execute(
            'SELECT * FROM arac_operasyon_ayar WHERE aktif=1 ORDER BY id DESC LIMIT 1',
        ).fetchone()
        return _row_to_dto(row)
    finally:
        con.close()


def save_base_location(session_user_id: int, payload: dict) -> dict:
    if not operasyon_ayar_ready():
        raise RuntimeError('arac_operasyon_ayar tablosu hazır değil')
    name = (payload.get('base_name') or payload.get('name') or '').strip()
    if not name:
        raise ValueError('Başlangıç noktası adı gerekli')
    address = (payload.get('base_address') or payload.get('address') or '').strip() or None
    maps_url = (payload.get('base_maps_url') or payload.get('maps_url') or '').strip()
    lat = payload.get('base_latitude') if 'base_latitude' in payload else payload.get('latitude')
    lng = payload.get('base_longitude') if 'base_longitude' in payload else payload.get('longitude')
    if lat in ('', None) or lng in ('', None):
        parsed_lat, parsed_lng = parse_maps_coords(maps_url)
        if lat in ('', None):
            lat = parsed_lat
        if lng in ('', None):
            lng = parsed_lng
    try:
        lat = float(lat) if lat not in (None, '') else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng) if lng not in (None, '') else None
    except (TypeError, ValueError):
        lng = None
    if lat is None or lng is None:
        raise ValueError('Koordinat gerekli — Google Maps linkinden okunamadıysa lat/lon girin')

    now = _now_iso()
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        existing = con.execute(
            'SELECT id FROM arac_operasyon_ayar WHERE aktif=1 ORDER BY id DESC LIMIT 1',
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE arac_operasyon_ayar
                SET base_name=?, base_latitude=?, base_longitude=?, base_address=?,
                    base_maps_url=?, updated_at=?, updated_by=?
                WHERE id=?
                """,
                (name, lat, lng, address, maps_url or None, now, session_user_id, existing['id']),
            )
            base_id = int(existing['id'])
        else:
            cur = con.execute(
                """
                INSERT INTO arac_operasyon_ayar (
                    base_name, base_latitude, base_longitude, base_address, base_maps_url,
                    aktif, created_at, updated_at, updated_by
                ) VALUES (?,?,?,?,?,1,?,?,?)
                """,
                (name, lat, lng, address, maps_url or None, now, now, session_user_id),
            )
            base_id = int(cur.lastrowid)
        con.commit()
        row = con.execute('SELECT * FROM arac_operasyon_ayar WHERE id=?', (base_id,)).fetchone()
        return {'ok': True, 'base': _row_to_dto(row)}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
