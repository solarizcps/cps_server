# -*- coding: utf-8 -*-
"""WhatsApp production route — e4abd03 service, real GET /api/whatsapp."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
MIG = APP / 'migrations'
CANONICAL = Path(r'C:\Solariz_CPS_SERVER\app\mock_data.db')
PLAN_DATE = '2026-09-14'
VEHICLE = '45077045'
PLAKA = '34 MOR 049'
USER_ID = 1
NOW = '2026-09-14 10:00:00'
EXPECTED = ['Tamam', 'Basladi', 'EskiAcil', 'YeniAcil', 'Normal1', 'Normal2']
YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})


def _run_migration(db_path: str, filename: str) -> None:
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    spec = importlib.util.spec_from_file_location(filename, MIG / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _seed(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        con.execute("DELETE FROM arac_plan_is_ziyaret_durum WHERE arac_external_id=?", (VEHICLE,))
        con.execute(
            "DELETE FROM arac_gunluk_plan_is WHERE plan_id IN "
            "(SELECT id FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?)",
            (VEHICLE, PLAN_DATE),
        )
        con.execute("DELETE FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?", (VEHICLE, PLAN_DATE))
        con.execute("DELETE FROM arac_is_talebi WHERE talep_no LIKE 'WA-%'")
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
                (f'WA-{suf}', USER_ID, 'WA', PLAN_DATE, loc(), yap, 'Adres', 41.01, 29.01, yap, onc, 'PLANA_ALINDI', ts, USER_ID, ts, USER_ID),
            ).lastrowid)

        pid = int(con.execute(
            "INSERT INTO arac_gunluk_plan (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,durum,created_at,created_by,updated_at,updated_by) "
            "VALUES (?,?,?,?,'AKTIF',?,?,?,?)",
            (PLAN_DATE, 'TURKCELL_FILOM', VEHICLE, PLAKA, NOW, USER_ID, NOW, USER_ID),
        ).lastrowid)
        for yap, onc, dur, sira, ts in [
            ('Tamam', 'NORMAL', 'TAMAMLANDI', 1, NOW),
            ('Basladi', 'NORMAL', 'BASLADI', 2, NOW),
            ('EskiAcil', 'ACIL', 'PLANLANDI', 3, '2026-09-14 09:00:00'),
            ('Normal1', 'NORMAL', 'PLANLANDI', 4, NOW),
            ('Normal2', 'NORMAL', 'PLANLANDI', 5, NOW),
        ]:
            tid = talep(onc, yap, f'{yap}-{sira}', ts)
            con.execute(
                "INSERT INTO arac_gunluk_plan_is (plan_id,is_talebi_id,sira,durum,created_at,created_by) VALUES (?,?,?,?,?,?)",
                (pid, tid, sira, dur, ts, USER_ID),
            )
        con.commit()
        return pid
    finally:
        con.close()


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    svc_path = APP / 'modules' / 'planlama' / 'arac_whatsapp_message_service.py'
    sha = hashlib.sha256(svc_path.read_bytes()).hexdigest().upper()
    result = {
        'whatsapp_source_sha256': sha,
        'module_import_pass': False,
        'http_status': None,
        'order_match': False,
        'driver_map_url_present': False,
    }
    try:
        sys.path.insert(0, str(APP))
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_api_response  # noqa: F401
        result['module_import_pass'] = True
    except Exception as exc:
        print('IMPORT_FAIL', exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    tmpdir = tempfile.mkdtemp(prefix='wa_real_')
    db_path = str(Path(tmpdir) / 'wa.db')
    for mig in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py', '178_arac_is_talebi_ux_v2_fields.py',
        '179_arac_gps_snapshot_p1.py', '180_arac_plan_ziyaret_durum.py', '182_arac_plan_change_v1.py',
    ):
        _run_migration(db_path, mig)
    _seed(db_path)
    os.environ['CPS_MOCK_DB_PATH'] = db_path
    os.environ['CPS_TEST_DB_GUARD'] = '0'
    import config
    config.Config.MOCK_DB_PATH = db_path

    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    add_job_to_plan_atomic(USER_ID, {
        'plan_tarihi': PLAN_DATE, 'arac_external_id': VEHICLE,
        'firma': 'YeniAcil', 'adres': 'Yeni Acil Adres', 'yapilacak_is': 'YeniAcil',
        'latitude': 41.02, 'longitude': 29.02, 'oncelik': 'ACIL', 'client_submit_id': 'wa-real-1',
    })

    with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
         patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
         patch('modules.auth.yetki_var', return_value=True), \
         patch('modules.auth.is_superadmin', return_value=True):
        import app as flask_app
        flask_app.app.config['TESTING'] = True
        client = flask_app.app.test_client()
        with client.session_transaction() as sess:
            sess['kullanici'] = {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
        resp = client.get(f'/planlama/arac-takip/api/whatsapp?date={PLAN_DATE}&vehicle_id={VEHICLE}')
        result['http_status'] = resp.status_code
        body = resp.get_json()
        result['body_ok'] = body.get('ok') is True
        result['stop_count'] = body.get('stop_count')
        result['order_ids'] = body.get('order_ids') or []

        from modules.planlama.arac_takip_repo import list_plan_tasks
        from modules.planlama.arac_whatsapp_message_service import sort_stops_for_whatsapp

        tasks = list_plan_tasks(PLAN_DATE, VEHICLE)
        wa_stops = sort_stops_for_whatsapp(tasks)
        wa_names = [s.get('company_name') for s in wa_stops]
        expected_ids = [str(s.get('plan_item_id') or s.get('id')) for s in wa_stops]
        result['whatsapp_order'] = wa_names
        result['order_match'] = wa_names == EXPECTED and result['order_ids'] == expected_ids
        result['driver_map_url_present'] = bool(body.get('driver_map_url'))

    ok = (
        result['module_import_pass']
        and result['http_status'] == 200
        and result.get('body_ok')
        and result['order_match']
        and result['driver_map_url_present']
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
