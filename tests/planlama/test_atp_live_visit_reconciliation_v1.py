# -*- coding: utf-8 -*-
"""ATP live visit reconciliation — LCW 11:02/11:09 split-brain + dynamic next-stop."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
_PLANLAMA_TESTS = Path(__file__).resolve().parent
CANONICAL_PATH = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
)).resolve()
for _p in (str(_APP), str(_PLANLAMA_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')
from tools.atp_test_db_guard import install_atp_test_db_guard, bind_temp_db_path  # noqa: E402

os.environ.setdefault('CPS_CANONICAL_DB_SOURCE', str(CANONICAL_PATH))
install_atp_test_db_guard(str(CANONICAL_PATH))

from atp_canonical_forensic import assert_canonical_atp_unchanged, canonical_logical_snapshot  # noqa: E402

CANONICAL_BEFORE = (
    canonical_logical_snapshot(str(CANONICAL_PATH)) if CANONICAL_PATH.is_file() else None
)

PLAN_DATE = '2026-09-16'
VEHICLE = 'LCW-V1'
PLATE = '34 LCW 001'
LCW_LAT, LCW_LNG = 40.9900, 28.8900
STOP_NAMES = [
    'Lcw', 'DeFacto', 'Koton', 'Mavi', 'Vakko',
    'Boyner', 'Flo', 'Ipekyol', 'Kigili', 'Twist',
]


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _APP / 'migrations' / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _m_offset(lat: float, lng: float, meters: float) -> tuple[float, float]:
    return lat + (meters / 111320.0), lng


@contextmanager
def temp_lcw_db():
    tmpdir = tempfile.mkdtemp(prefix='atp_lvr_')
    db_path = os.path.join(tmpdir, 'lvr.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
        '192_arac_plan_olay_auto_tamamlandi.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    now = f'{PLAN_DATE} 08:00:00'
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?, 'TURKCELL_FILOM', ?, ?, 1, 'Oktay', 'AKTIF', ?, 1, ?, 1)
        """,
        (PLAN_DATE, VEHICLE, PLATE, now, now),
    )
    plan_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    ids = []
    coords = []
    for i, name in enumerate(STOP_NAMES):
        slat, slng = (LCW_LAT, LCW_LNG) if i == 0 else _m_offset(LCW_LAT, LCW_LNG, 2500.0 * i)
        coords.append((slat, slng))
        con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                firma_adi, adres, yapilacak_is, oncelik, durum,
                latitude, longitude, created_at, created_by, updated_at, updated_by
            ) VALUES (?,1,'Test',?,?,?,'Teslimat','NORMAL','PLANA_ALINDI',?,?,?,?,?,?)
            """,
            (f'LVR-{i+1:02d}', PLAN_DATE, name, f'{name} Adres', slat, slng, now, 1, now, 1),
        )
        tid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
            ) VALUES (?,?,?,?,'PLANLANDI',?,?)
            """,
            (plan_id, tid, i + 1, f'{9+i:02d}:00', now, 1),
        )
        ids.append(int(con.execute('SELECT last_insert_rowid()').fetchone()[0]))
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        bind_temp_db_path(db_path)
        yield db_path, plan_id, ids, coords


def _snap(con, ts, lat, lng):
    from modules.planlama.arac_gps_poll_service import make_dedup_key
    dk = make_dedup_key(ts, lat, lng)
    con.execute(
        """
        INSERT INTO arac_gps_snapshot (
            arac_provider, arac_external_id, plate_snapshot, gps_timestamp, received_at,
            latitude, longitude, speed_kmh, is_stale, dedup_key, created_at
        ) VALUES ('TURKCELL_FILOM',?,?,?,?,?,?,?,?,?,?)
        """,
        (VEHICLE, PLATE, ts, ts, lat, lng, 3, 0, dk, ts),
    )
    sid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    con.row_factory = sqlite3.Row
    return dict(con.execute('SELECT * FROM arac_gps_snapshot WHERE id=?', (sid,)).fetchone())


def _process(db_path, ts, lat, lng):
    from modules.planlama.arac_geofence_service import process_gps_snapshot_for_geofence
    con = sqlite3.connect(db_path)
    row = _snap(con, ts, lat, lng)
    con.commit()
    con.close()
    now = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') + timedelta(seconds=20)
    return process_gps_snapshot_for_geofence(row, plan_date=PLAN_DATE, now=now)


def _ops():
    from modules.planlama.arac_today_operations_service import get_today_vehicle_operations
    return get_today_vehicle_operations(
        PLAN_DATE, filom_payload={'ok': True, 'vehicles': [], 'kpi': {}},
    )


def _lcw(ops):
    return next(it for it in (ops.get('items') or []) if it.get('company_name') == 'Lcw')


def _item(ops, name):
    return next(it for it in (ops.get('items') or []) if it.get('company_name') == name)


def _seed_split_brain(db_path, plan_id, plan_is_id):
    con = sqlite3.connect(db_path)
    arrived = f'{PLAN_DATE} 11:02:00'
    departed = f'{PLAN_DATE} 11:09:00'
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m, consecutive_inside, consecutive_outside,
            arrived_at, departed_at, dwell_seconds, result_status, updated_at, created_at
        ) VALUES (?, ?, ?, 'DEPARTED_PENDING', 200, 300, 0, 2, ?, ?, 420, 'SONUC_BEKLIYOR', ?, ?)
        """,
        (plan_id, plan_is_id, VEHICLE, arrived, departed, departed, departed),
    )
    con.execute(
        """
        INSERT INTO arac_plan_olay (
            plan_id, plan_is_id, arac_external_id, olay_turu, mesaj, metadata_json,
            olay_zamani, created_at
        ) VALUES (?, ?, ?, 'KONUMA_VARILDI', 'vardı', '{}', ?, ?)
        """,
        (plan_id, plan_is_id, VEHICLE, arrived, arrived),
    )
    con.execute(
        """
        INSERT INTO arac_plan_olay (
            plan_id, plan_is_id, arac_external_id, olay_turu, mesaj, metadata_json,
            olay_zamani, created_at
        ) VALUES (?, ?, ?, 'KONUMDAN_AYRILDI', 'ayrıldı', '{}', ?, ?)
        """,
        (plan_id, plan_is_id, VEHICLE, departed, departed),
    )
    con.commit()
    con.close()


def _durum(db_path, plan_is_id):
    return sqlite3.connect(db_path).execute(
        'SELECT durum FROM arac_gunluk_plan_is WHERE id=?', (plan_is_id,),
    ).fetchone()[0]


def _db_write_fingerprint(db_path: str) -> str:
    import hashlib
    con = sqlite3.connect(db_path)
    parts = []
    for sql in (
        'SELECT id, durum FROM arac_gunluk_plan_is ORDER BY id',
        'SELECT id, olay_turu, plan_is_id FROM arac_plan_olay ORDER BY id',
        'SELECT plan_is_id, state FROM arac_plan_is_ziyaret_durum ORDER BY plan_is_id',
    ):
        parts.append(repr(con.execute(sql).fetchall()))
    con.close()
    return hashlib.sha256(''.join(parts).encode('utf-8')).hexdigest()


def test_get_today_ops_does_not_write_db():
    with temp_lcw_db() as (db, plan_id, ids, _coords):
        _seed_split_brain(db, plan_id, ids[0])
        fp_before = _db_write_fingerprint(db)
        ops = _ops()
        fp_after = _db_write_fingerprint(db)
        assert fp_before == fp_after
        lcw = _lcw(ops)
        assert lcw['status'] == 'PLANLANDI'
        assert ops['kpi']['tamamlandi'] == 0
        assert 'VISIT_RESULT_PENDING' in [a.get('type') for a in (ops.get('alerts') or [])]


def test_production_split_brain_healed_on_worker_reconcile():
    with temp_lcw_db() as (db, plan_id, ids, _coords):
        _seed_split_brain(db, plan_id, ids[0])
        assert _durum(db, ids[0]) == 'PLANLANDI'
        from modules.planlama.arac_geofence_service import process_new_snapshots_since
        out = process_new_snapshots_since(10**9)
        assert out['reconcile']['reconciled'] >= 1
        n_auto = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='AUTO_TAMAMLANDI'",
            (ids[0],),
        ).fetchone()[0]
        assert n_auto == 1
        assert _durum(db, ids[0]) == 'TAMAMLANDI'
        ops = _ops()
        kpi = ops['kpi']
        lcw = _lcw(ops)
        vehicle = (ops.get('vehicles') or [None])[0]
        assert lcw['status'] == 'TAMAMLANDI'
        assert lcw['visit_state'] == 'DEPARTED_PENDING'
        assert '11:02' in (lcw.get('visit_label') or '')
        assert '11:09' in (lcw.get('visit_label') or '')
        assert lcw.get('dwell_minutes') == 7
        assert kpi['tamamlandi'] == 1
        assert kpi['toplam_is'] == 10
        assert 'Lcw' not in str(vehicle.get('next_stop_label') or vehicle.get('next_stop') or '')
        assert 'DeFacto' in str(vehicle.get('next_stop_label') or vehicle.get('next_stop') or '')
        assert 'VISIT_RESULT_PENDING' not in [a.get('type') for a in (ops.get('alerts') or [])]


def test_reconcile_idempotent_second_poll():
    with temp_lcw_db() as (db, plan_id, ids, _coords):
        _seed_split_brain(db, plan_id, ids[0])
        from modules.planlama.arac_geofence_service import reconcile_departed_pending_completions
        r1 = reconcile_departed_pending_completions(plan_date=PLAN_DATE, vehicle_id=VEHICLE)
        r2 = reconcile_departed_pending_completions(plan_date=PLAN_DATE, vehicle_id=VEHICLE)
        assert r1['reconciled'] == 1
        assert r2['reconciled'] == 0
        n_auto = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='AUTO_TAMAMLANDI'",
            (ids[0],),
        ).fetchone()[0]
        assert n_auto == 1
        assert _durum(db, ids[0]) == 'TAMAMLANDI'


@contextmanager
def temp_lcw_db_no_auto_event_migration():
    """180 CHECK without AUTO_TAMAMLANDI — simulates pre-192 schema fault."""
    tmpdir = tempfile.mkdtemp(prefix='atp_lvr_no192_')
    db_path = os.path.join(tmpdir, 'lvr.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py',
        '180_arac_plan_ziyaret_durum.py',
        '182_arac_plan_change_v1.py',
    ):
        _run_migration(db_path, mig)
    con = sqlite3.connect(db_path)
    now = f'{PLAN_DATE} 08:00:00'
    con.execute(
        """
        INSERT INTO arac_operasyon_ayar (
            base_name, base_latitude, base_longitude, base_address, base_maps_url,
            aktif, created_at, updated_at, updated_by
        ) VALUES ('Base',41.0,29.0,'Adres','https://maps.google.com/?q=41,29',1,?,?,1)
        """,
        (now, now),
    )
    con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?, 'TURKCELL_FILOM', ?, ?, 1, 'Oktay', 'AKTIF', ?, 1, ?, 1)
        """,
        (PLAN_DATE, VEHICLE, PLATE, now, now),
    )
    plan_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            firma_adi, adres, yapilacak_is, oncelik, durum,
            latitude, longitude, created_at, created_by, updated_at, updated_by
        ) VALUES ('LVR-01',1,'Test',?,?,?,'Teslimat','NORMAL','PLANA_ALINDI',?,?,?,?,?,?)
        """,
        (PLAN_DATE, 'Lcw', 'Lcw Adres', LCW_LAT, LCW_LNG, now, 1, now, 1),
    )
    tid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
        ) VALUES (?,?,?,?,'PLANLANDI',?,?)
        """,
        (plan_id, tid, 1, '09:00', now, 1),
    )
    plan_is_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    con.commit()
    con.close()
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        bind_temp_db_path(db_path)
        yield db_path, plan_id, plan_is_id


def test_auto_complete_event_fault_rolls_back_status():
    with temp_lcw_db_no_auto_event_migration() as (db, plan_id, plan_is_id):
        _seed_split_brain(db, plan_id, plan_is_id)
        from modules.planlama.arac_geofence_service import reconcile_departed_pending_completions
        with pytest.raises(sqlite3.IntegrityError):
            reconcile_departed_pending_completions(plan_date=PLAN_DATE, vehicle_id=VEHICLE)
        assert _durum(db, plan_is_id) == 'PLANLANDI'
        n_auto = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM arac_plan_olay WHERE plan_is_id=? AND olay_turu='AUTO_TAMAMLANDI'",
            (plan_is_id,),
        ).fetchone()[0]
        assert n_auto == 0


def test_preexisting_departed_event_still_autocompletes():
    with temp_lcw_db() as (db, plan_id, ids, coords):
        inside = _m_offset(coords[0][0], coords[0][1], 40)
        outside = _m_offset(coords[0][0], coords[0][1], 420)
        _process(db, f'{PLAN_DATE} 11:02:00', inside[0], inside[1])
        _process(db, f'{PLAN_DATE} 11:03:00', inside[0], inside[1])
        con = sqlite3.connect(db)
        con.execute(
            """
            INSERT INTO arac_plan_olay (
                plan_id, plan_is_id, arac_external_id, olay_turu, mesaj, metadata_json,
                olay_zamani, created_at
            ) VALUES (?, ?, ?, 'KONUMDAN_AYRILDI', 'preexisting', '{}', ?, ?)
            """,
            (plan_id, ids[0], VEHICLE, f'{PLAN_DATE} 11:09:00', f'{PLAN_DATE} 11:09:00'),
        )
        con.commit()
        con.close()
        _process(db, f'{PLAN_DATE} 11:09:00', outside[0], outside[1])
        out = _process(db, f'{PLAN_DATE} 11:10:00', outside[0], outside[1])
        assert out.get('results', [{}])[0].get('state') == 'DEPARTED_PENDING'
        assert _durum(db, ids[0]) == 'TAMAMLANDI'


def test_happy_path_two_in_two_out_still_completes():
    with temp_lcw_db() as (db, _plan_id, ids, coords):
        inside = _m_offset(coords[0][0], coords[0][1], 40)
        outside = _m_offset(coords[0][0], coords[0][1], 420)
        _process(db, f'{PLAN_DATE} 11:02:00', inside[0], inside[1])
        _process(db, f'{PLAN_DATE} 11:03:00', inside[0], inside[1])
        _process(db, f'{PLAN_DATE} 11:09:00', outside[0], outside[1])
        last = _process(db, f'{PLAN_DATE} 11:10:00', outside[0], outside[1])
        assert last.get('results', [{}])[0].get('auto_completed') is True
        assert _durum(db, ids[0]) == 'TAMAMLANDI'
        ops = _ops()
        assert ops['kpi']['tamamlandi'] == 1
        assert 'DeFacto' in str((ops['vehicles'][0] or {}).get('next_stop_label') or '')


def test_out_of_sequence_visit_completes_actual_next_stays_first_open():
    with temp_lcw_db() as (db, _plan_id, ids, coords):
        koton = coords[2]
        inside = _m_offset(koton[0], koton[1], 40)
        outside = _m_offset(koton[0], koton[1], 420)
        _process(db, f'{PLAN_DATE} 11:20:00', inside[0], inside[1])
        _process(db, f'{PLAN_DATE} 11:21:00', inside[0], inside[1])
        _process(db, f'{PLAN_DATE} 11:25:00', outside[0], outside[1])
        _process(db, f'{PLAN_DATE} 11:26:00', outside[0], outside[1])
        assert _durum(db, ids[2]) == 'TAMAMLANDI'
        assert _durum(db, ids[0]) == 'PLANLANDI'
        ops = _ops()
        assert _item(ops, 'Koton')['status'] == 'TAMAMLANDI'
        assert _lcw(ops)['status'] == 'PLANLANDI'
        nxt = str((ops['vehicles'][0] or {}).get('next_stop_label') or '')
        assert 'Lcw' in nxt


def test_gidilemedi_advances_next_and_clones_retry():
    with temp_lcw_db() as (db, _plan_id, ids, _coords):
        from modules.planlama.arac_plan_change_service import apply_plan_job_change
        out = apply_plan_job_change(ids[0], 1, {
            'action': 'defer_next_day',
            'mark_gidilemedi': True,
            'reason': 'Ulaşılamadı — tekrar ziyaret',
            'client_submit_id': 'lvr-gidilemedi-1',
        })
        assert out.get('ok') is not False
        assert _durum(db, ids[0]) == 'GIDILEMEDI'
        ops = _ops()
        nxt = str((ops['vehicles'][0] or {}).get('next_stop_label') or '')
        assert 'Lcw' not in nxt
        assert 'DeFacto' in nxt
        assert ops['kpi']['toplam_is'] == 9
        tomorrow = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM arac_gunluk_plan_is i JOIN arac_gunluk_plan p ON p.id=i.plan_id "
            "WHERE p.plan_tarihi=? AND i.durum='PLANLANDI'",
            ('2026-09-17',),
        ).fetchone()[0]
        assert tomorrow >= 1


def test_eta_honesty_flag_when_eta_present():
    with temp_lcw_db() as (db, _plan_id, ids, _coords):
        con = sqlite3.connect(db)
        cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
        if 'tahmini_varis_saati' in cols:
            con.execute(
                "UPDATE arac_gunluk_plan_is SET tahmini_varis_saati='11:40' WHERE id=?",
                (ids[0],),
            )
            con.commit()
        con.close()
        ops = _ops()
        v = ops['vehicles'][0]
        assert v.get('eta_is_traffic_free') is True
        if 'tahmini_varis_saati' in cols:
            assert v.get('next_eta_time')
            assert 'trafiksiz' in (v.get('eta_honesty_note') or '').lower()


def test_canonical_db_unchanged():
    if CANONICAL_BEFORE is None:
        pytest.skip('canonical snapshot unavailable')
    assert_canonical_atp_unchanged(str(CANONICAL_PATH), CANONICAL_BEFORE)
