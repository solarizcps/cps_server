# -*- coding: utf-8 -*-
"""
Permanent pytest suite — ATP multi-add identity, outage safety, request-scope
cache, coordinate persistence, and physical vehicle unique dropdown.

Consolidated from root scripts:
  _test_atp_vehicle_plate_identity_v1.py          (11 assertions)
  _test_atp_vehicle_identity_context_gate_v1.py   (8 assertions)
  _test_atp_multi_coordinate_persistence_v1.py    (8 assertions)
  _test_atp_physical_vehicle_unique_list_v1.py    (7 assertions)
"""
from __future__ import annotations

import importlib.util
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from contextvars import copy_context
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'

PLAN_PROVIDER = 'TURKCELL_FILOM'

FILOM_FIXTURE = {
    'ok': True,
    'vehicles': [
        {
            'id': '45077045',
            'plate': '34MOR049',
            'plate_display': '34 MOR 049',
            'driver_name': 'ibrahim',
        },
    ],
}

FILOM_OUTAGE = {
    'ok': False,
    'vehicles': [],
    'error': 'Filom register bağlantı hatası: TooManyRedirects',
    'error_category': 'network',
}

MOR_LIVE = {
    'id': '45077045',
    'plate_display': '34 MOR 049',
    'driver_name': 'ibrahim',
    'gps_last_seen_at': '2026-08-26 12:00:00',
}
MOR_PLAN = {
    'arac_external_id': '991001',
    'arac_provider': 'TURKCELL_FILOM',
    'arac_plaka_snapshot': '34 MOR 049',
    'plan_id': 42,
    'driver_name': 'Ahmet',
}
MOR_LIVE_EMPTY_OPS = {
    'arac_external_id': '45077045',
    'arac_plaka_snapshot': '',
    'plan_id': None,
}
BPY_CURRENT = {
    'id': '45077046',
    'plate_display': '34 BPY 282',
    'gps_last_seen_at': '2026-08-26 11:00:00',
    'is_stale_data': False,
}
BPY_STALE = {
    'id': '43567534',
    'plate_display': '34  BPY 282',
    'gps_last_seen_at': '2025-01-28 21:34:12',
    'is_stale_data': True,
    'gps_is_stale': True,
}
BLANK_UNKNOWN = {'id': '880001', 'plate_display': '', 'is_stale_data': True}
BLANK_WITH_LIVE = {'id': '45077045', 'plate_display': '34 MOR 049'}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _temp_db(*, with_gps: bool = False, prefix: str = 'atp_test_'):
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    db_path = str(Path(tmpdir) / 'test.db')
    migs = [
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
    ]
    if with_gps:
        migs.append('179_arac_gps_snapshot_p1.py')
    for mig in migs:
        _run_migration(db_path, mig)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


def _base_payload(**overrides):
    payload = {
        'plan_tarihi': '2026-08-26',
        'arac_external_id': '45077045',
        'firma': 'Test Firma',
        'adres': 'Test Adres Istanbul',
        'yapilacak_is': 'Teslimat',
        'latitude': 41.01,
        'longitude': 29.01,
        'sofor_adi': 'ibrahim',
    }
    payload.update(overrides)
    return payload


def _coord_payload(**kw):
    p = {
        'plan_tarihi': '2026-08-26',
        'arac_external_id': '45077045',
        'firma': 'Test Firma',
        'adres': 'Istanbul Test Adres',
        'yapilacak_is': 'Teslim',
        'latitude': 41.015,
        'longitude': 29.005,
    }
    p.update(kw)
    return p


def _plan_row(db_path: str, ext_id: str = '45077045') -> sqlite3.Row | None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            """
            SELECT arac_provider, arac_external_id, arac_plaka_snapshot
            FROM arac_gunluk_plan WHERE arac_external_id=?
            """,
            (ext_id,),
        ).fetchone()
    finally:
        con.close()


def _counts(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    try:
        return {
            'plan': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0],
            'item': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0],
        }
    finally:
        con.close()


def _seed_catalog():
    from modules.planlama.arac_vehicle_identity_service import update_filom_vehicle_catalog
    update_filom_vehicle_catalog(FILOM_FIXTURE['vehicles'])


def _reset_resolver_state():
    from modules.planlama.arac_vehicle_identity_service import (
        clear_vehicle_identity_resolve_cache,
        update_filom_vehicle_catalog,
    )
    clear_vehicle_identity_resolve_cache()
    update_filom_vehicle_catalog([])


def _simulate_http_request(fn):
    from modules.planlama.arac_vehicle_identity_service import vehicle_identity_request_scope
    with vehicle_identity_request_scope():
        return fn()


@pytest.fixture(autouse=True)
def _isolate_vehicle_identity_contextvar():
    """Fresh ContextVar per test — mirrors standalone script process isolation."""
    from modules.planlama.arac_vehicle_identity_service import (
        _RESOLVE_CACHE,
        update_filom_vehicle_catalog,
    )
    _RESOLVE_CACHE.set(None)
    update_filom_vehicle_catalog([])
    yield
    _RESOLVE_CACHE.set(None)
    update_filom_vehicle_catalog([])


@pytest.fixture
def filom_calls():
    calls = {'n': 0}

    def _tracked(*_a, **_k):
        calls['n'] += 1
        return FILOM_OUTAGE

    def _success(*_a, **_k):
        calls['n'] += 1
        return dict(FILOM_FIXTURE)

    calls['tracked'] = _tracked
    calls['success'] = _success
    return calls


@pytest.fixture
def impl_calls():
    return {'n': 0}


def _counting_impl(impl_calls, provider: str, external_id: str):
    impl_calls['n'] += 1
    from modules.planlama.arac_vehicle_identity_service import _identity_result
    return _identity_result(provider, external_id, '34 MOR 049', 'test')


def _counting_impl_multi(impl_calls, provider: str, external_id: str):
    impl_calls['n'] += 1
    from modules.planlama.arac_vehicle_identity_service import _identity_result
    plate = '34 MOR 049' if external_id == '45077045' else '34 XYZ 999'
    return _identity_result(provider, external_id, plate, 'test')


# ---------------------------------------------------------------------------
# JS helper mirror — buildUniquePhysicalVehicleOptions (production JS unchanged)
# ---------------------------------------------------------------------------

def _normalize_physical_plate(label: str) -> str:
    raw = str(label or '').strip()
    if not raw or raw == 'Plaka bilgisi yok':
        return ''
    compact = raw.upper().replace(' ', '').replace('.', '').replace('-', '').replace('_', '')
    m = re.match(r'^(\d{2})([A-Z]{1,3})(\d{2,4})$', compact)
    if m:
        return f'{m.group(1)} {m.group(2)} {m.group(3)}'
    return raw.upper()


def _gps_ts(v: dict) -> int:
    ts = v.get('gps_last_seen_at') or v.get('last_seen_at') or v.get('posTimestamp')
    if not ts:
        return 0
    try:
        return int(datetime.fromisoformat(str(ts).replace(' ', 'T')).timestamp() * 1000)
    except ValueError:
        return 0


def _canonical_score(ext: str) -> int:
    if re.match(r'^45\d{5,}$', ext):
        return 30
    if re.match(r'^99\d{3,}$', ext):
        return 5
    return 15


def _priority(c: dict) -> int:
    if c['has_current_plan']:
        return 1_000_000 + _canonical_score(c['external_id']) * 1000
    if not c['is_stale'] and c['source'] == 'filom':
        return 500_000 + _canonical_score(c['external_id']) * 1000
    if c['source'] == 'today-operations':
        return 200_000 + _canonical_score(c['external_id']) * 1000
    return 100_000 + _canonical_score(c['external_id'])


def _beats(n: dict, p: dict) -> bool:
    pn, pp = _priority(n), _priority(p)
    if pn != pp:
        return pn > pp
    if n['gps_ts'] != p['gps_ts']:
        return n['gps_ts'] > p['gps_ts']
    return _canonical_score(n['external_id']) > _canonical_score(p['external_id'])


def _build_unique_physical_vehicle_options(filom, ops):
    candidates = []

    def push(v, source):
        ext = str(v.get('arac_external_id') or v.get('id') or '').strip()
        if not ext:
            return
        provider = str(v.get('arac_provider') or v.get('provider') or PLAN_PROVIDER).strip()
        live_plate = _normalize_physical_plate(v.get('plate_display') or v.get('plate') or '')
        ops_plate = _normalize_physical_plate(v.get('arac_plaka_snapshot') or '')
        plate_key = live_plate or ops_plate or ''
        candidates.append({
            'external_id': ext,
            'provider': provider,
            'plateKey': plate_key,
            'driver': v.get('driver_name') or v.get('driver') or '',
            'plan_id': v.get('plan_id'),
            'has_current_plan': v.get('plan_id') not in (None, ''),
            'is_stale': bool(v.get('is_stale_data') or v.get('gps_is_stale')),
            'gps_ts': _gps_ts(v),
            'source': source,
        })

    for v in ops or []:
        push(v, 'today-operations')
    for v in filom or []:
        push(v, 'filom')

    winner_by_plate = {}
    winner_by_blank = {}
    for c in candidates:
        if c['plateKey']:
            prev = winner_by_plate.get(c['plateKey'])
            if not prev or _beats(c, prev):
                winner_by_plate[c['plateKey']] = c
        else:
            bk = f"{c['provider']}:{c['external_id']}"
            prev = winner_by_blank.get(bk)
            if not prev or _beats(c, prev):
                winner_by_blank[bk] = c

    winners = []
    for plate_key, w in winner_by_plate.items():
        winners.append({'value': w['external_id'], 'label': plate_key, 'plan_id': w['plan_id']})
    for bk, c in winner_by_blank.items():
        resolved = next(
            (x['plateKey'] for x in candidates if x['external_id'] == c['external_id'] and x['plateKey']),
            '',
        )
        if resolved or not c['plateKey']:
            continue
        winners.append({'value': c['external_id'], 'label': c['plateKey'], 'plan_id': c['plan_id']})
    winners.sort(key=lambda o: o['label'])
    return [{'value': '', 'label': '— Araç seç —'}] + winners


def _mor_opts(opts):
    return [o for o in opts if o['label'] == '34 MOR 049' or o['value'] in ('991001', '45077045')]


def _bpy_opts(opts):
    return [o for o in opts if 'BPY' in o['label'] or o['value'] in ('45077046', '43567534')]


# ---------------------------------------------------------------------------
# Identity / outage (11 assertions)
# ---------------------------------------------------------------------------

class TestIdentityOutage:
    def test_clean_import(self):
        from modules.planlama.arac_vehicle_identity_service import resolve_vehicle_identity  # noqa: F401
        from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic  # noqa: F401

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_filom_success(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['success']
        _reset_resolver_state()
        with _temp_db(prefix='atp_outage_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(1, _base_payload())
            row = _plan_row(db_path)
            assert row is not None
            assert row['arac_plaka_snapshot'] == '34 MOR 049'

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_outage_trusted_catalog(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['tracked']
        _reset_resolver_state()
        _seed_catalog()
        with _temp_db(prefix='atp_outage_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(1, _base_payload())
            row = _plan_row(db_path)
            assert row is not None
            assert row['arac_plaka_snapshot'] == '34 MOR 049'
            assert filom_calls['n'] == 0

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_outage_unknown_vehicle(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['tracked']
        _reset_resolver_state()
        with _temp_db(prefix='atp_outage_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            before = _counts(db_path)
            with pytest.raises(ValueError, match='VEHICLE_NOT_RESOLVED'):
                add_job_to_plan_atomic(1, _base_payload(arac_external_id='99999999'))
            assert _counts(db_path) == before

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_three_jobs_one_resolver_filom_call(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['tracked']
        _reset_resolver_state()
        _seed_catalog()
        with _temp_db(prefix='atp_outage_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            from modules.planlama.arac_vehicle_identity_service import clear_vehicle_identity_resolve_cache

            clear_vehicle_identity_resolve_cache()
            for idx in range(3):
                add_job_to_plan_atomic(1, _base_payload(
                    firma=f'Firma {idx}',
                    yapilacak_is=f'Is {idx}',
                    client_submit_id=f'outage_{idx}',
                ))
            counts = _counts(db_path)
            assert counts['plan'] == 1 and counts['item'] == 3
            assert filom_calls['n'] == 0

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_client_wrong_plate(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['success']
        _reset_resolver_state()
        with _temp_db(prefix='atp_outage_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(1, _base_payload(arac_plaka='YANLIS PLAKA'))
            row = _plan_row(db_path)
            assert row is not None
            assert row['arac_plaka_snapshot'] == '34 MOR 049'

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
    )
    def test_gps_snapshot_fallback(self, mock_filom, filom_calls):
        mock_filom.side_effect = filom_calls['tracked']
        _reset_resolver_state()
        with _temp_db(with_gps=True, prefix='atp_outage_') as db_path:
            con = sqlite3.connect(db_path)
            con.execute(
                """
                INSERT INTO arac_gps_snapshot (
                    arac_provider, arac_external_id, plate_snapshot,
                    gps_timestamp, received_at, latitude, longitude,
                    speed_kmh, is_stale, dedup_key, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    'TURKCELL_FILOM', '45077045', '34 MOR 049',
                    '2026-08-26T10:00:00', '2026-08-26T10:00:01',
                    41.0, 29.0, 0, 0, 'dedup1', '2026-08-26T10:00:01',
                ),
            )
            con.commit()
            con.close()

            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(1, _base_payload())
            row = _plan_row(db_path)
            assert row is not None
            assert row['arac_plaka_snapshot'] == '34 MOR 049'
            assert filom_calls['n'] == 0


# ---------------------------------------------------------------------------
# Request-scope ContextVar gate (8 assertions)
# ---------------------------------------------------------------------------

class TestIdentityContextGate:
    def test_request_a_then_b_fresh_scope(self, impl_calls):
        _seed_catalog()
        from modules.planlama.arac_vehicle_identity_service import resolve_vehicle_identity

        with patch(
            'modules.planlama.arac_vehicle_identity_service._resolve_vehicle_identity_impl',
            side_effect=lambda p, e: _counting_impl(impl_calls, p, e),
        ):
            def req_a():
                r = resolve_vehicle_identity(None, '45077045')
                return r['arac_plaka_snapshot'], impl_calls['n']

            def req_b():
                r = resolve_vehicle_identity(None, '45077045')
                return r['arac_plaka_snapshot'], impl_calls['n']

            plate_a, calls_a = _simulate_http_request(req_a)
            impl_calls['n'] = 0
            plate_b, calls_b = _simulate_http_request(req_b)

        assert plate_a == '34 MOR 049'
        assert plate_b == '34 MOR 049'
        assert calls_a == 1
        assert calls_b == 1

    def test_reset_on_success(self):
        from modules.planlama.arac_vehicle_identity_service import (
            _RESOLVE_CACHE,
            resolve_vehicle_identity,
            vehicle_identity_request_scope,
        )

        with vehicle_identity_request_scope():
            resolve_vehicle_identity(None, '45077045')

        assert _RESOLVE_CACHE.get() is None

    def test_reset_on_exception(self, impl_calls):
        _seed_catalog()
        from modules.planlama.arac_vehicle_identity_service import (
            _RESOLVE_CACHE,
            resolve_vehicle_identity,
            vehicle_identity_request_scope,
        )

        with patch(
            'modules.planlama.arac_vehicle_identity_service._resolve_vehicle_identity_impl',
            side_effect=lambda p, e: _counting_impl(impl_calls, p, e),
        ):
            with pytest.raises(RuntimeError, match='simulated post-resolve failure'):
                with vehicle_identity_request_scope():
                    resolve_vehicle_identity(None, '45077045')
                    raise RuntimeError('simulated post-resolve failure')

            cache_after_exc = _RESOLVE_CACHE.get()

            with vehicle_identity_request_scope():
                resolve_vehicle_identity(None, '45077045')
            calls_after_c = impl_calls['n']

        assert cache_after_exc is None
        assert calls_after_c == 2

    def test_batch_three_rows_one_resolution(self, impl_calls):
        _seed_catalog()
        with _temp_db(prefix='ctx_gate_') as _db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic

            with patch(
                'modules.planlama.arac_vehicle_identity_service._resolve_vehicle_identity_impl',
                side_effect=lambda p, e: _counting_impl(impl_calls, p, e),
            ):
                def batch():
                    for i in range(3):
                        add_job_to_plan_atomic(1, _base_payload(
                            firma=f'F{i}',
                            yapilacak_is=f'I{i}',
                            client_submit_id=f'gate_{i}',
                        ))
                    return impl_calls['n']

                calls = _simulate_http_request(batch)

        assert calls == 1

    def test_two_batches_separate_scopes(self, impl_calls):
        _seed_catalog()
        from modules.planlama.arac_vehicle_identity_service import resolve_vehicle_identity

        with patch(
            'modules.planlama.arac_vehicle_identity_service._resolve_vehicle_identity_impl',
            side_effect=lambda p, e: _counting_impl(impl_calls, p, e),
        ):
            def one():
                before = impl_calls['n']
                resolve_vehicle_identity(None, '45077045')
                return impl_calls['n'] - before

            first = _simulate_http_request(one)
            second = _simulate_http_request(one)

        assert first == 1
        assert second == 1

    def test_parallel_context_isolation(self, impl_calls):
        _seed_catalog()
        barrier = threading.Barrier(2)
        results: dict[str, list] = {}

        def worker(name: str, ext_id: str):
            def run():
                from modules.planlama.arac_vehicle_identity_service import (
                    _RESOLVE_CACHE,
                    resolve_vehicle_identity,
                    vehicle_identity_request_scope,
                )
                with patch(
                    'modules.planlama.arac_vehicle_identity_service._resolve_vehicle_identity_impl',
                    side_effect=lambda p, e: _counting_impl_multi(impl_calls, p, e),
                ):
                    with vehicle_identity_request_scope():
                        barrier.wait(timeout=5)
                        resolve_vehicle_identity(None, ext_id)
                        results[name] = list((_RESOLVE_CACHE.get() or {}).keys())

            ctx = copy_context()
            ctx.run(run)

        t1 = threading.Thread(target=worker, args=('A', '45077045'))
        t2 = threading.Thread(target=worker, args=('B', 'V999'))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results.get('A') == [('TURKCELL_FILOM', '45077045')]
        assert results.get('B') == [('TURKCELL_FILOM', 'V999')]


# ---------------------------------------------------------------------------
# Coordinate persistence (8 assertions)
# ---------------------------------------------------------------------------

class TestCoordinatePersistence:
    @staticmethod
    def _talep_coords(db_path: str, talep_id: int) -> tuple:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                'SELECT latitude, longitude, kayitli_yer_id FROM arac_is_talebi WHERE id=?',
                (talep_id,),
            ).fetchone()
            return row['latitude'], row['longitude'], row['kayitli_yer_id']
        finally:
            con.close()

    @staticmethod
    def _task_dto(vehicle: str = '45077045') -> list[dict]:
        from modules.planlama.arac_takip_repo import list_plan_tasks
        return list_plan_tasks('2026-08-26', vehicle)

    @staticmethod
    def _routable(tasks: list[dict]) -> list[dict]:
        from modules.planlama.arac_route_constraints import active_tasks_sorted
        active = active_tasks_sorted(tasks)
        return [
            t for t in active
            if t.get('has_coordinates')
            and t.get('latitude') is not None
            and t.get('longitude') is not None
        ]

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_new_location_coords(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(1, _coord_payload(client_submit_id='c1'))
            lat, lng, _ = self._talep_coords(db_path, r['talep_id'])
            tasks = self._task_dto()
            assert lat is not None and lng is not None
            assert self._routable(tasks)

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_saved_location_master_fallback(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            con = sqlite3.connect(db_path)
            cur = con.execute(
                """
                INSERT INTO arac_kayitli_yer (
                    firma_adi, adres, latitude, longitude, aktif, kullanim_sayisi,
                    created_at, created_by
                ) VALUES (?,?,?,?,1,0,datetime('now'),1)
                """,
                ('Kayitli Firma', 'Kayitli Adres', 41.02, 29.01),
            )
            con.commit()
            loc_id = int(cur.lastrowid)
            con.close()

            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(1, _coord_payload(
                location_master_id=loc_id,
                latitude=None,
                longitude=None,
                lat=None,
                lng=None,
                is_new_location=False,
                client_submit_id='c2',
            ))
            lat, lng, kid = self._talep_coords(db_path, r['talep_id'])
            tasks = self._task_dto()
            assert float(lat) == 41.02
            assert float(lng) == 29.01
            assert kid == loc_id
            assert self._routable(tasks)

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_maps_link_coords(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            r = add_job_to_plan_atomic(1, _coord_payload(
                latitude=None,
                longitude=None,
                maps_url='https://maps.google.com/?q=41.03,29.02',
                client_submit_id='c3',
            ))
            lat, lng, _ = self._talep_coords(db_path, r['talep_id'])
            assert lat is not None and lng is not None
            assert self._routable(self._task_dto())

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_batch_three_items_coords(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            coords = [(41.01, 29.01), (41.02, 29.02), (41.03, 29.03)]
            for i, (la, ln) in enumerate(coords):
                add_job_to_plan_atomic(1, _coord_payload(
                    firma=f'Firma {i}',
                    yapilacak_is=f'Is {i}',
                    latitude=la,
                    longitude=ln,
                    client_submit_id=f'cb{i}',
                ))
            routable = self._routable(self._task_dto())
            assert len(routable) == 3

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_missing_coords_no_insert(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            con = sqlite3.connect(db_path)
            before = con.execute('SELECT COUNT(*) FROM arac_is_talebi').fetchone()[0]
            con.close()
            with pytest.raises(ValueError):
                add_job_to_plan_atomic(1, _coord_payload(
                    latitude=None,
                    longitude=None,
                    maps_url='',
                    adres='',
                    client_submit_id='c5',
                ))
            con = sqlite3.connect(db_path)
            after = con.execute('SELECT COUNT(*) FROM arac_is_talebi').fetchone()[0]
            con.close()
            assert after == before

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value=FILOM_FIXTURE,
    )
    def test_map_departure_parity(self, _mock):
        _seed_catalog()
        with _temp_db(prefix='atp_coord_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            add_job_to_plan_atomic(1, _coord_payload(client_submit_id='c6'))
            tasks = self._task_dto()
            routable = self._routable(tasks)
            for t in tasks:
                map_ok = t.get('has_coordinates') and t.get('latitude') is not None
                dep_ok = t in routable
                assert map_ok == dep_ok


# ---------------------------------------------------------------------------
# Physical vehicle unique dropdown (7 assertions)
# ---------------------------------------------------------------------------

class TestPhysicalVehicleUniqueDropdown:
    def test_mor_plan_wins(self):
        opts = _build_unique_physical_vehicle_options([MOR_LIVE], [MOR_PLAN])
        mor = _mor_opts(opts)
        assert len(mor) == 1
        assert mor[0]['value'] == '991001'

    def test_mor_planless(self):
        opts = _build_unique_physical_vehicle_options(
            [MOR_LIVE],
            [{'arac_external_id': '991001', 'arac_plaka_snapshot': '34 MOR 049'}],
        )
        mor = _mor_opts(opts)
        assert len(mor) == 1
        assert mor[0]['value'] == '45077045'

    def test_bpy_current_wins(self):
        opts = _build_unique_physical_vehicle_options([BPY_CURRENT, BPY_STALE], [])
        bpy = _bpy_opts(opts)
        assert len(bpy) == 1
        assert bpy[0]['value'] == '45077046'

    def test_blank_resolves_live(self):
        opts = _build_unique_physical_vehicle_options([BLANK_WITH_LIVE], [MOR_LIVE_EMPTY_OPS])
        mor = [o for o in opts if o['value'] == '45077045']
        blank = [o for o in opts if o['label'] == 'Plaka bilgisi yok']
        assert len(mor) == 1
        assert mor[0]['label'] == '34 MOR 049'
        assert not blank

    def test_blank_unknown_isolated(self):
        opts = _build_unique_physical_vehicle_options([BLANK_UNKNOWN, MOR_LIVE], [])
        unk = [o for o in opts if o['value'] == '880001']
        assert not unk
        assert len([o for o in opts if o['value'] == '45077045']) == 1

    @patch(
        'modules.planlama.arac_operasyonu.services.turkcell_filom_adapter.get_live_vehicles',
        return_value={'ok': True, 'vehicles': [MOR_LIVE]},
    )
    def test_plan_reuse(self, _mock):
        from modules.planlama.arac_vehicle_identity_service import (
            clear_vehicle_identity_resolve_cache,
            update_filom_vehicle_catalog,
        )
        clear_vehicle_identity_resolve_cache()
        update_filom_vehicle_catalog([MOR_LIVE])
        with _temp_db(prefix='atp_uniq_') as db_path:
            from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
            con = sqlite3.connect(db_path)
            con.execute(
                """
                INSERT INTO arac_gunluk_plan (
                    plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
                    sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
                ) VALUES ('2026-08-26','TURKCELL_FILOM','991001','34 MOR 049',NULL,'Ahmet','AKTIF',
                          '2026-08-26 10:00:00',1,'2026-08-26 10:00:00',1)
                """
            )
            plan_id = con.execute(
                "SELECT id FROM arac_gunluk_plan WHERE arac_external_id='991001'"
            ).fetchone()[0]
            con.commit()
            con.close()
            r = add_job_to_plan_atomic(1, {
                'plan_tarihi': '2026-08-26',
                'arac_external_id': '991001',
                'firma': 'Firma X',
                'adres': 'Istanbul',
                'yapilacak_is': 'Teslim',
                'latitude': 41.0,
                'longitude': 29.0,
                'client_submit_id': 'uniq_reuse_1',
            })
            con = sqlite3.connect(db_path)
            plans = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0]
            items = con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0]
            con.close()
            assert plans == 1
            assert items == 1
            assert r.get('plan_id') == plan_id
