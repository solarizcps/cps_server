# -*- coding: utf-8 -*-
"""GPS P1/P2 kapanış öncesi — foundation + GPS master regression (canonical koruma)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = Path(__file__).resolve().parent
_APP = _ROOT / 'app'
_LIVE_CANONICAL: Path | None = None
_LOCAL_MOCK_PREEXISTED = False


def _prepare_gate_canonical() -> Path:
    """Byte-copy live canonical into integration TEMP; never run write suites on live file."""
    global _LIVE_CANONICAL, _LOCAL_MOCK_PREEXISTED
    env = os.environ.get('CPS_CANONICAL_DB_SOURCE', '').strip()
    if env:
        _LIVE_CANONICAL = Path(env)
        gate = _ROOT / '_tempdb' / 'gps_master_gate_source.db'
        gate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_LIVE_CANONICAL, gate)
        local_mock = _APP / 'mock_data.db'
        _LOCAL_MOCK_PREEXISTED = local_mock.exists()
        if not _LOCAL_MOCK_PREEXISTED:
            shutil.copy2(gate, local_mock)
        print(f'GPS_MASTER_GATE_DB={gate}')
        print(f'GPS_MASTER_LIVE_CANONICAL={_LIVE_CANONICAL}')
        print(f'GPS_MASTER_LOCAL_MOCK={local_mock}')
        return gate
    return _APP / 'mock_data.db'


CANONICAL = _APP / 'mock_data.db'
CANON_SHA = ''
CANON_SIZE = 0

# Self-isolated — kendi temp DB'sini kurar
ISOLATED_SUITES = [
    ('KONUM V1', '_test_faz_arac_konum_v1.py'),
    ('ROUTEVIS', '_test_faz_arac_routevis.py'),
    ('ROUTE14B', '_test_faz_arac_route14b.py'),
    ('ROUTE APPLY ATOMIC', '_test_faz_arac_route_apply_atomic.py'),
    ('GPS P1', '_test_faz_arac_gps_p1.py'),
    ('GPS P2', '_test_faz_arac_gps_p2.py'),
    ('GPS P3 GEOFENCE', '_test_faz_arac_gps_p3.py'),
    ('PLANA IS EKLE ATOMIC', '_test_faz_arac_atomic_plana.py'),
]

# Read-only / auth-patch — canonical DB okuma riski düşük
READONLY_SUITES = [
    ('LIVEVIS', '_test_faz_arac_livevis.py'),
    ('TAKIP V1.1', '_test_faz_arac_takip_v1_1.py'),
    ('UXLOC', '_test_faz_arac_uxloc_v1_2.py'),
    ('DAYPLAN READ V1', '_test_faz_arac_day_plan_read_v1.py'),
]

# Shared temp DB copy üzerinde çalışır
WRITE_SUITES = [
    ('REQV2', '_test_faz_arac_req_v2.py'),
    ('REQ-UX', '_test_faz_arac_req_ux_v12.py'),
    ('TIMEUX', '_test_faz_arac_timeux_v12.py'),
    ('REQPOOL', '_test_faz_arac_reqpool_v13.py'),
    ('MAP14A', '_test_faz_arac_map14a.py'),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def db_stats(path: Path) -> dict:
    con = sqlite3.connect(str(path), timeout=15)
    try:
        try:
            mig = con.execute('SELECT MAX(version) v FROM schema_migrations').fetchone()[0]
        except Exception:
            mig = None
        bek = con.execute("SELECT COUNT(*) c FROM arac_is_talebi WHERE durum='BEKLIYOR'").fetchone()[0]
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        return {
            'migration_max': mig,
            'bekleyen': bek,
            'integrity': integrity,
            'size': path.stat().st_size,
            'sha256': sha256(path),
        }
    finally:
        con.close()


def assert_not_canonical(active: str) -> None:
    canon = os.path.normcase(os.path.normpath(str(CANONICAL)))
    act = os.path.normcase(os.path.normpath(active))
    if act == canon:
        raise RuntimeError(f'STOP: canonical DB path: {active}')


def run_migrations(temp_db: Path) -> None:
    for fname in (
        '176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py', '179_arac_gps_snapshot_p1.py',
    ):
        spec = importlib.util.spec_from_file_location(fname, _APP / 'migrations' / fname)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(str(temp_db))


def bootstrap_vehui_fixture(target_db: Path, *, source_canonical: Path | None = None) -> Path:
    """Isolated TEMP DB for VEHUI read-only suite (no canonical writes)."""
    src = source_canonical or CANONICAL
    if not src.is_file():
        raise FileNotFoundError(f'Canonical source missing: {src}')
    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target_db)
    run_migrations(target_db)
    spec = importlib.util.spec_from_file_location(
        '180_arac_plan_ziyaret_durum.py', _APP / 'migrations' / '180_arac_plan_ziyaret_durum.py',
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(str(target_db))

    plan_date = '2026-09-14'
    vehicle = '45077045'
    plaka = '34 MOR 049'
    user_id = 1
    now = '2026-09-14 10:00:00'
    con = sqlite3.connect(str(target_db))
    try:
        con.execute(
            "DELETE FROM arac_gunluk_plan_is WHERE plan_id IN "
            "(SELECT id FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?)",
            (vehicle, plan_date),
        )
        con.execute(
            "DELETE FROM arac_gunluk_plan WHERE arac_external_id=? AND plan_tarihi=?",
            (vehicle, plan_date),
        )
        if not con.execute('SELECT 1 FROM arac_operasyon_ayar LIMIT 1').fetchone():
            con.execute(
                """
                INSERT INTO arac_operasyon_ayar (
                    base_name, base_latitude, base_longitude, base_address, aktif,
                    created_at, updated_at, updated_by
                ) VALUES (?,?,?,?,1,datetime('now'),datetime('now'),1)
                """,
                ('Fabrika', 41.0, 29.0, 'Istanbul'),
            )
        loc_id = con.execute(
            """
            INSERT INTO arac_kayitli_yer (
                firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi, created_at, created_by
            ) VALUES (?,?,?,?,1,0,?,?)
            """,
            ('VEHUI Test Firma', 'Istanbul', 41.01, 29.01, now, user_id),
        ).lastrowid
        talep_id = con.execute(
            """
            INSERT INTO arac_is_talebi (
                talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
                kayitli_yer_id, firma_adi, adres, latitude, longitude, yapilacak_is,
                oncelik, durum, save_to_master, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)
            """,
            (
                'VEHUI-12-BOOT', user_id, 'Admin', plan_date, loc_id, 'VEHUI Test Firma',
                'Istanbul', 41.01, 29.01, 'WhatsApp test stop', 'NORMAL', 'BEKLIYOR',
                now, user_id, now, user_id,
            ),
        ).lastrowid
        plan_id = con.execute(
            """
            INSERT INTO arac_gunluk_plan (
                plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
            ) VALUES (?,?,?,?,'Test Sofor','AKTIF',?,?,?,?)
            """,
            (plan_date, 'TURKCELL_FILOM', vehicle, plaka, now, user_id, now, user_id),
        ).lastrowid
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, created_at, created_by
            ) VALUES (?,?,1,'PLANLANDI',?,?)
            """,
            (plan_id, talep_id, now, user_id),
        )
        con.commit()
    finally:
        con.close()
    return target_db


def parse_suite_output(stdout: str) -> tuple[int, int, int]:
    passed = failed = total = 0
    for line in stdout.splitlines():
        m = re.search(r'(\d+)\s*PASS\s*/\s*(\d+)\s*FAIL\s*/\s*(\d+)\s*total', line, re.I)
        if m:
            passed, failed, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
            continue
        m = re.search(r'(\d+)/(\d+)\s*PASS', line)
        if m and 'FAIL' not in line.split('PASS')[0][-10:]:
            passed, total = int(m.group(1)), int(m.group(2))
            failed = total - passed
            continue
        m = re.search(r'TOTAL\s+(\d+)\s+pass\s*/\s*(\d+)\s+fail', line, re.I)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
            total = passed + failed
    return passed, failed, total


def run_subprocess_suite(name: str, script: str, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(_ROOT / script)],
        cwd=str(_ROOT),
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    out = proc.stdout + proc.stderr
    print(out)
    p, f, t = parse_suite_output(out)
    ok = proc.returncode == 0 and f == 0 and t > 0
    return {'name': name, 'script': script, 'passed': p, 'failed': f, 'total': t,
            'ok': ok, 'exit_code': proc.returncode}


def temp_e2e_gps(temp_db: Path) -> dict:
    """Temp DB E2E — talep, plan, route apply, snapshot, GPS, sapma senaryoları."""
    assert_not_canonical(str(temp_db))
    os.environ['CPS_MOCK_DB_PATH'] = str(temp_db.resolve())
    os.environ['ARAC_ROUTING_PROVIDER'] = 'mock'
    sys.path.insert(0, str(_APP))
    os.chdir(_APP)
    import config
    config.Config.MOCK_DB_PATH = str(temp_db.resolve())

    from datetime import datetime
    from modules.planlama.road_routing.mock_provider import MockRoadRoutingProvider
    from modules.planlama.arac_gps_poll_service import poll_once, persist_vehicle_snapshot
    from modules.planlama.arac_plan_rota_snapshot_service import get_applied_route_for_plan
    from modules.planlama.arac_takip_repo import get_active_plan_row
    from modules.planlama.arac_rota_deviation_service import (
        STATE_DEVIATING, STATE_ON_ROUTE, process_gps_snapshot_for_deviation,
    )
    from modules.planlama.arac_rota_deviation_repo import get_deviation_state

    YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})
    FILOM = {
        'ok': True,
        'vehicles': [{
            'id': '993001', 'plate': '34 E2E GPS', 'plate_display': '34 E2E GPS',
            'driver_name': 'Oktay', 'latitude': 40.876, 'longitude': 29.234,
            'has_valid_location': True, 'last_seen_at': '2026-12-02 10:05:00',
            'is_stale_data': False, 'speed_kmh': 45, 'activity_status': 'HAREKETLI',
        }],
        'count': 1,
    }
    results: list[tuple[str, bool, str]] = []

    def step(name: str, cond: bool, detail: str = '') -> None:
        results.append((name, cond, detail))
        print(f'  [{"PASS" if cond else "FAIL"}] E2E-{name}' + (f' — {detail}' if detail else ''))

    mock = MockRoadRoutingProvider()
    with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
         patch('modules.auth.sistem_session_gecerli_mi', return_value=True), \
         patch('modules.auth.yetki_var', return_value=True), \
         patch('modules.auth.is_superadmin', return_value=True), \
         patch('modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles', return_value=FILOM), \
         patch('modules.planlama.road_routing.route_planner_service.get_routing_provider', return_value=mock):
        import app as flask_app
        flask_app.app.config['TESTING'] = True
        c = flask_app.app.test_client()
        with c.session_transaction() as s:
            s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'alpay', 'AdSoyad': 'Alpay Test',
                              'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}
            s['kullanici_tip'] = 'sistem'

        req = c.post('/planlama/arac-takip/api/request', json={
            'tarih': '2026-12-02', 'istenen_saat': '10:00', 'is': 'E2E GPS job',
            'oncelik': 'NORMAL', 'talep_eden_user_id': 1, 'talep_eden_adi': 'Alpay Test',
            'firma': 'E2E GPS Co', 'adres': 'Gebze', 'telefon': '05550001122',
            'latitude': 40.876, 'longitude': 29.234,
            'maps_url': 'https://maps.google.com/?q=40.876,29.234', 'save_to_master': True,
            'sofor_secim': 'OKTAY', 'is_turu': 'ALINACAK',
        }).get_json()
        step('01-talep', req and req.get('ok'), str(req))
        tid = (req.get('request') or {}).get('id') if req else None

        plan = c.post('/planlama/arac-takip/api/talepler/plana-al', json={
            'talep_id': tid, 'plan_tarihi': '2026-12-02', 'arac_external_id': '993001',
            'arac_plaka': '34 E2E GPS', 'sofor_id': 1, 'sofor_adi': 'Oktay KAŞIKÇI',
            'planlanan_saat': '10:30', 'sira': 1,
        }).get_json()
        step('02-plana-al', plan and plan.get('ok'), str(plan))

        rp = c.get('/planlama/arac-takip/api/route/plan?date=2026-12-02&vehicle_id=993001').get_json()
        step('03-rota-analizi', rp and rp.get('ok'), (rp.get('route') or {}).get('status') if rp else None)

        tasks = (c.get('/planlama/arac-takip/api/dashboard?date=2026-12-02&vehicle_id=993001').get_json()
                 .get('dashboard') or {}).get('daily_tasks') or []
        step('04-dashboard', len(tasks) >= 1, str(len(tasks)))

        ap = c.post('/planlama/arac-takip/api/route/apply', json={
            'date': '2026-12-02', 'vehicle_id': '993001', 'task_ids': [t['id'] for t in tasks],
        }).get_json()
        step('05-route-apply', ap and ap.get('ok') and ap.get('applied') is True, str(ap))
        has_snap = bool(ap and ap.get('route_snapshot'))
        step('06-route-snapshot', has_snap, str(ap.get('route_snapshot') if ap else None))

        plan_row = get_active_plan_row('2026-12-02', '993001')
        snap_db = get_applied_route_for_plan(int(plan_row['id'])) if plan_row else None
        step('07-snapshot-persist', snap_db is not None, str(snap_db))

        poll_now = datetime(2026, 12, 2, 10, 6, 0)
        with patch('modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles', return_value=FILOM):
            poll_res = poll_once(live_fetcher=lambda: FILOM, now=poll_now)
        step('08-gps-snapshot', poll_res.get('ok') and poll_res.get('inserted', 0) >= 1,
             f"inserted={poll_res.get('inserted')} rejected={poll_res.get('rejected')}")

        import json

        def _ins_gps(ts: str, lat: float, lon: float) -> dict:
            persist_vehicle_snapshot({
                'id': '993001', 'latitude': lat, 'longitude': lon,
                'has_valid_location': True, 'last_seen_at': ts,
                'is_stale_data': False, 'speed_kmh': 40, 'activity_status': 'HAREKETLI',
            }, now=datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'))
            from modules.planlama.arac_gps_snapshot_repo import list_gps_snapshots_ordered
            return list_gps_snapshots_ordered('993001')[-1]

        if snap_db and plan_row:
            geo = json.loads(snap_db.get('geometry_json') or '{}')
            line = geo.get('coordinates') or [[29.0, 41.0], [29.1, 41.0]]
            a_lon, a_lat = float(line[0][0]), float(line[0][1])
            b_lon, b_lat = float(line[-1][0]), float(line[-1][1])
            mid_lon, mid_lat = (a_lon + b_lon) / 2, (a_lat + b_lat) / 2
            far_lat, far_lon = mid_lat + 0.009, mid_lon
            dev_state = None
            for i in range(3):
                row = _ins_gps(f'2026-12-02 11:0{i}:00', far_lat, far_lon + i * 0.0001)
                dev_state = process_gps_snapshot_for_deviation(row, plan_date='2026-12-02')
            st = get_deviation_state(int(plan_row['id']))
            step('09-uc-sapma', (st or {}).get('state') == STATE_DEVIATING
                 or (dev_state or {}).get('state') == STATE_DEVIATING, str(st or dev_state))
            rec_state = None
            for i in range(2):
                t = 0.45 + i * 0.05
                row = _ins_gps(
                    f'2026-12-02 12:0{i}:00',
                    a_lat + (b_lat - a_lat) * t,
                    a_lon + (b_lon - a_lon) * t,
                )
                rec_state = process_gps_snapshot_for_deviation(row, plan_date='2026-12-02')
            st2 = get_deviation_state(int(plan_row['id']))
            step('10-iki-geri-donus', (st2 or {}).get('state') == STATE_ON_ROUTE
                 or (rec_state or {}).get('state') == STATE_ON_ROUTE, str(st2 or rec_state))
        else:
            step('09-uc-sapma', False, 'no snapshot')
            step('10-iki-geri-donus', False, 'no snapshot')

        dps = c.get('/planlama/arac-takip/api/day-plan-summary?date=2026-12-02').get_json()
        step('11-day-plan-summary', dps and dps.get('ok'), str(dps.get('day_plan_summary') if dps else None))

    passed = sum(1 for _, ok, _ in results if ok)
    return {'passed': passed, 'total': len(results), 'ok': passed == len(results), 'results': results}


def _run_guard_subprocess(code: str, *, env: dict | None = None) -> tuple[int, str]:
    """Invoke arac_gps_canonical_guard in isolated subprocess (parity with hardening suite)."""
    env2 = os.environ.copy()
    env2['PYTHONPATH'] = str(_APP)
    for key in ('CPS_MOCK_DB_PATH', 'CPS_ARAC_GPS_CANONICAL_WRITE'):
        env2.pop(key, None)
    if env:
        for key, val in env.items():
            if val is None:
                env2.pop(key, None)
            else:
                env2[key] = val
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=str(_APP),
        env=env2,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def _verify_canonical_guard_behavior() -> dict[str, bool]:
    """
    Behavior contract for arac_gps_canonical_guard (replaces legacy static grep).

    Legacy runner expected worker source to contain private `_assert_temp_db` text.
    Worker now delegates to assert_gps_db_write_allowed(); verify runtime gates instead.
    """
    if not CANONICAL.is_file() or CANONICAL.stat().st_size <= 0:
        return {
            'behavior_canonical_no_env_rejected': False,
            'behavior_canonical_wrong_env_rejected': False,
            'behavior_canonical_yes_allowed': False,
            'behavior_temp_allowed': False,
            'worker_entry_rejects_without_yes': False,
        }

    guard_call = (
        'from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed\n'
        'assert_gps_db_write_allowed()\n'
    )
    rc_no_env, _ = _run_guard_subprocess(
        guard_call,
        env={'CPS_ARAC_GPS_CANONICAL_WRITE': None, 'CPS_MOCK_DB_PATH': None},
    )
    rc_wrong_env, _ = _run_guard_subprocess(
        guard_call,
        env={'CPS_ARAC_GPS_CANONICAL_WRITE': 'NO', 'CPS_MOCK_DB_PATH': None},
    )
    rc_yes, _ = _run_guard_subprocess(
        guard_call,
        env={'CPS_ARAC_GPS_CANONICAL_WRITE': 'YES', 'CPS_MOCK_DB_PATH': None},
    )

    temp_path = _APP / f'_gps_guard_behavior_{os.getpid()}.db'
    temp_ok = False
    try:
        shutil.copy2(CANONICAL, temp_path)
        rc_temp, out_temp = _run_guard_subprocess(
            'from modules.planlama.arac_gps_canonical_guard import assert_gps_db_write_allowed\n'
            'p = assert_gps_db_write_allowed()\n'
            'print("TEMP_OK:" + p)\n',
            env={'CPS_MOCK_DB_PATH': str(temp_path.resolve()), 'CPS_ARAC_GPS_CANONICAL_WRITE': None},
        )
        temp_ok = rc_temp == 0 and 'TEMP_OK:' in out_temp
    finally:
        temp_path.unlink(missing_ok=True)

    worker_env = os.environ.copy()
    worker_env['PYTHONPATH'] = str(_APP)
    worker_env.pop('CPS_MOCK_DB_PATH', None)
    worker_env.pop('CPS_ARAC_GPS_CANONICAL_WRITE', None)
    worker_rc = subprocess.run(
        [sys.executable, str(_APP / 'tools' / 'arac_gps_poll_worker.py'), '--once'],
        cwd=str(_APP),
        env=worker_env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    ).returncode

    return {
        'behavior_canonical_no_env_rejected': rc_no_env == 2,
        'behavior_canonical_wrong_env_rejected': rc_wrong_env == 2,
        'behavior_canonical_yes_allowed': rc_yes == 0,
        'behavior_temp_allowed': temp_ok,
        'worker_entry_rejects_without_yes': worker_rc == 2,
    }


def verify_worker_security() -> dict:
    src = (_APP / 'tools' / 'arac_gps_poll_worker.py').read_text(encoding='utf-8')
    behavior = _verify_canonical_guard_behavior()
    checks = {
        'rejects_canonical': (
            behavior['behavior_canonical_no_env_rejected']
            and behavior['behavior_canonical_wrong_env_rejected']
            and behavior['worker_entry_rejects_without_yes']
        ),
        'canonical_yes_gate_opens': behavior['behavior_canonical_yes_allowed'],
        'explicit_temp_db_allowed': behavior['behavior_temp_allowed'],
        'uses_shared_canonical_guard': (
            '_assert_db_write' in src
            and 'assert_gps_db_write_allowed' in src
        ),
        'single_instance_lock': '_SingleInstanceLock' in src and 'another worker instance' in src,
        'default_60s': "DEFAULT_INTERVAL_SEC = int(os.environ.get('ARAC_GPS_POLL_INTERVAL_SEC', '60'))" in src,
        'api_backoff': 'BACKOFF_BASE_SEC' in src and 'backoff * 2' in src,
        'graceful_stop': '_handle_stop' in src and 'signal.signal' in src,
        'once_flag': "'--once' in sys.argv" in src,
        'no_token_log': 'FILOM_PASSWORD' not in src and 'api_key' not in src.lower(),
    }
    checks.update(behavior)
    return checks


def git_diff_audit() -> dict:
    proc_status = subprocess.run(
        ['git', 'status', '--short'], cwd=str(_ROOT), capture_output=True, text=True,
    )
    proc_check = subprocess.run(
        ['git', 'diff', '--check'], cwd=str(_ROOT), capture_output=True, text=True,
    )
    gps_prod = [
        'app/migrations/179_arac_gps_snapshot_p1.py',
        'app/modules/planlama/arac_gps_snapshot_repo.py',
        'app/modules/planlama/arac_gps_poll_service.py',
        'app/modules/planlama/arac_plan_rota_snapshot_service.py',
        'app/modules/planlama/arac_geo_distance.py',
        'app/modules/planlama/arac_route_geometry.py',
        'app/modules/planlama/arac_rota_deviation_repo.py',
        'app/modules/planlama/arac_rota_deviation_service.py',
        'app/modules/planlama/arac_takip_routes.py',
        'app/tools/arac_gps_poll_once.py',
        'app/tools/arac_gps_poll_worker.py',
    ]
    gps_test = [
        '_test_faz_arac_gps_p1.py', '_test_faz_arac_gps_p2.py',
        '_test_faz_arac_gps_p3.py', '_test_faz_arac_atomic_plana.py',
        '_test_faz_arac_route14b.py', '_test_faz_arac_routevis.py',
        '_test_faz_arac_uxloc_v1_2.py', '_run_arac_gps_master_regression.py',
    ]
    staged_179 = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'], cwd=str(_ROOT), capture_output=True, text=True,
    )
    return {
        'git_diff_check_exit': proc_check.returncode,
        'git_diff_check_output': proc_check.stdout + proc_check.stderr,
        'git_status_short': proc_status.stdout,
        'gps_production_files': gps_prod,
        'gps_test_files': gps_test,
        'migration_179_staged': '179_arac_gps_snapshot_p1.py' in staged_179.stdout,
        'migration_179_committed': subprocess.run(
            ['git', 'log', '-1', '--name-only', '--', 'app/migrations/179_arac_gps_snapshot_p1.py'],
            cwd=str(_ROOT), capture_output=True, text=True,
        ).stdout.strip() == '',
    }


def main() -> int:
    global CANONICAL, CANON_SHA, CANON_SIZE
    CANONICAL = _prepare_gate_canonical()
    CANON_SHA = sha256(CANONICAL) if CANONICAL.is_file() else ''
    CANON_SIZE = CANONICAL.stat().st_size if CANONICAL.is_file() else 0
    live_before_sha = sha256(_LIVE_CANONICAL) if _LIVE_CANONICAL and _LIVE_CANONICAL.is_file() else ''

    if not CANONICAL.exists():
        print('Canonical DB missing')
        return 1

    print('=' * 72)
    print('GPS P1/P2 MASTER REGRESSION')
    print('=' * 72)

    before = db_stats(CANONICAL)
    print(f'GATE_DB_BEFORE {before}')

    all_results: list[dict] = []

    # Isolated suites
    for name, script in ISOLATED_SUITES:
        print('=' * 72)
        print(f'ISOLATED SUITE: {name}')
        r = run_subprocess_suite(name, script)
        all_results.append(r)
        if not r['ok']:
            print(f'STOP: {name} failed')
            return 1

    # Read-only suites (VEHUI uses isolated TEMP fixture — no canonical dependency)
    vehui_db = _ROOT / '_tempdb' / f'gps_master_vehui_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    try:
        bootstrap_vehui_fixture(vehui_db, source_canonical=CANONICAL)
        assert_not_canonical(str(vehui_db))
        print(f'VEHUI_TEMP_DB={vehui_db}')
    except Exception as exc:
        print(f'STOP: VEHUI bootstrap failed: {exc}')
        return 1

    for name, script in READONLY_SUITES:
        print('=' * 72)
        print(f'READONLY SUITE: {name}')
        suite_env = os.environ.copy()
        if script == '_test_faz_arac_takip_v1_1.py':
            suite_env['CPS_MOCK_DB_PATH'] = str(vehui_db.resolve())
        r = run_subprocess_suite(name, script, suite_env)
        all_results.append(r)
        if not r['ok']:
            print(f'STOP: {name} failed')
            return 1

    # Shared temp DB write suites
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_db = _APP / f'mock_data_arac_gps_master_{ts}.db'
    shutil.copy2(CANONICAL, temp_db)
    assert sha256(temp_db) == before['sha256']
    run_migrations(temp_db)
    env = os.environ.copy()
    env['CPS_MOCK_DB_PATH'] = str(temp_db.resolve())
    assert_not_canonical(env['CPS_MOCK_DB_PATH'])

    for name, script in WRITE_SUITES:
        print('=' * 72)
        print(f'WRITE SUITE: {name} — DB={temp_db}')
        r = run_subprocess_suite(name, script, env)
        all_results.append(r)
        if not r['ok']:
            print(f'STOP: {name} failed')
            return 1

    print('=' * 72)
    print('TEMP E2E GPS')
    e2e = temp_e2e_gps(temp_db)
    if not e2e['ok']:
        print('STOP: TEMP E2E failed')
        return 1

    after = db_stats(CANONICAL)
    print('=' * 72)
    print(f'GATE_DB_AFTER {after}')
    canon_ok = (
        before['sha256'] == after['sha256']
        and before['size'] == after['size']
        and str(before['migration_max']) == str(after['migration_max'])
        and before['bekleyen'] == after['bekleyen']
    )
    print(f'GATE_DB_UNCHANGED={canon_ok}')
    live_after_sha = sha256(_LIVE_CANONICAL) if _LIVE_CANONICAL and _LIVE_CANONICAL.is_file() else ''
    live_unchanged = (not live_before_sha) or (live_before_sha == live_after_sha)
    print(f'LIVE_CANONICAL_UNCHANGED={live_unchanged}')
    if _LIVE_CANONICAL:
        print(f'LIVE_CANONICAL_SHA_BEFORE={live_before_sha}')
        print(f'LIVE_CANONICAL_SHA_AFTER={live_after_sha}')

    worker = verify_worker_security()
    print('=' * 72)
    print('WORKER SECURITY CHECKS')
    for k, v in worker.items():
        print(f'  {k}: {v}')

    audit = git_diff_audit()
    print('=' * 72)
    print('GIT DIFF AUDIT')
    print(f"  diff --check exit={audit['git_diff_check_exit']}")
    if audit['git_diff_check_output'].strip():
        print(audit['git_diff_check_output'])
    print(f"  migration_179_staged={audit['migration_179_staged']}")
    print(f"  migration_179_committed={not audit['migration_179_committed']}")

    total_pass = sum(r['passed'] for r in all_results) + e2e['passed']
    total_tests = sum(r['total'] for r in all_results) + e2e['total']
    all_ok = all(r['ok'] for r in all_results) and e2e['ok'] and canon_ok and all(worker.values())
    if _LIVE_CANONICAL and not live_unchanged:
        print('NOTE: live canonical changed during run (likely external 8080/worker); gate DB unchanged.')

    print('=' * 72)
    print('SUMMARY')
    for r in all_results:
        print(f"  {r['name']}: {r['passed']}/{r['total']} PASS")
    print(f"  TEMP E2E GPS: {e2e['passed']}/{e2e['total']} PASS")
    print(f'  GRAND TOTAL: {total_pass}/{total_tests} PASS')
    print(f'  CHECKPOINT_LOCK_CANDIDATE={all_ok}')
    print('=' * 72)

    try:
        temp_db.unlink(missing_ok=True)
        vehui_db.unlink(missing_ok=True)
        local_mock = _APP / 'mock_data.db'
        if not _LOCAL_MOCK_PREEXISTED and local_mock.exists():
            local_mock.unlink()
    except Exception:
        pass
    return 0 if all_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
