# -*- coding: utf-8 -*-
"""Araç Takip V1.3 — canonical SQLite repository."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any

from db import get_conn, tablo_var_mi

PRIORITY_LABEL = {
    'DUSUK': 'Düşük', 'NORMAL': 'Normal', 'YUKSEK': 'Yüksek', 'ACIL': 'Acil',
}
STATUS_LABEL = {
    'BEKLIYOR': 'Bekliyor', 'PLANA_ALINDI': 'Plana Alındı',
    'REDDEDILDI': 'Reddedildi', 'IPTAL': 'İptal',
}
PLAN_ITEM_STATUS = {
    'PLANLANDI': 'Planlandı', 'BASLADI': 'Başladı',
    'TAMAMLANDI': 'Tamamlandı', 'IPTAL': 'İptal',
}

_SEED_LOCATIONS = [
    {
        'firma_adi': 'AVEL Avrupa Elektrik', 'kisi_adi': 'Mehmet Bey',
        'telefon': '0532 111 2233', 'adres': 'Tuzla OSB, İstanbul',
        'konum_linki': 'https://maps.google.com/?q=40.818,29.305',
        'latitude': 40.818, 'longitude': 29.305,
    },
    {
        'firma_adi': 'Anıl Torna', 'kisi_adi': 'Anıl Usta',
        'telefon': '0533 444 5566', 'adres': 'Pendik, İstanbul',
        'konum_linki': 'https://maps.google.com/?q=40.876,29.234',
        'latitude': 40.876, 'longitude': 29.234,
    },
    {
        'firma_adi': 'B Lojistik', 'kisi_adi': 'Ayşe Hanım',
        'telefon': '0216 555 0101', 'adres': 'Çayırova Mah., Kocaeli',
        'konum_linki': '', 'latitude': 40.825, 'longitude': 29.372,
    },
]


def tables_ready() -> bool:
    return all(
        tablo_var_mi(t)
        for t in ('arac_kayitli_yer', 'arac_is_talebi', 'arac_gunluk_plan', 'arac_gunluk_plan_is')
    )


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def _norm_firma(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _norm_phone(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _norm_adres(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _short_adres(adres: str, limit: int = 42) -> str:
    s = (adres or '').strip()
    return s if len(s) <= limit else s[: limit - 1] + '…'


def _row_dict(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def _uret_talep_no(con: sqlite3.Connection) -> str:
    """AIT-YYYY-NNNN — repo MTT standardı."""
    yil = datetime.now().year
    prefix = f'AIT-{yil}-'
    row = con.execute(
        "SELECT MAX(CAST(SUBSTR(talep_no, -4) AS INTEGER)) AS son "
        "FROM arac_is_talebi WHERE talep_no LIKE ?",
        (prefix + '%',),
    ).fetchone()
    son = int(row['son'] or 0) if row and row['son'] is not None else 0
    return f'{prefix}{son + 1:04d}'


def ensure_seed_locations(user_id: int = 0) -> None:
    if not tables_ready():
        return
    con = get_conn()
    try:
        cnt = con.execute('SELECT COUNT(*) c FROM arac_kayitli_yer WHERE aktif=1').fetchone()['c']
        if cnt:
            return
        now = _now_iso()
        for seed in _SEED_LOCATIONS:
            con.execute(
                """
                INSERT INTO arac_kayitli_yer (
                    firma_adi, kisi_adi, telefon, adres, konum_linki,
                    latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
                ) VALUES (?,?,?,?,?,?,?,1,0,?,?)
                """,
                (
                    seed['firma_adi'], seed['kisi_adi'], seed['telefon'], seed['adres'],
                    seed.get('konum_linki'), seed.get('latitude'), seed.get('longitude'),
                    now, user_id,
                ),
            )
        con.commit()
    finally:
        con.close()


def find_duplicate_location(candidate: dict) -> dict | None:
    if not tables_ready():
        return None
    nf = _norm_firma(candidate.get('firma_adi') or candidate.get('firma', ''))
    if not nf:
        return None
    np = _norm_phone(candidate.get('telefon', ''))
    na = _norm_adres(candidate.get('adres', ''))
    lat = candidate.get('latitude')
    lng = candidate.get('longitude')
    con = get_conn()
    try:
        rows = con.execute(
            'SELECT * FROM arac_kayitli_yer WHERE aktif=1',
        ).fetchall()
        for row in rows:
            if _norm_firma(row['firma_adi']) != nf:
                continue
            if np and _norm_phone(row['telefon'] or '') == np:
                return _location_dto(row)
            if na and _norm_adres(row['adres'] or '') == na:
                return _location_dto(row)
            if (
                lat is not None and lng is not None
                and row['latitude'] is not None and row['longitude'] is not None
                and abs(float(lat) - float(row['latitude'])) < 0.0001
                and abs(float(lng) - float(row['longitude'])) < 0.0001
            ):
                return _location_dto(row)
    finally:
        con.close()
    return None


def _location_dto(row: sqlite3.Row | dict, usage: dict | None = None) -> dict:
    usage = usage or {}
    r = _row_dict(row) or {}
    lat = r.get('latitude')
    lng = r.get('longitude')
    return {
        'id': str(r['id']),
        'firma': r.get('firma_adi', ''),
        'kisi': r.get('kisi_adi') or '',
        'telefon': r.get('telefon') or '',
        'adres': r.get('adres') or '',
        'latitude': lat,
        'longitude': lng,
        'maps_url': r.get('konum_linki') or '',
        'short_adres': _short_adres(r.get('adres') or ''),
        'has_location': lat is not None and lng is not None,
        'last_used_at': usage.get('last_used_at') or r.get('son_kullanim_at'),
        'usage_count': usage.get('usage_count', r.get('kullanim_sayisi') or 0),
    }


def search_locations(query: str = '', limit: int = 12) -> list[dict]:
    if not tables_ready():
        return []
    ensure_seed_locations()
    q = (query or '').strip()
    con = get_conn()
    try:
        if q:
            like = f'%{q}%'
            digits = _norm_phone(q)
            rows = con.execute(
                """
                SELECT * FROM arac_kayitli_yer
                WHERE aktif=1 AND (
                    firma_adi LIKE ? OR kisi_adi LIKE ? OR adres LIKE ? OR telefon LIKE ?
                    OR REPLACE(REPLACE(REPLACE(telefon,' ',''),'-',''),'+','') LIKE ?
                )
                ORDER BY COALESCE(son_kullanim_at,'') DESC, firma_adi
                LIMIT ?
                """,
                (like, like, like, like, f'%{digits}%' if digits else like, limit),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT * FROM arac_kayitli_yer WHERE aktif=1
                ORDER BY COALESCE(son_kullanim_at,'') DESC, firma_adi LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_location_dto(r) for r in rows]
    finally:
        con.close()


def get_location_suggestions(limit_recent: int = 5, limit_frequent: int = 5) -> dict:
    if not tables_ready():
        return {'recent': [], 'frequent': []}
    con = get_conn()
    try:
        recent = con.execute(
            """
            SELECT ky.* FROM arac_kayitli_yer ky
            WHERE ky.aktif=1 AND ky.son_kullanim_at IS NOT NULL
            ORDER BY ky.son_kullanim_at DESC LIMIT ?
            """,
            (limit_recent,),
        ).fetchall()
        frequent = con.execute(
            """
            SELECT ky.* FROM arac_kayitli_yer ky
            WHERE ky.aktif=1 AND ky.kullanim_sayisi > 0
            ORDER BY ky.kullanim_sayisi DESC, COALESCE(ky.son_kullanim_at,'') DESC
            LIMIT ?
            """,
            (limit_frequent + limit_recent,),
        ).fetchall()
        recent_ids = {r['id'] for r in recent}
        return {
            'recent': [_location_dto(r) for r in recent],
            'frequent': [_location_dto(r) for r in frequent if r['id'] not in recent_ids][:limit_frequent],
        }
    finally:
        con.close()


def _touch_location(con: sqlite3.Connection, loc_id: int | None) -> None:
    if not loc_id:
        return
    con.execute(
        """
        UPDATE arac_kayitli_yer
        SET kullanim_sayisi = COALESCE(kullanim_sayisi,0)+1, son_kullanim_at=?
        WHERE id=?
        """,
        (_now_iso(), loc_id),
    )


def create_is_talebi(session_user_id: int, payload: dict) -> dict:
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    ensure_seed_locations(session_user_id)
    now = _now_iso()
    try:
        talep_uid = int(payload.get('talep_eden_user_id') or session_user_id or 0)
    except (TypeError, ValueError):
        talep_uid = int(session_user_id or 0)
    talep_adi = (payload.get('talep_eden_adi') or payload.get('talep_eden') or '').strip()
    istenen_saat = (payload.get('istenen_saat') or '').strip() or None
    save_master = bool(payload.get('save_to_master'))
    loc_id = payload.get('location_master_id') or payload.get('kayitli_yer_id')
    try:
        loc_id = int(loc_id) if loc_id not in (None, '') else None
    except (TypeError, ValueError):
        loc_id = None

    firma = (payload.get('firma') or '').strip()
    kisi = (payload.get('kisi') or '').strip() or None
    telefon = (payload.get('telefon') or '').strip() or None
    adres = (payload.get('adres') or '').strip()
    konum = (payload.get('maps_url') or payload.get('konum_linki') or '').strip() or None
    lat = payload.get('latitude')
    lng = payload.get('longitude')
    try:
        lat = float(lat) if lat not in (None, '') else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng) if lng not in (None, '') else None
    except (TypeError, ValueError):
        lng = None

    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        master_action = 'none'
        if save_master and firma:
            dup = find_duplicate_location({
                'firma_adi': firma, 'telefon': telefon, 'adres': adres,
                'latitude': lat, 'longitude': lng,
            })
            if dup:
                loc_id = int(dup['id'])
                master_action = 'duplicate_reused'
            else:
                cur = con.execute(
                    """
                    INSERT INTO arac_kayitli_yer (
                        firma_adi, kisi_adi, telefon, adres, konum_linki,
                        latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
                    ) VALUES (?,?,?,?,?,?,?,1,0,?,?)
                    """,
                    (firma, kisi, telefon, adres, konum, lat, lng, now, session_user_id),
                )
                loc_id = int(cur.lastrowid)
                master_action = 'created'
        elif loc_id:
            master_action = 'linked_existing'

        if loc_id:
            _touch_location(con, loc_id)

        for _ in range(5):
            talep_no = _uret_talep_no(con)
            try:
                cur = con.execute(
                    """
                    INSERT INTO arac_is_talebi (
                        talep_no, talep_eden_user_id, talep_eden_adi_snapshot,
                        talep_tarihi, istenen_saat, kayitli_yer_id,
                        firma_adi, kisi_adi, telefon, adres, konum_linki,
                        latitude, longitude, yapilacak_is, oncelik, not_text,
                        durum, save_to_master, created_at, created_by, updated_at, updated_by
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'BEKLIYOR',?,?,?,?,?)
                    """,
                    (
                        talep_no, talep_uid, talep_adi,
                        payload.get('tarih') or now[:10], istenen_saat, loc_id,
                        firma, kisi, telefon, adres, konum, lat, lng,
                        payload.get('is') or payload.get('yapilacak_is') or '',
                        payload.get('oncelik') or 'NORMAL',
                        payload.get('not') or payload.get('not_text') or None,
                        1 if save_master else 0,
                        now, session_user_id, now, session_user_id,
                    ),
                )
                talep_id = int(cur.lastrowid)
                con.commit()
                row = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (talep_id,)).fetchone()
                dto = _talep_dto(row)
                dto['master_action'] = master_action
                return dto
            except sqlite3.IntegrityError as exc:
                if 'talep_no' in str(exc).lower() or 'unique' in str(exc).lower():
                    continue
                raise
        raise RuntimeError('talep_no üretilemedi')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _talep_dto(row: sqlite3.Row | dict) -> dict:
    r = _row_dict(row) or {}
    return {
        'id': r['id'],
        'talep_no': r.get('talep_no'),
        'talep_eden_user_id': r.get('talep_eden_user_id'),
        'talep_eden_adi': r.get('talep_eden_adi_snapshot'),
        'talep_eden': r.get('talep_eden_adi_snapshot'),
        'tarih': r.get('talep_tarihi'),
        'istenen_saat': r.get('istenen_saat'),
        'firma': r.get('firma_adi'),
        'kisi': r.get('kisi_adi'),
        'telefon': r.get('telefon'),
        'adres': r.get('adres'),
        'maps_url': r.get('konum_linki'),
        'is': r.get('yapilacak_is'),
        'oncelik': r.get('oncelik'),
        'oncelik_label': PRIORITY_LABEL.get(r.get('oncelik', ''), r.get('oncelik', '')),
        'not': r.get('not_text'),
        'durum': r.get('durum'),
        'durum_label': STATUS_LABEL.get(r.get('durum', ''), r.get('durum', '')),
        'location_master_id': r.get('kayitli_yer_id'),
        'save_to_master': bool(r.get('save_to_master')),
        'created_at': r.get('created_at'),
    }


def list_bekleyen_talepler() -> list[dict]:
    if not tables_ready():
        return []
    con = get_conn()
    try:
        rows = con.execute(
            """
            SELECT * FROM arac_is_talebi
            WHERE durum='BEKLIYOR'
            ORDER BY
                CASE oncelik WHEN 'ACIL' THEN 0 WHEN 'YUKSEK' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END,
                talep_tarihi, COALESCE(istenen_saat,'99:99'), id
            """,
        ).fetchall()
        return [_talep_dto(r) for r in rows]
    finally:
        con.close()


def get_talep_by_id(talep_id: int) -> dict | None:
    if not tables_ready():
        return None
    con = get_conn()
    try:
        row = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()
        return _talep_dto(row) if row else None
    finally:
        con.close()


def _plan_task_dto(row: sqlite3.Row, talep: sqlite3.Row) -> dict:
    t = _row_dict(talep) or {}
    pri = t.get('oncelik', 'NORMAL')
    st = row['durum']
    return {
        'id': f'pi-{row["id"]}',
        'plan_item_id': row['id'],
        'is_talebi_id': row['is_talebi_id'],
        'order_no': row['sira'],
        'planned_time': row['planlanan_saat'] or '—',
        'job_title': t.get('yapilacak_is') or '',
        'company_name': t.get('firma_adi') or '',
        'address_text': t.get('adres') or '',
        'phone': t.get('telefon') or '',
        'location_url': t.get('konum_linki') or '',
        'latitude': t.get('latitude'),
        'longitude': t.get('longitude'),
        'priority': pri,
        'priority_label': PRIORITY_LABEL.get(pri, pri),
        'distance_km': None,
        'distance_label': '—',
        'status': st,
        'status_label': PLAN_ITEM_STATUS.get(st, st),
    }


def list_plan_tasks(plan_date: str, arac_external_id: str) -> list[dict]:
    if not tables_ready() or not arac_external_id:
        return []
    con = get_conn()
    try:
        plan = con.execute(
            """
            SELECT id FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider='TURKCELL_FILOM' AND arac_external_id=?
            """,
            (plan_date, str(arac_external_id)),
        ).fetchone()
        if not plan:
            return []
        items = con.execute(
            'SELECT * FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (plan['id'],),
        ).fetchall()
        result = []
        for item in items:
            talep = con.execute(
                'SELECT * FROM arac_is_talebi WHERE id=?', (item['is_talebi_id'],),
            ).fetchone()
            if talep:
                result.append(_plan_task_dto(item, talep))
        return result
    finally:
        con.close()


def assign_to_plan(
    session_user_id: int,
    talep_id: int,
    plan_date: str,
    arac_external_id: str,
    arac_plaka: str,
    sofor_id: int | None,
    sofor_adi: str | None,
    planlanan_saat: str | None,
    sira: int | None = None,
) -> dict:
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    now = _now_iso()
    plan_saat = (planlanan_saat or '').strip() or None
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        talep = con.execute(
            "SELECT * FROM arac_is_talebi WHERE id=? AND durum='BEKLIYOR'",
            (int(talep_id),),
        ).fetchone()
        if not talep:
            raise ValueError('Talep bulunamadı veya bekleyen durumda değil')

        existing_item = con.execute(
            'SELECT id FROM arac_gunluk_plan_is WHERE is_talebi_id=?', (int(talep_id),),
        ).fetchone()
        if existing_item:
            raise ValueError('Talep zaten plana alınmış')

        plan = con.execute(
            """
            SELECT id FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider='TURKCELL_FILOM' AND arac_external_id=?
            """,
            (plan_date, str(arac_external_id)),
        ).fetchone()
        if plan:
            plan_id = plan['id']
            con.execute(
                """
                UPDATE arac_gunluk_plan
                SET sofor_id=?, sofor_adi_snapshot=?, updated_at=?, updated_by=?
                WHERE id=?
                """,
                (sofor_id, sofor_adi, now, session_user_id, plan_id),
            )
        else:
            cur = con.execute(
                """
                INSERT INTO arac_gunluk_plan (
                    plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                    sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
                ) VALUES (?,'TURKCELL_FILOM',?,?,?,?,'AKTIF',?,?,?,?)
                """,
                (
                    plan_date, str(arac_external_id), arac_plaka,
                    sofor_id, sofor_adi, now, session_user_id, now, session_user_id,
                ),
            )
            plan_id = int(cur.lastrowid)

        max_sira = con.execute(
            'SELECT COALESCE(MAX(sira),0) ms FROM arac_gunluk_plan_is WHERE plan_id=?',
            (plan_id,),
        ).fetchone()['ms']
        new_sira = int(sira) if sira else int(max_sira) + 1

        conflict = con.execute(
            'SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? AND sira=?',
            (plan_id, new_sira),
        ).fetchone()
        if conflict:
            bump_rows = con.execute(
                'SELECT id, sira FROM arac_gunluk_plan_is WHERE plan_id=? AND sira>=? ORDER BY sira DESC',
                (plan_id, new_sira),
            ).fetchall()
            for row in bump_rows:
                con.execute(
                    'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
                    (-int(row['id']), row['id']),
                )
            for row in bump_rows:
                con.execute(
                    'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
                    (int(row['sira']) + 1, row['id']),
                )

        use_saat = plan_saat or talep['istenen_saat']

        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,'PLANLANDI',?,?)
            """,
            (plan_id, int(talep_id), new_sira, use_saat, now, session_user_id),
        )
        con.execute(
            """
            UPDATE arac_is_talebi
            SET durum='PLANA_ALINDI', updated_at=?, updated_by=?
            WHERE id=?
            """,
            (now, session_user_id, int(talep_id)),
        )
        con.commit()
        return {
            'ok': True,
            'plan_id': plan_id,
            'talep': _talep_dto(con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()),
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def reorder_plan_items(
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    task_id: str,
    direction: str,
) -> list[dict]:
    if not tables_ready():
        return []
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        plan = con.execute(
            """
            SELECT id FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider='TURKCELL_FILOM' AND arac_external_id=?
            """,
            (plan_date, str(arac_external_id)),
        ).fetchone()
        if not plan:
            con.commit()
            return []
        items = con.execute(
            'SELECT * FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (plan['id'],),
        ).fetchall()
        if not items:
            con.commit()
            return []
        ids = [f"pi-{r['id']}" for r in items]
        try:
            idx = ids.index(task_id)
        except ValueError:
            con.commit()
            return list_plan_tasks(plan_date, arac_external_id)
        if direction == 'up' and idx > 0:
            items[idx], items[idx - 1] = items[idx - 1], items[idx]
        elif direction == 'down' and idx < len(items) - 1:
            items[idx], items[idx + 1] = items[idx + 1], items[idx]
        else:
            con.commit()
            return list_plan_tasks(plan_date, arac_external_id)
        now = _now_iso()
        # Two-phase reorder: UNIQUE(plan_id, sira) ihlali önlenir.
        # Tek fazda [2→1] yazarken mevcut sira=1 kaydı ile çakışma oluşur.
        for item in items:
            con.execute(
                'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
                (-int(item['id']), item['id']),
            )
        for i, item in enumerate(items, start=1):
            con.execute(
                'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
                (i, item['id']),
            )
        con.execute(
            'UPDATE arac_gunluk_plan SET updated_at=?, updated_by=? WHERE id=?',
            (now, session_user_id, plan['id']),
        )
        con.commit()
        return list_plan_tasks(plan_date, arac_external_id)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
