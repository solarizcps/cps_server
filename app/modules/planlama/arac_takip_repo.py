# -*- coding: utf-8 -*-
"""Araç Takip V1.3 — canonical SQLite repository."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
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
    'ERTELENDI': 'Ertelendi', 'GIDILEMEDI': 'Gidilemedi',
}
PLAN_ITEM_STATUS_KEYS = (
    'PLANLANDI', 'BASLADI', 'TAMAMLANDI', 'IPTAL', 'ERTELENDI', 'GIDILEMEDI',
)
OPERATIONAL_STATUS_KEYS = ('PLANLANDI', 'BASLADI', 'TAMAMLANDI')
INACTIVE_PLAN_STATUSES = frozenset({'IPTAL', 'ERTELENDI', 'GIDILEMEDI'})
NEXT_ITEM_STATUSES = frozenset({'PLANLANDI', 'BASLADI'})
PLAN_PROVIDER_FILOM = 'TURKCELL_FILOM'
IS_TURU_LABEL = {
    'ALINACAK': 'Alınacak',
    'GONDERILECEK': 'Gönderilecek',
    'ZIYARET': 'Ziyaret / Evrak',
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


def ux_v2_columns_ready() -> bool:
    if not tablo_var_mi('arac_is_talebi'):
        return False
    con = get_conn()
    try:
        cols = {r[1] for r in con.execute('PRAGMA table_info(arac_is_talebi)').fetchall()}
        return all(c in cols for c in (
            'sofor_id', 'sofor_adi_snapshot', 'is_turu', 'urun_malzeme',
            'miktar', 'miktar_birim', 'ek_not',
        ))
    finally:
        con.close()


def multi_location_columns_ready() -> bool:
    if not tablo_var_mi('arac_kayitli_yer'):
        return False
    con = get_conn()
    try:
        cols = {r[1] for r in con.execute('PRAGMA table_info(arac_kayitli_yer)').fetchall()}
        return all(c in cols for c in ('konum_adi', 'cari_id', 'updated_at'))
    finally:
        con.close()


def idempotency_ready() -> bool:
    return tablo_var_mi('arac_plana_idempotency')


def _parse_ux_v2_payload(payload: dict) -> dict:
    from modules.planlama.arac_sofor_service import resolve_sofor_from_payload

    sofor_id, sofor_adi = resolve_sofor_from_payload(payload)
    is_turu = (payload.get('is_turu') or '').strip().upper() or None
    if is_turu not in (None, 'ALINACAK', 'GONDERILECEK', 'ZIYARET'):
        is_turu = None
    urun_malzeme = (payload.get('urun_malzeme') or '').strip() or None
    miktar = None
    miktar_raw = payload.get('miktar')
    if miktar_raw not in (None, ''):
        try:
            miktar = float(miktar_raw)
        except (TypeError, ValueError):
            miktar = None
    miktar_birim = (payload.get('miktar_birim') or '').strip() or None
    ek_not = (payload.get('ek_not') or '').strip() or None
    return {
        'sofor_id': sofor_id,
        'sofor_adi_snapshot': sofor_adi,
        'is_turu': is_turu,
        'urun_malzeme': urun_malzeme,
        'miktar': miktar,
        'miktar_birim': miktar_birim,
        'ek_not': ek_not,
    }


def _product_summary(urun: str | None, miktar: float | None, birim: str | None) -> str | None:
    parts = []
    if urun:
        parts.append(urun)
    if miktar is not None:
        qty = str(int(miktar)) if miktar == int(miktar) else str(miktar)
        parts.append(qty + ((' ' + birim) if birim else ''))
    elif birim:
        parts.append(birim)
    return ' · '.join(parts) if parts else None


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
    firma = r.get('firma_adi', '')
    adres = r.get('adres') or ''
    konum_adi = (r.get('konum_adi') or '').strip() if multi_location_columns_ready() else ''
    short = _short_adres(adres)
    display = f'{konum_adi} — {short}' if konum_adi else short or adres
    return {
        'id': str(r['id']),
        'firma': firma,
        'name': firma,
        'kisi': r.get('kisi_adi') or '',
        'telefon': r.get('telefon') or '',
        'adres': adres,
        'address': adres,
        'konum_adi': konum_adi,
        'display_label': display,
        'cari_id': r.get('cari_id') if multi_location_columns_ready() else None,
        'latitude': lat,
        'longitude': lng,
        'maps_url': r.get('konum_linki') or '',
        'short_adres': short,
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


def list_company_locations(
    anchor_location_id: int | None = None,
    cari_id: int | None = None,
) -> dict:
    """List saved locations for a company (cari_id or anchor-scoped firma group)."""
    if not tables_ready():
        return {'locations': [], 'company': None}
    con = get_conn()
    try:
        anchor = None
        if anchor_location_id:
            anchor = con.execute(
                'SELECT * FROM arac_kayitli_yer WHERE id=? AND aktif=1',
                (int(anchor_location_id),),
            ).fetchone()
        resolved_cari = int(cari_id) if cari_id not in (None, '') else None
        if resolved_cari is None and anchor and multi_location_columns_ready():
            anchor_cari = anchor['cari_id'] if 'cari_id' in anchor.keys() else None
            if anchor_cari not in (None, ''):
                resolved_cari = int(anchor_cari)
        rows: list[sqlite3.Row] = []
        if resolved_cari is not None and multi_location_columns_ready():
            rows = con.execute(
                """
                SELECT * FROM arac_kayitli_yer
                WHERE aktif=1 AND cari_id=?
                ORDER BY COALESCE(son_kullanim_at,'') DESC, COALESCE(konum_adi,''), id
                """,
                (resolved_cari,),
            ).fetchall()
        elif anchor:
            nf = _norm_firma(anchor['firma_adi'] or '')
            all_rows = con.execute(
                """
                SELECT * FROM arac_kayitli_yer WHERE aktif=1
                ORDER BY COALESCE(son_kullanim_at,'') DESC, id
                """,
            ).fetchall()
            rows = [r for r in all_rows if _norm_firma(r['firma_adi'] or '') == nf]
        company = None
        if anchor:
            company = {
                'firma': anchor['firma_adi'],
                'cari_id': resolved_cari,
                'anchor_location_id': int(anchor['id']),
            }
        elif resolved_cari is not None:
            sample = rows[0] if rows else None
            company = {
                'firma': sample['firma_adi'] if sample else '',
                'cari_id': resolved_cari,
                'anchor_location_id': int(sample['id']) if sample else None,
            }
        return {
            'locations': [_location_dto(r) for r in rows],
            'company': company,
        }
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


def _ensure_kayitli_yer(
    con: sqlite3.Connection,
    session_user_id: int,
    firma: str,
    adres: str,
    latitude: float,
    longitude: float,
    konum_linki: str | None,
    kisi: str | None = None,
    telefon: str | None = None,
    existing_yer_id: int | None = None,
    now: str | None = None,
    konum_adi: str | None = None,
    cari_id: int | None = None,
) -> tuple[int, str]:
    """Create/reuse arac_kayitli_yer; returns (yer_id, master_action)."""
    now = now or _now_iso()
    master_action = 'reused'
    loc_id = None
    if existing_yer_id:
        row = con.execute(
            'SELECT id FROM arac_kayitli_yer WHERE id=? AND aktif=1',
            (int(existing_yer_id),),
        ).fetchone()
        if row:
            loc_id = int(existing_yer_id)
            master_action = 'linked_existing'
    if loc_id is None:
        nf = _norm_firma(firma)
        np = _norm_phone(telefon or '')
        na = _norm_adres(adres)
        rows = con.execute(
            'SELECT id, firma_adi, telefon, adres, latitude, longitude FROM arac_kayitli_yer WHERE aktif=1',
        ).fetchall()
        for row in rows:
            if _norm_firma(row['firma_adi'] or '') != nf:
                continue
            if (
                latitude is not None and longitude is not None
                and row['latitude'] is not None and row['longitude'] is not None
                and abs(float(latitude) - float(row['latitude'])) < 0.0001
                and abs(float(longitude) - float(row['longitude'])) < 0.0001
            ):
                loc_id = int(row['id'])
                master_action = 'reused'
                break
            if np and _norm_phone(row['telefon'] or '') == np:
                loc_id = int(row['id'])
                master_action = 'reused'
                break
            if na and _norm_adres(row['adres'] or '') == na:
                loc_id = int(row['id'])
                master_action = 'reused'
                break
    update_cols = [
        'latitude=?', 'longitude=?',
        'konum_linki=COALESCE(?, konum_linki)',
        'kisi_adi=COALESCE(?, kisi_adi)', 'telefon=COALESCE(?, telefon)',
    ]
    update_vals: list[Any] = [float(latitude), float(longitude), konum_linki, kisi, telefon]
    if multi_location_columns_ready():
        if konum_adi:
            update_cols.append('konum_adi=COALESCE(?, konum_adi)')
            update_vals.append(konum_adi.strip())
        if cari_id is not None:
            update_cols.append('cari_id=COALESCE(?, cari_id)')
            update_vals.append(int(cari_id))
        update_cols.append('updated_at=?')
        update_vals.append(now)
    if loc_id is not None:
        update_vals.append(loc_id)
        con.execute(
            f"UPDATE arac_kayitli_yer SET {', '.join(update_cols)} WHERE id=?",
            tuple(update_vals),
        )
    else:
        cols = [
            'firma_adi', 'kisi_adi', 'telefon', 'adres', 'konum_linki',
            'latitude', 'longitude', 'aktif', 'kullanim_sayisi', 'created_at', 'created_by',
        ]
        vals: list[Any] = [
            firma, kisi, telefon, adres, konum_linki,
            float(latitude), float(longitude), 1, 0, now, session_user_id,
        ]
        if multi_location_columns_ready():
            cols.extend(['konum_adi', 'cari_id', 'updated_at'])
            vals.extend([(konum_adi or '').strip() or None, cari_id, now])
        placeholders = ','.join('?' for _ in cols)
        cur = con.execute(
            f"INSERT INTO arac_kayitli_yer ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
        loc_id = int(cur.lastrowid)
        master_action = 'created'
    _touch_location(con, loc_id)
    return loc_id, master_action


def create_or_resolve_kayitli_yer(session_user_id: int, payload: dict) -> dict:
    """Resolve maps link → master row (Konum V1 canonical, no talep)."""
    from modules.planlama.arac_lokasyon_service import MAPS_COORD_USER_ERROR, parse_maps_coords

    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    firma = (payload.get('firma') or '').strip()
    adres = (payload.get('adres') or '').strip()
    if not firma:
        raise ValueError('Firma gerekli')
    if not adres:
        raise ValueError('Adres gerekli')
    maps_url = (payload.get('maps_url') or payload.get('konum_linki') or '').strip()
    if not maps_url:
        raise ValueError(MAPS_COORD_USER_ERROR)
    lat, lng = parse_maps_coords(maps_url)
    if lat is None or lng is None:
        raise ValueError(MAPS_COORD_USER_ERROR)
    kisi = (payload.get('kisi') or '').strip() or None
    telefon = (payload.get('telefon') or '').strip() or None
    now = _now_iso()
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        loc_id, master_action = _ensure_kayitli_yer(
            con, session_user_id, firma, adres, lat, lng, maps_url, kisi, telefon, None, now,
        )
        con.commit()
        row = con.execute('SELECT * FROM arac_kayitli_yer WHERE id=?', (loc_id,)).fetchone()
        loc = _location_dto(row)
        loc['master_action'] = master_action
        return {'ok': True, 'location': loc, 'master_action': master_action}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


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

    from modules.planlama.arac_lokasyon_service import parse_maps_coords
    lat = payload.get('latitude')
    lng = payload.get('longitude')
    explicit_coords = lat not in (None, '') or lng not in (None, '')
    if konum and not explicit_coords and not loc_id:
        parsed_lat, parsed_lng = parse_maps_coords(konum)
        if lat in (None, ''):
            lat = parsed_lat
        if lng in (None, ''):
            lng = parsed_lng
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

        if loc_id:
            master_row = con.execute(
                'SELECT * FROM arac_kayitli_yer WHERE id=? AND aktif=1', (loc_id,),
            ).fetchone()
            if master_row:
                if explicit_coords:
                    if lat is None and master_row['latitude'] is not None:
                        lat = float(master_row['latitude'])
                        lng = float(master_row['longitude'])
                else:
                    lat = None
                    lng = None
                if not konum and master_row['konum_linki']:
                    konum = master_row['konum_linki']
                if not firma:
                    firma = master_row['firma_adi'] or firma
                if not adres:
                    adres = master_row['adres'] or adres
                master_action = 'linked_existing'
        elif lat is not None and lng is not None and firma and adres:
            loc_id, master_action = _ensure_kayitli_yer(
                con, session_user_id, firma, adres, lat, lng, konum, kisi, telefon, None, now,
            )
            save_master = True
        elif save_master and firma and lat is not None and lng is not None:
            loc_id, master_action = _ensure_kayitli_yer(
                con, session_user_id, firma, adres, lat, lng, konum, kisi, telefon, None, now,
            )
        elif loc_id:
            master_action = 'linked_existing'

        if loc_id:
            _touch_location(con, loc_id)

        ux2 = _parse_ux_v2_payload(payload) if ux_v2_columns_ready() else {}
        not_text = (payload.get('not') or payload.get('not_text') or '').strip() or None

        for _ in range(5):
            talep_no = _uret_talep_no(con)
            try:
                if ux_v2_columns_ready():
                    cur = con.execute(
                        """
                        INSERT INTO arac_is_talebi (
                            talep_no, talep_eden_user_id, talep_eden_adi_snapshot,
                            talep_tarihi, istenen_saat, kayitli_yer_id,
                            firma_adi, kisi_adi, telefon, adres, konum_linki,
                            latitude, longitude, yapilacak_is, oncelik, not_text,
                            sofor_id, sofor_adi_snapshot, is_turu,
                            urun_malzeme, miktar, miktar_birim, ek_not,
                            durum, save_to_master, created_at, created_by, updated_at, updated_by
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'BEKLIYOR',?,?,?,?,?)
                        """,
                        (
                            talep_no, talep_uid, talep_adi,
                            payload.get('tarih') or now[:10], istenen_saat, loc_id,
                            firma, kisi, telefon, adres, konum, lat, lng,
                            payload.get('is') or payload.get('yapilacak_is') or '',
                            payload.get('oncelik') or 'NORMAL', not_text,
                            ux2.get('sofor_id'), ux2.get('sofor_adi_snapshot'), ux2.get('is_turu'),
                            ux2.get('urun_malzeme'), ux2.get('miktar'), ux2.get('miktar_birim'),
                            ux2.get('ek_not'),
                            1 if save_master else 0,
                            now, session_user_id, now, session_user_id,
                        ),
                    )
                else:
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
                            payload.get('oncelik') or 'NORMAL', not_text,
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
    is_turu = r.get('is_turu')
    urun = r.get('urun_malzeme')
    miktar = r.get('miktar')
    birim = r.get('miktar_birim')
    dto = {
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
        'is_detayi': r.get('not_text'),
        'durum': r.get('durum'),
        'durum_label': STATUS_LABEL.get(r.get('durum', ''), r.get('durum', '')),
        'location_master_id': r.get('kayitli_yer_id'),
        'save_to_master': bool(r.get('save_to_master')),
        'created_at': r.get('created_at'),
        'sofor_id': r.get('sofor_id'),
        'sofor_adi_snapshot': r.get('sofor_adi_snapshot'),
        'sofor': r.get('sofor_adi_snapshot'),
        'is_turu': is_turu,
        'is_turu_label': IS_TURU_LABEL.get(is_turu, is_turu) if is_turu else None,
        'urun_malzeme': urun,
        'miktar': miktar,
        'miktar_birim': birim,
        'ek_not': r.get('ek_not'),
        'urun_ozet': _product_summary(urun, miktar, birim),
    }
    return dto


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


def _plan_task_dto(row: sqlite3.Row, talep: sqlite3.Row, master: sqlite3.Row | None = None) -> dict:
    from modules.planlama.arac_location_resolver import resolve_item_location

    t = _row_dict(talep) or {}
    m = _row_dict(master) or {}
    pri = t.get('oncelik', 'NORMAL')
    st = row['durum']
    loc = resolve_item_location(t, m if m else None)

    # ── Semantik ayrım ─────────────────────────────────────────────────────
    # planlanan_saat = LEGACY "istenen" (plan eklenirken girilen veya talep fallback)
    # istenen_varis_saati = migration 188 sonrası canonical istenen
    # tahmini_varis_saati = migration 188 sonrası ETA (sadece sistem yazar)

    row_d = _row_dict(row) or {}

    # Canonical istenen — migration 188 uygulandıktan sonra dolu gelir
    # Önce mi-188 kolonunu, yoksa planlanan_saat'i (legacy anlamı = istenen) kullan
    if 'istenen_varis_saati' in row_d:
        istenen_varis = row_d.get('istenen_varis_saati') or None
        istenen_kaynak = row_d.get('istenen_saat_kaynak') or None
        istenen_manuel = bool(row_d.get('istenen_saat_manuel')) if row_d.get('istenen_saat_manuel') is not None else False
    else:
        # Migration 188 uygulanmamış — planlanan_saat'in legacy istenen anlamını kullan
        legacy_val = row_d.get('planlanan_saat') or None
        talep_val = t.get('istenen_saat') or None
        istenen_varis = legacy_val or talep_val or None
        if istenen_varis is None:
            istenen_kaynak = 'YOK'
        elif legacy_val and talep_val and legacy_val == talep_val:
            istenen_kaynak = 'SISTEM'
        elif legacy_val:
            istenen_kaynak = 'LEGACY'
        else:
            istenen_kaynak = 'SISTEM'
        istenen_manuel = False

    # Kaynak normalize: kolon geldi ama değer yoksa talep'ten fallback
    if istenen_varis is None and istenen_kaynak in (None, 'YOK'):
        talep_val = t.get('istenen_saat') or None
        if talep_val:
            istenen_varis = talep_val
            istenen_kaynak = 'SISTEM'
        else:
            istenen_varis = None
            istenen_kaynak = 'YOK'

    # ETA — sadece migration 188 sonrası tahmini_varis_saati kolonundan gelir
    # Migration öncesi: NULL (ETA hesaplanmamış anlamında doğru)
    eta_saati = row_d.get('tahmini_varis_saati') or None

    return {
        'id': f'pi-{row["id"]}',
        'plan_item_id': row['id'],
        'is_talebi_id': row['is_talebi_id'],
        'order_no': row['sira'],
        # planlanan_saat: legacy değer — görüntüleme ve geriye uyumluluk için korunur
        'planned_time': row_d.get('planlanan_saat') or '—',
        # Yeni semantik ayrımlı alanlar
        'istenen_varis_saati': istenen_varis,
        'istenen_saat_kaynak': istenen_kaynak,
        'istenen_saat_manuel': istenen_manuel,
        'tahmini_varis_saati': eta_saati,
        # Frontend/API alias'ları (optimizer DTO ve UI kullanır)
        'desired_time': istenen_varis,
        'desired_time_source': istenen_kaynak,
        'eta_time': eta_saati,
        'job_title': t.get('yapilacak_is') or '',
        'company_name': t.get('firma_adi') or '',
        'address_text': t.get('adres') or '',
        'phone': t.get('telefon') or '',
        'location_url': t.get('konum_linki') or '',
        'latitude': loc['latitude'],
        'longitude': loc['longitude'],
        'location_status': loc['location_status'],
        'location_source': loc['location_source'],
        'location_source_label': loc['location_source_label'],
        'has_coordinates': loc['has_coordinates'],
        'kayitli_yer_id': t.get('kayitli_yer_id'),
        'priority': pri,
        'priority_label': PRIORITY_LABEL.get(pri, pri),
        'distance_km': None,
        'distance_label': '—',
        'status': st,
        'status_label': PLAN_ITEM_STATUS.get(st, st),
    }


def get_active_plan_row(plan_date: str, arac_external_id: str) -> dict | None:
    """Günün aktif plan satırı — durum=AKTIF, UNIQUE(plan_tarihi, provider, external_id).

    cikis_saati kolonunu da döndürür (migration 187 ile eklendi; öncesinde NULL gelir).
    """
    if not tables_ready() or not arac_external_id:
        return None
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        # cikis_saati: idempotent — kolon yoksa (migration uygulanmamış ortam) SELECT * ile fallback
        try:
            row = con.execute(
                """
                SELECT id, plan_tarihi, arac_external_id, arac_plaka_snapshot, durum,
                       sofor_id, sofor_adi_snapshot, cikis_saati
                FROM arac_gunluk_plan
                WHERE plan_tarihi=? AND arac_provider=? AND arac_external_id=? AND durum='AKTIF'
                """,
                (plan_date, PLAN_PROVIDER_FILOM, str(arac_external_id)),
            ).fetchone()
        except Exception:
            row = con.execute(
                """
                SELECT id, plan_tarihi, arac_external_id, arac_plaka_snapshot, durum,
                       sofor_id, sofor_adi_snapshot
                FROM arac_gunluk_plan
                WHERE plan_tarihi=? AND arac_provider=? AND arac_external_id=? AND durum='AKTIF'
                """,
                (plan_date, PLAN_PROVIDER_FILOM, str(arac_external_id)),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d.setdefault('cikis_saati', None)
        return d
    finally:
        con.close()


def update_plan_cikis_saati(
    plan_id: int,
    cikis_saati: str | None,
    session_user_id: int,
    con: sqlite3.Connection,
) -> None:
    """Update arac_gunluk_plan.cikis_saati within an open transaction (caller commits)."""
    now = _now_iso()
    con.execute(
        'UPDATE arac_gunluk_plan SET cikis_saati=?, updated_at=?, updated_by=? WHERE id=?',
        (cikis_saati, now, session_user_id, plan_id),
    )


def update_plan_item_desired_time_conn(
    con: sqlite3.Connection,
    plan_is_id: int,
    istenen_varis_saati: str | None,
    kaynak: str,
    manuel: bool,
    session_user_id: int,
) -> None:
    """
    Update arac_gunluk_plan_is.istenen_varis_saati within an open transaction (caller commits).

    Migration 188 gerektirir. Kolon yoksa (migration uygulanmamış ortam) sessizce atlar.
    kaynak: 'SISTEM' | 'MANUEL' | 'SERBEST' | 'KULLANICI' | 'LEGACY' | 'YOK'

    NOT: planlanan_saat'e asla dokunmaz — bu alan legacy istenen saattir, ETA değildir.
    tahmini_varis_saati'ne de dokunmaz — o alan yalnız ETA servisi tarafından yazılır.
    """
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    if 'istenen_varis_saati' not in cols:
        return
    con.execute(
        """
        UPDATE arac_gunluk_plan_is
        SET istenen_varis_saati=?,
            istenen_saat_kaynak=?,
            istenen_saat_manuel=?
        WHERE id=?
        """,
        (
            istenen_varis_saati,
            kaynak,
            1 if manuel else 0,
            plan_is_id,
        ),
    )


def update_plan_item_eta_conn(
    con: sqlite3.Connection,
    plan_is_id: int,
    tahmini_varis_saati: str | None,
) -> None:
    """
    Update arac_gunluk_plan_is.tahmini_varis_saati — sadece ETA servisi çağırır.

    Migration 188 gerektirir. Kolon yoksa sessizce atlar.
    Kullanıcı istenen saatini (istenen_varis_saati, planlanan_saat) asla ezmez.
    """
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    if 'tahmini_varis_saati' not in cols:
        return
    con.execute(
        'UPDATE arac_gunluk_plan_is SET tahmini_varis_saati=? WHERE id=?',
        (tahmini_varis_saati, plan_is_id),
    )


def clear_plan_item_etas_conn(con: sqlite3.Connection, plan_id: int) -> int:
    """
    Clear stale ETA values for all items in a plan — caller-owned connection.

    Yalnız tahmini_varis_saati temizlenir; visit/geofence alanlarına dokunulmaz.
    Returns rows updated. No-op when column missing.
    """
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    if 'tahmini_varis_saati' not in cols:
        return 0
    cur = con.execute(
        'UPDATE arac_gunluk_plan_is SET tahmini_varis_saati=NULL WHERE plan_id=?',
        (int(plan_id),),
    )
    return int(cur.rowcount or 0)


def get_plan_vehicle_meta(plan_date: str, arac_external_id: str) -> dict | None:
    """Plan row vehicle snapshot for URL hydrate (external_id may differ from Filom id)."""
    if not tables_ready() or not arac_external_id:
        return None
    con = get_conn()
    try:
        row = con.execute(
            """
            SELECT arac_external_id, arac_plaka_snapshot, arac_provider
            FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider='TURKCELL_FILOM' AND arac_external_id=?
            """,
            (plan_date, str(arac_external_id)),
        ).fetchone()
        if not row:
            return None
        return {
            'external_id': row['arac_external_id'],
            'plate_snapshot': row['arac_plaka_snapshot'],
            'provider': row['arac_provider'],
        }
    finally:
        con.close()


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
            if not talep:
                continue
            master = None
            if talep['kayitli_yer_id']:
                master = con.execute(
                    'SELECT * FROM arac_kayitli_yer WHERE id=?',
                    (talep['kayitli_yer_id'],),
                ).fetchone()
            result.append(_plan_task_dto(item, talep, master))
        _assign_display_order(result)
        return result
    finally:
        con.close()


def _assign_display_order(tasks: list[dict]) -> None:
    """
    Mutate tasks in-place: add display_order_no (frontend read-model only).

    Active tasks (sorted by order_no) get 1-based sequential numbers.
    Inactive tasks (IPTAL/ERTELENDI/GIDILEMEDI) get display_order_no=None.
    DB canonical sira is never touched.
    """
    active = sorted(
        [t for t in tasks if (t.get('status') or '').upper() not in INACTIVE_PLAN_STATUSES],
        key=lambda x: x.get('order_no') or 0,
    )
    for i, t in enumerate(active, start=1):
        t['display_order_no'] = i
    inactive_ids = {t['id'] for t in tasks if (t.get('status') or '').upper() in INACTIVE_PLAN_STATUSES}
    for t in tasks:
        if t['id'] in inactive_ids:
            t['display_order_no'] = None


def _empty_status_counts() -> dict[str, int]:
    return {k: 0 for k in PLAN_ITEM_STATUS_KEYS}


def _count_task_statuses(tasks: list[dict]) -> dict[str, int]:
    counts = _empty_status_counts()
    for task in tasks:
        st = task.get('status') or 'PLANLANDI'
        if st in counts:
            counts[st] += 1
    return counts


def _operational_count(status_counts: dict) -> int:
    """Operasyonel kalem: IPTAL/ERTELENDI/GIDILEMEDI hariç."""
    return sum(int(status_counts.get(k) or 0) for k in OPERATIONAL_STATUS_KEYS)


def _pick_next_task(tasks: list[dict]) -> dict | None:
    """İlk aktif, tamamlanmamış kalem — canonical order_no (sira) kuralı."""
    for task in sorted(tasks, key=lambda x: x.get('order_no') or 0):
        st = (task.get('status') or 'PLANLANDI').upper()
        if st in INACTIVE_PLAN_STATUSES:
            continue
        if st in NEXT_ITEM_STATUSES:
            return task
    return None


def canonical_item_sort_key(item: dict) -> tuple:
    """
    Canonical sort: vehicle → order_no (when set) → legacy planned_time → plan_item_id.
    planned_time must not override a defined order_no.
    """
    vehicle = item.get('arac_plaka_snapshot') or item.get('arac_external_id') or ''
    order_no = item.get('order_no')
    try:
        has_order = order_no is not None and order_no != '' and int(order_no) > 0
    except (TypeError, ValueError):
        has_order = False
    plan_item_id = item.get('plan_item_id') or 0
    if has_order:
        return (vehicle, 0, int(order_no), plan_item_id)
    pt = (item.get('planned_time') or '').strip()
    pt_sort = pt if pt and pt != '—' else '99:99'
    return (vehicle, 1, pt_sort, plan_item_id)


def _next_item_summary(task: dict | None) -> dict | None:
    if not task:
        return None
    return {
        'plan_item_id': task.get('plan_item_id'),
        'is_talebi_id': task.get('is_talebi_id'),
        'order_no': task.get('order_no'),
        'display_order_no': task.get('display_order_no'),
        'company_name': task.get('company_name'),
        'job_title': task.get('job_title'),
        'planned_time': task.get('planned_time'),
        'has_coordinates': task.get('has_coordinates'),
        'location_status': task.get('location_status'),
        'location_source': task.get('location_source'),
        'location_source_label': task.get('location_source_label'),
        'kayitli_yer_id': task.get('kayitli_yer_id'),
        'status': task.get('status'),
        'status_label': task.get('status_label'),
    }


def _load_taleps_by_ids(con: sqlite3.Connection, talep_ids: list[int]) -> dict[int, sqlite3.Row]:
    if not talep_ids:
        return {}
    placeholders = ','.join('?' * len(talep_ids))
    rows = con.execute(
        f'SELECT * FROM arac_is_talebi WHERE id IN ({placeholders})',
        talep_ids,
    ).fetchall()
    return {int(r['id']): r for r in rows}


def _load_masters_by_ids(con: sqlite3.Connection, yer_ids: list[int]) -> dict[int, sqlite3.Row]:
    if not yer_ids:
        return {}
    placeholders = ','.join('?' * len(yer_ids))
    rows = con.execute(
        f'SELECT * FROM arac_kayitli_yer WHERE id IN ({placeholders})',
        yer_ids,
    ).fetchall()
    return {int(r['id']): r for r in rows}


def _assemble_tasks_for_plan_items(
    items: list[sqlite3.Row],
    taleps: dict[int, sqlite3.Row],
    masters: dict[int, sqlite3.Row],
) -> list[dict]:
    tasks: list[dict] = []
    for item in items:
        talep = taleps.get(int(item['is_talebi_id']))
        if not talep:
            continue
        master = None
        if talep['kayitli_yer_id']:
            master = masters.get(int(talep['kayitli_yer_id']))
        tasks.append(_plan_task_dto(item, talep, master))
    return tasks


def _flat_item_sort_key(item: dict) -> tuple:
    return canonical_item_sort_key(item)


def _format_next_stop_label(task: dict | None) -> str | None:
    if not task:
        return None
    name = (task.get('company_name') or task.get('job_title') or '').strip()
    if not name:
        return None
    # Prefer display_order_no (1-based active sequential) over canonical order_no for user-facing label
    display_no = task.get('display_order_no')
    order_no = task.get('order_no')
    label_no = display_no if display_no is not None else order_no
    pt = (task.get('planned_time') or '').strip()
    has_time = bool(pt and pt != '—')
    if has_time:
        if label_no is not None and label_no != '':
            return f'{pt[:5]} · {label_no}. Durak · {name}'
        return f'{pt[:5]} · {name}'
    if label_no is not None and label_no != '':
        return f'{label_no}. Durak · {name}'
    return name


def _attach_vehicle_context(task: dict, plan: dict) -> dict:
    out = dict(task)
    out['plan_id'] = plan['plan_id']
    out['plan_tarihi'] = plan['plan_tarihi']
    out['arac_external_id'] = plan['arac_external_id']
    out['arac_plaka_snapshot'] = plan['arac_plaka_snapshot']
    out['sofor_id'] = plan.get('sofor_id')
    out['sofor_adi_snapshot'] = plan.get('sofor_adi_snapshot')
    return out


def _empty_daily_plan_aggregate(plan_date: str) -> dict:
    counts = _empty_status_counts()
    return {
        'plan_date': plan_date,
        'plan_count': 0,
        'planned_vehicle_count': 0,
        'total_item_count': 0,
        'operational_total_count': 0,
        'planned_count': 0,
        'started_count': 0,
        'completed_count': 0,
        'canceled_count': 0,
        'active_item_count': 0,
        'plans': [],
        'vehicles': [],
        'items': [],
    }


def list_plans_for_date(plan_date: str) -> list[dict]:
    """Seçilen günün tüm araç planları — READ only, canonical SQLite."""
    if not tables_ready():
        return []
    con = get_conn()
    try:
        plans = con.execute(
            """
            SELECT * FROM arac_gunluk_plan
            WHERE plan_tarihi=? AND arac_provider=?
            ORDER BY arac_plaka_snapshot, arac_external_id
            """,
            (plan_date, PLAN_PROVIDER_FILOM),
        ).fetchall()
        if not plans:
            return []

        plan_ids = [int(p['id']) for p in plans]
        placeholders = ','.join('?' * len(plan_ids))
        all_items = con.execute(
            f"""
            SELECT * FROM arac_gunluk_plan_is
            WHERE plan_id IN ({placeholders})
            ORDER BY plan_id, sira
            """,
            plan_ids,
        ).fetchall()

        items_by_plan: dict[int, list[sqlite3.Row]] = {pid: [] for pid in plan_ids}
        talep_ids: set[int] = set()
        for item in all_items:
            pid = int(item['plan_id'])
            items_by_plan.setdefault(pid, []).append(item)
            talep_ids.add(int(item['is_talebi_id']))

        taleps = _load_taleps_by_ids(con, sorted(talep_ids))
        yer_ids = sorted({
            int(t['kayitli_yer_id'])
            for t in taleps.values()
            if t['kayitli_yer_id']
        })
        masters = _load_masters_by_ids(con, yer_ids)

        result: list[dict] = []
        for plan in plans:
            pid = int(plan['id'])
            plan_items = items_by_plan.get(pid, [])
            tasks = _assemble_tasks_for_plan_items(plan_items, taleps, masters)
            _assign_display_order(tasks)
            status_counts = _count_task_statuses(tasks)
            next_task = _pick_next_task(tasks)
            plan_d = _row_dict(plan) or {}
            result.append({
                'plan_id': pid,
                'plan_tarihi': plan['plan_tarihi'],
                'arac_provider': plan['arac_provider'],
                'arac_external_id': plan['arac_external_id'],
                'arac_plaka_snapshot': plan['arac_plaka_snapshot'],
                'sofor_id': plan['sofor_id'],
                'sofor_adi_snapshot': plan['sofor_adi_snapshot'],
                'cikis_saati': plan_d.get('cikis_saati'),
                'plan_durum': plan['durum'],
                'items': tasks,
                'item_count': len(tasks),
                'operational_item_count': _operational_count(status_counts),
                'status_counts': status_counts,
                'next_item': _next_item_summary(next_task),
            })
        return result
    finally:
        con.close()


def build_daily_plan_aggregate(plan_date: str) -> dict:
    """Gün geneli canonical read model — ham durum sayımları + plans/vehicles/items."""
    plans = list_plans_for_date(plan_date)
    if not plans:
        return _empty_daily_plan_aggregate(plan_date)

    totals = _empty_status_counts()
    flat_items: list[dict] = []
    vehicles: list[dict] = []

    for plan in plans:
        sc = plan['status_counts']
        for key in PLAN_ITEM_STATUS_KEYS:
            totals[key] += int(sc.get(key) or 0)
        for task in plan['items']:
            flat_items.append(_attach_vehicle_context(task, plan))
        completed = sc.get('TAMAMLANDI', 0)
        operational = _operational_count(sc)
        next_item = plan.get('next_item')
        vehicles.append({
            'plan_id': plan['plan_id'],
            'arac_external_id': plan['arac_external_id'],
            'arac_plaka_snapshot': plan['arac_plaka_snapshot'],
            'sofor_id': plan.get('sofor_id'),
            'sofor_adi_snapshot': plan.get('sofor_adi_snapshot'),
            'cikis_saati': plan.get('cikis_saati'),
            'driver_name': plan.get('sofor_adi_snapshot'),
            'status_counts': dict(sc),
            'item_count': plan['item_count'],
            'operational_total_count': operational,
            'completed_count': completed,
            'progress_completed': completed,
            'progress_total': operational,
            'progress_label': f'{completed}/{operational}',
            'next_item': next_item,
            'next_time': (next_item or {}).get('planned_time'),
            'next_order_no': (next_item or {}).get('order_no'),
            'next_stop_label': _format_next_stop_label(next_item),
            'next_display_order_no': (next_item or {}).get('display_order_no'),
        })

    flat_items.sort(key=_flat_item_sort_key)
    total_items = sum(totals.values())
    operational_total = _operational_count(totals)

    return {
        'plan_date': plan_date,
        'plan_count': len(plans),
        'planned_vehicle_count': len(plans),
        'total_item_count': total_items,
        'operational_total_count': operational_total,
        'planned_count': totals['PLANLANDI'],
        'started_count': totals['BASLADI'],
        'completed_count': totals['TAMAMLANDI'],
        'canceled_count': totals['IPTAL'],
        'active_item_count': totals['PLANLANDI'] + totals['BASLADI'],
        'plans': plans,
        'vehicles': vehicles,
        'items': flat_items,
    }


def update_talep_coordinates(
    session_user_id: int,
    talep_id: int,
    latitude: float,
    longitude: float,
    konum_linki: str | None = None,
) -> dict:
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    now = _now_iso()
    con = get_conn()
    try:
        row = con.execute('SELECT id FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()
        if not row:
            raise ValueError('Talep bulunamadı')
        con.execute(
            """
            UPDATE arac_is_talebi
            SET latitude=?, longitude=?, konum_linki=COALESCE(?, konum_linki),
                updated_at=?, updated_by=?
            WHERE id=?
            """,
            (float(latitude), float(longitude), konum_linki, now, session_user_id, int(talep_id)),
        )
        con.commit()
        updated = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()
        return {'ok': True, 'talep': _talep_dto(updated)}
    finally:
        con.close()


def save_talep_konum_with_master(
    session_user_id: int,
    talep_id: int,
    latitude: float,
    longitude: float,
    konum_linki: str | None = None,
) -> dict:
    """Save coordinates on talep snapshot and link/create arac_kayitli_yer master."""
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    now = _now_iso()
    con = get_conn()
    try:
        talep = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()
        if not talep:
            raise ValueError('Talep bulunamadı')

        candidate = {
            'firma_adi': talep['firma_adi'],
            'telefon': talep['telefon'],
            'adres': talep['adres'],
            'latitude': float(latitude),
            'longitude': float(longitude),
        }
        master_action = 'reused'
        loc_id = None
        existing_yer_id = talep['kayitli_yer_id']
        if existing_yer_id:
            master_row = con.execute(
                'SELECT id FROM arac_kayitli_yer WHERE id=? AND aktif=1',
                (int(existing_yer_id),),
            ).fetchone()
            if master_row:
                loc_id = int(existing_yer_id)
                master_action = 'linked_existing'
        if loc_id is None:
            dup = find_duplicate_location(candidate)
            if dup:
                loc_id = int(dup['id'])
                master_action = 'reused'
        if loc_id is not None:
            con.execute(
                """
                UPDATE arac_kayitli_yer
                SET latitude=?, longitude=?, konum_linki=COALESCE(?, konum_linki)
                WHERE id=?
                """,
                (float(latitude), float(longitude), konum_linki, loc_id),
            )
        else:
            cur = con.execute(
                """
                INSERT INTO arac_kayitli_yer (
                    firma_adi, kisi_adi, telefon, adres, konum_linki,
                    latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
                ) VALUES (?,?,?,?,?,?,?,1,0,?,?)
                """,
                (
                    talep['firma_adi'],
                    talep['kisi_adi'],
                    talep['telefon'],
                    talep['adres'],
                    konum_linki,
                    float(latitude),
                    float(longitude),
                    now,
                    session_user_id,
                ),
            )
            loc_id = int(cur.lastrowid)
            master_action = 'created'

        _touch_location(con, loc_id)
        con.execute(
            """
            UPDATE arac_is_talebi
            SET latitude=?, longitude=?, konum_linki=COALESCE(?, konum_linki),
                kayitli_yer_id=?, updated_at=?, updated_by=?
            WHERE id=?
            """,
            (
                float(latitude),
                float(longitude),
                konum_linki,
                loc_id,
                now,
                session_user_id,
                int(talep_id),
            ),
        )
        con.commit()
        updated = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (int(talep_id),)).fetchone()
        master = con.execute('SELECT * FROM arac_kayitli_yer WHERE id=?', (loc_id,)).fetchone()
        return {
            'ok': True,
            'talep': _talep_dto(updated),
            'location': _location_dto(master),
            'master_action': master_action,
            'kayitli_yer_id': loc_id,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def update_kayitli_yer_coordinates(
    session_user_id: int,
    yer_id: int,
    latitude: float,
    longitude: float,
    konum_linki: str | None = None,
) -> dict:
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')
    now = _now_iso()
    con = get_conn()
    try:
        row = con.execute('SELECT id FROM arac_kayitli_yer WHERE id=?', (int(yer_id),)).fetchone()
        if not row:
            raise ValueError('Kayıtlı yer bulunamadı')
        con.execute(
            """
            UPDATE arac_kayitli_yer
            SET latitude=?, longitude=?, konum_linki=COALESCE(?, konum_linki)
            WHERE id=?
            """,
            (float(latitude), float(longitude), konum_linki, int(yer_id)),
        )
        con.commit()
        updated = con.execute('SELECT * FROM arac_kayitli_yer WHERE id=?', (int(yer_id),)).fetchone()
        return {'ok': True, 'location': _location_dto(updated)}
    finally:
        con.close()


def _geofence_table_exists_conn(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_plan_is_ziyaret_durum'",
    ).fetchone())


def _get_visit_state_conn(con: sqlite3.Connection, plan_is_id: int) -> dict | None:
    if not _geofence_table_exists_conn(con):
        return None
    row = con.execute(
        'SELECT * FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?',
        (int(plan_is_id),),
    ).fetchone()
    return dict(row) if row else None


def _load_plan_items_for_order_policy_conn(
    con: sqlite3.Connection,
    plan_id: int,
) -> list[dict]:
    """Load existing plan items in canonical sira order for U1 route policy."""
    rows = con.execute(
        """
        SELECT pi.id, pi.sira, pi.durum, pi.created_at, t.oncelik
        FROM arac_gunluk_plan_is pi
        JOIN arac_is_talebi t ON t.id = pi.is_talebi_id
        WHERE pi.plan_id=?
        ORDER BY pi.sira, pi.id
        """,
        (int(plan_id),),
    ).fetchall()
    tasks: list[dict] = []
    for row in rows:
        task: dict = {
            'plan_item_id': int(row['id']),
            'status': row['durum'],
            'priority': row['oncelik'] or 'NORMAL',
            'created_at': row['created_at'],
        }
        visit = _get_visit_state_conn(con, int(row['id']))
        if visit:
            if visit.get('state'):
                task['visit_state'] = visit['state']
            if visit.get('arrived_at'):
                task['arrived_at'] = visit['arrived_at']
            if visit.get('departed_at'):
                task['departed_at'] = visit['departed_at']
        tasks.append(task)
    return tasks


def get_plan_row_by_id_conn(con: sqlite3.Connection, plan_id: int) -> dict | None:
    """Load one plan row on caller-owned connection."""
    row = con.execute(
        """
        SELECT id, plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
               durum, updated_at, updated_by
        FROM arac_gunluk_plan
        WHERE id=?
        """,
        (int(plan_id),),
    ).fetchone()
    return dict(row) if row else None


def load_manual_reorder_policy_tasks_conn(
    con: sqlite3.Connection,
    plan_id: int,
) -> list[dict]:
    """Canonical plan items with visit state and priority for U3B manual reorder."""
    rows = con.execute(
        """
        SELECT pi.id, pi.sira, pi.durum, t.oncelik
        FROM arac_gunluk_plan_is pi
        JOIN arac_is_talebi t ON t.id = pi.is_talebi_id
        WHERE pi.plan_id=?
        ORDER BY pi.sira
        """,
        (int(plan_id),),
    ).fetchall()
    tasks: list[dict] = []
    for row in rows:
        task: dict = {
            'id': f"pi-{int(row['id'])}",
            'sira': int(row['sira']),
            'order_no': int(row['sira']),
            'status': row['durum'],
            'priority': row['oncelik'] or 'NORMAL',
        }
        visit = _get_visit_state_conn(con, int(row['id']))
        if visit:
            if visit.get('state'):
                task['visit_state'] = visit['state']
            if visit.get('arrived_at'):
                task['arrived_at'] = visit['arrived_at']
            if visit.get('departed_at'):
                task['departed_at'] = visit['departed_at']
        tasks.append(task)
    return tasks


def reorder_plan_items_by_plan_id_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    plan_id: int,
    task_ids: list[str],
) -> None:
    """UNIQUE(plan_id,sira) safe bulk reorder on open connection — no commit."""
    items = con.execute(
        'SELECT * FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
        (int(plan_id),),
    ).fetchall()
    by_id = {f"pi-{r['id']}": r for r in items}
    if set(task_ids) != set(by_id.keys()):
        raise ValueError('Görev listesi plan ile uyuşmuyor')
    ordered_rows = [by_id[tid] for tid in task_ids if tid in by_id]
    if len(ordered_rows) != len(items):
        raise ValueError('Eksik görev sırası')
    now = _now_iso()
    for row in ordered_rows:
        con.execute(
            'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
            (-int(row['id']), row['id']),
        )
    for i, row in enumerate(ordered_rows, start=1):
        con.execute(
            'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
            (i, row['id']),
        )
    con.execute(
        'UPDATE arac_gunluk_plan SET updated_at=?, updated_by=? WHERE id=?',
        (now, session_user_id, int(plan_id)),
    )


def resolve_plan_insert_sira_conn(
    con: sqlite3.Connection,
    plan_id: int,
    oncelik: str | None,
    explicit_sira: int | None = None,
) -> int:
    """
    Resolve 1-based sira for a new plan item on an open connection.

    ACIL → U1 safe insert index; other priorities → append (MAX+1).
    Explicit sira always wins when provided.
    """
    if explicit_sira is not None:
        return int(explicit_sira)
    priority = (oncelik or 'NORMAL').strip().upper()
    if priority == 'ACIL':
        from modules.planlama.arac_route_order_policy import compute_acil_insert_index
        tasks = _load_plan_items_for_order_policy_conn(con, plan_id)
        return compute_acil_insert_index(tasks) + 1
    max_sira = con.execute(
        'SELECT COALESCE(MAX(sira), 0) AS ms FROM arac_gunluk_plan_is WHERE plan_id=?',
        (int(plan_id),),
    ).fetchone()['ms']
    return int(max_sira) + 1


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

        new_sira = resolve_plan_insert_sira_conn(
            con, plan_id, talep['oncelik'], sira,
        )

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
        from modules.planlama.arac_plan_rota_snapshot_service import (
            invalidate_plan_route_state_after_acil_insert_conn,
        )
        invalidate_plan_route_state_after_acil_insert_conn(con, plan_id, talep['oncelik'])
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


def reorder_plan_items_bulk(
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    task_ids: list[str],
) -> list[dict]:
    """Two-phase bulk reorder — V1.3 UNIQUE(plan_id,sira) safe."""
    if not tables_ready() or not task_ids:
        return list_plan_tasks(plan_date, arac_external_id)
    con = get_conn()
    try:
        con.execute('BEGIN IMMEDIATE')
        _reorder_plan_items_bulk_conn(
            con, session_user_id, plan_date, arac_external_id, task_ids,
        )
        con.commit()
        return list_plan_tasks(plan_date, arac_external_id)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _update_plan_item_times_bulk_conn(
    con: sqlite3.Connection,
    plan_id: int,
    task_time_map: dict[str, str],
) -> None:
    """
    ETA saatlerini bulk yaz — SADECE tahmini_varis_saati alanına.

    planlanan_saat'e ASLA dokunmaz:
      - planlanan_saat = legacy istenen saat (kullanıcı/talep kaynaklı)
      - tahmini_varis_saati = migration 188 sonrası ETA kolonu

    Migration 188 uygulanmamışsa (kolon yok): her satır için sessizce atlar.
    Caller must filter inactive tasks before calling.
    """
    for task_id, hhmm in task_time_map.items():
        if not task_id or not hhmm:
            continue
        if not str(task_id).startswith('pi-'):
            continue
        try:
            pi_id = int(str(task_id)[3:])
        except ValueError:
            continue
        row = con.execute(
            'SELECT id, plan_id, durum FROM arac_gunluk_plan_is WHERE id=?',
            (pi_id,),
        ).fetchone()
        if not row or int(row['plan_id']) != int(plan_id):
            continue
        if (row['durum'] or '').upper() in INACTIVE_PLAN_STATUSES:
            continue
        update_plan_item_eta_conn(con, pi_id, hhmm[:5])


def _reorder_plan_items_bulk_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    task_ids: list[str],
) -> int:
    """Apply bulk reorder on open connection — no commit/close. Returns plan_id."""
    plan = con.execute(
        """
        SELECT id FROM arac_gunluk_plan
        WHERE plan_tarihi=? AND arac_provider='TURKCELL_FILOM' AND arac_external_id=?
        """,
        (plan_date, str(arac_external_id)),
    ).fetchone()
    if not plan:
        raise ValueError('Plan bulunamadı')
    items = con.execute(
        'SELECT * FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
        (plan['id'],),
    ).fetchall()
    by_id = {f"pi-{r['id']}": r for r in items}
    if set(task_ids) != set(by_id.keys()):
        raise ValueError('Görev listesi plan ile uyuşmuyor')
    ordered_rows = [by_id[tid] for tid in task_ids if tid in by_id]
    if len(ordered_rows) != len(items):
        raise ValueError('Eksik görev sırası')
    now = _now_iso()
    for row in ordered_rows:
        con.execute(
            'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
            (-int(row['id']), row['id']),
        )
    for i, row in enumerate(ordered_rows, start=1):
        con.execute(
            'UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?',
            (i, row['id']),
        )
    con.execute(
        'UPDATE arac_gunluk_plan SET updated_at=?, updated_by=? WHERE id=?',
        (now, session_user_id, plan['id']),
    )
    return int(plan['id'])


# ─── Geçmiş Planlar (read-only) ─────────────────────────────────────────────

HISTORY_COMPUTED_STATUS_LABELS = {
    'TAMAMLANDI': 'Tamamlandı',
    'KISMI_TAMAMLANDI': 'Kısmi Tamamlandı',
    'GIDILMEDI': 'Gidilmedi',
    'BASLADI': 'Başladı',
    'IPTAL': 'İptal',
    'BOS_PLAN': 'Boş Plan',
}

HISTORY_ITEM_CATEGORY_LABELS = {
    'IPTAL': 'Plan dışı/İptal',
    'TAMAMLANDI': 'Tamamlandı',
    'ZIYARET_SONUC_BEKLIYOR': 'Gidildi / Sonuç bekliyor',
    'BASLADI': 'Başladı',
    'BASLADI_ZIYARET_DOGRULANAMADI': 'Başladı · Ziyaret doğrulanamadı',
    'GIDILMEDI': 'Gidilmedi',
}

VISIT_STATE_LABELS = {
    'OUTSIDE': 'Dışarıda',
    'INSIDE': 'İçeride',
    'DEPARTED_PENDING': 'Ayrılış bekleniyor',
    'DEPARTED': 'Ayrıldı',
}


def _history_status_counts_sql() -> str:
    parts = []
    for key in PLAN_ITEM_STATUS_KEYS:
        parts.append(f"SUM(CASE WHEN pi.durum='{key}' THEN 1 ELSE 0 END) AS cnt_{key}")
    return ', '.join(parts)


def _planned_arrival_timestamps(
    plan_date: str | None,
    planlanan_saat: str | None,
    istenen_varis_saati: str | None,
) -> list[str]:
    if not plan_date:
        return []
    out: list[str] = []
    for raw in (planlanan_saat, istenen_varis_saati):
        if not raw:
            continue
        ts = str(raw).strip()
        if not ts:
            continue
        if ' ' in ts:
            out.append(ts)
            continue
        if ts.count(':') == 1:
            out.append(f'{plan_date} {ts}:00')
        else:
            out.append(f'{plan_date} {ts}')
    return out


def _arrived_at_is_planned_only(
    arrived_at: str | None,
    *,
    plan_date: str | None,
    planlanan_saat: str | None,
    istenen_varis_saati: str | None,
    has_konuma_varildi: bool,
) -> bool:
    if not arrived_at or has_konuma_varildi:
        return False
    return arrived_at in _planned_arrival_timestamps(plan_date, planlanan_saat, istenen_varis_saati)


def _load_olay_evidence_for_plan_items(
    con: sqlite3.Connection,
    plan_item_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not plan_item_ids or not tablo_var_mi('arac_plan_olay'):
        return {}
    placeholders = ','.join('?' * len(plan_item_ids))
    rows = con.execute(
        f"""
        SELECT plan_is_id, olay_turu, metadata_json
        FROM arac_plan_olay
        WHERE plan_is_id IN ({placeholders})
        """,
        plan_item_ids,
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        pid = int(r['plan_is_id'])
        ev = out.setdefault(pid, {'has_konuma_varildi': False, 'departure_meta': None})
        tur = r['olay_turu']
        if tur == 'KONUMA_VARILDI':
            ev['has_konuma_varildi'] = True
        elif tur == 'KONUMDAN_AYRILDI':
            try:
                import json
                ev['departure_meta'] = json.loads(r['metadata_json'] or '{}')
            except (TypeError, ValueError, json.JSONDecodeError):
                ev['departure_meta'] = {}
    return out


def _evaluate_visit_evidence(
    visit: dict | None,
    *,
    plan_date: str | None = None,
    planlanan_saat: str | None = None,
    istenen_varis_saati: str | None = None,
    olay_evidence: dict | None = None,
) -> dict[str, Any]:
    """Güvenilir varış/ayrılış kanıtı — plan saati ve olay metadata dâhil."""
    ev = olay_evidence or {}
    has_konuma_varildi = bool(ev.get('has_konuma_varildi'))
    arrived_at = (visit or {}).get('arrived_at')
    departed_at = (visit or {}).get('departed_at')
    dwell_seconds = (visit or {}).get('dwell_seconds')

    reliable_arrival = False
    arrival_reason = 'yok'
    if arrived_at:
        if _arrived_at_is_planned_only(
            arrived_at,
            plan_date=plan_date,
            planlanan_saat=planlanan_saat,
            istenen_varis_saati=istenen_varis_saati,
            has_konuma_varildi=has_konuma_varildi,
        ):
            arrival_reason = 'planlanan_saat_eslesmesi_konuma_varildi_yok'
        elif has_konuma_varildi:
            reliable_arrival = True
            arrival_reason = 'konuma_varildi'
        else:
            reliable_arrival = True
            arrival_reason = 'arrived_at_geofence'

    reliable_departure = False
    departure_reason = 'yok'
    if departed_at:
        tl = _validate_visit_timeline(arrived_at, departed_at, dwell_seconds)
        if not tl['timeline_valid']:
            departure_reason = tl['timeline_issue'] or 'timeline_invalid'
        else:
            dep_meta = ev.get('departure_meta') or {}
            dist = dep_meta.get('distance_m')
            exit_r = dep_meta.get('exit_radius_m', 250)
            if dist is not None:
                try:
                    if float(dist) > float(exit_r):
                        departure_reason = f'distance_m={dist}>exit_radius_m={exit_r}'
                    else:
                        reliable_departure = True
                        departure_reason = 'konumdan_ayrildi'
                except (TypeError, ValueError):
                    reliable_departure = True
                    departure_reason = 'departed_at_timeline_ok'
            else:
                reliable_departure = True
                departure_reason = 'departed_at_timeline_ok'

    return {
        'reliable_arrival': reliable_arrival,
        'reliable_departure': reliable_departure,
        'reliable_visit': reliable_arrival or reliable_departure,
        'arrival_reason': arrival_reason,
        'departure_reason': departure_reason,
    }


def _classify_history_item(
    task_status: str,
    visit: dict | None,
    *,
    plan_date: str | None = None,
    planlanan_saat: str | None = None,
    istenen_varis_saati: str | None = None,
    olay_evidence: dict | None = None,
) -> dict[str, str]:
    st = (task_status or 'PLANLANDI').upper()
    if st == 'IPTAL':
        return {
            'category': 'IPTAL',
            'label': HISTORY_ITEM_CATEGORY_LABELS['IPTAL'],
            'category_reason': 'durum=IPTAL',
        }
    if st == 'TAMAMLANDI':
        return {
            'category': 'TAMAMLANDI',
            'label': HISTORY_ITEM_CATEGORY_LABELS['TAMAMLANDI'],
            'category_reason': 'durum=TAMAMLANDI',
        }

    evidence = _evaluate_visit_evidence(
        visit,
        plan_date=plan_date,
        planlanan_saat=planlanan_saat,
        istenen_varis_saati=istenen_varis_saati,
        olay_evidence=olay_evidence,
    )
    if evidence['reliable_visit']:
        if evidence['reliable_arrival']:
            reason = f"arrival={evidence['arrival_reason']}"
        else:
            reason = f"departure={evidence['departure_reason']}"
        return {
            'category': 'ZIYARET_SONUC_BEKLIYOR',
            'label': HISTORY_ITEM_CATEGORY_LABELS['ZIYARET_SONUC_BEKLIYOR'],
            'category_reason': reason,
        }
    if st == 'BASLADI':
        has_visit_row = bool(visit and (visit.get('arrived_at') or visit.get('departed_at')))
        if has_visit_row:
            return {
                'category': 'BASLADI_ZIYARET_DOGRULANAMADI',
                'label': HISTORY_ITEM_CATEGORY_LABELS['BASLADI_ZIYARET_DOGRULANAMADI'],
                'category_reason': 'durum=BASLADI,visit_kaniti_gecersiz',
            }
        return {
            'category': 'BASLADI',
            'label': HISTORY_ITEM_CATEGORY_LABELS['BASLADI'],
            'category_reason': 'durum=BASLADI,visit_yok',
        }
    return {
        'category': 'GIDILMEDI',
        'label': HISTORY_ITEM_CATEGORY_LABELS['GIDILMEDI'],
        'category_reason': f'durum={st},visit_yok',
    }


def _aggregate_visit_truth_counts(classifications: list[dict[str, str]]) -> dict[str, int | float]:
    total = len(classifications)
    cancelled = sum(1 for c in classifications if c['category'] == 'IPTAL')
    completed = sum(1 for c in classifications if c['category'] == 'TAMAMLANDI')
    visited_pending = sum(1 for c in classifications if c['category'] == 'ZIYARET_SONUC_BEKLIYOR')
    started_plain = sum(1 for c in classifications if c['category'] == 'BASLADI')
    started_unverified = sum(1 for c in classifications if c['category'] == 'BASLADI_ZIYARET_DOGRULANAMADI')
    started_without = started_plain + started_unverified
    not_visited = sum(1 for c in classifications if c['category'] == 'GIDILMEDI')
    active = total - cancelled
    ratio = round(100.0 * completed / active, 1) if active > 0 else 0.0
    return {
        'total_jobs': total,
        'cancelled': cancelled,
        'completed': completed,
        'visited_pending': visited_pending,
        'started_without_visit': started_without,
        'started_unverified_visit': started_unverified,
        'started_plain': started_plain,
        'not_visited': not_visited,
        'active_jobs': active,
        'completion_ratio': ratio,
        'started': started_without,
    }


def _plan_is_has_istenen_varis_saati(con: sqlite3.Connection) -> bool:
    cols = {r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()}
    return 'istenen_varis_saati' in cols


def _classify_plan_items_for_history(
    con: sqlite3.Connection,
    plan_id: int,
    plan_date: str | None,
) -> list[dict[str, str]]:
    has_istenen = _plan_is_has_istenen_varis_saati(con)
    cols = 'id, durum, planlanan_saat' + (', istenen_varis_saati' if has_istenen else '')
    rows = con.execute(
        f'SELECT {cols} FROM arac_gunluk_plan_is WHERE plan_id=?',
        (int(plan_id),),
    ).fetchall()
    if not rows:
        return []
    item_ids = [int(r['id']) for r in rows]
    visits = _load_visits_for_plan_items(con, item_ids)
    olay_map = _load_olay_evidence_for_plan_items(con, item_ids)
    out: list[dict[str, str]] = []
    for r in rows:
        rd = dict(r)
        out.append(_classify_history_item(
            rd['durum'],
            visits.get(int(rd['id'])),
            plan_date=plan_date,
            planlanan_saat=rd.get('planlanan_saat'),
            istenen_varis_saati=rd.get('istenen_varis_saati') if has_istenen else None,
            olay_evidence=olay_map.get(int(rd['id'])),
        ))
    return out


def _history_visit_truth_counts_for_plan(con: sqlite3.Connection, plan_id: int) -> dict[str, int | float]:
    plan_date = con.execute(
        'SELECT plan_tarihi FROM arac_gunluk_plan WHERE id=?',
        (int(plan_id),),
    ).fetchone()
    plan_date_s = plan_date[0] if plan_date else None
    return _aggregate_visit_truth_counts(_classify_plan_items_for_history(con, plan_id, plan_date_s))


def _compute_history_plan_status(counts: dict[str, int | float]) -> tuple[str, str]:
    total = int(counts.get('total_jobs') or 0)
    cancelled = int(counts.get('cancelled') or 0)
    active = int(counts.get('active_jobs') or 0)
    completed = int(counts.get('completed') or 0)
    visited_pending = int(counts.get('visited_pending') or 0)
    started_without = int(counts.get('started_without_visit') or counts.get('started') or 0)
    not_visited = int(counts.get('not_visited') or 0)

    if total == 0:
        code = 'BOS_PLAN'
    elif active == 0 and cancelled > 0:
        code = 'IPTAL'
    elif active > 0 and completed == active:
        code = 'TAMAMLANDI'
    elif completed > 0 or visited_pending > 0 or started_without > 0:
        code = 'KISMI_TAMAMLANDI'
    elif not_visited > 0:
        code = 'GIDILMEDI'
    else:
        code = 'GIDILMEDI'
    return code, HISTORY_COMPUTED_STATUS_LABELS.get(code, code)


def _history_summary_line(counts: dict[str, int | float]) -> str:
    active = int(counts.get('active_jobs') or 0)
    completed = int(counts.get('completed') or 0)
    visited_pending = int(counts.get('visited_pending') or 0)
    started_without = int(counts.get('started_without_visit') or counts.get('started') or 0)
    not_visited = int(counts.get('not_visited') or 0)
    cancelled = int(counts.get('cancelled') or 0)
    parts: list[str] = []
    if active > 0:
        parts.append(f'{completed}/{active} tamamlandı')
    started_unverified = int(counts.get('started_unverified_visit') or 0)
    started_plain = int(counts.get('started_plain') or 0)
    if visited_pending:
        parts.append(f'{visited_pending} gidildi/sonuç bekliyor')
    if started_unverified:
        parts.append(f'{started_unverified} başladı/ziyaret doğrulanamadı')
    if not_visited:
        parts.append(f'{not_visited} gidilmedi')
    if started_plain:
        parts.append(f'{started_plain} başladı')
    if cancelled:
        parts.append(f'{cancelled} plan dışı')
    return ' · '.join(parts)


HISTORY_MAX_DWELL_SECONDS = 86400  # 24 saat — makul bekleme üst sınırı


def _format_dwell_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return None
    if sec <= 0:
        return None
    mins, rem = divmod(sec, 60)
    if mins >= 60:
        hrs, mins = divmod(mins, 60)
        return f'{hrs}s {mins}dk'
    return f'{mins}dk {rem}sn'


def _parse_history_timestamp(raw: str | None):
    from modules.planlama.arac_gps_poll_service import parse_gps_timestamp

    if not raw:
        return None
    return parse_gps_timestamp(str(raw))


def _validate_visit_timeline(
    arrived_at: str | None,
    departed_at: str | None,
    dwell_seconds: int | None,
) -> dict[str, Any]:
    """Ziyaret zaman bütünlüğü — geçersiz kayıtları sessizce düzeltmez."""
    has_arr = bool(arrived_at)
    has_dep = bool(departed_at)
    issue: str | None = None
    valid = True

    if has_arr and has_dep:
        arr_dt = _parse_history_timestamp(arrived_at)
        dep_dt = _parse_history_timestamp(departed_at)
        if arr_dt and dep_dt:
            if dep_dt < arr_dt:
                valid = False
                issue = 'departure_before_arrival'
        elif str(departed_at) < str(arrived_at):
            valid = False
            issue = 'departure_before_arrival'

    if dwell_seconds is not None:
        try:
            ds = int(dwell_seconds)
            if ds < 0:
                valid = False
                issue = issue or 'negative_dwell'
            elif ds > HISTORY_MAX_DWELL_SECONDS:
                valid = False
                issue = issue or 'dwell_exceeds_limit'
        except (TypeError, ValueError):
            pass

    if has_dep and not has_arr:
        issue = issue or 'missing_arrival'

    return {'timeline_valid': valid, 'timeline_issue': issue}


def _build_history_visit_timeline(visit: dict | None) -> dict[str, Any]:
    """Geçmiş plan detay DTO — güvenli zaman gösterimi."""
    empty = {
        'timeline_valid': True,
        'timeline_issue': None,
        'timeline_warning': None,
        'timeline_tooltip': None,
        'arrived_at_display': None,
        'departed_at_display': None,
        'dwell_label': None,
        'visit_times_line': None,
    }
    if not visit:
        return empty

    arrived = visit.get('arrived_at')
    departed = visit.get('departed_at')
    dwell_raw = visit.get('dwell_seconds')
    tl = _validate_visit_timeline(arrived, departed, dwell_raw)

    arr_display = str(arrived) if arrived else None
    dep_display: str | None = None
    dwell_label: str | None = None
    warning: str | None = None
    tooltip: str | None = None
    parts: list[str] = []

    if arrived:
        parts.append(f'Varış: {arrived}')

    if tl['timeline_valid']:
        if departed:
            dep_display = str(departed)
            parts.append(f'Ayrılış: {departed}')
        if dwell_raw is not None:
            dwell_label = _format_dwell_label(dwell_raw)
            if dwell_label:
                parts.append(f'Bekleme: {dwell_label}')
    elif arrived and departed:
        warning = 'Zaman kaydı tutarsız'
        tooltip = 'Ayrılış zamanı varıştan önce'
        parts.append('Ayrılış: doğrulanamadı')
    elif tl['timeline_issue'] == 'negative_dwell' and arrived:
        warning = 'Zaman kaydı tutarsız'
        tooltip = 'Bekleme süresi geçersiz'
        if departed:
            parts.append('Ayrılış: doğrulanamadı')

    if tl['timeline_issue'] == 'missing_arrival' and departed and not arrived:
        warning = 'Eksik varış kaydı'
        dep_display = str(departed)
        parts = [f'Ayrılış: {departed}']

    return {
        'timeline_valid': tl['timeline_valid'],
        'timeline_issue': tl['timeline_issue'],
        'timeline_warning': warning,
        'timeline_tooltip': tooltip,
        'arrived_at_display': arr_display,
        'departed_at_display': dep_display,
        'dwell_label': dwell_label,
        'visit_times_line': ' · '.join(parts) if parts else None,
    }


def _history_visit_bounds(con: sqlite3.Connection, plan_id: int) -> tuple[str | None, str | None]:
    from modules.planlama.arac_geofence_repo import geofence_tables_ready

    if not geofence_tables_ready():
        return None, None
    row = con.execute(
        """
        SELECT MIN(z.arrived_at) AS first_arrived, MAX(COALESCE(z.departed_at, z.arrived_at)) AS last_event
        FROM arac_plan_is_ziyaret_durum z
        JOIN arac_gunluk_plan_is pi ON pi.id = z.plan_is_id
        WHERE pi.plan_id=? AND z.arrived_at IS NOT NULL
        """,
        (int(plan_id),),
    ).fetchone()
    if not row:
        return None, None
    return row['first_arrived'], row['last_event']


def _history_route_km(con: sqlite3.Connection, plan_row: dict) -> float | None:
    """Güvenilir plan günü GPS km — odometer farkı varsa döndür."""
    if not tablo_var_mi('arac_gps_snapshot'):
        return None
    ext_id = plan_row.get('arac_external_id')
    plan_date = plan_row.get('plan_tarihi') or plan_row.get('date')
    if not ext_id or not plan_date:
        return None
    rows = con.execute(
        """
        SELECT odometer_km FROM arac_gps_snapshot
        WHERE arac_provider=? AND arac_external_id=?
          AND date(gps_timestamp)=?
          AND odometer_km IS NOT NULL
        ORDER BY gps_timestamp
        """,
        (PLAN_PROVIDER_FILOM, str(ext_id), plan_date),
    ).fetchall()
    if len(rows) < 2:
        return None
    try:
        vals = [float(r[0]) for r in rows if r[0] is not None]
    except (TypeError, ValueError):
        return None
    if len(vals) < 2:
        return None
    delta = max(vals) - min(vals)
    return round(delta, 1) if delta >= 0 else None


def _history_plan_row_to_summary(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    plan_id = int(d['plan_id'])
    counts = _history_visit_truth_counts_for_plan(con, plan_id)
    status, status_label = _compute_history_plan_status(counts)
    first_visit, last_visit = _history_visit_bounds(con, plan_id)
    route_km = _history_route_km(con, d)
    return {
        'plan_id': plan_id,
        'date': d['date'],
        'vehicle': d.get('vehicle') or '—',
        'driver': d.get('driver') or '—',
        'vehicle_external_id': d.get('arac_external_id'),
        'sofor_id': d.get('sofor_id'),
        'plan_durum': d.get('plan_durum') or 'AKTIF',
        'total_jobs': counts['total_jobs'],
        'active_jobs': counts['active_jobs'],
        'completed': counts['completed'],
        'visited_pending': counts['visited_pending'],
        'started_without_visit': counts['started_without_visit'],
        'not_visited': counts['not_visited'],
        'started': counts['started'],
        'cancelled': counts['cancelled'],
        'completion_ratio': counts['completion_ratio'],
        'summary_line': _history_summary_line(counts),
        'status': status,
        'status_label': status_label,
        'first_visit_at': first_visit,
        'last_visit_at': last_visit,
        'total_km': route_km,
    }


def _normalize_plate(plate: str) -> str:
    """Plakayı karşılaştırma anahtarına dönüştür: büyük harf + yalnız alfanümerik."""
    import re
    return re.sub(r'[^A-Z0-9]', '', (plate or '').upper())


def list_history_filter_options(
    *,
    baslangic: str | None = None,
    bitis: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Geçmiş planlardan araç ve şoför filtre seçenekleri — read-only.

    Araç tekilleştirme: aynı plakaya ait birden fazla external_id varsa
    kazanan deterministik seçilir (en yeni plan_tarihi → en yüksek plan_id).
    Şoför tekilleştirme: isim trim/casefold bazlı — genel kullanıcı tablosuna bakılmaz.
    """
    if not tables_ready():
        return {'ok': True, 'vehicles': [], 'drivers': []}

    today_s = today or date.today().isoformat()
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        clauses = ['p.arac_provider=?', 'p.plan_tarihi < ?']
        params: list[Any] = [PLAN_PROVIDER_FILOM, today_s]
        if baslangic:
            clauses.append('p.plan_tarihi >= ?')
            params.append(baslangic)
        if bitis:
            clauses.append('p.plan_tarihi <= ?')
            params.append(bitis)
        where = ' AND '.join(clauses)

        # Araç: tüm (ext_id, plaka, plan_tarihi, plan_id) kombinasyonları — sonra Python'da dedupe
        veh_rows = con.execute(
            f"""
            SELECT arac_external_id, arac_plaka_snapshot, plan_tarihi, id AS plan_id
            FROM arac_gunluk_plan p
            WHERE {where}
              AND arac_external_id IS NOT NULL
              AND arac_external_id != ''
            ORDER BY plan_tarihi DESC, id DESC
            """,
            params,
        ).fetchall()

        # Normalize plaka → en yeni/yüksek external_id seç (kazananı sadece plaka ile göster)
        seen_plate_keys: dict[str, dict] = {}   # normalize_key → best_row
        for r in veh_rows:
            plate = r['arac_plaka_snapshot'] or r['arac_external_id']
            key = _normalize_plate(plate)
            if not key:
                continue
            if key not in seen_plate_keys:
                seen_plate_keys[key] = {
                    'vehicle_id': r['arac_external_id'],
                    'plate': plate,
                    'plate_key': key,
                }
            # İlk satır zaten en yeni plan_tarihi + en yüksek plan_id (ORDER BY DESC)

        # Plaka sırası ile döndür
        vehicles = sorted(seen_plate_keys.values(), key=lambda x: x['plate'])

        # Şoför: sofor_adi_snapshot trim/casefold dedupe; genel kullanıcı tablosuna bakılmaz
        drv_rows = con.execute(
            f"""
            SELECT sofor_id, sofor_adi_snapshot
            FROM arac_gunluk_plan p
            WHERE {where}
              AND (sofor_id IS NOT NULL OR (sofor_adi_snapshot IS NOT NULL AND sofor_adi_snapshot != ''))
            ORDER BY sofor_adi_snapshot
            """,
            params,
        ).fetchall()

        seen_driver_keys: set[str] = set()
        drivers = []
        for r in drv_rows:
            name = (r['sofor_adi_snapshot'] or '').strip()
            if not name:
                continue
            name_key = name.casefold()
            if name_key in seen_driver_keys:
                continue
            seen_driver_keys.add(name_key)
            # sofor_id: bu isim için ilk (en düşük/en eski) id'yi koru
            drivers.append({'sofor_id': r['sofor_id'], 'name': name, 'name_key': name_key})

        return {'ok': True, 'vehicles': vehicles, 'drivers': drivers}
    finally:
        con.close()


def list_history_plans(
    *,
    baslangic: str | None = None,
    bitis: str | None = None,
    vehicle_id: str | None = None,
    plate: str | None = None,          # plaka bazlı filtre (vehicle_id yerine veya ek olarak)
    sofor_id: str | None = None,
    sofor_name: str | None = None,     # isim bazlı şoför filtresi (sofor_id yerine)
    page: int = 1,
    page_size: int = 50,
    today: str | None = None,
) -> dict[str, Any]:
    """Read-only geçmiş plan listesi — plan_tarihi < bugün."""
    if not tables_ready():
        return {'ok': True, 'rows': [], 'count': 0, 'total_count': 0, 'page': page, 'page_size': page_size}

    today_s = today or date.today().isoformat()
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 50)))
    offset = (page - 1) * page_size

    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        clauses = ['p.arac_provider=?', 'p.plan_tarihi < ?']
        params: list[Any] = [PLAN_PROVIDER_FILOM, today_s]
        if baslangic:
            clauses.append('p.plan_tarihi >= ?')
            params.append(baslangic)
        if bitis:
            clauses.append('p.plan_tarihi <= ?')
            params.append(bitis)
        if vehicle_id:
            # vehicle_id: external_id ile doğrudan eşleştir
            clauses.append('p.arac_external_id=?')
            params.append(str(vehicle_id))
        elif plate:
            # plate: normalize karşılaştırma (SQLite upper + REPLACE ile boşluk/tire kaldır)
            # Basit yaklaşım: UPPER(REPLACE(REPLACE(arac_plaka_snapshot,' ',''),'-','')) = ?
            clauses.append(
                "UPPER(REPLACE(REPLACE(COALESCE(p.arac_plaka_snapshot,''),' ',''),'-','')) = ?"
            )
            import re as _re
            params.append(_re.sub(r'[^A-Z0-9]', '', plate.upper()))
        if sofor_id and not sofor_name:
            clauses.append('p.sofor_id=?')
            params.append(str(sofor_id))
        elif sofor_name:
            # İsim bazlı filtre: casefold eşleşmesi için LOWER(TRIM(...))
            clauses.append("LOWER(TRIM(COALESCE(p.sofor_adi_snapshot,''))) = ?")
            params.append(sofor_name.strip().casefold())

        where = ' AND '.join(clauses)
        status_sql = _history_status_counts_sql()

        total_count = con.execute(
            f'SELECT COUNT(DISTINCT p.id) FROM arac_gunluk_plan p WHERE {where}',
            params,
        ).fetchone()[0]

        rows = con.execute(
            f"""
            SELECT
                p.id AS plan_id,
                p.plan_tarihi AS date,
                p.arac_external_id,
                p.arac_plaka_snapshot AS vehicle,
                p.sofor_adi_snapshot AS driver,
                p.sofor_id,
                p.durum AS plan_durum,
                {status_sql}
            FROM arac_gunluk_plan p
            LEFT JOIN arac_gunluk_plan_is pi ON pi.plan_id = p.id
            WHERE {where}
            GROUP BY p.id
            ORDER BY p.plan_tarihi DESC, p.arac_plaka_snapshot, p.arac_external_id, p.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        ).fetchall()

        out = [_history_plan_row_to_summary(con, row) for row in rows]
        return {
            'ok': True,
            'rows': out,
            'count': len(out),
            'total_count': int(total_count or 0),
            'page': page,
            'page_size': page_size,
            'today': today_s,
        }
    finally:
        con.close()


def _load_visits_for_plan_items(con: sqlite3.Connection, plan_item_ids: list[int]) -> dict[int, dict]:
    from modules.planlama.arac_geofence_repo import geofence_tables_ready

    if not plan_item_ids or not geofence_tables_ready():
        return {}
    placeholders = ','.join('?' * len(plan_item_ids))
    rows = con.execute(
        f"""
        SELECT plan_is_id, state, arrived_at, departed_at, dwell_seconds, result_status
        FROM arac_plan_is_ziyaret_durum
        WHERE plan_is_id IN ({placeholders})
        """,
        plan_item_ids,
    ).fetchall()
    return {int(r['plan_is_id']): dict(r) for r in rows}


def _history_item_visit_fields(
    task: dict,
    visit: dict | None,
    *,
    plan_date: str | None = None,
    planlanan_saat: str | None = None,
    istenen_varis_saati: str | None = None,
    olay_evidence: dict | None = None,
) -> dict[str, Any]:
    st = (task.get('status') or 'PLANLANDI').upper()
    cls = _classify_history_item(
        st,
        visit,
        plan_date=plan_date,
        planlanan_saat=planlanan_saat,
        istenen_varis_saati=istenen_varis_saati,
        olay_evidence=olay_evidence,
    )
    visit_state = (visit or {}).get('state') or 'OUTSIDE'

    if cls['category'] == 'BASLADI_ZIYARET_DOGRULANAMADI':
        timeline = {
            'timeline_valid': False,
            'timeline_issue': 'visit_unverified',
            'timeline_warning': None,
            'timeline_tooltip': None,
            'arrived_at_display': None,
            'departed_at_display': None,
            'dwell_label': None,
            'visit_times_line': cls['label'],
        }
    else:
        timeline = _build_history_visit_timeline(visit)

    safe_departed = timeline['departed_at_display']
    safe_dwell = (
        (visit or {}).get('dwell_seconds')
        if timeline['dwell_label'] is not None
        else None
    )
    visit_times_line = cls['label']
    if cls['category'] != 'BASLADI_ZIYARET_DOGRULANAMADI' and timeline.get('visit_times_line'):
        visit_times_line = f"{cls['label']} · {timeline['visit_times_line']}"

    return {
        'order_no': task.get('order_no'),
        'display_order_no': task.get('display_order_no'),
        'plan_item_id': task.get('plan_item_id'),
        'company_name': task.get('company_name'),
        'job_title': task.get('job_title'),
        'address_text': task.get('address_text'),
        'location_url': task.get('location_url') or '',
        'priority': task.get('priority'),
        'priority_label': task.get('priority_label'),
        'task_status': st,
        'task_status_label': task.get('status_label') or PLAN_ITEM_STATUS.get(st, st),
        'visit_state': visit_state,
        'visit_state_label': VISIT_STATE_LABELS.get(visit_state, visit_state),
        'visit_result': (visit or {}).get('result_status'),
        'arrived_at': timeline['arrived_at_display'],
        'departed_at': safe_departed,
        'dwell_seconds': safe_dwell,
        'dwell_label': timeline['dwell_label'],
        'timeline_valid': timeline['timeline_valid'],
        'timeline_issue': timeline['timeline_issue'],
        'timeline_warning': timeline['timeline_warning'],
        'timeline_tooltip': timeline['timeline_tooltip'],
        'visit_times_line': visit_times_line,
        'category': cls['category'],
        'category_label': cls['label'],
        'category_reason': cls['category_reason'],
        'not_visited_label': cls['label'],
    }


def get_history_plan_detail(plan_id: int) -> dict[str, Any]:
    """Tek geçmiş plan — tüm iş kalemleri + ziyaret read-model."""
    if not tables_ready():
        return {'ok': False, 'error': 'Tablolar hazır değil'}

    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        plan = con.execute(
            'SELECT * FROM arac_gunluk_plan WHERE id=?',
            (int(plan_id),),
        ).fetchone()
        if not plan:
            return {'ok': False, 'error': 'Plan bulunamadı'}

        plan_items = con.execute(
            'SELECT * FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira',
            (int(plan_id),),
        ).fetchall()
        talep_ids = sorted({int(r['is_talebi_id']) for r in plan_items})
        taleps = _load_taleps_by_ids(con, talep_ids)
        yer_ids = sorted({
            int(t['kayitli_yer_id'])
            for t in taleps.values()
            if t['kayitli_yer_id']
        })
        masters = _load_masters_by_ids(con, yer_ids)
        tasks = _assemble_tasks_for_plan_items(plan_items, taleps, masters)
        _assign_display_order(tasks)

        plan_d = dict(plan)
        plan_date_s = plan_d.get('plan_tarihi')
        item_meta = {
            int(r['id']): {
                'planlanan_saat': r['planlanan_saat'],
                'istenen_varis_saati': (
                    r['istenen_varis_saati']
                    if 'istenen_varis_saati' in r.keys()
                    else None
                ),
            }
            for r in plan_items
        }
        item_ids = [int(t['plan_item_id']) for t in tasks if t.get('plan_item_id')]
        visits = _load_visits_for_plan_items(con, item_ids)
        olay_map = _load_olay_evidence_for_plan_items(con, item_ids)
        classifications = _classify_plan_items_for_history(con, int(plan_id), plan_date_s)
        counts = _aggregate_visit_truth_counts(classifications)
        status, status_label = _compute_history_plan_status(counts)

        items_out = []
        for t in tasks:
            pid = int(t['plan_item_id']) if t.get('plan_item_id') else None
            meta = item_meta.get(pid or 0, {})
            items_out.append(_history_item_visit_fields(
                t,
                visits.get(pid) if pid else None,
                plan_date=plan_date_s,
                planlanan_saat=meta.get('planlanan_saat'),
                istenen_varis_saati=meta.get('istenen_varis_saati'),
                olay_evidence=olay_map.get(pid) if pid else None,
            ))
        first_visit, last_visit = _history_visit_bounds(con, int(plan_id))
        route_km = _history_route_km(con, {
            'arac_external_id': plan_d.get('arac_external_id'),
            'plan_tarihi': plan_d.get('plan_tarihi'),
        })

        return {
            'ok': True,
            'plan': {
                'plan_id': int(plan_id),
                'date': plan_d.get('plan_tarihi'),
                'vehicle': plan_d.get('arac_plaka_snapshot') or '—',
                'driver': plan_d.get('sofor_adi_snapshot') or '—',
                'vehicle_external_id': plan_d.get('arac_external_id'),
                'sofor_id': plan_d.get('sofor_id'),
                'plan_durum': plan_d.get('durum') or 'AKTIF',
                'total_jobs': counts['total_jobs'],
                'active_jobs': counts['active_jobs'],
                'completed': counts['completed'],
                'visited_pending': counts['visited_pending'],
                'started_without_visit': counts['started_without_visit'],
                'not_visited': counts['not_visited'],
                'started': counts['started'],
                'cancelled': counts['cancelled'],
                'completion_ratio': counts['completion_ratio'],
                'summary_line': _history_summary_line(counts),
                'status': status,
                'status_label': status_label,
                'first_visit_at': first_visit,
                'last_visit_at': last_visit,
                'total_km': route_km,
            },
            'items': items_out,
        }
    finally:
        con.close()
