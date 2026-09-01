# -*- coding: utf-8 -*-
"""Shared helpers — ATP Geofence A3 replay / temp DB seed."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
_MIGS = _APP / 'migrations'

A3_VEHICLE = '998877001'
A3_PLAKA = '34 A3 001'
A3_SOFOR_ID = 90001
A3_SOFOR = 'A3 Test Sofor'
A3_USER_ID = 1

MIGRATION_SET = (
    '176_arac_takip_v13.py',
    '177_arac_operasyon_ayar.py',
    '178_arac_is_talebi_ux_v2_fields.py',
    '179_arac_gps_snapshot_p1.py',
    '180_arac_plan_ziyaret_durum.py',
    '182_arac_plan_change_v1.py',
)


def run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def run_migration_set(db_path: str, *, extra: tuple[str, ...] = ()) -> None:
    for mig in (*MIGRATION_SET, *extra):
        run_migration(db_path, mig)


def m_offset(lat: float, lng: float, meters: float) -> tuple[float, float]:
    return lat + (meters / 111320.0), lng


def plan_date_today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def seed_minimal_auth(db_path: str, *, user: str = 'mehmet', password: str = '1453') -> None:
    """Bootstrap auth tables for isolated browser/API sanity — no canonical DB read."""
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS sistem_rol (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Ad TEXT UNIQUE NOT NULL,
            Aciklama TEXT,
            Renk TEXT DEFAULT '#64748b',
            Aktif INTEGER DEFAULT 1,
            SuperAdmin INTEGER DEFAULT 0,
            OlusturmaTarih TEXT,
            OlusturanKullanici TEXT
        );
        CREATE TABLE IF NOT EXISTS sistem_kullanici (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            KullaniciAdi TEXT UNIQUE NOT NULL,
            AdSoyad TEXT,
            Email TEXT,
            Sifre TEXT NOT NULL,
            RolId INTEGER,
            Rol TEXT,
            Aktif INTEGER DEFAULT 1,
            ZorunluSifreDegistir INTEGER DEFAULT 0,
            OlusturmaTarih TEXT,
            OlusturanKullanici TEXT,
            SonGirisTarih TEXT,
            AuthVersion INTEGER NOT NULL DEFAULT 1,
            Tip TEXT DEFAULT 'sistem'
        );
        """
    )
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    con.execute(
        """
        INSERT OR IGNORE INTO sistem_rol (Id, Ad, Aktif, SuperAdmin, OlusturmaTarih)
        VALUES (1, 'Yönetim', 1, 1, ?)
        """,
        (now,),
    )
    con.execute(
        """
        INSERT OR IGNORE INTO sistem_kullanici (
            Id, KullaniciAdi, AdSoyad, Sifre, RolId, Rol, Aktif,
            ZorunluSifreDegistir, AuthVersion, Tip
        ) VALUES (1, ?, 'Mehmet Test', ?, 1, 'Yönetim', 1, 0, 1, 'sistem')
        """,
        (user, password),
    )
    con.commit()
    con.close()


def prepare_isolated_a3_db(db_path: str) -> None:
    """Migration-only temp DB + minimal superadmin auth — canonical-free."""
    from tools.atp_test_db_guard import bind_temp_db_path

    if os.path.isfile(db_path):
        os.remove(db_path)
    sqlite3.connect(db_path).close()
    run_migration_set(db_path)
    seed_minimal_auth(db_path)
    bind_temp_db_path(db_path)


def seed_a3_plan(
    db_path: str,
    *,
    plan_date: str | None = None,
    task3_status: str = 'TAMAMLANDI',
) -> dict[str, Any]:
    """3-task plan: task1 active BASLADI, task2 second coord, task3 completed control."""
    plan_date = plan_date or plan_date_today()
    lat, lng = 40.9900, 28.8900
    t2_lat, t2_lng = m_offset(lat, lng, 1500.0)
    con = sqlite3.connect(db_path)
    now = f'{plan_date} 08:00:00'
    if not con.execute('SELECT 1 FROM arac_operasyon_ayar WHERE aktif=1 LIMIT 1').fetchone():
        con.execute(
            """
            INSERT INTO arac_operasyon_ayar (
                base_name, base_latitude, base_longitude, base_address, base_maps_url,
                aktif, created_at, updated_at, updated_by
            ) VALUES ('A3 Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
            """,
            (now, now),
        )
    for (opid,) in con.execute(
        'SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
        (plan_date, A3_VEHICLE),
    ).fetchall():
        con.execute('DELETE FROM arac_plan_is_ziyaret_durum WHERE plan_id=?', (opid,))
        con.execute('DELETE FROM arac_plan_olay WHERE plan_id=?', (opid,))
        con.execute('DELETE FROM arac_gunluk_plan_is WHERE plan_id=?', (opid,))
        con.execute('DELETE FROM arac_gunluk_plan WHERE id=?', (opid,))
    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            plan_date, 'TURKCELL_FILOM', A3_VEHICLE, A3_PLAKA,
            A3_SOFOR_ID, A3_SOFOR, 'AKTIF', now, A3_USER_ID, now, A3_USER_ID,
        ),
    )
    plan_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    plan_is_ids: list[int] = []
    coords = [(lat, lng), (t2_lat, t2_lng), (t2_lat + 0.002, t2_lng + 0.002)]
    statuses = ('BASLADI', 'PLANLANDI', task3_status)
    for s, ((slat, slng), st) in enumerate(zip(coords, statuses, strict=True)):
        con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f'A3-{9000+s}', A3_USER_ID, 'A3 Test', plan_date,
                f'A3 Firma {s+1}', f'Adres {s+1}', f'Is {s+1}', 'NORMAL', 'PLANA_ALINDI',
                slat, slng, now, A3_USER_ID, now, A3_USER_ID,
            ),
        )
        tid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (plan_id, tid, s + 1, f'0{9+s}:30', st, now, A3_USER_ID),
        )
        plan_is_ids.append(int(con.execute('SELECT last_insert_rowid()').fetchone()[0]))
    con.commit()
    con.close()
    from modules.planlama.arac_vehicle_identity_service import update_filom_vehicle_catalog
    update_filom_vehicle_catalog([{
        'id': A3_VEHICLE,
        'plate': '34A3001',
        'plate_display': A3_PLAKA,
        'driver_name': A3_SOFOR,
    }])
    return {
        'plan_date': plan_date,
        'plan_id': plan_id,
        'plan_is_ids': plan_is_ids,
        'coords': coords,
        'base_lat': lat,
        'base_lng': lng,
    }


def vehicle_dto(lat: float, lng: float, ts: str, *, stale: bool = False) -> dict:
    return {
        'id': A3_VEHICLE,
        'plate': '34A3001',
        'plate_display': A3_PLAKA,
        'driver_name': A3_SOFOR,
        'latitude': lat,
        'longitude': lng,
        'has_valid_location': True,
        'last_seen_at': ts,
        'is_stale_data': stale,
        'speed_kmh': 30,
        'activity_status': 'HAREKETLI',
    }


def poll_fixture(
    lat: float,
    lng: float,
    ts: str,
    *,
    now: datetime | None = None,
    stale: bool = False,
) -> dict:
    from unittest.mock import patch

    from modules.planlama import arac_geofence_service as geofence_svc
    from modules.planlama.arac_gps_poll_service import poll_once

    payload = {'ok': True, 'vehicles': [vehicle_dto(lat, lng, ts, stale=stale)]}
    now = now or (datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=30))
    real_process = geofence_svc.process_gps_snapshot_for_geofence

    def _process_with_poll_clock(row, **kw):
        kw.setdefault('now', now)
        return real_process(row, **kw)

    with patch.object(
        geofence_svc, 'process_gps_snapshot_for_geofence', side_effect=_process_with_poll_clock,
    ):
        return poll_once(live_fetcher=lambda: payload, now=now)


def visit_row(db_path: str, plan_is_id: int) -> dict | None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        'SELECT * FROM arac_plan_is_ziyaret_durum WHERE plan_is_id=?', (plan_is_id,),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def count_events(db_path: str, plan_is_id: int, olay_turu: str) -> int:
    con = sqlite3.connect(db_path)
    n = con.execute(
        'SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu=?',
        (plan_is_id, olay_turu),
    ).fetchone()[0]
    con.close()
    return int(n)


def item_from_today_ops(plan_date: str, plan_is_id: int) -> dict | None:
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    ops = get_today_vehicle_operations(plan_date, filom_payload={'ok': True, 'vehicles': []})
    for it in ops.get('items') or []:
        if int(it.get('plan_item_id') or 0) == int(plan_is_id):
            return it
    return None
