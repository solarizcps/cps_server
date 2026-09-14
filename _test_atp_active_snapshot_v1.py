# -*- coding: utf-8 -*-
"""Active route snapshot + ACIL insert must deactivate and require rebuild."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
MIG = APP / 'migrations'
PLAN_DATE = '2026-09-14'
VEHICLE = '45077045'
PLAKA = '34 MOR 049'
USER_ID = 1
NOW = '2026-09-14 10:00:00'


def _run_migration(db_path: str, filename: str) -> None:
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    spec = importlib.util.spec_from_file_location(filename, MIG / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _seed(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        con.execute("DELETE FROM arac_plan_rota_snapshot")
        con.execute(
            "DELETE FROM arac_gunluk_plan_is WHERE plan_id IN "
            "(SELECT id FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?)",
            (VEHICLE, PLAN_DATE),
        )
        con.execute("DELETE FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?", (VEHICLE, PLAN_DATE))
        con.execute("DELETE FROM arac_is_talebi WHERE talep_no LIKE 'SNAP-%'")
        con.commit()

        def loc():
            return int(con.execute(
                "INSERT INTO arac_kayitli_yer (firma_adi,adres,latitude,longitude,aktif,kullanim_sayisi,created_at,created_by) "
                "VALUES (?,?,?,?,1,0,?,?)", ('Loc', 'Adres', 41.01, 29.01, NOW, USER_ID),
            ).lastrowid)

        def talep(onc, yap, suf, ts=NOW):
            return int(con.execute(
                "INSERT INTO arac_is_talebi (talep_no,talep_eden_user_id,talep_eden_adi_snapshot,talep_tarihi,kayitli_yer_id,"
                "firma_adi,adres,latitude,longitude,yapilacak_is,oncelik,durum,save_to_master,created_at,created_by,updated_at,updated_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
                (f'SNAP-{suf}', USER_ID, 'SNAP', PLAN_DATE, loc(), yap, 'Adres', 41.01, 29.01, yap, onc, 'PLANA_ALINDI', ts, USER_ID, ts, USER_ID),
            ).lastrowid)

        pid = int(con.execute(
            "INSERT INTO arac_gunluk_plan (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,durum,created_at,created_by,updated_at,updated_by) "
            "VALUES (?,?,?,?,'AKTIF',?,?,?,?)",
            (PLAN_DATE, 'TURKCELL_FILOM', VEHICLE, PLAKA, NOW, USER_ID, NOW, USER_ID),
        ).lastrowid)
        items = [
            ('Tamam', 'NORMAL', 'TAMAMLANDI', 1),
            ('Basladi', 'NORMAL', 'BASLADI', 2),
            ('EskiAcil', 'ACIL', 'PLANLANDI', 3),
            ('Normal1', 'NORMAL', 'PLANLANDI', 4),
            ('Normal2', 'NORMAL', 'PLANLANDI', 5),
        ]
        stop_order = []
        for yap, onc, dur, sira in items:
            tid = talep(onc, yap, f'{yap}-{sira}')
            pi = int(con.execute(
                "INSERT INTO arac_gunluk_plan_is (plan_id,is_talebi_id,sira,durum,created_at,created_by) VALUES (?,?,?,?,?,?)",
                (pid, tid, sira, dur, NOW, USER_ID),
            ).lastrowid)
            stop_order.append({'plan_item_id': f'pi-{pi}', 'order_no': sira, 'company_name': yap})
        con.execute(
            """
            INSERT INTO arac_plan_rota_snapshot (
                plan_id, route_version, arac_provider, routing_provider,
                geometry_json, geometry_schema, content_hash,
                total_distance_m, total_duration_s, stop_order_json,
                is_active, created_at, created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
            """,
            (
                pid, 1, 'TURKCELL_FILOM', 'mock',
                json.dumps({'type': 'LineString', 'coordinates': [[29.01, 41.01], [29.02, 41.02]]}),
                'geojson_linestring_v1', 'snap-test-hash-v1',
                12500.0, 2700.0, json.dumps(stop_order), NOW, USER_ID,
            ),
        )
        con.commit()
        return pid
    finally:
        con.close()


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    tmpdir = tempfile.mkdtemp(prefix='snap_active_')
    db_path = str(Path(tmpdir) / 'snap.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py', '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py', '180_arac_plan_ziyaret_durum.py', '182_arac_plan_change_v1.py',
    ):
        _run_migration(db_path, mig)
    plan_id = _seed(db_path)
    os.environ['CPS_MOCK_DB_PATH'] = db_path
    os.environ['CPS_TEST_DB_GUARD'] = '0'
    sys.path.insert(0, str(APP))
    import config
    config.Config.MOCK_DB_PATH = db_path

    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic

    con = sqlite3.connect(db_path)
    active_before = con.execute(
        "SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1", (plan_id,),
    ).fetchone()[0]
    con.close()

    resp = add_job_to_plan_atomic(USER_ID, {
        'plan_tarihi': PLAN_DATE, 'arac_external_id': VEHICLE,
        'firma': 'YeniAcil', 'adres': 'Yeni Acil Adres', 'yapilacak_is': 'YeniAcil',
        'latitude': 41.02, 'longitude': 29.02, 'oncelik': 'ACIL', 'client_submit_id': 'snap-active-1',
    })

    con = sqlite3.connect(db_path)
    active_after = con.execute(
        "SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=1", (plan_id,),
    ).fetchone()[0]
    inactive_count = con.execute(
        "SELECT COUNT(*) FROM arac_plan_rota_snapshot WHERE plan_id=? AND is_active=0", (plan_id,),
    ).fetchone()[0]
    con.close()

    result = {
        'active_snapshot_created': active_before == 1,
        'snapshot_deactivated': active_after == 0 and inactive_count >= 1,
        'route_rebuild_required': bool(resp.get('route_rebuild_required')),
        'route_snapshots_deactivated': int(resp.get('route_snapshots_deactivated') or 0),
        'old_snapshot_not_consumed': active_after == 0,
    }
    ok = all([
        result['active_snapshot_created'],
        result['snapshot_deactivated'],
        result['route_rebuild_required'],
        result['route_snapshots_deactivated'] >= 1,
    ])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
