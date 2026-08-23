# -*- coding: utf-8 -*-
"""DAYPLAN-01..14 — Gün geneli canonical read katmanı (list_plans_for_date + aggregate)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

CANONICAL_DB = os.path.join(_APP, 'mock_data.db')
CANONICAL_SHA_BEFORE = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()

YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})
results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def _run_migration_176(db_path: str) -> None:
    spec = importlib.util.spec_from_file_location(
        'm176', os.path.join(_APP, 'migrations', '176_arac_takip_v13.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def tmp_db_ctx():
    tmpdir = tempfile.mkdtemp(prefix='dayplan_read_')
    db_path = os.path.join(tmpdir, 'test.db')
    _run_migration_176(db_path)
    import config
    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


def _conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def _insert_talep(con: sqlite3.Connection, talep_no: str, firma: str, is_text: str,
                  lat: float | None = None, lng: float | None = None) -> int:
    now = '2026-08-23 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            firma_adi, adres, yapilacak_is, oncelik, durum,
            latitude, longitude, created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            talep_no, 1, 'Test User', '2026-08-23', firma, f'Adres {firma}', is_text,
            'NORMAL', 'PLANA_ALINDI', lat, lng, now, 1, now, 1,
        ),
    )
    con.commit()
    return int(cur.lastrowid)


def _insert_plan(con: sqlite3.Connection, plan_date: str, ext_id: str, plate: str,
                 sofor: str = 'Oktay TEST') -> int:
    now = '2026-08-23 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'TURKCELL_FILOM',?,?,1,?,'AKTIF',?,?,?,?)
        """,
        (plan_date, ext_id, plate, sofor, now, 1, now, 1),
    )
    con.commit()
    return int(cur.lastrowid)


def _insert_plan_item(con: sqlite3.Connection, plan_id: int, talep_id: int, sira: int,
                      saat: str | None, durum: str) -> None:
    con.execute(
        """
        INSERT INTO arac_gunluk_plan_is (
            plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (plan_id, talep_id, sira, saat, durum, '2026-08-23 10:00:00', 1),
    )
    con.commit()


def client():
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'AdSoyad': 'Admin',
            'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
    return c


print('=' * 72)
print('DAYPLAN — Gün geneli canonical read')
print('=' * 72)

from modules.planlama.arac_takip_repo import (
    build_daily_plan_aggregate,
    list_plan_tasks,
    list_plans_for_date,
)
from modules.planlama.arac_plan_service import get_daily_plan_aggregate

# DAYPLAN-01 empty day
with tmp_db_ctx() as db_path:
    agg = build_daily_plan_aggregate('2030-01-01')
    ok('DAYPLAN-01 empty day', agg['plan_count'] == 0 and agg['items'] == [] and agg['total_item_count'] == 0)

# DAYPLAN-02 single vehicle single plan
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9001', 'Firma A', 'Is A', 40.81, 29.30)
    p1 = _insert_plan(con, '2026-08-24', '991001', '34 AAA 001')
    _insert_plan_item(con, p1, t1, 1, '09:00', 'PLANLANDI')
    con.close()
    plans = list_plans_for_date('2026-08-24')
    ok('DAYPLAN-02 single plan', len(plans) == 1 and plans[0]['item_count'] == 1)
    ok('DAYPLAN-02 plate snapshot', plans[0]['arac_plaka_snapshot'] == '34 AAA 001')

# DAYPLAN-03 multi vehicle same day
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9002', 'Firma B', 'Is B')
    t2 = _insert_talep(con, 'AIT-2026-9003', 'Firma C', 'Is C')
    p1 = _insert_plan(con, '2026-08-25', '991101', '34 BBB 101')
    p2 = _insert_plan(con, '2026-08-25', '991102', '34 BBB 102', 'Serhat TEST')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'PLANLANDI')
    _insert_plan_item(con, p2, t2, 1, '10:00', 'PLANLANDI')
    con.close()
    agg = build_daily_plan_aggregate('2026-08-25')
    ok('DAYPLAN-03 multi vehicle', agg['plan_count'] == 2 and agg['planned_vehicle_count'] == 2)
    ok('DAYPLAN-03 total items', agg['total_item_count'] == 2)

# DAYPLAN-04 all status counts
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    ids = []
    for i, st in enumerate(['PLANLANDI', 'BASLADI', 'TAMAMLANDI', 'IPTAL'], start=1):
        ids.append(_insert_talep(con, f'AIT-2026-910{i}', f'Firma {i}', f'Is {i}'))
    p1 = _insert_plan(con, '2026-08-26', '991201', '34 CCC 201')
    for i, (tid, st) in enumerate(zip(ids, ['PLANLANDI', 'BASLADI', 'TAMAMLANDI', 'IPTAL']), start=1):
        _insert_plan_item(con, p1, tid, i, f'0{i}:00', st)
    con.close()
    agg = build_daily_plan_aggregate('2026-08-26')
    ok('DAYPLAN-04 status counts',
       agg['planned_count'] == 1 and agg['started_count'] == 1
       and agg['completed_count'] == 1 and agg['canceled_count'] == 1)
    ok('DAYPLAN-04 total includes iptal', agg['total_item_count'] == 4)
    ok('DAYPLAN-04 operational excludes iptal', agg['operational_total_count'] == 3)
    ok('DAYPLAN-04 active count', agg['active_item_count'] == 2)

# DAYPLAN-05 next item selection
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9201', 'Done Co', 'Done')
    t2 = _insert_talep(con, 'AIT-2026-9202', 'Next Co', 'Next job')
    t3 = _insert_talep(con, 'AIT-2026-9203', 'Later Co', 'Later')
    p1 = _insert_plan(con, '2026-08-27', '991301', '34 DDD 301')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'TAMAMLANDI')
    _insert_plan_item(con, p1, t2, 2, '09:30', 'PLANLANDI')
    _insert_plan_item(con, p1, t3, 3, '11:00', 'BASLADI')
    con.close()
    plan = list_plans_for_date('2026-08-27')[0]
    ok('DAYPLAN-05 next item', plan['next_item'] and plan['next_item']['company_name'] == 'Next Co',
       str(plan.get('next_item')))

# DAYPLAN-06 completed not next
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9301', 'All Done', 'X')
    p1 = _insert_plan(con, '2026-08-28', '991401', '34 EEE 401')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'TAMAMLANDI')
    con.close()
    plan = list_plans_for_date('2026-08-28')[0]
    ok('DAYPLAN-06 no next when all done', plan['next_item'] is None)

# DAYPLAN-07 IPTAL excluded from next
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9401', 'Cancel Co', 'C')
    t2 = _insert_talep(con, 'AIT-2026-9402', 'Real Next', 'N')
    p1 = _insert_plan(con, '2026-08-29', '991501', '34 FFF 501')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'IPTAL')
    _insert_plan_item(con, p1, t2, 2, '09:00', 'PLANLANDI')
    con.close()
    plan = list_plans_for_date('2026-08-29')[0]
    ok('DAYPLAN-07 iptal skipped', plan['next_item']['company_name'] == 'Real Next')

# DAYPLAN-08 missing coordinates
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9501', 'No Loc Co', 'Missing', None, None)
    p1 = _insert_plan(con, '2026-08-30', '991601', '34 GGG 601')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'PLANLANDI')
    con.close()
    item = list_plans_for_date('2026-08-30')[0]['items'][0]
    ok('DAYPLAN-08 missing coords', item['has_coordinates'] is False)

# DAYPLAN-09 stable sort same time
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9601', 'Z Plaka Item', 'A')
    t2 = _insert_talep(con, 'AIT-2026-9602', 'A Plaka Item', 'B')
    p1 = _insert_plan(con, '2026-09-01', '991701', '34 ZZZ 999')
    p2 = _insert_plan(con, '2026-09-01', '991702', '34 AAA 111')
    _insert_plan_item(con, p1, t1, 1, '09:00', 'PLANLANDI')
    _insert_plan_item(con, p2, t2, 1, '09:00', 'PLANLANDI')
    con.close()
    items = build_daily_plan_aggregate('2026-09-01')['items']
    ok('DAYPLAN-09 stable sort', items[0]['arac_plaka_snapshot'] == '34 AAA 111',
       ' -> '.join(i['arac_plaka_snapshot'] for i in items))

# DAYPLAN-10 aggregate totals
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9701', 'V1', 'a')
    t2 = _insert_talep(con, 'AIT-2026-9702', 'V2', 'b')
    p1 = _insert_plan(con, '2026-09-02', '991801', '34 H 1')
    p2 = _insert_plan(con, '2026-09-02', '991802', '34 H 2')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'PLANLANDI')
    _insert_plan_item(con, p2, t2, 1, '09:00', 'TAMAMLANDI')
    con.close()
    agg = get_daily_plan_aggregate('2026-09-02')
    ok('DAYPLAN-10 aggregate totals',
       agg['total_item_count'] == 2 and agg['planned_count'] == 1 and agg['completed_count'] == 1)

# DAYPLAN-11 vehicle progress
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9801', 'P1', 'a')
    t2 = _insert_talep(con, 'AIT-2026-9802', 'P2', 'b')
    t3 = _insert_talep(con, 'AIT-2026-9803', 'P3', 'c')
    p1 = _insert_plan(con, '2026-09-03', '991901', '34 PROG 1')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'TAMAMLANDI')
    _insert_plan_item(con, p1, t2, 2, '09:00', 'TAMAMLANDI')
    _insert_plan_item(con, p1, t3, 3, '10:00', 'PLANLANDI')
    con.close()
    veh = build_daily_plan_aggregate('2026-09-03')['vehicles'][0]
    ok('DAYPLAN-11 vehicle progress', veh['progress_label'] == '2/3' and veh['progress_completed'] == 2)
    ok('DAYPLAN-11 progress denominator operational', veh['progress_total'] == veh['operational_total_count'] == 3)

# DAYPLAN-15 IPTAL excluded from progress denominator
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9851', 'Done', 'a')
    t2 = _insert_talep(con, 'AIT-2026-9852', 'Cancel', 'b')
    t3 = _insert_talep(con, 'AIT-2026-9853', 'Open', 'c')
    p1 = _insert_plan(con, '2026-09-06', '992201', '34 IPTAL 1')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'TAMAMLANDI')
    _insert_plan_item(con, p1, t2, 2, '09:00', 'IPTAL')
    _insert_plan_item(con, p1, t3, 3, '10:00', 'PLANLANDI')
    con.close()
    agg = build_daily_plan_aggregate('2026-09-06')
    veh = agg['vehicles'][0]
    ok('DAYPLAN-15 total includes iptal', agg['total_item_count'] == 3 and veh['item_count'] == 3)
    ok('DAYPLAN-15 operational excludes iptal', agg['operational_total_count'] == 2 and veh['operational_total_count'] == 2)
    ok('DAYPLAN-15 progress excludes iptal', veh['progress_label'] == '1/2' and veh['progress_total'] == 2)

# DAYPLAN-16 TURKCELL_FILOM provider filter
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9861', 'Filom Co', 'a')
    t2 = _insert_talep(con, 'AIT-2026-9862', 'Other Co', 'b')
    now = '2026-08-23 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by
        ) VALUES (?,'OTHER_PROVIDER','992301','34 OTHER 1',1,'X','AKTIF',?,?,?,?)
        """,
        ('2026-09-07', now, 1, now, 1),
    )
    other_plan = int(cur.lastrowid)
    p_filom = _insert_plan(con, '2026-09-07', '992302', '34 FILOM 1')
    _insert_plan_item(con, other_plan, t1, 1, '08:00', 'PLANLANDI')
    _insert_plan_item(con, p_filom, t2, 1, '09:00', 'PLANLANDI')
    con.close()
    plans = list_plans_for_date('2026-09-07')
    ok('DAYPLAN-16 filom filter', len(plans) == 1 and plans[0]['arac_plaka_snapshot'] == '34 FILOM 1')
    ok('DAYPLAN-16 provider constant', plans[0]['arac_provider'] == 'TURKCELL_FILOM')

# DAYPLAN-12 list_plan_tasks regression
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9901', 'Reg Co', 'Reg', 41.0, 29.0)
    t2 = _insert_talep(con, 'AIT-2026-9902', 'Reg Co2', 'Reg2')
    p1 = _insert_plan(con, '2026-09-04', '992001', '34 REG 01')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'PLANLANDI')
    _insert_plan_item(con, p1, t2, 2, '09:00', 'BASLADI')
    con.close()
    single = list_plan_tasks('2026-09-04', '992001')
    day = list_plans_for_date('2026-09-04')[0]['items']
    ok('DAYPLAN-12 list_plan_tasks parity', len(single) == 2 and len(day) == 2)
    ok('DAYPLAN-12 same order ids', [x['plan_item_id'] for x in single] == [x['plan_item_id'] for x in day])

# DAYPLAN-13 dashboard contract (new field only)
with tmp_db_ctx() as db_path:
    con = _conn(db_path)
    t1 = _insert_talep(con, 'AIT-2026-9951', 'API Co', 'Api')
    p1 = _insert_plan(con, '2026-09-05', '992101', '34 API 01')
    _insert_plan_item(con, p1, t1, 1, '08:00', 'PLANLANDI')
    con.close()
    with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
         patch('modules.auth.sistem_session_gecerli_mi', return_value=True):
        c = client()
        r = c.get('/planlama/arac-takip/api/dashboard?date=2026-09-05')
        j = r.get_json()
        dash = j.get('dashboard') or {}
        ok('DAYPLAN-13 dashboard 200', r.status_code == 200 and j.get('ok'))
        ok('DAYPLAN-13 day_plan_summary field', 'day_plan_summary' in dash and dash['day_plan_summary']['plan_count'] == 1)
        ok('DAYPLAN-13 legacy kpi preserved', 'kpi' in dash and 'daily_tasks' in dash and 'bekleyen_count' in dash)
        ok('DAYPLAN-13 operational_total_count field', dash['day_plan_summary']['operational_total_count'] == 1)
        ok('DAYPLAN-13 page html no day summary', 'day_plan_summary' not in c.get('/planlama/arac-takip/?date=2026-09-05').get_data(as_text=True))
        ep = c.get('/planlama/arac-takip/api/day-plan-summary?date=2026-09-05').get_json()
        ok('DAYPLAN-13 endpoint contract', ep.get('ok') and ep['day_plan_summary']['total_item_count'] == 1)
        ok('DAYPLAN-13 endpoint keys',
           set(ep.keys()) == {'ok', 'plan_date', 'day_plan_summary'}
           and set(ep['day_plan_summary'].keys()) >= {
               'plan_date', 'plan_count', 'planned_vehicle_count',
               'total_item_count', 'operational_total_count',
               'planned_count', 'started_count', 'completed_count', 'canceled_count',
               'active_item_count', 'plans', 'vehicles', 'items',
           })

# DAYPLAN-14 canonical DB write-free
CANONICAL_SHA_AFTER = hashlib.sha256(open(CANONICAL_DB, 'rb').read()).hexdigest()
ok('DAYPLAN-14 canonical hash unchanged', CANONICAL_SHA_BEFORE == CANONICAL_SHA_AFTER,
   CANONICAL_SHA_BEFORE[:16])

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'DAYPLAN SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
if failed:
    for name, p, detail in results:
        if not p:
            print(f'  FAIL: {name} {detail}')
    sys.exit(1)
print('ALL PASS')
