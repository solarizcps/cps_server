# -*- coding: utf-8 -*-
"""Plan-2 production-like ATP fixture for temp DB validation."""
from __future__ import annotations

import sqlite3
from datetime import datetime

PLAN_DATE = '2026-08-28'
VEHICLE = '45077045'
PLAKA = '34 MOR 049'
SOFOR = 'ibrahim'
PLAN_ID = 2
PLAN_IS_ID = 2
TALEP_ID = 2
KY_ID = 5
FIRMA = 'şahin taban'
IS_TEXT = 'mal alıcak'
STOP_LAT = 41.0473976
STOP_LNG = 28.6385286
CIKIS = '19:00'


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=' ')


def ensure_operasyon_table(con: sqlite3.Connection) -> None:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_operasyon_ayar'",
    ).fetchone()
    if row:
        return
    con.execute(
        """
        CREATE TABLE arac_operasyon_ayar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_name TEXT NOT NULL,
            base_latitude REAL,
            base_longitude REAL,
            base_address TEXT,
            base_maps_url TEXT,
            aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER
        )
        """,
    )


def insert_factory_base(
    con: sqlite3.Connection,
    *,
    base_name: str,
    latitude: float,
    longitude: float,
    maps_url: str,
    user_id: int = 1,
) -> dict:
    ensure_operasyon_table(con)
    now = _now()
    con.execute('DELETE FROM arac_operasyon_ayar')
    cur = con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES (?,?,?,?,?,1,?,?,?)
        """,
        (base_name, float(latitude), float(longitude), None, maps_url, now, now, user_id),
    )
    return {
        'id': int(cur.lastrowid),
        'base_name': base_name,
        'base_latitude': float(latitude),
        'base_longitude': float(longitude),
        'base_maps_url': maps_url,
        'aktif': 1,
    }


def clear_factory_base(con: sqlite3.Connection) -> None:
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arac_operasyon_ayar'",
    ).fetchone():
        con.execute('DELETE FROM arac_operasyon_ayar')


def seed_plan2_fixture(
    con: sqlite3.Connection,
    *,
    with_coords: bool = True,
) -> dict:
    """Production-like plan 2 on temp DB only."""
    now = _now()
    con.execute('DELETE FROM arac_gunluk_plan_is WHERE id=? OR plan_id=?', (PLAN_IS_ID, PLAN_ID))
    con.execute('DELETE FROM arac_gunluk_plan WHERE id=? OR (plan_tarihi=? AND arac_external_id=?)',
                (PLAN_ID, PLAN_DATE, VEHICLE))
    con.execute('DELETE FROM arac_is_talebi WHERE id=?', (TALEP_ID,))

    lat = STOP_LAT if with_coords else None
    lng = STOP_LNG if with_coords else None

    if con.execute('SELECT id FROM arac_kayitli_yer WHERE id=?', (KY_ID,)).fetchone():
        con.execute(
            """
            UPDATE arac_kayitli_yer
            SET firma_adi=?, latitude=?, longitude=?, aktif=1, adres=COALESCE(adres, 'Test')
            WHERE id=?
            """,
            (FIRMA, STOP_LAT, STOP_LNG, KY_ID),
        )
    else:
        con.execute(
            """
            INSERT INTO arac_kayitli_yer (
                id, firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
            ) VALUES (?,?,?,?,?,1,0,?,1)
            """,
            (KY_ID, FIRMA, 'Test adres', STOP_LAT, STOP_LNG, now),
        )

    con.execute(
        """
        INSERT INTO arac_is_talebi (
            id, talep_no, talep_eden_user_id, talep_eden_adi_snapshot,
            talep_tarihi, kayitli_yer_id, firma_adi, adres,
            latitude, longitude, yapilacak_is, oncelik, durum,
            save_to_master, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'PLANA_ALINDI',0,?,?,?,?)
        """,
        (
            TALEP_ID, f'PLAN2-{PLAN_DATE}', 1, 'Test',
            PLAN_DATE, KY_ID if with_coords else None, FIRMA, 'Test adres',
            lat, lng, IS_TEXT, 'NORMAL',
            now, 1, now, 1,
        ),
    )

    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            id, plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_adi_snapshot, durum, cikis_saati, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,'TURKCELL_FILOM',?,?,?,'AKTIF',?,?,?,?,?)
        """,
        (PLAN_ID, PLAN_DATE, VEHICLE, PLAKA, SOFOR, CIKIS, now, 1, now, 1),
    )

    con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            id, plan_id, is_talebi_id, sira, durum, created_at, created_by
        ) VALUES (?,?,?,1,'PLANLANDI',?,?)
        """,
        (PLAN_IS_ID, PLAN_ID, TALEP_ID, now, 1),
    )
    con.commit()
    return {
        'plan_id': PLAN_ID,
        'plan_is_id': PLAN_IS_ID,
        'talep_id': TALEP_ID,
        'kayitli_yer_id': KY_ID,
        'stop_lat': lat,
        'stop_lng': lng,
    }
