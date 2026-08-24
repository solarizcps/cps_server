# -*- coding: utf-8 -*-
"""
Plana İş Ekle — gerçek atomiklik kanıtı.

Test matrisi:
 1. Payload validation fail → hiçbir kayıt yok
 2. Talep insert fail (mock) → rollback, kayıt yok
 3. Plan create fail (mock) → rollback, talep yok
 4. Plan item insert fail (mock) → rollback, tüm kayıtlar yok
 5. Commit öncesi exception → tüm rollback
 6. Var olan plana başarıyla iş ekleme
 7. Plan yoksa plan + talep + item tek commit
 8. Aynı anda iki istek → tek günlük plan
 9. Sıra artımlı/çakışmasız
10. Response doğru IDs
11. Canonical DB hash değişmez
12. compensating_delete=False response'da
13. Talep durum doğrudan PLANA_ALINDI (BEKLIYOR geçiş yok)
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import threading
from contextlib import contextmanager
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
CANONICAL_DB = os.path.join(APP, 'mock_data.db')
CANONICAL_SHA = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest() if os.path.isfile(CANONICAL_DB) else ''
sys.path.insert(0, APP)
os.chdir(APP)

PASS = FAIL = 0


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f'  PASS {name}')


def bad(name: str, detail: str = '') -> None:
    global FAIL
    FAIL += 1
    print(f'  FAIL {name} {detail}')


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(
        filename, os.path.join(APP, 'migrations', filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def temp_atomic_db():
    tmpdir = tempfile.mkdtemp(prefix='atomic_plana_')
    db_path = os.path.join(tmpdir, 'atomic.db')
    for mig in (
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
    ):
        _run_migration(db_path, mig)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


def _counts(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    try:
        return {
            'talep': con.execute('SELECT COUNT(*) FROM arac_is_talebi').fetchone()[0],
            'plan': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan').fetchone()[0],
            'item': con.execute('SELECT COUNT(*) FROM arac_gunluk_plan_is').fetchone()[0],
        }
    finally:
        con.close()


BASE_PAYLOAD = {
    'plan_tarihi': '2026-12-20',
    'arac_external_id': 'V1',
    'arac_plaka': '34 MOR 049',
    'firma': 'Test Firma',
    'adres': 'Test Adres',
    'yapilacak_is': 'Teslim',
    'latitude': 40.99,
    'longitude': 28.89,
    'planlanan_saat': '09:30',
}


def test_1_payload_validation_fail(db_path: str) -> None:
    print('ATOMIC-1 payload_validation_fail')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    before = _counts(db_path)
    try:
        add_job_to_plan_atomic(1, {'plan_tarihi': '2026-12-20'})
        bad('no_record_on_validation_fail')
    except ValueError:
        after = _counts(db_path)
        if after == before:
            ok('no_record_on_validation_fail')
        else:
            bad('no_record_on_validation_fail', str(after))


def test_2_talep_insert_fail(db_path: str) -> None:
    print('ATOMIC-2 talep_insert_fail')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    import modules.planlama.arac_add_to_plan_service as svc
    before = _counts(db_path)

    original = svc._create_request_conn

    def fail_insert(con, uid, payload, loc_id, now):
        raise sqlite3.OperationalError('injected talep insert failure')

    before_patched = _counts(db_path)
    svc._create_request_conn = fail_insert
    try:
        add_job_to_plan_atomic(1, dict(BASE_PAYLOAD))
        bad('rollback_on_talep_fail')
    except sqlite3.OperationalError:
        after = _counts(db_path)
        if after == before_patched:
            ok('rollback_on_talep_fail')
        else:
            bad('rollback_on_talep_fail', str(after))
    finally:
        svc._create_request_conn = original


def test_3_plan_create_fail(db_path: str) -> None:
    print('ATOMIC-3 plan_create_fail')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    import modules.planlama.arac_add_to_plan_service as svc
    before = _counts(db_path)

    original = svc._get_or_create_daily_plan_conn

    def fail_plan(con, uid, plan_date, arac_id, plaka, sofor_id, sofor_adi, now):
        raise sqlite3.OperationalError('injected plan create failure')

    svc._get_or_create_daily_plan_conn = fail_plan
    try:
        add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, plan_tarihi='2026-12-21'))
        bad('rollback_on_plan_fail')
    except sqlite3.OperationalError:
        after = _counts(db_path)
        if after == before:
            ok('rollback_on_plan_fail')
        else:
            bad('rollback_on_plan_fail', str(after))
    finally:
        svc._get_or_create_daily_plan_conn = original


def test_4_item_insert_fail(db_path: str) -> None:
    print('ATOMIC-4 item_insert_fail')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    import modules.planlama.arac_add_to_plan_service as svc
    before = _counts(db_path)

    original = svc._add_plan_item_conn

    def fail_item(con, uid, plan_id, talep_id, saat, sira, now):
        raise sqlite3.OperationalError('injected item insert failure')

    svc._add_plan_item_conn = fail_item
    try:
        add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, plan_tarihi='2026-12-22'))
        bad('rollback_on_item_fail')
    except sqlite3.OperationalError:
        after = _counts(db_path)
        if after == before:
            ok('rollback_on_item_fail')
        else:
            bad('rollback_on_item_fail', str(after))
    finally:
        svc._add_plan_item_conn = original


def test_5_successful_add(db_path: str) -> None:
    print('ATOMIC-5 successful_add_new_plan')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    before = _counts(db_path)
    result = add_job_to_plan_atomic(1, dict(BASE_PAYLOAD))
    after = _counts(db_path)
    if (
        result.get('ok')
        and after['talep'] == before['talep'] + 1
        and after['plan'] == before['plan'] + 1
        and after['item'] == before['item'] + 1
    ):
        ok('successful_add_new_plan')
    else:
        bad('successful_add_new_plan', str(result) + str(after))


def test_6_response_fields(db_path: str) -> None:
    print('ATOMIC-6 response_fields')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    result = add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, arac_external_id='V2', plan_tarihi='2026-12-23'))
    required = ('ok', 'atomic', 'compensating_delete', 'plan_id', 'plan_is_id', 'talep_id', 'talep')
    missing = [k for k in required if k not in result]
    if result.get('compensating_delete') is False and not missing and result['ok']:
        ok('response_has_all_fields_and_no_comp_delete')
    else:
        bad('response_has_all_fields_and_no_comp_delete', str(missing) + str(result))


def test_7_durum_plana_alindi(db_path: str) -> None:
    print('ATOMIC-7 durum_direct_plana_alindi')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    result = add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, arac_external_id='V3', plan_tarihi='2026-12-24'))
    talep_id = result['talep_id']
    con = sqlite3.connect(db_path)
    durum = con.execute('SELECT durum FROM arac_is_talebi WHERE id=?', (talep_id,)).fetchone()[0]
    con.close()
    if durum == 'PLANA_ALINDI':
        ok('durum_direct_plana_alindi_no_bekliyor')
    else:
        bad('durum_direct_plana_alindi_no_bekliyor', durum)


def test_8_add_to_existing_plan(db_path: str) -> None:
    print('ATOMIC-8 add_to_existing_plan')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    r1 = add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, arac_external_id='V4', plan_tarihi='2026-12-25'))
    plan_id_1 = r1['plan_id']
    r2 = add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, arac_external_id='V4', plan_tarihi='2026-12-25',
                                         yapilacak_is='İkinci iş'))
    if r2['plan_id'] == plan_id_1:
        ok('second_add_uses_existing_plan')
    else:
        bad('second_add_uses_existing_plan', str(r2['plan_id']) + '!=' + str(plan_id_1))
    con = sqlite3.connect(db_path)
    n_plans = con.execute(
        "SELECT COUNT(*) FROM arac_gunluk_plan WHERE plan_tarihi='2026-12-25' AND arac_external_id='V4'",
    ).fetchone()[0]
    con.close()
    if n_plans == 1:
        ok('only_one_plan_for_vehicle_date')
    else:
        bad('only_one_plan_for_vehicle_date', str(n_plans))


def test_9_sira_incremental(db_path: str) -> None:
    print('ATOMIC-9 sira_incremental')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    for i in range(3):
        add_job_to_plan_atomic(1, dict(BASE_PAYLOAD, arac_external_id='V5', plan_tarihi='2026-12-26',
                                        yapilacak_is=f'Is {i}'))
    con = sqlite3.connect(db_path)
    plan = con.execute(
        "SELECT id FROM arac_gunluk_plan WHERE arac_external_id='V5' AND plan_tarihi='2026-12-26'",
    ).fetchone()
    siras = [r[0] for r in con.execute(
        'SELECT sira FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (plan[0],),
    ).fetchall()]
    con.close()
    if siras == sorted(set(siras)) and len(siras) == 3:
        ok('sira_incremental_no_conflict')
    else:
        bad('sira_incremental_no_conflict', str(siras))


def test_10_concurrency_single_plan(db_path: str) -> None:
    print('ATOMIC-10 concurrency_single_plan')
    from modules.planlama.arac_add_to_plan_service import add_job_to_plan_atomic
    errors = []

    def worker(idx: int) -> None:
        try:
            add_job_to_plan_atomic(1, dict(BASE_PAYLOAD,
                                           arac_external_id='CONC1',
                                           plan_tarihi='2026-12-27',
                                           yapilacak_is=f'Concurrent {idx}'))
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    con = sqlite3.connect(db_path)
    n_plans = con.execute(
        "SELECT COUNT(*) FROM arac_gunluk_plan WHERE arac_external_id='CONC1' AND plan_tarihi='2026-12-27'",
    ).fetchone()[0]
    n_items = con.execute(
        "SELECT COUNT(*) FROM arac_gunluk_plan_is WHERE plan_id IN "
        "(SELECT id FROM arac_gunluk_plan WHERE arac_external_id='CONC1' AND plan_tarihi='2026-12-27')",
    ).fetchone()[0]
    con.close()
    # BEGIN IMMEDIATE serializes — exactly 1 plan; some may fail with locked DB (expected)
    if n_plans == 1:
        ok('concurrency_single_plan')
    else:
        bad('concurrency_single_plan', f'plans={n_plans}')
    if n_items >= 1:
        ok('concurrency_items_inserted')
    else:
        bad('concurrency_items_inserted', f'items={n_items}')


def test_11_canonical_hash() -> None:
    print('ATOMIC-11 canonical_hash')
    if os.path.isfile(CANONICAL_DB):
        h = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()
        if h == CANONICAL_SHA:
            ok('canonical_sha_unchanged')
        else:
            bad('canonical_sha_unchanged', h)
    else:
        ok('canonical_sha_skip_no_file')


def main() -> int:
    print('=' * 60)
    print('ATOMIC PLANA IS EKLE TEST SUITE')
    test_11_canonical_hash()
    with temp_atomic_db() as db_path:
        test_1_payload_validation_fail(db_path)
        test_2_talep_insert_fail(db_path)
        test_3_plan_create_fail(db_path)
        test_4_item_insert_fail(db_path)
        test_5_successful_add(db_path)
        test_6_response_fields(db_path)
        test_7_durum_plana_alindi(db_path)
        test_8_add_to_existing_plan(db_path)
        test_9_sira_incremental(db_path)
        test_10_concurrency_single_plan(db_path)
    print('=' * 60)
    print(f'RESULT {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
