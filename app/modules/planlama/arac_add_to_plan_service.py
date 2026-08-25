# -*- coding: utf-8 -*-
"""
Mehmet V1–V2 — Plana İş Ekle: gerçek tek BEGIN IMMEDIATE atomikliği.

Eski tasarım (compensating delete) tamamen kaldırıldı.

Tek transaction:
    BEGIN IMMEDIATE
      → payload validation
      → kayıtlı yer çözümleme (conn içinde)
      → arac_is_talebi insert  (durum = BEKLIYOR → hemen PLANA_ALINDI)
      → arac_gunluk_plan bul/oluştur
      → sıra güvenli hesapla
      → arac_gunluk_plan_is insert
    COMMIT — ya hepsi ya hiç
    ROLLBACK — tek rollback, hiçbir compensating delete yok
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.planlama.arac_takip_repo import (
    PLAN_PROVIDER_FILOM,
    _ensure_kayitli_yer,
    _norm_adres,
    _norm_firma,
    _norm_phone,
    _now_iso,
    _parse_ux_v2_payload,
    _row_dict,
    _talep_dto,
    _touch_location,
    _uret_talep_no,
    get_conn,
    idempotency_ready,
    tables_ready,
    ux_v2_columns_ready,
)


# ---------------------------------------------------------------------------
# 1. _conn helpers — connection-agnostic, no open/close/commit/rollback
# ---------------------------------------------------------------------------

def _find_duplicate_location_conn(
    con: sqlite3.Connection,
    firma: str,
    telefon: str | None,
    adres: str,
    lat: float | None,
    lng: float | None,
) -> int | None:
    """
    Duplicate kayıtlı yer arama — caller-owned connection.
    Returns yer_id or None.
    """
    nf = _norm_firma(firma)
    if not nf:
        return None
    np = _norm_phone(telefon or '')
    na = _norm_adres(adres)
    rows = con.execute('SELECT id, firma_adi, telefon, adres, latitude, longitude FROM arac_kayitli_yer WHERE aktif=1').fetchall()
    for row in rows:
        if _norm_firma(row['firma_adi'] or '') != nf:
            continue
        if np and _norm_phone(row['telefon'] or '') == np:
            return int(row['id'])
        if na and _norm_adres(row['adres'] or '') == na:
            return int(row['id'])
        if (
            lat is not None and lng is not None
            and row['latitude'] is not None and row['longitude'] is not None
            and abs(float(lat) - float(row['latitude'])) < 0.0001
            and abs(float(lng) - float(row['longitude'])) < 0.0001
        ):
            return int(row['id'])
    return None


def _resolve_location_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    payload: dict,
    now: str,
) -> tuple[int | None, str]:
    """
    Resolve kayıtlı yer within caller transaction.
    Returns (yer_id | None, master_action).
    Koordinat validation yok burada — pre-transaction'da yapılmalı.
    """
    loc_id_raw = payload.get('location_master_id') or payload.get('kayitli_yer_id')
    try:
        given_loc_id = int(loc_id_raw) if loc_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        given_loc_id = None

    lat = payload.get('_lat')
    lng = payload.get('_lng')
    firma = (payload.get('firma') or payload.get('firma_adi') or '').strip()
    adres = (payload.get('adres') or '').strip()
    konum = (payload.get('maps_url') or payload.get('konum_linki') or '').strip() or None
    kisi = (payload.get('kisi') or '').strip() or None
    telefon = (payload.get('telefon') or '').strip() or None
    konum_adi = (payload.get('konum_adi') or '').strip() or None
    cari_id_raw = payload.get('cari_id')
    try:
        cari_id = int(cari_id_raw) if cari_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        cari_id = None
    is_new_location = bool(payload.get('is_new_location'))

    if given_loc_id and not is_new_location:
        master_row = con.execute(
            'SELECT * FROM arac_kayitli_yer WHERE id=? AND aktif=1', (given_loc_id,),
        ).fetchone()
        if master_row:
            if lat is None and master_row['latitude'] is not None:
                lat = float(master_row['latitude'])
                lng = float(master_row['longitude'])
            if not firma:
                firma = master_row['firma_adi'] or firma
            if not adres:
                adres = master_row['adres'] or adres
            if not konum and master_row['konum_linki']:
                konum = master_row['konum_linki']
            _touch_location(con, given_loc_id)
            return given_loc_id, 'linked_existing'

    if lat is not None and lng is not None and firma and adres:
        loc_id, master_action = _ensure_kayitli_yer(
            con, session_user_id, firma, adres, lat, lng, konum, kisi, telefon,
            None if is_new_location else given_loc_id, now,
            konum_adi=konum_adi, cari_id=cari_id,
        )
        return loc_id, master_action

    return None, 'none'


def _get_idempotent_result(con: sqlite3.Connection, token: str | None) -> dict | None:
    if not token or not idempotency_ready():
        return None
    row = con.execute(
        'SELECT talep_id, plan_id, plan_is_id FROM arac_plana_idempotency WHERE token=?',
        (str(token),),
    ).fetchone()
    if not row:
        return None
    talep_row = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (row['talep_id'],)).fetchone()
    return {
        'ok': True,
        'atomic': True,
        'compensating_delete': False,
        'plan_id': int(row['plan_id']),
        'plan_is_id': int(row['plan_is_id']),
        'talep_id': int(row['talep_id']),
        'talep': _talep_dto(talep_row),
        'master_action': 'idempotent_replay',
        'idempotent': True,
    }


def _save_idempotent_result(
    con: sqlite3.Connection,
    token: str | None,
    talep_id: int,
    plan_id: int,
    plan_is_id: int,
    now: str,
) -> None:
    if not token or not idempotency_ready():
        return
    con.execute(
        """
        INSERT OR IGNORE INTO arac_plana_idempotency (token, talep_id, plan_id, plan_is_id, created_at)
        VALUES (?,?,?,?,?)
        """,
        (str(token), int(talep_id), int(plan_id), int(plan_is_id), now),
    )


def _create_request_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    payload: dict,
    loc_id: int | None,
    now: str,
) -> int:
    """
    Insert arac_is_talebi — durum doğrudan 'PLANA_ALINDI' (tek atomik adım).
    Returns talep_id.
    """
    try:
        talep_uid = int(payload.get('talep_eden_user_id') or session_user_id or 0)
    except (TypeError, ValueError):
        talep_uid = int(session_user_id or 0)

    talep_adi = (payload.get('talep_eden_adi') or payload.get('talep_eden') or '').strip()
    istenen_saat = (payload.get('istenen_saat') or payload.get('planlanan_saat') or payload.get('saat') or '').strip() or None
    plan_date = str(payload.get('plan_tarihi') or payload.get('tarih') or '')[:10]
    firma = (payload.get('firma') or payload.get('firma_adi') or '').strip()
    adres = (payload.get('adres') or '').strip()
    konum = (payload.get('maps_url') or payload.get('konum_linki') or '').strip() or None
    kisi = (payload.get('kisi') or '').strip() or None
    telefon = (payload.get('telefon') or '').strip() or None
    not_text = (payload.get('not') or payload.get('not_text') or '').strip() or None
    yapilacak_is = (payload.get('is') or payload.get('yapilacak_is') or '').strip()
    oncelik = (payload.get('oncelik') or 'NORMAL').strip().upper()
    lat = payload.get('_lat')
    lng = payload.get('_lng')

    ux2 = _parse_ux_v2_payload(payload) if ux_v2_columns_ready() else {}

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
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',?,?,?,?,?)
                    """,
                    (
                        talep_no, talep_uid, talep_adi,
                        plan_date, istenen_saat, loc_id,
                        firma, kisi, telefon, adres, konum, lat, lng,
                        yapilacak_is, oncelik, not_text,
                        ux2.get('sofor_id'), ux2.get('sofor_adi_snapshot'), ux2.get('is_turu'),
                        ux2.get('urun_malzeme'), ux2.get('miktar'), ux2.get('miktar_birim'), ux2.get('ek_not'),
                        1 if payload.get('save_to_master') else 0,
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
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',?,?,?,?,?)
                    """,
                    (
                        talep_no, talep_uid, talep_adi,
                        plan_date, istenen_saat, loc_id,
                        firma, kisi, telefon, adres, konum, lat, lng,
                        yapilacak_is, oncelik, not_text,
                        1 if payload.get('save_to_master') else 0,
                        now, session_user_id, now, session_user_id,
                    ),
                )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            if 'talep_no' in str(exc).lower() or 'unique' in str(exc).lower():
                continue
            raise
    raise RuntimeError('talep_no üretilemedi')


def _get_or_create_daily_plan_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    plan_date: str,
    arac_external_id: str,
    arac_plaka: str,
    sofor_id: int | None,
    sofor_adi: str | None,
    now: str,
) -> int:
    """
    Bul veya oluştur arac_gunluk_plan — UNIQUE constraint korunur.
    Returns plan_id.
    """
    plan = con.execute(
        """
        SELECT id FROM arac_gunluk_plan
        WHERE plan_tarihi=? AND arac_provider=? AND arac_external_id=? AND durum='AKTIF'
        """,
        (plan_date, PLAN_PROVIDER_FILOM, str(arac_external_id)),
    ).fetchone()
    if plan:
        plan_id = int(plan['id'])
        con.execute(
            """
            UPDATE arac_gunluk_plan
            SET sofor_id=COALESCE(?,sofor_id), sofor_adi_snapshot=COALESCE(?,sofor_adi_snapshot),
                updated_at=?, updated_by=?
            WHERE id=?
            """,
            (sofor_id, sofor_adi, now, session_user_id, plan_id),
        )
        return plan_id
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum,
            created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,'AKTIF',?,?,?,?)
        """,
        (
            plan_date, PLAN_PROVIDER_FILOM, str(arac_external_id), arac_plaka,
            sofor_id, sofor_adi,
            now, session_user_id, now, session_user_id,
        ),
    )
    return int(cur.lastrowid)


def _add_plan_item_conn(
    con: sqlite3.Connection,
    session_user_id: int,
    plan_id: int,
    talep_id: int,
    planlanan_saat: str | None,
    sira: int | None,
    now: str,
) -> int:
    """
    Plan kalemi ekle — sıra çakışmasını güvenli çöz.
    Returns plan_is_id.
    """
    existing = con.execute(
        'SELECT id FROM arac_gunluk_plan_is WHERE is_talebi_id=?', (talep_id,),
    ).fetchone()
    if existing:
        raise ValueError('Talep zaten plana alınmış')

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
            con.execute('UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?', (-int(row['id']), row['id']))
        for row in bump_rows:
            con.execute('UPDATE arac_gunluk_plan_is SET sira=? WHERE id=?', (int(row['sira']) + 1, row['id']))

    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
        ) VALUES (?,?,?,?,'PLANLANDI',?,?)
        """,
        (plan_id, talep_id, new_sira, planlanan_saat, now, session_user_id),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# 2. Validation helpers (pre-transaction — no DB calls)
# ---------------------------------------------------------------------------

import re as _re
_SENTINEL_PAT = _re.compile(r'^[\s\-\u2014\u2013]+$')


def _is_blank_value(s: str) -> bool:
    """True if value is empty, whitespace-only, or a dash/em-dash sentinel."""
    return not s or not s.strip() or bool(_SENTINEL_PAT.match(s.strip()))


def _validate_payload(payload: dict) -> None:
    plan_date = str(payload.get('plan_tarihi') or payload.get('tarih') or '').strip()
    if not plan_date or len(plan_date) < 10:
        raise ValueError('plan_tarihi gerekli (YYYY-MM-DD)')

    arac_id = str(payload.get('arac_external_id') or '').strip()
    if not arac_id:
        raise ValueError('arac_external_id gerekli')

    yapilacak = (payload.get('is') or payload.get('yapilacak_is') or '').strip()
    if _is_blank_value(yapilacak) or len(yapilacak) < 2:
        raise ValueError('yapilacak_is gerekli ve en az 2 karakter olmalı')

    firma = (payload.get('firma') or payload.get('firma_adi') or '').strip()
    loc_id_raw = payload.get('location_master_id') or payload.get('kayitli_yer_id')

    if _is_blank_value(firma) and not loc_id_raw:
        raise ValueError('firma adı gerekli (en az 2 karakter)')

    if not _is_blank_value(firma) and len(firma) < 2:
        raise ValueError('firma adı en az 2 karakter olmalı')


def _require_coordinates(payload: dict, lat: float | None, lng: float | None) -> None:
    if lat is None or lng is None:
        raise ValueError(
            'Geçerli konum koordinatı gerekli. Google Maps bağlantısını doğrulayın veya haritadan pin seçin.'
        )
    adres = (payload.get('adres') or '').strip()
    if not adres:
        raise ValueError('Adres veya Google Maps bağlantısı gerekli')


def _extract_coords(payload: dict) -> tuple[float | None, float | None]:
    """Parse lat/lng from payload fields. No network call."""
    lat_raw = payload.get('latitude') or payload.get('lat')
    lng_raw = payload.get('longitude') or payload.get('lng') or payload.get('lon')
    try:
        lat = float(lat_raw) if lat_raw not in (None, '') else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng_raw) if lng_raw not in (None, '') else None
    except (TypeError, ValueError):
        lng = None
    if lat is None or lng is None:
        maps_url = (payload.get('maps_url') or payload.get('konum_linki') or '').strip()
        if maps_url:
            try:
                from modules.planlama.arac_lokasyon_service import parse_maps_coords
                lat, lng = parse_maps_coords(maps_url)
            except Exception:
                pass
    return lat, lng


# ---------------------------------------------------------------------------
# 3. Public atomic entry point
# ---------------------------------------------------------------------------

def add_job_to_plan_atomic(session_user_id: int, payload: dict) -> dict:
    """
    Tek BEGIN IMMEDIATE transaction içinde:
      - arac_is_talebi (durum=PLANA_ALINDI, BEKLIYOR aşaması yok)
      - arac_gunluk_plan bul/oluştur
      - arac_gunluk_plan_is insert

    Compensating delete yok. Yarım kayıt yok.
    """
    if not tables_ready():
        raise RuntimeError('arac_takip tabloları hazır değil')

    # Pre-transaction validation (no DB)
    _validate_payload(payload)
    lat, lng = _extract_coords(payload)
    _require_coordinates(payload, lat, lng)

    plan_date = str(payload.get('plan_tarihi') or payload.get('tarih') or '')[:10]
    arac_external_id = str(payload.get('arac_external_id') or '').strip()
    arac_plaka = str(payload.get('arac_plaka') or payload.get('plaka') or '').strip()
    planlanan_saat = (payload.get('planlanan_saat') or payload.get('saat') or payload.get('istenen_saat') or '').strip() or None
    sira_raw = payload.get('sira')
    sira = int(sira_raw) if sira_raw not in (None, '') else None

    sofor_id_raw = payload.get('sofor_id')
    try:
        sofor_id = int(sofor_id_raw) if sofor_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        sofor_id = None
    sofor_adi = (payload.get('sofor_adi') or '').strip() or None

    enriched = dict(payload)
    enriched['_lat'] = lat
    enriched['_lng'] = lng
    if not enriched.get('adres'):
        enriched['adres'] = (payload.get('adres') or payload.get('maps_url') or payload.get('konum_linki') or '').strip()

    submit_token = (payload.get('client_submit_id') or payload.get('submit_token') or '').strip() or None
    now = _now_iso()
    con = get_conn()
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN IMMEDIATE')

        replay = _get_idempotent_result(con, submit_token)
        if replay:
            con.commit()
            return replay

        # Step 1: kayıtlı yer (conn-içi)
        loc_id, master_action = _resolve_location_conn(con, session_user_id, enriched, now)
        if loc_id is None:
            raise ValueError('Konum kaydedilemedi — koordinat ve adres gerekli')

        # Step 2: talep insert — durum doğrudan PLANA_ALINDI
        talep_id = _create_request_conn(con, session_user_id, enriched, loc_id, now)

        # Step 3: günlük plan bul/oluştur
        plan_id = _get_or_create_daily_plan_conn(
            con, session_user_id, plan_date, arac_external_id,
            arac_plaka, sofor_id, sofor_adi, now,
        )

        # Step 4: plan item ekle
        plan_is_id = _add_plan_item_conn(
            con, session_user_id, plan_id, talep_id, planlanan_saat, sira, now,
        )

        _save_idempotent_result(con, submit_token, talep_id, plan_id, plan_is_id, now)

        con.commit()

        talep_row = con.execute('SELECT * FROM arac_is_talebi WHERE id=?', (talep_id,)).fetchone()
        return {
            'ok': True,
            'atomic': True,
            'compensating_delete': False,
            'plan_id': plan_id,
            'plan_is_id': plan_is_id,
            'talep_id': talep_id,
            'talep': _talep_dto(talep_row),
            'master_action': master_action,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
