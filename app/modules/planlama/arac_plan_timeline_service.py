# -*- coding: utf-8 -*-
"""Plan olay zaman çizelgesi — READ-ONLY from arac_plan_olay."""
from __future__ import annotations

import json
import sqlite3

from modules.planlama.arac_gps_poll_service import parse_gps_timestamp
from modules.planlama.arac_takip_repo import get_conn

OLAY_LABELS = {
    'ROTA_SAPMA_BASLADI': 'Rota sapması başladı',
    'ROTA_GERI_DONDU': 'Rotaya geri döndü',
    'KONUMA_VARILDI': 'Konuma varıldı',
    'KONUMDAN_AYRILDI': 'Konumdan ayrıldı',
    'ZIYARET_SONUC_BEKLIYOR': 'Ziyaret sonucu bekleniyor',
    'AMBIGUOUS_STOP': 'Belirsiz durak',
    'GEOFENCE_GIRIS': 'Geofence giriş',
    'GEOFENCE_CIKIS': 'Geofence çıkış',
    'GECIKME': 'Gecikme',
    'ROTA_SAPMA': 'Rota sapması',
    'NOT': 'Not',
}


def _fmt_time(iso: str | None) -> str | None:
    if not iso:
        return None
    dt = parse_gps_timestamp(iso)
    return dt.strftime('%H:%M') if dt else None


def _parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def list_plan_timeline(
    *,
    plan_id: int | None = None,
    plan_is_id: int | None = None,
    plan_date: str | None = None,
    vehicle_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Return chronological events from arac_plan_olay — no synthetic events."""
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_olay'",
        ).fetchone()
        if not exists:
            return {'ok': True, 'events': [], 'message': 'Olay tablosu hazır değil'}

        clauses: list[str] = []
        params: list = []
        if plan_id:
            clauses.append('plan_id=?')
            params.append(int(plan_id))
        if plan_is_id:
            clauses.append('plan_is_id=?')
            params.append(int(plan_is_id))
        if vehicle_id:
            clauses.append('arac_external_id=?')
            params.append(str(vehicle_id))
        if plan_date:
            clauses.append('date(olay_zamani)=?')
            params.append(plan_date)

        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = con.execute(
            f"""
            SELECT id, plan_id, plan_is_id, arac_external_id, olay_turu, mesaj,
                   metadata_json, olay_zamani, created_at
            FROM arac_plan_olay
            {where}
            ORDER BY COALESCE(olay_zamani, created_at) ASC, id ASC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

        events = []
        for row in rows:
            meta = _parse_meta(row['metadata_json'])
            olay = row['olay_turu']
            events.append({
                'id': int(row['id']),
                'plan_id': row['plan_id'],
                'plan_is_id': row['plan_is_id'],
                'vehicle_id': row['arac_external_id'],
                'type': olay,
                'title': OLAY_LABELS.get(olay, olay.replace('_', ' ').title()),
                'message': row['mesaj'],
                'time': row['olay_zamani'],
                'time_display': _fmt_time(row['olay_zamani']),
                'metadata': meta,
            })

        return {'ok': True, 'events': events, 'count': len(events)}
    finally:
        con.close()
