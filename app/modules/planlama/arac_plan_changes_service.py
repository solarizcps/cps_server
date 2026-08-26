# -*- coding: utf-8 -*-
"""Read-only plan change / inactive job visibility for daily screen."""
from __future__ import annotations

import json

from modules.planlama.arac_plan_change_service import change_tables_ready
from modules.planlama.arac_takip_repo import INACTIVE_PLAN_STATUSES, PLAN_ITEM_STATUS, get_conn, tables_ready

ACTION_LABELS = {
    'cancel': 'İptal',
    'delete': 'İptal',
    'defer_next_day': 'Ertelendi',
    'transfer_vehicle': 'Araç transferi',
    'bind_location': 'Konum bağlama',
    'complete': 'Tamamlandı',
}


def _parse_audit_message(metadata_json: str | None) -> str | None:
    if not metadata_json:
        return None
    try:
        meta = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return meta.get('message') if isinstance(meta, dict) else None


def _user_display_name(con, user_id: int | None) -> str | None:
    if not user_id:
        return None
    row = con.execute(
        'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
        (int(user_id),),
    ).fetchone()
    if not row:
        return None
    return (row['AdSoyad'] or row['KullaniciAdi'] or '').strip() or None


def list_plan_changes_for_date(plan_date: str) -> dict:
    """Inactive plan items for a date, enriched with latest audit metadata."""
    if not tables_ready():
        return {
            'ok': True,
            'plan_date': plan_date,
            'count': 0,
            'items': [],
            'message': 'Tablolar hazır değil',
        }

    inactive = tuple(sorted(INACTIVE_PLAN_STATUSES))
    placeholders = ','.join('?' * len(inactive))
    con = get_conn()
    try:
        rows = con.execute(
            f"""
            SELECT
                pi.id AS plan_is_id,
                pi.is_talebi_id AS talep_id,
                p.id AS plan_id,
                pi.durum AS current_durum,
                pi.sira,
                p.arac_external_id,
                p.arac_plaka_snapshot AS plaka,
                p.sofor_adi_snapshot AS sofor,
                t.firma_adi AS firma,
                t.yapilacak_is,
                t.istenen_saat AS planned_time
            FROM arac_gunluk_plan_is pi
            JOIN arac_gunluk_plan p ON p.id = pi.plan_id
            JOIN arac_is_talebi t ON t.id = pi.is_talebi_id
            WHERE p.plan_tarihi = ?
              AND pi.durum IN ({placeholders})
            ORDER BY pi.sira, pi.id
            """,
            (plan_date, *inactive),
        ).fetchall()

        items: list[dict] = []
        audit_ready = change_tables_ready()

        for row in rows:
            plan_is_id = int(row['plan_is_id'])
            audit = None
            if audit_ready:
                audit = con.execute(
                    """
                    SELECT * FROM arac_plan_is_degisim
                    WHERE plan_is_id=?
                      AND new_durum IN ({ph})
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """.format(ph=placeholders),
                    (plan_is_id, *inactive),
                ).fetchone()

            new_durum = (audit['new_durum'] if audit else row['current_durum']) or row['current_durum']
            old_durum = audit['old_durum'] if audit else None
            action = (audit['action'] if audit else None) or new_durum.lower()
            reason = (audit['reason'] if audit else None)
            created_at = audit['created_at'] if audit else None
            created_by = audit['created_by'] if audit else None
            message = _parse_audit_message(audit['metadata_json'] if audit else None)

            items.append({
                'plan_is_id': plan_is_id,
                'talep_id': row['talep_id'],
                'plan_id': row['plan_id'],
                'action': action,
                'action_label': ACTION_LABELS.get(action, action),
                'old_durum': old_durum,
                'old_durum_label': PLAN_ITEM_STATUS.get(old_durum, old_durum) if old_durum else None,
                'new_durum': new_durum,
                'new_durum_label': PLAN_ITEM_STATUS.get(new_durum, new_durum),
                'reason': reason,
                'message': message or 'İş plan dışına alındı.',
                'firma': row['firma'],
                'yapilacak_is': row['yapilacak_is'],
                'planned_time': row['planned_time'],
                'arac_external_id': row['arac_external_id'],
                'plaka': row['plaka'],
                'sofor': row['sofor'],
                'created_by': created_by,
                'created_by_name': _user_display_name(con, created_by),
                'created_at': created_at,
            })

        return {
            'ok': True,
            'plan_date': plan_date,
            'count': len(items),
            'items': items,
        }
    finally:
        con.close()
