# -*- coding: utf-8 -*-
"""Araç Takip — plan job change / cancel / defer / transfer service."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from db import get_conn, tablo_var_mi
from modules.planlama.arac_add_to_plan_service import (
    PLAN_PROVIDER_FILOM,
    _add_plan_item_conn,
    _get_or_create_daily_plan_conn,
)
from modules.planlama.arac_takip_repo import (
    INACTIVE_PLAN_STATUSES,
    PLAN_ITEM_STATUS,
    _plan_task_dto,
    _row_dict,
    _uret_talep_no,
    tables_ready,
)

VALID_ACTIONS = frozenset({
    'bind_location',
    'transfer_vehicle',
    'defer_next_day',
    'cancel',
    'iptal',
    'complete',
    'reorder_info',
    # legacy alias — mapped to cancel, never physical DELETE
    'delete',
})

VISIT_ACTIVE = frozenset({'ARRIVED', 'DEPARTED_PENDING'})


class PlanChangeError(ValueError):
    pass


class PlanChangeForbidden(PermissionError):
    pass


def change_tables_ready() -> bool:
    return tables_ready() and tablo_var_mi('arac_plan_is_degisim')


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _tomorrow_iso(from_date: str | None = None) -> str:
    base = date.fromisoformat((from_date or date.today().isoformat())[:10])
    return (base + timedelta(days=1)).isoformat()


def _load_visit(plan_is_id: int) -> dict | None:
    from modules.planlama.arac_geofence_repo import geofence_tables_ready, get_visit_state
    if not geofence_tables_ready():
        return None
    row = get_visit_state(int(plan_is_id))
    return dict(row) if row else None


def _has_gps_events(con: sqlite3.Connection, plan_is_id: int, plan_id: int | None) -> bool:
    if tablo_var_mi('arac_plan_olay'):
        row = con.execute(
            """
            SELECT 1 FROM arac_plan_olay
            WHERE plan_is_id=? OR (plan_id=? AND plan_is_id IS NULL)
            LIMIT 1
            """,
            (int(plan_is_id), int(plan_id) if plan_id else 0),
        ).fetchone()
        if row:
            return True
    visit = _load_visit(plan_is_id)
    if visit and (visit.get('arrived_at') or visit.get('departed_at')):
        return True
    return False


def _allowed_actions(ctx: dict) -> dict[str, bool | str]:
    st = (ctx.get('status') or 'PLANLANDI').upper()
    visit = (ctx.get('visit_state') or 'OUTSIDE').upper()
    has_visit = visit in VISIT_ACTIVE or bool(ctx.get('arrived_at'))
    has_coords = bool(ctx.get('has_coordinates'))
    gps_ev = bool(ctx.get('has_gps_events'))
    pri = (ctx.get('priority') or 'NORMAL').upper()
    locked_done = st == 'TAMAMLANDI'
    locked_started = st == 'BASLADI'
    inactive = st in INACTIVE_PLAN_STATUSES

    notes: dict[str, str] = {}
    if locked_done:
        notes['general'] = 'Tamamlanan iş değiştirilemez.'
    elif inactive:
        notes['general'] = 'Bu kayıt artık aktif planda değil.'

    # TAMAMLANDI: all change actions blocked; reorder_info omitted for cleanliness
    if locked_done:
        return {
            'bind_location': False,
            'transfer_vehicle': False,
            'defer_next_day': False,
            'cancel': False,
            'complete': False,
            'reorder_info': False,
            'notes': notes,
            'acil_warning': False,
            'locked': True,
            'lock_reason': 'Bu iş tamamlandığı için değiştirilemez.',
        }

    return {
        'bind_location': (not inactive and not has_visit and not has_coords),
        'transfer_vehicle': (st == 'PLANLANDI' and not has_visit and not inactive),
        'defer_next_day': (st in ('PLANLANDI', 'BASLADI') and not inactive),
        'cancel': (st in ('PLANLANDI', 'BASLADI') and not inactive),
        'complete': (not inactive and (visit == 'DEPARTED_PENDING' or st == 'BASLADI')),
        'reorder_info': True,
        'notes': notes,
        'acil_warning': pri == 'ACIL',
        'locked': False,
        'lock_reason': None,
    }


def _fetch_context(con: sqlite3.Connection, plan_is_id: int) -> dict:
    row = con.execute(
        """
        SELECT pi.*, p.plan_tarihi, p.arac_external_id, p.arac_plaka_snapshot,
               p.sofor_id, p.sofor_adi_snapshot, p.id AS plan_header_id
        FROM arac_gunluk_plan_is pi
        JOIN arac_gunluk_plan p ON p.id = pi.plan_id
        WHERE pi.id=?
        """,
        (int(plan_is_id),),
    ).fetchone()
    if not row:
        raise PlanChangeError('Plan kalemi bulunamadı')
    talep = con.execute(
        'SELECT * FROM arac_is_talebi WHERE id=?', (row['is_talebi_id'],),
    ).fetchone()
    if not talep:
        raise PlanChangeError('İş talebi bulunamadı')
    master = None
    if talep['kayitli_yer_id']:
        master = con.execute(
            'SELECT * FROM arac_kayitli_yer WHERE id=?', (talep['kayitli_yer_id'],),
        ).fetchone()
    task = _plan_task_dto(row, talep, master)
    visit = _load_visit(int(plan_is_id))
    visit_state = (visit or {}).get('state') or 'OUTSIDE'
    ctx = {
        **task,
        'plan_id': row['plan_header_id'],
        'plan_tarihi': row['plan_tarihi'],
        'arac_external_id': row['arac_external_id'],
        'arac_plaka_snapshot': row['arac_plaka_snapshot'],
        'sofor_id': row['sofor_id'],
        'sofor_adi_snapshot': row['sofor_adi_snapshot'],
        'visit_state': visit_state,
        'visit_label': visit_state,
        'arrived_at': (visit or {}).get('arrived_at'),
        'departed_at': (visit or {}).get('departed_at'),
        'has_gps_events': _has_gps_events(con, int(plan_is_id), int(row['plan_header_id'])),
        'status_label': PLAN_ITEM_STATUS.get(task['status'], task['status']),
    }
    ctx['allowed_actions'] = _allowed_actions(ctx)
    return ctx


def get_plan_job_detail(plan_is_id: int) -> dict:
    if not tables_ready():
        raise RuntimeError('Tablolar hazır değil')
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        ctx = _fetch_context(con, int(plan_is_id))
        vehicles = con.execute(
            """
            SELECT arac_external_id, arac_plaka_snapshot, sofor_adi_snapshot
            FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider=? AND durum='AKTIF'
            ORDER BY arac_plaka_snapshot
            """,
            (ctx['plan_tarihi'], PLAN_PROVIDER_FILOM),
        ).fetchall()
        return {
            'ok': True,
            'detail': ctx,
            'vehicles': [dict(v) for v in vehicles],
            'default_target_date': _tomorrow_iso(ctx['plan_tarihi']),
        }
    finally:
        con.close()


def _check_idempotent(con: sqlite3.Connection, client_submit_id: str | None) -> dict | None:
    if not client_submit_id or not change_tables_ready():
        return None
    row = con.execute(
        'SELECT * FROM arac_plan_is_degisim WHERE client_submit_id=?',
        (client_submit_id,),
    ).fetchone()
    if not row:
        return None
    meta = {}
    if row['metadata_json']:
        try:
            meta = json.loads(row['metadata_json'])
        except json.JSONDecodeError:
            meta = {}
    return {'ok': True, 'duplicate': True, **meta}


def _write_audit(
    con: sqlite3.Connection,
    *,
    plan_is_id: int,
    action: str,
    user_id: int,
    reason: str | None,
    old_ctx: dict,
    new_durum: str | None = None,
    new_plan_tarihi: str | None = None,
    new_arac_external_id: str | None = None,
    new_plan_is_id: int | None = None,
    client_submit_id: str | None = None,
    extra: dict | None = None,
) -> None:
    if not change_tables_ready():
        return
    payload = extra or {}
    con.execute(
        """
        INSERT INTO arac_plan_is_degisim (
            plan_is_id, action, reason,
            old_plan_tarihi, new_plan_tarihi,
            old_arac_external_id, new_arac_external_id,
            old_durum, new_durum, new_plan_is_id,
            metadata_json, client_submit_id, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            int(plan_is_id), action, (reason or '').strip() or None,
            old_ctx.get('plan_tarihi'), new_plan_tarihi,
            old_ctx.get('arac_external_id'), new_arac_external_id,
            old_ctx.get('status'), new_durum, new_plan_is_id,
            json.dumps(payload, ensure_ascii=False) if payload else None,
            client_submit_id, _now_iso(), int(user_id),
        ),
    )


def _clone_talep_conn(con: sqlite3.Connection, talep_row: sqlite3.Row, user_id: int, now: str) -> int:
    talep_no = _uret_talep_no(con)
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            istenen_saat, kayitli_yer_id, firma_adi, kisi_adi, telefon, adres,
            konum_linki, latitude, longitude, yapilacak_is, oncelik, not_text,
            durum, save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
        """,
        (
            talep_no,
            talep_row['talep_eden_user_id'],
            talep_row['talep_eden_adi_snapshot'],
            now[:10],
            talep_row['istenen_saat'],
            talep_row['kayitli_yer_id'],
            talep_row['firma_adi'],
            talep_row['kisi_adi'],
            talep_row['telefon'],
            talep_row['adres'],
            talep_row['konum_linki'],
            talep_row['latitude'],
            talep_row['longitude'],
            talep_row['yapilacak_is'],
            talep_row['oncelik'],
            talep_row['not_text'],
            now, user_id, now, user_id,
        ),
    )
    return int(cur.lastrowid)


def apply_plan_job_change(plan_is_id: int, user_id: int, payload: dict) -> dict:
    if not tables_ready():
        raise RuntimeError('Tablolar hazır değil')
    action = (payload.get('action') or '').strip().lower()
    if action == 'iptal':
        action = 'cancel'
    mapped_from_delete = False
    if action == 'delete':
        mapped_from_delete = True
        action = 'cancel'
    if action not in VALID_ACTIONS:
        raise PlanChangeError(f'Geçersiz aksiyon: {action}')
    if action == 'reorder_info':
        return {
            'ok': True,
            'message': 'Saatler rota hesaplamasıyla atanır. Sıra değişikliği rota panelinden uygulanır.',
        }

    reason = (payload.get('reason') or '').strip()
    client_submit_id = (payload.get('client_submit_id') or '').strip() or None
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        dup = _check_idempotent(con, client_submit_id)
        if dup:
            return dup

        ctx = _fetch_context(con, int(plan_is_id))
        allowed = ctx['allowed_actions']
        if not allowed.get(action):
            if mapped_from_delete:
                raise PlanChangeError('Bu iş silinemez; iptal olarak kapatabilirsiniz.')
            raise PlanChangeForbidden(f'Bu işlem şu an izinli değil: {action}')

        if action in ('cancel', 'defer_next_day') and not reason:
            raise PlanChangeError('Neden alanı zorunlu')

        now = _now_iso()
        result_extra: dict[str, Any] = {'action': action, 'plan_is_id': int(plan_is_id)}
        if mapped_from_delete:
            result_extra['mapped_from'] = 'delete'
        new_plan_is_id = None

        con.execute('BEGIN IMMEDIATE')

        if action == 'bind_location':
            loc_id = payload.get('location_id') or payload.get('kayitli_yer_id')
            lat = payload.get('latitude') or payload.get('lat')
            lng = payload.get('longitude') or payload.get('lng')
            adres = (payload.get('adres') or payload.get('address') or '').strip()
            maps_url = (payload.get('maps_url') or payload.get('konum_linki') or '').strip()
            talep = con.execute(
                'SELECT * FROM arac_is_talebi WHERE id=?', (ctx['is_talebi_id'],),
            ).fetchone()
            if loc_id:
                master = con.execute(
                    'SELECT * FROM arac_kayitli_yer WHERE id=? AND aktif=1', (int(loc_id),),
                ).fetchone()
                if not master:
                    raise PlanChangeError('Kayıtlı konum bulunamadı')
                con.execute(
                    """
                    UPDATE arac_is_talebi
                    SET kayitli_yer_id=?, firma_adi=COALESCE(?, firma_adi),
                        adres=COALESCE(?, adres), latitude=?, longitude=?,
                        konum_linki=COALESCE(?, konum_linki),
                        updated_at=?, updated_by=?
                    WHERE id=?
                    """,
                    (
                        int(loc_id), master['firma_adi'], master['adres'] or adres,
                        master['latitude'], master['longitude'], master['konum_linki'] or maps_url,
                        now, user_id, ctx['is_talebi_id'],
                    ),
                )
            elif lat not in (None, '') and lng not in (None, ''):
                con.execute(
                    """
                    UPDATE arac_is_talebi
                    SET latitude=?, longitude=?,
                        adres=COALESCE(NULLIF(?, ''), adres),
                        konum_linki=COALESCE(NULLIF(?, ''), konum_linki),
                        updated_at=?, updated_by=?
                    WHERE id=?
                    """,
                    (float(lat), float(lng), adres, maps_url, now, user_id, ctx['is_talebi_id']),
                )
            else:
                raise PlanChangeError('location_id veya latitude/longitude gerekli')
            new_durum = ctx['status']

        elif action == 'transfer_vehicle':
            target_vid = str(payload.get('target_vehicle_external_id') or '').strip()
            if not target_vid:
                raise PlanChangeError('target_vehicle_external_id gerekli')
            if target_vid == str(ctx['arac_external_id']):
                raise PlanChangeError('İş zaten bu araçta')
            plate = (payload.get('target_plate') or payload.get('arac_plaka') or target_vid).strip()
            sofor = (payload.get('sofor_adi') or payload.get('driver') or '').strip() or None
            target_plan_id = _get_or_create_daily_plan_conn(
                con, user_id, ctx['plan_tarihi'], target_vid, plate, None, sofor, now,
            )
            max_sira = con.execute(
                'SELECT COALESCE(MAX(sira),0) ms FROM arac_gunluk_plan_is WHERE plan_id=?',
                (target_plan_id,),
            ).fetchone()['ms']
            con.execute(
                'UPDATE arac_gunluk_plan_is SET plan_id=?, sira=? WHERE id=?',
                (target_plan_id, int(max_sira) + 1, int(plan_is_id)),
            )
            new_durum = ctx['status']
            result_extra['new_arac_external_id'] = target_vid

        elif action == 'defer_next_day':
            target_date = (payload.get('target_date') or _tomorrow_iso(ctx['plan_tarihi']))[:10]
            old_status = 'GIDILEMEDI' if payload.get('mark_gidilemedi') else 'ERTELENDI'
            con.execute(
                'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
                (old_status, int(plan_is_id)),
            )
            talep = con.execute(
                'SELECT * FROM arac_is_talebi WHERE id=?', (ctx['is_talebi_id'],),
            ).fetchone()
            new_talep_id = _clone_talep_conn(con, talep, user_id, now)
            target_vid = str(payload.get('target_vehicle_external_id') or ctx['arac_external_id'])
            plate = (payload.get('target_plate') or ctx['arac_plaka_snapshot'] or target_vid).strip()
            sofor = (payload.get('sofor_adi') or ctx['sofor_adi_snapshot'] or '').strip() or None
            target_plan_id = _get_or_create_daily_plan_conn(
                con, user_id, target_date, target_vid, plate, None, sofor, now,
            )
            new_plan_is_id = _add_plan_item_conn(
                con, user_id, target_plan_id, new_talep_id,
                talep['istenen_saat'], None, now,
            )
            new_durum = old_status
            result_extra.update({
                'new_plan_is_id': new_plan_is_id,
                'new_plan_tarihi': target_date,
                'new_status': 'PLANLANDI',
            })

        elif action == 'cancel':
            con.execute(
                'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
                ('IPTAL', int(plan_is_id)),
            )
            new_durum = 'IPTAL'
            result_extra['message'] = 'İş plan dışına alındı.'

        elif action == 'complete':
            con.execute(
                'UPDATE arac_gunluk_plan_is SET durum=? WHERE id=?',
                ('TAMAMLANDI', int(plan_is_id)),
            )
            if tablo_var_mi('arac_plan_is_ziyaret_durum'):
                con.execute(
                    """
                    UPDATE arac_plan_is_ziyaret_durum
                    SET result_status=NULL, updated_at=?
                    WHERE plan_is_id=?
                    """,
                    (now, int(plan_is_id)),
                )
            new_durum = 'TAMAMLANDI'

        else:
            raise PlanChangeError(f'Desteklenmeyen aksiyon: {action}')

        _write_audit(
            con,
            plan_is_id=int(plan_is_id),
            action='cancel' if mapped_from_delete else action,
            user_id=user_id,
            reason=reason,
            old_ctx=ctx,
            new_durum=new_durum,
            new_plan_tarihi=result_extra.get('new_plan_tarihi'),
            new_arac_external_id=result_extra.get('new_arac_external_id'),
            new_plan_is_id=new_plan_is_id,
            client_submit_id=client_submit_id,
            extra=result_extra,
        )
        con.commit()
        out = {'ok': True, **result_extra}
        if action == 'cancel' and 'message' not in out:
            out['message'] = 'İş plan dışına alındı.'
        return out
    except sqlite3.IntegrityError:
        con.rollback()
        raise PlanChangeError('Bu iş silinemez; iptal olarak kapatabilirsiniz.')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
